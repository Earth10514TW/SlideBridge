import SwiftUI

struct ContentView: View {
    @StateObject private var appState = AppState()
    @EnvironmentObject private var lm: LanguageManager

    var body: some View {
        NavigationSplitView {
            VStack(alignment: .leading, spacing: 0) {
                // Sidebar Header / Branding
                HStack(spacing: 10) {
                    Image(systemName: "chart.bar.doc.horizontal.fill")
                        .font(.title2)
                        .foregroundStyle(Color.accentColor)

                    VStack(alignment: .leading, spacing: 1) {
                        Text(lm.t(.appName))
                            .font(.headline.bold())
                        Text(lm.t(.appSubtitle))
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 14)

                Divider()

                // Navigation List
                List(AppTab.allCases, selection: $appState.selectedTab) { tab in
                    NavigationLink(value: tab) {
                        Label(tab.title(using: lm), systemImage: tab.iconName)
                            .font(.subheadline)
                            .padding(.vertical, 4)
                    }
                }
                .listStyle(.sidebar)

                Spacer()

                Divider()

                // Sidebar Footer
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(lm.t(.version))
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                        Text(lm.t(.nativeArch))
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                    }
                    Spacer()
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
            }
            .navigationSplitViewColumnWidth(min: 190, ideal: 220, max: 260)
        } detail: {
            Group {
                switch appState.selectedTab {
                case .batchRepair:
                    BatchRepairView()
                case .originEdit:
                    OriginEditView()
                case .doctor:
                    DoctorView()
                }
            }
            .frame(minWidth: 540, minHeight: 480)
            .toolbar {
                ToolbarItem(placement: .automatic) {
                    Menu {
                        Picker("Language", selection: $lm.currentLanguage) {
                            ForEach(AppLanguage.allCases) { lang in
                                Text(lang.displayName).tag(lang)
                            }
                        }
                    } label: {
                        Label(lm.effectiveLanguage == .en ? "English" : "繁體中文", systemImage: "globe")
                            .font(.subheadline)
                    }
                    .help(lm.t(.language))
                }
            }
        }
    }
}
