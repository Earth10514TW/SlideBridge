import SwiftUI

@main
struct SlideBridgeApp: App {
    @StateObject private var languageManager = LanguageManager.shared
    @StateObject private var appState = AppState()
    @StateObject private var batchRepairVM = BatchRepairViewModel()
    @StateObject private var originEditVM = OriginEditViewModel()
    @StateObject private var doctorVM = DoctorViewModel()

    var body: some Scene {
        WindowGroup {
            ContentView(
                appState: appState,
                batchVM: batchRepairVM,
                originVM: originEditVM,
                doctorVM: doctorVM
            )
            .environmentObject(languageManager)
            .frame(minWidth: 760, idealWidth: 1000, minHeight: 520, idealHeight: 720)
        }
        .windowStyle(.titleBar)
        .windowToolbarStyle(.unified)
        .commands {
            SidebarCommands()
            FileCommands(
                languageManager: languageManager,
                batchRepairVM: batchRepairVM,
                originEditVM: originEditVM,
                appState: appState
            )
            CommandMenu(languageManager.t(.languageMenu)) {
                Button("繁體中文") {
                    languageManager.currentLanguage = .zhTW
                }
                Button("English") {
                    languageManager.currentLanguage = .en
                }
                Divider()
                Button(languageManager.t(.systemDefault)) {
                    languageManager.currentLanguage = .system
                }
            }
            CommandGroup(after: .help) {
                Button(languageManager.t(.setupGuideMenu)) {
                    appState.resetAndShowOnboarding()
                }
            }
        }
    }
}


private struct FileCommands: Commands {
    @ObservedObject var languageManager: LanguageManager
    @ObservedObject var batchRepairVM: BatchRepairViewModel
    @ObservedObject var originEditVM: OriginEditViewModel
    @ObservedObject var appState: AppState

    var body: some Commands {
        CommandGroup(after: .newItem) {
            Button(languageManager.t(.selectFileButton)) {
                guard !batchRepairVM.isScanning, !batchRepairVM.isFixing, !batchRepairVM.isSelectingFile else { return }
                appState.selectedTab = .batchRepair
                batchRepairVM.selectFile()
            }
            .keyboardShortcut("o", modifiers: .command)
            .disabled(batchRepairVM.isScanning || batchRepairVM.isFixing || batchRepairVM.isSelectingFile)

            Divider()

            // Reachable from any tab: backups outlive the edit that created
            // them, so discarding them should not require finding that page.
            Button(languageManager.t(.backupClearAllMenu)) {
                appState.selectedTab = .originEdit
                originEditVM.requestClearAllBackups()
            }
            .disabled(originEditVM.isBackupBusy || (originEditVM.backupList?.count ?? 0) == 0)
        }
    }
}
