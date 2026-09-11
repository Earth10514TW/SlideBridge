import SwiftUI

struct OriginEditView: View {
    @StateObject private var vm = OriginEditViewModel()
    @EnvironmentObject private var lm: LanguageManager

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                // Header
                VStack(alignment: .leading, spacing: 6) {
                    Label(lm.t(.originEditTitle), systemImage: "chart.xyaxis.line")
                        .font(.title2.bold())
                    Text(lm.t(.originEditSubtitle))
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }

                Divider()

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
                .padding(20)
                .background(RoundedRectangle(cornerRadius: 14).fill(Color(nsColor: .controlBackgroundColor)))

                // Result Card
                if let report = vm.editReport {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack {
                            Image(systemName: "checkmark.seal.fill")
                                .foregroundStyle(.green)
                                .font(.title2)
                            Text(lm.t(.editSuccessTitle))
                                .font(.headline)
                        }

                        VStack(alignment: .leading, spacing: 6) {
                            HStack {
                                Text(lm.t(.presFileLabel)).font(.caption.bold())
                                Text(URL(fileURLWithPath: report.presentation).lastPathComponent).font(.caption)
                            }
                            HStack {
                                Text(lm.t(.slideAndShapeLabel)).font(.caption.bold())
                                Text("Slide \(report.slide_index) (Shape: \(report.shape_name))").font(.caption)
                            }
                            HStack {
                                Text(lm.t(.oleBinaryLabel)).font(.caption.bold())
                                Text(report.member).font(.caption)
                            }
                            if let backup = report.backup {
                                HStack {
                                    Text(lm.t(.backupPresLabel)).font(.caption.bold())
                                    Text(URL(fileURLWithPath: backup).lastPathComponent).font(.caption).foregroundStyle(.secondary)
                                }
                            }
                        }
                        .padding(12)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(RoundedRectangle(cornerRadius: 8).fill(Color(nsColor: .windowBackgroundColor)))

                        Text(lm.t(.hotReloadNotice))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .padding(16)
                    .background(RoundedRectangle(cornerRadius: 12).fill(Color.green.opacity(0.08)))
                }

                // Workflow Instructions
                VStack(alignment: .leading, spacing: 14) {
                    Text(lm.t(.guideTitle))
                        .font(.headline)

                    VStack(alignment: .leading, spacing: 10) {
                        stepRow(num: "1", title: lm.t(.step1Title), desc: lm.t(.step1Desc))
                        stepRow(num: "2", title: lm.t(.step2Title), desc: lm.t(.step2Desc))
                        stepRow(num: "3", title: lm.t(.step3Title), desc: lm.t(.step3Desc))
                        stepRow(num: "4", title: lm.t(.step4Title), desc: lm.t(.step4Desc))
                    }
                }
                .padding(20)
                .background(RoundedRectangle(cornerRadius: 14).fill(Color(nsColor: .controlBackgroundColor).opacity(0.6)))
            }
            .padding(24)
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
                    .frame(width: 24, height: 24)
                Text(num)
                    .font(.caption.bold())
                    .foregroundStyle(Color.accentColor)
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.subheadline.bold())
                Text(desc)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }
}
