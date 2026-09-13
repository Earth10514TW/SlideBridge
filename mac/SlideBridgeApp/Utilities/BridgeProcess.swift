import Foundation

public enum BridgeError: LocalizedError {
    case pythonNotFound
    case projectRootNotFound
    case executionFailed(String)
    case decodingFailed(String)

    public var errorDescription: String? {
        switch self {
        case .pythonNotFound:
            return "找不到相容的 Python 3 直譯器。請確認已安裝 Python 3.10+。"
        case .projectRootNotFound:
            return "找不到 SlideBridge 專案根目錄。請確認專案位置未更動或執行安裝腳本。"
        case .executionFailed(let msg):
            return BridgeProcess.cleanErrorMessage(from: msg)
        case .decodingFailed(let msg):
            return "輸出解析失敗：\(BridgeProcess.cleanErrorMessage(from: msg))"
        }
    }
}

public actor BridgeProcess {
    public static let shared = BridgeProcess()

    private var cachedPythonPath: String?
    private var cachedProjectRoot: URL?

    private init() {}

    public func resolvePythonPath() -> String? {
        if let cached = cachedPythonPath {
            return cached
        }

        let fm = FileManager.default

        // 1. Environment variable
        if let env = ProcessInfo.processInfo.environment["SLIDEBRIDGE_PYTHON"], !env.isEmpty, fm.isExecutableFile(atPath: env) {
            cachedPythonPath = env
            return env
        }

        // 2. ~/.slidebridge/python-path (written by installer or python_env.sh)
        let configPath = fm.homeDirectoryForCurrentUser.appendingPathComponent(".slidebridge/python-path")
        if let data = try? Data(contentsOf: configPath),
           let str = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines),
           !str.isEmpty, fm.isExecutableFile(atPath: str) {
            cachedPythonPath = str
            return str
        }

        // 3. Known candidate locations
        let candidates = [
            "/usr/local/bin/python3",
            "/opt/homebrew/bin/python3",
            "/Library/Frameworks/Python.framework/Versions/Current/bin/python3",
            "/usr/bin/python3"
        ]
        for path in candidates {
            if fm.isExecutableFile(atPath: path) {
                cachedPythonPath = path
                return path
            }
        }
        return nil
    }

    public func resolveProjectRoot() -> URL? {
        if let cached = cachedProjectRoot {
            return cached
        }

        let fm = FileManager.default

        // 1. Environment variable
        if let env = ProcessInfo.processInfo.environment["SLIDEBRIDGE_PROJECT_ROOT"], !env.isEmpty {
            let url = URL(fileURLWithPath: env)
            if fm.fileExists(atPath: url.path) {
                cachedProjectRoot = url
                return url
            }
        }

        // 2. ~/.slidebridge/project-root
        let configPath = fm.homeDirectoryForCurrentUser.appendingPathComponent(".slidebridge/project-root")
        if let data = try? Data(contentsOf: configPath),
           let str = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines),
           !str.isEmpty, fm.fileExists(atPath: str) {
            let url = URL(fileURLWithPath: str)
            cachedProjectRoot = url
            return url
        }

        // 3. App bundle ancestor directories
        var current = Bundle.main.bundleURL
        for _ in 0..<5 {
            current = current.deletingLastPathComponent()
            let marker = current.appendingPathComponent("slidebridge/core.py")
            if fm.fileExists(atPath: marker.path) {
                cachedProjectRoot = current
                return current
            }
        }

        // 4. Current working directory
        let cwd = URL(fileURLWithPath: fm.currentDirectoryPath)
        if fm.fileExists(atPath: cwd.appendingPathComponent("slidebridge/core.py").path) {
            cachedProjectRoot = cwd
            return cwd
        }

        return nil
    }

    public static func cleanErrorMessage(from raw: String) -> String {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.hasPrefix("{"),
              let data = trimmed.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return raw
        }

        // 1. Check if it's a DoctorReport format
        if let checks = json["checks"] as? [[String: Any]] {
            var items: [String] = []
            for check in checks {
                let status = check["status"] as? String ?? ""
                if status == "fail" || status == "warn" {
                    let name = check["name"] as? String ?? "環境檢查"
                    let detail = check["detail"] as? String ?? ""
                    let fix = check["fix"] as? String ?? ""
                    var line = "• \(name)：\(detail)"
                    if !fix.isEmpty {
                        line += "\n  建議解決方式：\(fix)"
                    }
                    items.append(line)
                }
            }
            if !items.isEmpty {
                return "環境檢測發現以下項目需要處理：\n\n" + items.joined(separator: "\n\n")
            }
        }

        // 2. Generic message / error / detail fields
        if let msg = json["message"] as? String, !msg.isEmpty {
            return msg
        }
        if let err = json["error"] as? String, !err.isEmpty {
            return err
        }
        if let detail = json["detail"] as? String, !detail.isEmpty {
            return detail
        }

        return raw
    }

    private func execute(
        executable: URL,
        arguments: [String],
        workingDirectory: URL,
        extraEnvironment: [String: String] = [:],
        allowNonZeroExit: Bool = false
    ) async throws -> String {
        return try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                let process = Process()
                process.executableURL = executable
                process.currentDirectoryURL = workingDirectory
                process.arguments = arguments

                var env = ProcessInfo.processInfo.environment
                let existingPath = env["PATH"] ?? ""
                let extraPaths = "/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/local/sbin:/usr/bin:/bin:/usr/sbin:/sbin"
                env["PATH"] = existingPath.isEmpty ? extraPaths : "\(extraPaths):\(existingPath)"
                for (k, v) in extraEnvironment {
                    env[k] = v
                }
                process.environment = env

                let stdoutPipe = Pipe()
                let stderrPipe = Pipe()
                process.standardOutput = stdoutPipe
                process.standardError = stderrPipe

                do {
                    try process.run()
                    process.waitUntilExit()

                    let outData = stdoutPipe.fileHandleForReading.readDataToEndOfFile()
                    let errData = stderrPipe.fileHandleForReading.readDataToEndOfFile()

                    let stdoutStr = String(data: outData, encoding: .utf8) ?? ""
                    let stderrStr = String(data: errData, encoding: .utf8) ?? ""

                    if process.terminationStatus != 0 {
                        if allowNonZeroExit && !stdoutStr.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                            continuation.resume(returning: stdoutStr)
                        } else {
                            let combined = stderrStr.isEmpty ? stdoutStr : stderrStr
                            let clean = BridgeProcess.cleanErrorMessage(from: combined.trimmingCharacters(in: .whitespacesAndNewlines))
                            continuation.resume(throwing: BridgeError.executionFailed(clean))
                        }
                    } else {
                        continuation.resume(returning: stdoutStr)
                    }
                } catch {
                    continuation.resume(throwing: BridgeError.executionFailed(error.localizedDescription))
                }
            }
        }
    }

    public func run(subcommand: [String], allowNonZeroExit: Bool = false) async throws -> String {
        guard let python = resolvePythonPath() else {
            throw BridgeError.pythonNotFound
        }
        guard let root = resolveProjectRoot() else {
            throw BridgeError.projectRootNotFound
        }

        var args = ["-m", "slidebridge"]
        args.append(contentsOf: subcommand)

        return try await execute(
            executable: URL(fileURLWithPath: python),
            arguments: args,
            workingDirectory: root,
            extraEnvironment: [
                "PYTHONUNBUFFERED": "1",
                "SLIDEBRIDGE_PROJECT_ROOT": root.path
            ],
            allowNonZeroExit: allowNonZeroExit
        )
    }

    private func extractJSON(from raw: String) -> String {
        let lines = raw.components(separatedBy: .newlines)
        for index in 0..<lines.count {
            let trimmed = lines[index].trimmingCharacters(in: .whitespaces)
            if trimmed.hasPrefix("{") {
                let candidate = lines[index...].joined(separator: "\n")
                if let data = candidate.data(using: .utf8),
                   (try? JSONSerialization.jsonObject(with: data)) != nil {
                    return candidate
                }
            }
        }
        return raw
    }

    private func decodeJSON<T: Decodable>(_ type: T.Type, from raw: String) throws -> T {
        let jsonStr = extractJSON(from: raw)
        guard let data = jsonStr.data(using: .utf8) else {
            throw BridgeError.decodingFailed("無效的 UTF-8 資料")
        }
        do {
            return try JSONDecoder().decode(T.self, from: data)
        } catch {
            let clean = BridgeProcess.cleanErrorMessage(from: raw)
            throw BridgeError.decodingFailed(error.localizedDescription + "\n" + clean)
        }
    }

    public func scan(fileURL: URL) async throws -> ScanReport {
        let output = try await run(subcommand: ["scan", fileURL.path, "--json"])
        return try decodeJSON(ScanReport.self, from: output)
    }

    public func fix(fileURL: URL, outputURL: URL? = nil, dpi: Int = 300) async throws -> FixReport {
        var args = ["fix", fileURL.path, "--dpi", String(dpi), "--json"]
        if let out = outputURL {
            args.append(contentsOf: ["-o", out.path])
        }
        let output = try await run(subcommand: args)
        return try decodeJSON(FixReport.self, from: output)
    }

    public func doctor() async throws -> DoctorReport {
        let output = try await run(subcommand: ["doctor", "--json"], allowNonZeroExit: true)
        return try decodeJSON(DoctorReport.self, from: output)
    }

    public func editActive() async throws -> EditActiveReport {
        let output = try await run(subcommand: ["edit-active", "--json"])
        return try decodeJSON(EditActiveReport.self, from: output)
    }

    public func installIntegration() async throws -> String {
        guard let root = resolveProjectRoot() else {
            throw BridgeError.projectRootNotFound
        }
        let script = root.appendingPathComponent("scripts/install_mac_integration.sh")
        return try await execute(
            executable: URL(fileURLWithPath: "/bin/bash"),
            arguments: [script.path],
            workingDirectory: root
        )
    }

    public func uninstallIntegration() async throws -> String {
        guard let root = resolveProjectRoot() else {
            throw BridgeError.projectRootNotFound
        }
        let script = root.appendingPathComponent("scripts/uninstall_mac_integration.sh")
        return try await execute(
            executable: URL(fileURLWithPath: "/bin/bash"),
            arguments: [script.path],
            workingDirectory: root
        )
    }
}
