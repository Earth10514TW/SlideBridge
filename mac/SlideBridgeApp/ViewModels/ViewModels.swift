import SwiftUI
import Combine
import UniformTypeIdentifiers

@MainActor
public class AppState: ObservableObject {
    @Published public var selectedTab: AppTab = .batchRepair

    public init() {}
}

@MainActor
public class BatchRepairViewModel: ObservableObject {
    @Published public var selectedFileURL: URL?
    @Published public var scanReport: ScanReport?
    @Published public var fixReport: FixReport?

    @Published public var isScanning = false
    @Published public var isFixing = false
    @Published public var isDropTargeted = false

    @Published public var selectedDPI = 300
    @Published public var errorMessage: String?
    @Published public var showErrorAlert = false

    public init() {}

    public func selectFile() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [UTType(filenameExtension: "pptx") ?? .data]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        if panel.runModal() == .OK, let url = panel.url {
            loadAndScanFile(url: url)
        }
    }

    public func loadAndScanFile(url: URL) {
        selectedFileURL = url
        fixReport = nil
        isScanning = true
        Task {
            do {
                let report = try await BridgeProcess.shared.scan(fileURL: url)
                self.scanReport = report
                self.isScanning = false
            } catch {
                self.isScanning = false
                self.errorMessage = error.localizedDescription
                self.showErrorAlert = true
            }
        }
    }

    public func startRepair() {
        guard let url = selectedFileURL else { return }
        isFixing = true
        Task {
            do {
                let report = try await BridgeProcess.shared.fix(fileURL: url, dpi: selectedDPI)
                self.fixReport = report
                self.isFixing = false
            } catch {
                self.isFixing = false
                self.errorMessage = error.localizedDescription
                self.showErrorAlert = true
            }
        }
    }

    public func reset() {
        selectedFileURL = nil
        scanReport = nil
        fixReport = nil
        isScanning = false
        isFixing = false
        errorMessage = nil
        showErrorAlert = false
    }
}

@MainActor
public class OriginEditViewModel: ObservableObject {
    @Published public var isEditing = false
    @Published public var editReport: EditActiveReport?
    @Published public var errorMessage: String?
    @Published public var showErrorAlert = false

    public init() {}

    public func triggerActiveEdit() {
        isEditing = true
        editReport = nil
        Task {
            do {
                let report = try await BridgeProcess.shared.editActive()
                self.editReport = report
                self.isEditing = false
            } catch {
                self.isEditing = false
                self.errorMessage = error.localizedDescription
                self.showErrorAlert = true
            }
        }
    }
}

@MainActor
public class DoctorViewModel: ObservableObject {
    @Published public var doctorReport: DoctorReport?
    @Published public var isLoading = false
    @Published public var isInstalling = false
    @Published public var isUninstalling = false
    @Published public var installMessage: String?
    @Published public var errorMessage: String?
    @Published public var showErrorAlert = false

    public init() {}

    public func runDoctor() {
        isLoading = true
        Task {
            do {
                let report = try await BridgeProcess.shared.doctor()
                self.doctorReport = report
                self.isLoading = false
            } catch {
                self.isLoading = false
                self.errorMessage = error.localizedDescription
                self.showErrorAlert = true
            }
        }
    }

    public func installIntegration() {
        isInstalling = true
        installMessage = nil
        Task {
            do {
                _ = try await BridgeProcess.shared.installIntegration()
                self.isInstalling = false
                self.installMessage = "✔ 系統整合安裝成功！已註冊至 PowerPoint 與系統服務。"
                self.runDoctor()
            } catch {
                self.isInstalling = false
                self.errorMessage = error.localizedDescription
                self.showErrorAlert = true
            }
        }
    }

    public func uninstallIntegration() {
        isUninstalling = true
        installMessage = nil
        Task {
            do {
                _ = try await BridgeProcess.shared.uninstallIntegration()
                self.isUninstalling = false
                self.installMessage = "✔ 已成功移除所有 macOS 系統整合服務（右鍵快速動作與選單）。"
                self.runDoctor()
            } catch {
                self.isUninstalling = false
                self.errorMessage = error.localizedDescription
                self.showErrorAlert = true
            }
        }
    }
}
