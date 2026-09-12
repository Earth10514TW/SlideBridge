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
            return msg
        case .decodingFailed(let msg):
            return "輸出解析失敗：\(msg)"
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

    private func execute(executable: URL, arguments: [String], workingDirectory: URL, extraEnvironment: [String: String] = [:]) async throws -> String {
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
                        let combined = stderrStr.isEmpty ? stdoutStr : stderrStr
                        continuation.resume(throwing: BridgeError.executionFailed(combined.trimmingCharacters(in: .whitespacesAndNewlines)))
                    } else {
                        continuation.resume(returning: stdoutStr)
                    }
                } catch {
                    continuation.resume(throwing: BridgeError.executionFailed(error.localizedDescription))
                }
            }
        }
    }

    public func run(subcommand: [String]) async throws -> String {
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
            ]
        )
    }

    public func scan(fileURL: URL) async throws -> ScanReport {
        let output = try await run(subcommand: ["scan", fileURL.path, "--json"])
        guard let data = output.data(using: .utf8) else {
            throw BridgeError.decodingFailed("無效的 UTF-8 資料")
        }
        do {
            return try JSONDecoder().decode(ScanReport.self, from: data)
        } catch {
            throw BridgeError.decodingFailed(error.localizedDescription + "\n原始輸出: " + output)
        }
    }

    public func fix(fileURL: URL, outputURL: URL? = nil, dpi: Int = 300) async throws -> FixReport {
        var args = ["fix", fileURL.path, "--dpi", String(dpi), "--json"]
        if let out = outputURL {
            args.append(contentsOf: ["-o", out.path])
        }
        let output = try await run(subcommand: args)
        guard let data = output.data(using: .utf8) else {
            throw BridgeError.decodingFailed("無效的 UTF-8 資料")
        }
        do {
            return try JSONDecoder().decode(FixReport.self, from: data)
        } catch {
            throw BridgeError.decodingFailed(error.localizedDescription + "\n原始輸出: " + output)
        }
    }

    public func doctor() async throws -> DoctorReport {
        let output = try await run(subcommand: ["doctor", "--json"])
        guard let data = output.data(using: .utf8) else {
            throw BridgeError.decodingFailed("無效的 UTF-8 資料")
        }
        do {
            return try JSONDecoder().decode(DoctorReport.self, from: data)
        } catch {
            throw BridgeError.decodingFailed(error.localizedDescription + "\n原始輸出: " + output)
        }
    }

    public func editActive() async throws -> EditActiveReport {
        let output = try await run(subcommand: ["edit-active", "--json"])
        guard let data = output.data(using: .utf8) else {
            throw BridgeError.decodingFailed("無效的 UTF-8 資料")
        }
        do {
            return try JSONDecoder().decode(EditActiveReport.self, from: data)
        } catch {
            throw BridgeError.decodingFailed(error.localizedDescription + "\n原始輸出: " + output)
        }
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
