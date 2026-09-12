import SwiftUI
import UniformTypeIdentifiers

struct BatchRepairView: View {
    @ObservedObject var vm: BatchRepairViewModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @EnvironmentObject private var lm: LanguageManager

    private var isBusy: Bool {
        vm.isScanning || vm.isFixing
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                WorkspaceHeader(
                    title: lm.t(.repairTitle),
                    subtitle: lm.t(.repairSubtitle),
                    icon: "wand.and.stars"
                )

                if let fix = vm.fixReport {
                    // Success View
                    successCard(fix: fix)
                } else if let file = vm.selectedFileURL {
                    // File loaded view
                    fileLoadedCard(file: file)
                } else {
                    // Drop Zone
                    dropZone
                }
            }
            .frame(maxWidth: 920, alignment: .leading)
            .padding(28)
            .frame(maxWidth: .infinity, alignment: .top)
        }
        .alert(lm.t(.processingError), isPresented: $vm.showErrorAlert) {
            Button(lm.t(.ok), role: .cancel) {}
        } message: {
            Text(vm.errorMessage ?? lm.t(.unknownError))
        }
    }

    // MARK: - Drop Zone
    private var dropZone: some View {
        VStack(spacing: 16) {
            ZStack {
                Circle()
                    .fill(Color.accentColor.opacity(vm.isDropTargeted ? 0.2 : 0.08))
                    .frame(width: 80, height: 80)
                Image(systemName: vm.isDropTargeted ? "arrow.down.doc.fill" : "doc.badge.plus")
                    .font(.system(size: 36))
                    .foregroundStyle(Color.accentColor)
                    .scaleEffect(vm.isDropTargeted && !reduceMotion ? 1.1 : 1.0)
                    .animation(reduceMotion ? nil : .spring(response: 0.3), value: vm.isDropTargeted)
            }

            VStack(spacing: 4) {
                Text(lm.t(.dropTitle))
                    .font(.headline)
                Text(lm.t(.dropSubtitle))
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            Button {
                vm.selectFile()
            } label: {
                Label(lm.t(.selectFileButton), systemImage: "folder")
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
        }
        .frame(maxWidth: .infinity)
        .frame(minHeight: 280)
        .background(
            RoundedRectangle(cornerRadius: 16)
                .strokeBorder(
                    Color.accentColor.opacity(vm.isDropTargeted ? 0.8 : 0.25),
                    style: StrokeStyle(lineWidth: vm.isDropTargeted ? 2.5 : 1.5, dash: [8, 6])
                )
                .background(
                    RoundedRectangle(cornerRadius: 16)
                        .fill(Color(nsColor: .controlBackgroundColor).opacity(vm.isDropTargeted ? 0.6 : 0.3))
                )
        )
        .onDrop(of: [.fileURL], isTargeted: $vm.isDropTargeted) { providers in
            guard let provider = providers.first else { return false }
            _ = provider.loadObject(ofClass: URL.self) { url, _ in
                guard let url = url, url.pathExtension.lowercased() == "pptx" else {
                    Task { @MainActor in
                        vm.errorMessage = lm.t(.invalidPptxError)
                        vm.showErrorAlert = true
                    }
                    return
                }
                Task { @MainActor in
                    vm.loadAndScanFile(url: url)
                }
            }
            return true
        }
    }

    // MARK: - File Loaded Card
    private func fileLoadedCard(file: URL) -> some View {
        VStack(alignment: .leading, spacing: 18) {
            // File Header
            HStack(spacing: 14) {
                Image(systemName: "doc.fill")
                    .font(.system(size: 21, weight: .semibold))
                    .foregroundStyle(.white)
                    .frame(width: 46, height: 46)
                    .background(Color.orange.gradient, in: RoundedRectangle(cornerRadius: 12))
                    .accessibilityHidden(true)

                VStack(alignment: .leading, spacing: 4) {
                    Text(file.lastPathComponent)
                        .font(.headline)
                        .lineLimit(2)
                        .truncationMode(.middle)
                        .accessibilityLabel(Text(file.lastPathComponent))
                    Text(file.path)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                        .truncationMode(.middle)
                        .textSelection(.enabled)
                        .accessibilityLabel(Text(file.path))
                }

                .frame(maxWidth: .infinity, alignment: .leading)

                Button {
                    vm.reset()
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(.title3)
                        .foregroundStyle(.secondary)
                        .frame(width: 28, height: 28)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .disabled(isBusy)
                .accessibilityLabel(Text(lm.t(.changeFileButton)))
                .help(lm.t(.changeFileButton))
            }
            .workspaceCard()

            // Scan Info Card
            if vm.isScanning {
                HStack(spacing: 12) {
                    ProgressView()
                        .controlSize(.small)
                    Text(lm.t(.scanningMessage))
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    Spacer(minLength: 0)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .workspaceCard()
            } else if let scan = vm.scanReport {
                VStack(alignment: .leading, spacing: 12) {
                    Text(lm.t(.scanResultsTitle))
                        .font(.headline)

                    LazyVGrid(
                        columns: [GridItem(.adaptive(minimum: 145), spacing: 12)],
                        spacing: 12
                    ) {
                        statPill(title: lm.t(.brokenVectorCharts), count: "\(scan.media.count)", icon: "photo.badge.exclamationmark", color: .red)
                        statPill(title: lm.t(.emfCharts), count: "\(scan.emfCount)", icon: "chart.xyaxis.line", color: .orange)
                        statPill(title: lm.t(.embeddedOle), count: "\(scan.ole_objects)", icon: "cube.transparent", color: .blue)
                    }

                    if scan.media.isEmpty {
                        Text(lm.t(.noBrokenNotice))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                .workspaceCard()

                // Options
                VStack(alignment: .leading, spacing: 9) {
                    Text(lm.t(.previewDpiLabel))
                        .font(.subheadline.weight(.medium))

                    Picker(lm.t(.previewDpiLabel), selection: $vm.selectedDPI) {
                        Text(lm.t(.dpi150)).tag(150)
                        Text(lm.t(.dpi300)).tag(300)
                        Text(lm.t(.dpi600)).tag(600)
                    }
                    .pickerStyle(.segmented)
                    .labelsHidden()
                    .disabled(isBusy)
                }
                .frame(maxWidth: 420, alignment: .leading)
                .padding(.horizontal, 4)

                // Repair Button
                if vm.isFixing {
                    VStack(spacing: 10) {
                        ProgressView()
                        Text(lm.t(.fixingMessage))
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 20)
                } else {
                    ViewThatFits(in: .horizontal) {
                        HStack(spacing: 12) {
                            repairButton
                                .frame(maxWidth: .infinity, alignment: .leading)

                            changeFileButton
                        }
                        VStack(alignment: .leading, spacing: 10) {
                            repairButton
                                .frame(maxWidth: .infinity, alignment: .leading)
                            changeFileButton
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                    .padding(.top, 8)
                }
            } else if let error = vm.errorMessage {
                VStack(alignment: .leading, spacing: 12) {
                    Label(lm.t(.scanFailed), systemImage: "exclamationmark.triangle")
                        .font(.headline)
                    Text(error)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                    Button {
                        vm.loadAndScanFile(url: file)
                    } label: {
                        Label(lm.t(.retryScan), systemImage: "arrow.clockwise")
                    }
                    .buttonStyle(.borderedProminent)
                }
                .workspaceCard()
            }
        }
    }

    // MARK: - Success Card
    private func successCard(fix: FixReport) -> some View {
        VStack(spacing: 20) {
            ZStack {
                Circle()
                    .fill(Color.green.opacity(0.15))
                    .frame(width: 72, height: 72)
                Image(systemName: "checkmark.circle.fill")
                    .font(.system(size: 40))
                    .foregroundStyle(.green)
            }

            VStack(spacing: 6) {
                Text(lm.t(.repairCompleteTitle))
                    .font(.title3.bold())
                Text(lm.t(.repairCompleteDesc(count: fix.converted.count, dpi: vm.selectedDPI)))
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }

            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text(lm.t(.outputFileLabel))
                        .font(.subheadline.bold())
                    Spacer(minLength: 8)
                    Text(URL(fileURLWithPath: fix.output).lastPathComponent)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .truncationMode(.middle)
                }
                Text(fix.output)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                    .truncationMode(.middle)
                    .textSelection(.enabled)
            }
            .accessibilityElement(children: .combine)
            .accessibilityLabel(Text(URL(fileURLWithPath: fix.output).lastPathComponent))
            .accessibilityValue(Text(fix.output))
            .workspaceCard()

            ViewThatFits(in: .horizontal) {
                HStack(spacing: 12) {
                    outputActions(fix: fix)
                    Spacer(minLength: 0)
                    repairAnotherButton
                }
                VStack(alignment: .leading, spacing: 10) {
                    outputActions(fix: fix)
                    repairAnotherButton
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
        .padding(4)
    }

    private var repairButton: some View {
        Button {
            vm.startRepair()
        } label: {
            Label(lm.t(.startRepairButton), systemImage: "wand.and.stars")
                .font(.headline)
                .frame(minWidth: 160)
        }
        .buttonStyle(.borderedProminent)
        .controlSize(.large)
    }

    private var changeFileButton: some View {
        Button(lm.t(.changeFileButton)) {
            vm.reset()
        }
        .buttonStyle(.bordered)
        .disabled(isBusy)
    }

    private func outputActions(fix: FixReport) -> some View {
        Group {
            Button {
                let outURL = URL(fileURLWithPath: fix.output)
                NSWorkspace.shared.activateFileViewerSelecting([outURL])
            } label: {
                Label(lm.t(.revealInFinder), systemImage: "folder")
            }
            .buttonStyle(.bordered)

            Button {
                let outURL = URL(fileURLWithPath: fix.output)
                NSWorkspace.shared.open(outURL)
            } label: {
                Label(lm.t(.openInPowerPoint), systemImage: "play.circle")
            }
            .buttonStyle(.borderedProminent)
        }
    }

    private var repairAnotherButton: some View {
        Button(lm.t(.repairAnother)) {
            vm.reset()
        }
        .buttonStyle(.plain)
        .foregroundStyle(Color.accentColor)
    }

    private func statPill(title: String, count: String, icon: String, color: Color) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top, spacing: 7) {
                Image(systemName: icon)
                    .foregroundStyle(color)
                    .accessibilityHidden(true)
                Text(title)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Text(count)
                .font(.title2.bold())
        }
        .padding(13)
        .frame(maxWidth: .infinity, minHeight: 78, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 11).fill(Color(nsColor: .windowBackgroundColor)))
        .overlay(
            RoundedRectangle(cornerRadius: 11)
                .strokeBorder(color.opacity(0.14))
        )
        .accessibilityElement(children: .combine)
        .accessibilityLabel(Text(title))
        .accessibilityValue(Text(count))
    }
}
