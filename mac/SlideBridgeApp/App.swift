import SwiftUI

@main
struct SlideBridgeApp: App {
    @StateObject private var languageManager = LanguageManager.shared

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(languageManager)
                .frame(minWidth: 760, idealWidth: 840, minHeight: 520, idealHeight: 600)
        }
        .windowStyle(.titleBar)
        .windowToolbarStyle(.unified)
        .commands {
            SidebarCommands()
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
        }
    }
}
