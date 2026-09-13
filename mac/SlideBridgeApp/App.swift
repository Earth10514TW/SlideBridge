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
                languageMenuItem(.zhTW)
                languageMenuItem(.en)
                Divider()
                languageMenuItem(.system)
            }
            CommandGroup(after: .help) {
                Button(languageManager.t(.setupGuideMenu)) {
                    appState.resetAndShowOnboarding()
                }
            }
        }
    }

    /// Menu bar counterpart of the toolbar language switcher. Uses the same
    /// labels and the same checkmark so the two never drift apart.
    private func languageMenuItem(_ lang: AppLanguage) -> some View {
        Button {
            languageManager.currentLanguage = lang
        } label: {
            if languageManager.currentLanguage == lang {
                Label(lang.menuLabel(using: languageManager), systemImage: "checkmark")
            } else {
                Text(lang.menuLabel(using: languageManager))
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
