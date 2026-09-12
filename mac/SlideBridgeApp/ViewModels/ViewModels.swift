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

    @Published public var isSelectingFile = false
    @Published public var isScanning = false
    @Published public var isFixing = false
    @Published public var isDropTargeted = false

    @Published public var selectedDPI = 300
    @Published public var errorMessage: String?
    @Published public var showErrorAlert = false

    public init() {}

    public func selectFile() {
        guard !isScanning, !isFixing, !isSelectingFile else { return }
        isSelectingFile = true
        defer { isSelectingFile = false }
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [UTType(filenameExtension: "pptx") ?? .data]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        if panel.runModal() == .OK, let url = panel.url {
            loadAndScanFile(url: url)
        }
    }

    public func loadAndScanFile(url: URL) {
        guard !isScanning, !isFixing else { return }
        errorMessage = nil
        showErrorAlert = false
        selectedFileURL = url
        scanReport = nil
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
        guard !isScanning, !isFixing else { return }
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
        guard !isScanning, !isFixing else { return }
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
        guard !isEditing else { return }
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
        guard !isLoading, !isInstalling, !isUninstalling else { return }
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
        guard !isLoading, !isInstalling, !isUninstalling else { return }
        isInstalling = true
        installMessage = nil
        Task {
            do {
                _ = try await BridgeProcess.shared.installIntegration()
                self.isInstalling = false
                self.installMessage = LanguageManager.shared.t(.installSuccess)
                self.runDoctor()
            } catch {
                self.isInstalling = false
                self.errorMessage = error.localizedDescription
                self.showErrorAlert = true
            }
        }
    }

    public func uninstallIntegration() {
        guard !isLoading, !isInstalling, !isUninstalling else { return }
        isUninstalling = true
        installMessage = nil
        Task {
            do {
                _ = try await BridgeProcess.shared.uninstallIntegration()
                self.isUninstalling = false
                self.installMessage = LanguageManager.shared.t(.uninstallSuccess)
                self.runDoctor()
            } catch {
                self.isUninstalling = false
                self.errorMessage = error.localizedDescription
                self.showErrorAlert = true
            }
        }
    }
}
