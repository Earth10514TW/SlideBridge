import SwiftUI

struct DoctorView: View {
    @StateObject private var vm = DoctorViewModel()
    @EnvironmentObject private var lm: LanguageManager

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                // Header
                HStack {
                    VStack(alignment: .leading, spacing: 6) {
                        Label(lm.t(.doctorTitle), systemImage: "stethoscope")
                            .font(.title2.bold())
                        Text(lm.t(.doctorSubtitle))
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }

                    Spacer()

                    Button {
                        vm.runDoctor()
                    } label: {
                        Label(lm.t(.refreshButton), systemImage: "arrow.clockwise")
                    }
                    .buttonStyle(.bordered)
                    .disabled(vm.isLoading)
                }

                Divider()

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
                        Picker("", selection: $lm.currentLanguage) {
                            ForEach(AppLanguage.allCases) { lang in
                                Text(lang.displayName).tag(lang)
                            }
                        }
                        .pickerStyle(.segmented)
                        .frame(maxWidth: 380)

                        Spacer()
                    }
                }
                .padding(18)
                .background(RoundedRectangle(cornerRadius: 14).fill(Color(nsColor: .controlBackgroundColor)))

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
                                                .font(.caption)
                                                .foregroundStyle(.secondary)

                                            if let fix = check.fix, !fix.isEmpty {
                                                Text("\(lm.t(.suggestionPrefix))\(fix)")
                                                    .font(.caption2)
                                                    .foregroundStyle(.orange)
                                                    .padding(.top, 2)
                                            }
                                        }

                                        Spacer()
                                    }
                                    .padding(.vertical, 10)
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
                                vm.uninstallIntegration()
                            } label: {
                                Label(lm.t(.uninstallButton), systemImage: "trash")
                            }
                            .buttonStyle(.bordered)
                        }
                    }

                    if let msg = vm.installMessage {
                        Text(msg)
                            .font(.caption)
                            .foregroundStyle(.green)
                            .padding(.top, 4)
                    }
                }
                .padding(20)
                .background(RoundedRectangle(cornerRadius: 14).fill(Color(nsColor: .controlBackgroundColor).opacity(0.6)))
            }
            .padding(24)
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
    }
}
