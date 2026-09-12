import SwiftUI

struct OriginEditView: View {
    @ObservedObject var vm: OriginEditViewModel
    @EnvironmentObject private var lm: LanguageManager

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                // Header
                WorkspaceHeader(title: lm.t(.originEditTitle), subtitle: lm.t(.originEditSubtitle), icon: "chart.xyaxis.line")

                // Trigger Action Card
                VStack(alignment: .leading, spacing: 16) {
                    HStack(spacing: 14) {
                        ZStack {
                            Circle()
                                .fill(Color.blue.opacity(0.12))
                                .frame(width: 54, height: 54)
                            Image(systemName: "macbook.and.ipad")
                                .font(.system(size: 26))
                                .foregroundStyle(.blue)
                        }

                        VStack(alignment: .leading, spacing: 4) {
                            Text(lm.t(.crossMachineHeader))
                                .font(.headline)
                            Text(lm.t(.crossMachineHint))
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }

                        Spacer()
                    }

                    if vm.isEditing {
                        VStack(spacing: 12) {
                            ProgressView()
                                .controlSize(.regular)
                            Text(lm.t(.editingConnecting))
                                .font(.headline)
                            Text(lm.t(.editingInstruction))
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 24)
                        .background(RoundedRectangle(cornerRadius: 12).fill(Color(nsColor: .windowBackgroundColor)))
                    } else {
                        Button {
                            vm.triggerActiveEdit()
                        } label: {
                            Label(lm.t(.editSelectedChartButton), systemImage: "arrow.triangle.2.circlepath.circle.fill")
                                .font(.headline)
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.large)
                    }
                }
                .workspaceCard()

                // Double-Click Auto-Intercept Card
                VStack(alignment: .leading, spacing: 14) {
                    HStack(alignment: .center, spacing: 12) {
                        Image(systemName: "cursorarrow.rays")
                            .font(.system(size: 20, weight: .semibold))
                            .foregroundStyle(vm.statusColor)
                            .frame(width: 40, height: 40)
                            .background(vm.statusColor.opacity(0.12), in: RoundedRectangle(cornerRadius: 10))

                        VStack(alignment: .leading, spacing: 3) {
                            HStack(spacing: 8) {
                                Text(lm.t(.doubleClickInterceptTitle))
                                    .font(.headline)

                                // Status Badge
                                HStack(spacing: 5) {
                                    Circle()
                                        .fill(vm.statusColor)
                                        .frame(width: 7, height: 7)
                                    Text(vm.statusText(using: lm))
                                        .font(.caption2.bold())
                                        .foregroundStyle(vm.statusColor)
                                }
                                .padding(.horizontal, 8)
                                .padding(.vertical, 3)
                                .background(vm.statusColor.opacity(0.12), in: Capsule())
                            }

                            Text(lm.t(.doubleClickInterceptDesc))
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }

                        Spacer()

                        Toggle(lm.t(.interceptorToggle), isOn: $vm.isDoubleCLickInterceptorEnabled)
                            .toggleStyle(.switch)
                            .labelsHidden()
                    }
                    if vm.isDoubleCLickInterceptorEnabled && !vm.isAccessibilityGranted {
                        Button(lm.t(.interceptorOpenSettings)) {
                            PPTAlertInterceptor.openAccessibilityPreferences()
                        }
                        .buttonStyle(.link)
                    }
                }
                .workspaceCard()

                // Result Card
                if let report = vm.editReport {
                    let isUnchanged = report.status == "unchanged"
                    let isCancelled = report.status == "cancelled"
                    let statusColor: Color = isUnchanged ? .blue : (isCancelled ? .secondary : .green)
                    let statusIcon: String = isUnchanged ? "info.circle.fill" : (isCancelled ? "xmark.circle.fill" : "checkmark.seal.fill")
                    let statusTitle: String = isUnchanged ? lm.t(.editUnchangedTitle) : (isCancelled ? lm.t(.editCancelledTitle) : lm.t(.editSuccessTitle))

                    VStack(alignment: .leading, spacing: 12) {
                        HStack {
                            Image(systemName: statusIcon)
                                .foregroundStyle(statusColor)
                                .font(.title2)
                            Text(statusTitle)
                                .font(.headline)
                        }

                        VStack(alignment: .leading, spacing: 6) {
                            HStack {
                                Text(lm.t(.presFileLabel)).font(.caption.bold())
                                Text(URL(fileURLWithPath: report.presentation).lastPathComponent).font(.caption)
                                    .textSelection(.enabled)
                                    .help(report.presentation)
                            }
                            HStack {
                                Text(lm.t(.slideAndShapeLabel)).font(.caption.bold())
                                Text("Slide \(report.slide_index) (Shape: \(report.shape_name))").font(.caption)
                            }
                            HStack {
                                Text(lm.t(.oleBinaryLabel)).font(.caption.bold())
                                Text(report.member).font(.caption)
                                    .textSelection(.enabled)
                            }
                            if let backup = report.backup {
                                HStack {
                                    Text(lm.t(.backupPresLabel)).font(.caption.bold())
                                    Text(URL(fileURLWithPath: backup).lastPathComponent).font(.caption).foregroundStyle(.secondary)
                                        .textSelection(.enabled)
                                        .help(backup)
                                }
                            }
                        }
                        .padding(12)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(RoundedRectangle(cornerRadius: 8).fill(Color(nsColor: .windowBackgroundColor)))

                        if isUnchanged {
                            Text(lm.t(.editUnchangedTip))
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        } else if !isCancelled {
                            Text(lm.t(.hotReloadNotice))
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    .padding(16)
                    .background(RoundedRectangle(cornerRadius: 12).fill(statusColor.opacity(0.08)))
                }

                // Workflow Instructions
                VStack(alignment: .leading, spacing: 14) {
                    Text(lm.t(.guideTitle))
                        .font(.headline)

                    VStack(alignment: .leading, spacing: 18) {
                        stepRow(num: "1", title: lm.t(.step1Title), desc: lm.t(.step1Desc))
                        stepRow(num: "2", title: lm.t(.step2Title), desc: lm.t(.step2Desc))
                        stepRow(num: "3", title: lm.t(.step3Title), desc: lm.t(.step3Desc))
                        stepRow(num: "4", title: lm.t(.step4Title), desc: lm.t(.step4Desc))
                    }
                }
                .workspaceCard()
            }
            .frame(maxWidth: 920, alignment: .leading)
            .padding(28)
            .frame(maxWidth: .infinity, alignment: .top)
        }
        .alert(lm.t(.editFailedAlert), isPresented: $vm.showErrorAlert) {
            Button(lm.t(.ok), role: .cancel) {}
        } message: {
            Text(vm.errorMessage ?? lm.t(.unknownError))
        }
    }

    private func stepRow(num: String, title: String, desc: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            ZStack {
                Circle()
                    .fill(Color.accentColor.opacity(0.15))
                    .frame(width: 30, height: 30)
                Text(num)
                    .font(.caption.bold())
                    .foregroundStyle(Color.accentColor)
            }
            VStack(alignment: .leading, spacing: 5) {
                Text(title)
                    .font(.subheadline.bold())
                Text(desc)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }
}
