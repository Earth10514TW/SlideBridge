import SwiftUI
import UniformTypeIdentifiers

struct BatchRepairView: View {
    @StateObject private var vm = BatchRepairViewModel()
    @EnvironmentObject private var lm: LanguageManager

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                // Header
                VStack(alignment: .leading, spacing: 6) {
                    Label(lm.t(.repairTitle), systemImage: "wand.and.stars")
                        .font(.title2.bold())
                    Text(lm.t(.repairSubtitle))
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }

                Divider()

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
            .padding(24)
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
                    .scaleEffect(vm.isDropTargeted ? 1.1 : 1.0)
                    .animation(.spring(response: 0.3), value: vm.isDropTargeted)
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
            .controlSize(.regular)
        }
        .frame(maxWidth: .infinity)
        .frame(height: 280)
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
                    .font(.system(size: 40))
                    .foregroundStyle(.orange)

                VStack(alignment: .leading, spacing: 4) {
                    Text(file.lastPathComponent)
                        .font(.headline)
                        .lineLimit(1)
                    Text(file.path)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }

                Spacer()

                Button {
                    vm.reset()
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(.title3)
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(.plain)
            }
            .padding()
            .background(RoundedRectangle(cornerRadius: 12).fill(Color(nsColor: .controlBackgroundColor)))

            // Scan Info Card
            if vm.isScanning {
                HStack(spacing: 12) {
                    ProgressView()
                        .controlSize(.small)
                    Text(lm.t(.scanningMessage))
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                .padding()
            } else if let scan = vm.scanReport {
                VStack(alignment: .leading, spacing: 12) {
                    Text(lm.t(.scanResultsTitle))
                        .font(.headline)

                    HStack(spacing: 20) {
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
                .padding()
                .background(RoundedRectangle(cornerRadius: 12).fill(Color(nsColor: .controlBackgroundColor)))

                // Options
                HStack {
                    Text(lm.t(.previewDpiLabel))
                        .font(.subheadline)

                    Picker("", selection: $vm.selectedDPI) {
                        Text(lm.t(.dpi150)).tag(150)
                        Text(lm.t(.dpi300)).tag(300)
                        Text(lm.t(.dpi600)).tag(600)
                    }
                    .pickerStyle(.segmented)
                    .frame(maxWidth: 380)
                }
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
                    HStack {
                        Button {
                            vm.startRepair()
                        } label: {
                            Label(lm.t(.startRepairButton), systemImage: "wand.and.stars")
                                .font(.headline)
                                .frame(minWidth: 160)
                        }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.large)

                        Spacer()

                        Button(lm.t(.changeFileButton)) {
                            vm.reset()
                        }
                        .buttonStyle(.bordered)
                    }
                    .padding(.top, 8)
                }
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
                    Text(URL(fileURLWithPath: fix.output).lastPathComponent)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                Text(fix.output)
                    .font(.caption)
                    .foregroundStyle(.tertiary)
                    .lineLimit(1)
            }
            .padding()
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))

            HStack(spacing: 16) {
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

                Spacer()

                Button(lm.t(.repairAnother)) {
                    vm.reset()
                }
                .buttonStyle(.plain)
                .foregroundStyle(Color.accentColor)
            }
        }
        .padding(24)
        .background(
            RoundedRectangle(cornerRadius: 16)
                .fill(Color(nsColor: .controlBackgroundColor).opacity(0.5))
        )
    }

    private func statPill(title: String, count: String, icon: String, color: Color) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Image(systemName: icon)
                    .foregroundStyle(color)
                Text(title)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Text(count)
                .font(.title2.bold())
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 8).fill(Color(nsColor: .windowBackgroundColor)))
    }
}
