import SwiftUI

@MainActor
final class OnboardingViewModel: ObservableObject {
    @Published var currentStep: Int = 0
    @Published var isAccessibilityGranted: Bool = PPTAlertInterceptor.isAccessibilityTrusted()
    private var pollTimer: Timer? = nil

    func checkAccessibility() {
        isAccessibilityGranted = PPTAlertInterceptor.isAccessibilityTrusted()
    }

    func startPolling() {
        pollTimer?.invalidate()
        pollTimer = Timer.scheduledTimer(withTimeInterval: 1.5, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in
                self?.checkAccessibility()
            }
        }
    }

    func stopPolling() {
        pollTimer?.invalidate()
        pollTimer = nil
    }
}

struct OnboardingView: View {
    @ObservedObject var appState: AppState
    @ObservedObject var doctorVM: DoctorViewModel
    @StateObject private var vm = OnboardingViewModel()
    @EnvironmentObject private var lm: LanguageManager

    private let totalSteps = 4

    var body: some View {
        VStack(spacing: 0) {
            // Header with Step Indicator
            HStack {
                HStack(spacing: 8) {
                    ForEach(0..<totalSteps, id: \.self) { idx in
                        Capsule()
                            .fill(idx == vm.currentStep ? Color.accentColor : Color.secondary.opacity(0.25))
                            .frame(width: idx == vm.currentStep ? 24 : 8, height: 7)
                            .animation(.spring(response: 0.35, dampingFraction: 0.7), value: vm.currentStep)
                    }
                }

                Spacer()

                if vm.currentStep < totalSteps - 1 {
                    Button(lm.t(.cancel)) {
                        finishOnboarding()
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(.secondary)
                    .font(.subheadline)
                    .accessibilityLabel(lm.t(.cancel))
                    .accessibilityIdentifier("onboardingCancelButton")
                }
            }
            .padding(.horizontal, 28)
            .padding(.top, 22)
            .padding(.bottom, 14)

            Divider()

            // Step Content
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    switch vm.currentStep {
                    case 0:
                        welcomeStep
                    case 1:
                        usageModeStep
                    case 2:
                        setupAndPermissionsStep
                    case 3:
                        doneStep
                    default:
                        EmptyView()
                    }
                }
                .padding(28)
            }
            .frame(maxHeight: .infinity)

            Divider()

            // Footer Navigation
            HStack {
                if vm.currentStep > 0 {
                    Button {
                        withAnimation(.easeInOut(duration: 0.2)) {
                            vm.currentStep -= 1
                        }
                    } label: {
                        HStack(spacing: 4) {
                            Image(systemName: "chevron.left")
                            Text(lm.t(.onboardingBack))
                        }
                    }
                    .buttonStyle(.bordered)
                    .accessibilityLabel(lm.t(.onboardingBack))
                    .accessibilityIdentifier("onboardingBackButton")
                }

                Spacer()

                if vm.currentStep < totalSteps - 1 {
                    Button {
                        withAnimation(.easeInOut(duration: 0.2)) {
                            vm.currentStep += 1
                        }
                    } label: {
                        HStack(spacing: 4) {
                            Text(lm.t(.onboardingNext))
                            Image(systemName: "chevron.right")
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .accessibilityLabel(lm.t(.onboardingNext))
                    .accessibilityIdentifier("onboardingNextButton")
                } else {
                    Button {
                        finishOnboarding()
                    } label: {
                        HStack(spacing: 6) {
                            Text(lm.t(.startUsingApp))
                            Image(systemName: "arrow.right.circle.fill")
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .accessibilityLabel(lm.t(.startUsingApp))
                    .accessibilityIdentifier("onboardingFinishButton")
                }
            }
            .padding(.horizontal, 28)
            .padding(.vertical, 16)
            .background(Color(nsColor: .windowBackgroundColor))
        }
        .frame(width: 620, height: 520)
        .onAppear {
            vm.checkAccessibility()
            vm.startPolling()
            if doctorVM.doctorReport == nil {
                doctorVM.runDoctor()
            }
        }
        .onDisappear {
            vm.stopPolling()
        }
    }

    // MARK: - Step 0: Welcome & Language
    private var welcomeStep: some View {
        VStack(alignment: .leading, spacing: 22) {
            HStack(spacing: 16) {
                Image(systemName: "chart.bar.doc.horizontal.fill")
                    .font(.system(size: 28, weight: .semibold))
                    .foregroundStyle(.white)
                    .frame(width: 56, height: 56)
                    .background(Color.accentColor.gradient, in: RoundedRectangle(cornerRadius: 14))

                VStack(alignment: .leading, spacing: 4) {
                    Text(lm.t(.onboardingWelcomeTitle))
                        .font(.title2.bold())
                    Text(lm.t(.appSubtitle))
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            }

            Text(lm.t(.onboardingWelcomeDesc))
                .font(.body)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            // Language Selection Card
            VStack(alignment: .leading, spacing: 12) {
                Label(lm.t(.interfaceLanguage), systemImage: "globe")
                    .font(.headline)

                Picker(lm.t(.interfaceLanguage), selection: $lm.currentLanguage) {
                    ForEach(AppLanguage.allCases) { lang in
                        Text(lang.displayName).tag(lang)
                    }
                }
                .pickerStyle(.segmented)
                .labelsHidden()
            }
            .workspaceCard()
        }
    }

    // MARK: - Step 1: Usage Mode Selection
    private var usageModeStep: some View {
        VStack(alignment: .leading, spacing: 18) {
            VStack(alignment: .leading, spacing: 6) {
                Text(lm.t(.onboardingStepModeTitle))
                    .font(.title2.bold())
                Text(lm.t(.onboardingStepModeDesc))
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            // Mode 1: Full Origin Bridge
            Button {
                appState.selectedUsageMode = .fullBridge
            } label: {
                HStack(alignment: .top, spacing: 16) {
                    Image(systemName: appState.selectedUsageMode == .fullBridge ? "checkmark.circle.fill" : "circle")
                        .font(.title3)
                        .foregroundStyle(appState.selectedUsageMode == .fullBridge ? Color.accentColor : Color.secondary)
                        .padding(.top, 2)

                    VStack(alignment: .leading, spacing: 6) {
                        HStack {
                            Text(lm.t(.modeFullBridgeTitle))
                                .font(.headline)
                                .foregroundStyle(Color.primary)
                            Text(lm.t(.recommendedBadge))
                                .font(.caption2.bold())
                                .padding(.horizontal, 6)
                                .padding(.vertical, 2)
                                .background(Color.accentColor.opacity(0.15))
                                .foregroundStyle(Color.accentColor)
                                .clipShape(Capsule())
                        }

                        Text(lm.t(.modeFullBridgeDesc))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)

                        Text(lm.t(.modeFullBridgeReq))
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                            .padding(.top, 2)
                    }
                }
            }
            .buttonStyle(.plain)
            .workspaceCard()
            .overlay(
                RoundedRectangle(cornerRadius: 16)
                    .strokeBorder(appState.selectedUsageMode == .fullBridge ? Color.accentColor : Color.clear, lineWidth: 2)
            )

            // Mode 2: Batch Repair Only
            Button {
                appState.selectedUsageMode = .batchOnly
            } label: {
                HStack(alignment: .top, spacing: 16) {
                    Image(systemName: appState.selectedUsageMode == .batchOnly ? "checkmark.circle.fill" : "circle")
                        .font(.title3)
                        .foregroundStyle(appState.selectedUsageMode == .batchOnly ? Color.accentColor : Color.secondary)
                        .padding(.top, 2)

                    VStack(alignment: .leading, spacing: 6) {
                        Text(lm.t(.modeBatchOnlyTitle))
                            .font(.headline)
                            .foregroundStyle(Color.primary)

                        Text(lm.t(.modeBatchOnlyDesc))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)

                        Text(lm.t(.modeBatchOnlyReq))
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                            .padding(.top, 2)
                    }
                }
            }
            .buttonStyle(.plain)
            .workspaceCard()
            .overlay(
                RoundedRectangle(cornerRadius: 16)
                    .strokeBorder(appState.selectedUsageMode == .batchOnly ? Color.accentColor : Color.clear, lineWidth: 2)
            )
        }
    }

    // MARK: - Step 2: System Integration & Permissions
    private var setupAndPermissionsStep: some View {
        VStack(alignment: .leading, spacing: 18) {
            VStack(alignment: .leading, spacing: 6) {
                Text(lm.t(.onboardingStepSetupTitle))
                    .font(.title2.bold())
                Text(lm.t(.onboardingStepSetupDesc))
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            // Card 1: PowerPoint Integration
            VStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .top, spacing: 14) {
                    Image(systemName: "arrow.down.doc.fill")
                        .font(.title3)
                        .foregroundStyle(Color.accentColor)

                    VStack(alignment: .leading, spacing: 4) {
                        HStack {
                            Text(lm.t(.integrationItemTitle))
                                .font(.headline)
                            Spacer()
                            if isIntegrationInstalled {
                                Label(lm.t(.integrationInstalled), systemImage: "checkmark.circle.fill")
                                    .font(.caption.bold())
                                    .foregroundStyle(.green)
                            } else {
                                Label(lm.t(.integrationNotInstalled), systemImage: "exclamationmark.triangle.fill")
                                    .font(.caption.bold())
                                    .foregroundStyle(.orange)
                            }
                        }

                        Text(lm.t(.integrationItemDesc))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)

                        HStack(spacing: 12) {
                            Button {
                                doctorVM.installIntegration()
                            } label: {
                                if doctorVM.isInstalling {
                                    ProgressView().controlSize(.small)
                                } else {
                                    Text(lm.t(.installButton))
                                }
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(doctorVM.isInstalling || doctorVM.isLoading)

                            if let msg = doctorVM.installMessage {
                                Text(msg)
                                    .font(.caption)
                                    .foregroundStyle(.green)
                            }
                        }
                        .padding(.top, 4)
                    }
                }
            }
            .workspaceCard()

            // Card 2: Accessibility Permission
            VStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .top, spacing: 14) {
                    Image(systemName: "hand.raised.fill")
                        .font(.title3)
                        .foregroundStyle(Color.accentColor)

                    VStack(alignment: .leading, spacing: 4) {
                        HStack {
                            Text(lm.t(.accessibilityItemTitle))
                                .font(.headline)
                            Spacer()
                            if vm.isAccessibilityGranted {
                                Label(lm.t(.permissionGranted), systemImage: "checkmark.circle.fill")
                                    .font(.caption.bold())
                                    .foregroundStyle(.green)
                            } else {
                                Label(lm.t(.permissionNeeded), systemImage: "lock.fill")
                                    .font(.caption.bold())
                                    .foregroundStyle(.orange)
                            }
                        }

                        Text(lm.t(.accessibilityItemDesc))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)

                        if !vm.isAccessibilityGranted {
                            Button {
                                PPTAlertInterceptor.openAccessibilityPreferences()
                            } label: {
                                Label(lm.t(.grantPermissionButton), systemImage: "gearshape")
                            }
                            .buttonStyle(.bordered)
                            .padding(.top, 4)
                        }
                    }
                }
            }
            .workspaceCard()
        }
    }

    // MARK: - Step 3: All Set & Start
    private var doneStep: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack(spacing: 16) {
                Image(systemName: "checkmark.seal.fill")
                    .font(.system(size: 40))
                    .foregroundStyle(.green)

                VStack(alignment: .leading, spacing: 4) {
                    Text(lm.t(.onboardingDoneTitle))
                        .font(.title2.bold())
                    Text(lm.t(.onboardingDoneDesc))
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }

            // Summary card
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Label(lm.t(.interfaceLanguage), systemImage: "globe")
                    Spacer()
                    Text(lm.effectiveLanguage == .en ? "English" : "繁體中文")
                        .foregroundStyle(.secondary)
                }
                .font(.subheadline)

                Divider()

                HStack {
                    Label(lm.t(.onboardingStepModeTitle), systemImage: "square.grid.2x2")
                    Spacer()
                    Text(appState.selectedUsageMode == .fullBridge ? lm.t(.modeFullBridgeTitle) : lm.t(.modeBatchOnlyTitle))
                        .foregroundStyle(.secondary)
                }
                .font(.subheadline)

                Divider()

                HStack {
                    Label(lm.t(.integrationItemTitle), systemImage: "arrow.down.doc")
                    Spacer()
                    Text(isIntegrationInstalled ? lm.t(.integrationInstalled) : lm.t(.integrationNotInstalled))
                        .foregroundStyle(isIntegrationInstalled ? .green : .secondary)
                }
                .font(.subheadline)
            }
            .workspaceCard()

            // Tip card about Doctor
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: "stethoscope")
                    .font(.title3)
                    .foregroundStyle(Color.accentColor)

                Text(lm.t(.onboardingDoneHint))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .workspaceCard()
        }
    }

    // MARK: - Helpers
    private var isIntegrationInstalled: Bool {
        guard let report = doctorVM.doctorReport else { return false }
        return report.checks.contains { check in
            check.name.contains("PowerPoint") && check.status == "ok"
        }
    }

    private func finishOnboarding() {
        vm.stopPolling()
        appState.hasCompletedOnboarding = true
        appState.showOnboardingSheet = false
        if appState.selectedUsageMode == .batchOnly {
            appState.selectedTab = .batchRepair
        } else {
            appState.selectedTab = .originEdit
        }
    }
}
