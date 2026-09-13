import SwiftUI

struct ContentView: View {
    @StateObject private var appState: AppState
    @StateObject private var batchRepairVM: BatchRepairViewModel
    @StateObject private var originEditVM: OriginEditViewModel
    @StateObject private var doctorVM: DoctorViewModel
    @EnvironmentObject private var lm: LanguageManager

    @MainActor
    init(
        appState: AppState? = nil,
        batchVM: BatchRepairViewModel? = nil,
        originVM: OriginEditViewModel? = nil,
        doctorVM: DoctorViewModel? = nil
    ) {
        _appState = StateObject(wrappedValue: appState ?? AppState())
        _batchRepairVM = StateObject(wrappedValue: batchVM ?? BatchRepairViewModel())
        _originEditVM = StateObject(wrappedValue: originVM ?? OriginEditViewModel())
        _doctorVM = StateObject(wrappedValue: doctorVM ?? DoctorViewModel())
    }

    var body: some View {
        NavigationSplitView {
            VStack(alignment: .leading, spacing: 0) {
                // Sidebar Header / Branding
                HStack(spacing: 10) {
                    Image(systemName: "chart.bar.doc.horizontal.fill")
                        .font(.system(size: 17, weight: .semibold))
                        .foregroundStyle(.white)
                        .frame(width: 32, height: 32)
                        .background(Color.accentColor.gradient, in: RoundedRectangle(cornerRadius: 12))

                    VStack(alignment: .leading, spacing: 1) {
                        Text(lm.t(.appName))
                            .font(.headline.bold())
                        Text(lm.t(.appSubtitle))
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 16)

                Divider()

                // Navigation List
                // Rows are tagged with AppTab so the selection type matches
                // `appState.selectedTab` exactly. A NavigationLink here would
                // draw a second, offset selection highlight on top of the
                // list's own one.
                List(selection: $appState.selectedTab) {
                    ForEach(AppTab.allCases) { tab in
                        Label(tab.title(using: lm), systemImage: tab.iconName)
                            .font(.system(size: 13, weight: .medium))
                            .tag(tab)
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
                    }
                    Spacer()
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
            }
            .navigationSplitViewColumnWidth(min: 210, ideal: 230, max: 280)
        } detail: {
            Group {
                switch appState.selectedTab {
                case .batchRepair:
                    BatchRepairView(vm: batchRepairVM)
                case .originEdit:
                    OriginEditView(vm: originEditVM)
                case .doctor:
                    DoctorView(vm: doctorVM, appState: appState)
                }
            }
            .frame(minWidth: 540, minHeight: 480)
            .background(Color(nsColor: .windowBackgroundColor))
            .sheet(isPresented: $appState.showOnboardingSheet) {
                OnboardingView(appState: appState, doctorVM: doctorVM)
                    .environmentObject(lm)
            }
            .toolbar {
                ToolbarItem(placement: .automatic) {
                    // A Picker nested in a Menu renders as an extra "Language"
                    // submenu, forcing a second click. Flat buttons show the
                    // three choices immediately, with a checkmark on the
                    // current one.
                    Menu {
                        ForEach([AppLanguage.zhTW, AppLanguage.en, AppLanguage.system]) { lang in
                            Button {
                                lm.currentLanguage = lang
                            } label: {
                                if lm.currentLanguage == lang {
                                    Label(lang.menuLabel(using: lm), systemImage: "checkmark")
                                } else {
                                    Text(lang.menuLabel(using: lm))
                                }
                            }
                        }
                    } label: {
                        Label(lm.effectiveLanguage == .en ? "English" : "繁體中文", systemImage: "globe")
                            .font(.subheadline)
                    }
                    .labelStyle(.titleAndIcon)
                    .help(lm.t(.language))
                }
            }
        }
    }
}

/// Consistent page hierarchy across the app's three workspaces.
struct WorkspaceHeader: View {
    let title: String
    let subtitle: String
    let icon: String

    var body: some View {
        HStack(alignment: .top, spacing: 16) {
            Image(systemName: icon)
                .font(.system(size: 24, weight: .medium))
                .foregroundStyle(Color.accentColor)
                .frame(width: 52, height: 52)
                .background(Color.accentColor.opacity(0.1), in: RoundedRectangle(cornerRadius: 14))
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 7) {
                Text(title)
                    .font(.title2.bold())
                    .fixedSize(horizontal: false, vertical: true)
                Text(subtitle)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
        }
        .padding(.bottom, 8)
    }
}

extension View {
    func workspaceCard() -> some View {
        modifier(WorkspaceCardModifier())
    }
}

private struct WorkspaceCardModifier: ViewModifier {
    @Environment(\.colorSchemeContrast) private var colorSchemeContrast

    func body(content: Content) -> some View {
        content
            .padding(20)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 16))
            .overlay(
                RoundedRectangle(cornerRadius: 16)
                    .strokeBorder(Color.primary.opacity(colorSchemeContrast == .increased ? 0.5 : 0.08))
            )
    }
}
