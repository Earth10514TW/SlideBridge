import SwiftUI

struct DoctorView: View {
    @StateObject private var confirmation = IntegrationConfirmation()
    @ObservedObject var vm: DoctorViewModel
    @EnvironmentObject private var lm: LanguageManager

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                // Header
                HStack {
                    WorkspaceHeader(title: lm.t(.doctorTitle), subtitle: lm.t(.doctorSubtitle), icon: "stethoscope")

                    Spacer()

                    Button {
                        vm.runDoctor()
                    } label: {
                        Label(lm.t(.refreshButton), systemImage: "arrow.clockwise")
                    }
                    .buttonStyle(.bordered)
                    .disabled(vm.isLoading || vm.isInstalling || vm.isUninstalling)
                }

                // Overall Health Banner
                if let report = vm.doctorReport {
                    HStack(spacing: 16) {
                        Image(systemName: report.ready ? "checkmark.seal.fill" : "exclamationmark.triangle.fill")
                            .font(.system(size: 32))
                            .foregroundStyle(report.ready ? .green : .yellow)

                        VStack(alignment: .leading, spacing: 4) {
                            Text(report.ready ? lm.t(.envReady) : lm.t(.envNeedConfig))
                                .font(.headline)
                            Text(lm.t(.envStats(passed: report.checks.filter { $0.status == "ok" }.count, warns: report.warnings, fails: report.failures)))
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }

                        Spacer()
                    }
                    .padding(16)
                    .background(
                        RoundedRectangle(cornerRadius: 12)
                            .fill((report.ready ? Color.green : Color.yellow).opacity(0.1))
                    )
                }

                // Language Preferences Card
                VStack(alignment: .leading, spacing: 12) {
                    Label(lm.t(.interfaceLanguage), systemImage: "globe")
                        .font(.headline)

                    HStack(spacing: 16) {
                        Picker(lm.t(.interfaceLanguage), selection: $lm.currentLanguage) {
                            ForEach(AppLanguage.allCases) { lang in
                                Text(lang.displayName).tag(lang)
                            }
                        }
                        .pickerStyle(.segmented)
                    .labelsHidden()
                        .frame(maxWidth: 380)

                        Spacer()
                    }
                }
                .workspaceCard()

                // Checks List
                if vm.isLoading {
                    HStack(spacing: 12) {
                        ProgressView()
                            .controlSize(.small)
                        Text(lm.t(.diagnosingProgress))
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                    .frame(maxWidth: .infinity, alignment: .center)
                    .padding(.vertical, 30)
                } else if let report = vm.doctorReport {
                    VStack(alignment: .leading, spacing: 10) {
                        Text(lm.t(.checkListTitle))
                            .font(.headline)

                        VStack(spacing: 0) {
                            ForEach(Array(report.checks.enumerated()), id: \.element.id) { index, check in
                                VStack(alignment: .leading, spacing: 6) {
                                    HStack(alignment: .top, spacing: 12) {
                                        statusIcon(status: check.status)

                                        VStack(alignment: .leading, spacing: 2) {
                                            Text(check.name)
                                                .font(.subheadline.bold())
                                            Text(check.detail)
                                                .textSelection(.enabled)
                                                .font(.caption)
                                                .foregroundStyle(.secondary)

                                            if let fix = check.fix, !fix.isEmpty {
                                                Text("\(lm.t(.suggestionPrefix))\(fix)")
                                                    .font(.caption)
                                                    .foregroundStyle(.secondary)
                                                    .padding(.top, 2)
                                            }
                                        }

                                        Spacer()
                                    }
                                    .padding(.vertical, 14)
                                    .padding(.horizontal, 12)

                                    if index < report.checks.count - 1 {
                                        Divider()
                                    }
                                }
                            }
                        }
                        .background(RoundedRectangle(cornerRadius: 12).fill(Color(nsColor: .controlBackgroundColor)))
                    }
                }

                // macOS System Integration Management
                VStack(alignment: .leading, spacing: 14) {
                    Label(lm.t(.integrationTitle), systemImage: "gearshape.2")
                        .font(.headline)

                    Text(lm.t(.integrationDesc))
                        .font(.caption)
                        .foregroundStyle(.secondary)

                    if vm.isInstalling || vm.isUninstalling {
                        HStack(spacing: 10) {
                            ProgressView().controlSize(.small)
                            Text(vm.isInstalling ? lm.t(.installingMsg) : lm.t(.uninstallingMsg))
                                .font(.caption)
                        }
                    } else {
                        HStack(spacing: 14) {
                            Button {
                                vm.installIntegration()
                            } label: {
                                Label(lm.t(.installButton), systemImage: "arrow.down.doc")
                            }
                            .buttonStyle(.borderedProminent)

                            Button(role: .destructive) {
                                confirmation.isPresented = true
                            } label: {
                                Label(lm.t(.uninstallButton), systemImage: "trash")
                            }
                            .buttonStyle(.bordered)
                        }
                        .disabled(vm.isLoading)
                    }

                    if let msg = vm.installMessage {
                        Text(msg)
                            .font(.caption)
                            .foregroundStyle(.green)
                            .padding(.top, 4)
                    }
                }
                .workspaceCard()
            }
            .frame(maxWidth: 920, alignment: .leading)
            .padding(28)
            .frame(maxWidth: .infinity, alignment: .top)
        }
        .alert(lm.t(.uninstallConfirmation), isPresented: $confirmation.isPresented) {
            Button(lm.t(.uninstallButton), role: .destructive) { vm.uninstallIntegration() }
            Button(lm.t(.cancel), role: .cancel) {}
        } message: {
            Text(lm.t(.uninstallExplanation))
        }
        .onAppear {
            if vm.doctorReport == nil {
                vm.runDoctor()
            }
        }
        .alert(lm.t(.doctorFailedAlert), isPresented: $vm.showErrorAlert) {
            Button(lm.t(.ok), role: .cancel) {}
        } message: {
            Text(vm.errorMessage ?? lm.t(.unknownError))
        }
    }

    private func statusIcon(status: String) -> some View {
        Group {
            switch status.lowercased() {
            case "ok":
                Image(systemName: "checkmark.circle.fill")
                    .foregroundStyle(.green)
            case "warn":
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(.yellow)
            case "fail":
                Image(systemName: "xmark.circle.fill")
                    .foregroundStyle(.red)
            default:
                Image(systemName: "info.circle.fill")
                    .foregroundStyle(.blue)
            }
        }
        .font(.title3)
        .accessibilityLabel(statusLabel(status))
        .help(statusLabel(status))
    }

    private func statusLabel(_ status: String) -> String {
        switch status.lowercased() {
        case "ok": return lm.t(.statusPassed)
        case "warn": return lm.t(.statusWarning)
        case "fail": return lm.t(.statusFailed)
        default: return lm.t(.statusInfo)
        }
    }
}


private final class IntegrationConfirmation: ObservableObject {
    @Published var isPresented = false
}
