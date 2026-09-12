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
            PresentationCommands(
                languageManager: languageManager,
                batchRepairVM: batchRepairVM,
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


private struct PresentationCommands: Commands {
    @ObservedObject var languageManager: LanguageManager
    @ObservedObject var batchRepairVM: BatchRepairViewModel
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
        }
    }
}
