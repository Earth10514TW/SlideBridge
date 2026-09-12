import Foundation
import AppKit
import ApplicationServices

/// Platform-independent alert matching and button-selection policy.
/// The AX adapter below builds this tree from PowerPoint; tests can build it
/// directly without a running application.
public enum PPTAlertPolicy {
    public struct DismissalLifecycle {
        private var pressSucceeded = false
        private var callbackDelivered = false

        public init() {}

        public mutating func recordPress(success: Bool) {
            if success { pressSucceeded = true }
        }

        public mutating func verify(dialogStillPresent: Bool) -> Bool {
            guard pressSucceeded, !callbackDelivered, !dialogStillPresent else { return false }
            callbackDelivered = true
            return true
        }
    }

    public static func isWithinDebounce(lastTrigger: Date, now: Date, interval: TimeInterval = 2.5) -> Bool {
        now.timeIntervalSince(lastTrigger) < interval
    }

    public struct Node {
        public let id: Int
        public let role: String?
        public let subrole: String?
        public let title: String?
        public let value: String?
        public let description: String?
        public let isModal: Bool
        public let isDefaultButton: Bool
        public let children: [Node]

        public init(id: Int, role: String? = nil, subrole: String? = nil, title: String? = nil,
                    value: String? = nil, description: String? = nil, isModal: Bool = false,
                    isDefaultButton: Bool = false, children: [Node] = []) {
            self.id = id; self.role = role; self.subrole = subrole; self.title = title
            self.value = value; self.description = description; self.isModal = isModal
            self.isDefaultButton = isDefaultButton; self.children = children
        }
    }

    public struct DismissalCandidate: Equatable {
        public let dialogID: Int
        public let buttonID: Int
        public init(dialogID: Int, buttonID: Int) { self.dialogID = dialogID; self.buttonID = buttonID }
    }

    /// Finds only alert-like roots. A normal document window is never a
    /// candidate unless explicitly modal or carrying a dialog subrole.
    public static func dismissalCandidates(in root: Node) -> [DismissalCandidate] {
        var result: [DismissalCandidate] = []
        visit(root, candidates: &result)
        return result
    }

    public static func matchesServerApplicationContext(_ text: String) -> Bool {
        let value = normalize(text)
        if value.contains("找不到伺服器應用程式") && value.contains("來源檔案") && value.contains("項目") { return true }
        if value.contains("找不到服务器应用程序") && value.contains("源文件") && value.contains("项目") { return true }
        if value.contains("server application") &&
            (value.contains("source file") || value.contains("sourcefile")) &&
            (value.contains("could not be found") || value.contains("cannot be found") || value.contains("not be found")) { return true }
        return value.contains("serveranwendung") && value.contains("quelldatei") &&
            (value.contains("nicht gefunden") || value.contains("unbekannt"))
    }

    private static func visit(_ node: Node, candidates: inout [DismissalCandidate]) {
        if isDialogRoot(node), containsSignature(node), let buttonID = buttonID(in: node) {
            candidates.append(DismissalCandidate(dialogID: node.id, buttonID: buttonID))
            return
        }
        for child in node.children { visit(child, candidates: &candidates) }
    }

    private static func isDialogRoot(_ node: Node) -> Bool {
        let roles = [node.role, node.subrole].compactMap { $0 }
        return node.isModal || roles.contains("AXSheet") || roles.contains("AXDialog") || roles.contains("AXSystemDialog")
    }

    private static func containsSignature(_ node: Node) -> Bool {
        if [node.title, node.value, node.description].compactMap({ $0 }).contains(where: matchesServerApplicationContext) { return true }
        return node.children.contains(where: containsSignature)
    }

    private static func buttonID(in node: Node) -> Int? {
        if node.role == "AXButton" && (node.isDefaultButton || isRecognizedOK(node.title)) { return node.id }
        for child in node.children { if let id = buttonID(in: child) { return id } }
        return nil
    }

    private static func isRecognizedOK(_ title: String?) -> Bool {
        guard let title else { return false }
        switch normalize(title) {
        case "確定", "确定", "ok", "okay", "done", "close", "schließen", "fertig": return true
        default: return false
        }
    }

    private static func normalize(_ text: String) -> String {
        text.replacingOccurrences(of: "\u{00a0}", with: " ")
            .split(whereSeparator: { $0.isWhitespace }).joined(separator: " ").lowercased()
    }
}

/// Monitors Microsoft PowerPoint for the "server application cannot be found" OLE alert.
public final class PPTAlertInterceptor: ObservableObject {
    public static let shared = PPTAlertInterceptor()
    public static let pptBundleId = "com.microsoft.Powerpoint"

    @Published public private(set) var isPowerPointRunning = false
    @Published public private(set) var isMonitoring = false
    @Published public private(set) var isAccessibilityGranted = false
    @Published public var isEnabled: Bool = true {
        didSet { if isEnabled { startMonitoring() } else { stopMonitoring() } }
    }

    private struct PendingDismissal {
        let element: AXUIElement
        let pid: pid_t
        let generation: UInt
        var attempt: Int
        var lifecycle: PPTAlertPolicy.DismissalLifecycle
    }

    private var observer: AXObserver?
    private var observedPid: pid_t = 0
    private var runLoopSource: CFRunLoopSource?
    private var monitorTimer: Timer?
    private var pendingDismissal: PendingDismissal?
    private var callbackGeneration: UInt = 0
    private var hasReportedTrust = false
    private var lastTriggeredAt: Date = .distantPast
    private let debounceInterval: TimeInterval = 2.5
    private var onIntercept: (@MainActor () -> Void)?

    public init(onIntercept: (@MainActor () -> Void)? = nil) {
        self.onIntercept = onIntercept
        setupWorkspaceNotifications()
        startMonitoring()
    }

    deinit {
        monitorTimer?.invalidate()
        monitorTimer = nil
        pendingDismissal = nil
        callbackGeneration &+= 1
        removeObserver()
        NotificationCenter.default.removeObserver(self)
        NSWorkspace.shared.notificationCenter.removeObserver(self)
    }

    public func setOnIntercept(_ callback: @escaping @MainActor () -> Void) {
        onIntercept = callback
        startMonitoring()
        scheduleScan(after: 0)
    }

    public func startMonitoring() {
        guard isEnabled else { return }
        if monitorTimer == nil {
            let timer = Timer(timeInterval: 0.5, repeats: true) { [weak self] _ in self?.monitorTick() }
            monitorTimer = timer
            RunLoop.main.add(timer, forMode: .common)
        }
        monitorTick()
    }

    public func stopMonitoring() {
        callbackGeneration &+= 1
        pendingDismissal = nil
        monitorTimer?.invalidate()
        monitorTimer = nil
        detachObserver()
        isMonitoring = false
    }

    private func setupWorkspaceNotifications() {
        let ws = NSWorkspace.shared.notificationCenter
        ws.addObserver(self, selector: #selector(applicationDidLaunch(_:)), name: NSWorkspace.didLaunchApplicationNotification, object: nil)
        ws.addObserver(self, selector: #selector(applicationDidTerminate(_:)), name: NSWorkspace.didTerminateApplicationNotification, object: nil)
    }

    private func monitorTick() {
        guard isEnabled else { return }
        let trusted = Self.isAccessibilityTrusted(prompt: false)
        let trustChanged = isAccessibilityGranted != trusted
        isAccessibilityGranted = trusted
        if !hasReportedTrust || trustChanged {
            hasReportedTrust = true
            isAccessibilityGranted = trusted
            print("SlideBridge [PPTAlertInterceptor]: Accessibility trusted = \(trusted)")
        }
        guard let ppt = NSRunningApplication.runningApplications(withBundleIdentifier: Self.pptBundleId).first(where: { !$0.isTerminated }) else {
            isPowerPointRunning = false
            detachObserver()
            return
        }
        isPowerPointRunning = true
        guard trusted else { detachObserver(); return }
        if ppt.processIdentifier != observedPid { attachObserver(to: ppt.processIdentifier) }
        let appElement = AXUIElementCreateApplication(ppt.processIdentifier)
        guard isAccessible(appElement) else { isMonitoring = false; return }
        isMonitoring = true
        scanCurrentDialogs(in: appElement, pid: ppt.processIdentifier)
    }

    @objc private func applicationDidLaunch(_ note: Notification) {
        guard let app = note.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication,
              app.bundleIdentifier == Self.pptBundleId else { return }
        isPowerPointRunning = true
        if isEnabled { attachObserver(to: app.processIdentifier); scheduleScan(after: 0.02) }
    }

    @objc private func applicationDidTerminate(_ note: Notification) {
        guard let app = note.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication,
              app.bundleIdentifier == Self.pptBundleId else { return }
        isPowerPointRunning = false
        detachObserver()
    }

    private func attachObserver(to pid: pid_t) {
        guard pid > 0, pid != observedPid, Self.isAccessibilityTrusted(prompt: false) else { return }
        detachObserver()
        let appElement = AXUIElementCreateApplication(pid)
        guard isAccessible(appElement) else { return }
        var newObserver: AXObserver?
        let err = AXObserverCreate(pid, { _, element, notification, refcon in
            guard let refcon else { return }
            let interceptor = Unmanaged<PPTAlertInterceptor>.fromOpaque(refcon).takeUnretainedValue()
            interceptor.handleNotification(element: element, notification: notification as String)
        }, &newObserver)
        guard err == .success, let obs = newObserver else {
            print("SlideBridge [PPTAlertInterceptor]: Failed to create AXObserver for PowerPoint (PID \(pid)): \(err.rawValue)")
            return
        }
        let ref = Unmanaged.passUnretained(self).toOpaque()
        let sheetError = AXObserverAddNotification(obs, appElement, kAXSheetCreatedNotification as CFString, ref)
        let windowError = AXObserverAddNotification(obs, appElement, kAXWindowCreatedNotification as CFString, ref)
        if sheetError != .success && windowError != .success {
            print("SlideBridge [PPTAlertInterceptor]: AX notifications unavailable (sheet \(sheetError.rawValue), window \(windowError.rawValue)); polling remains active")
        }
        let source = AXObserverGetRunLoopSource(obs)
        CFRunLoopAddSource(CFRunLoopGetMain(), source, CFRunLoopMode.commonModes)
        observer = obs; observedPid = pid; runLoopSource = source; isMonitoring = true
        scheduleScan(after: 0)
    }

    private func removeObserver() {
        if let obs = observer, let source = runLoopSource {
            CFRunLoopRemoveSource(CFRunLoopGetMain(), source, CFRunLoopMode.commonModes)
            if observedPid > 0 {
                let appElement = AXUIElementCreateApplication(observedPid)
                AXObserverRemoveNotification(obs, appElement, kAXSheetCreatedNotification as CFString)
                AXObserverRemoveNotification(obs, appElement, kAXWindowCreatedNotification as CFString)
            }
        }
        observer = nil; runLoopSource = nil; observedPid = 0; isMonitoring = false
    }

    private func detachObserver() {
        callbackGeneration &+= 1
        pendingDismissal = nil
        removeObserver()
    }

    private func handleNotification(element: AXUIElement, notification: String) {
        guard isEnabled else { return }
        scheduleScan(after: 0.02)
        scheduleScan(after: 0.12) // text may be populated after AXWindowCreated
    }

    private func scheduleScan(after delay: TimeInterval) {
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in self?.monitorTick() }
    }

    private func scanCurrentDialogs(in app: AXUIElement, pid: pid_t) {
        guard onIntercept != nil, pendingDismissal == nil,
              !PPTAlertPolicy.isWithinDebounce(lastTrigger: lastTriggeredAt, now: Date(), interval: debounceInterval) else { return }
        var windowsValue: CFTypeRef?
        guard AXUIElementCopyAttributeValue(app, kAXWindowsAttribute as CFString, &windowsValue) == .success,
              let windows = windowsValue as? [AXUIElement] else { return }
        for window in windows {
            for dialogRoot in dialogRoots(in: window) ?? [] {
                var elements: [Int: AXUIElement] = [:]
                let tree = snapshot(dialogRoot, elements: &elements)
                for candidate in PPTAlertPolicy.dismissalCandidates(in: tree) {
                    guard let dialog = elements[candidate.dialogID], let button = elements[candidate.buttonID] else { continue }
                    guard AXUIElementPerformAction(button, kAXPressAction as CFString) == .success else { continue }
                    callbackGeneration &+= 1
                    var lifecycle = PPTAlertPolicy.DismissalLifecycle()
                    lifecycle.recordPress(success: true)
                    pendingDismissal = PendingDismissal(element: dialog, pid: pid, generation: callbackGeneration, attempt: 0, lifecycle: lifecycle)
                    verifyDismissal()
                    return
                }
            }
        }
    }

    private func verifyDismissal() {
        guard let pending = pendingDismissal, isEnabled, currentPowerPointPID == pending.pid else { return }
        guard let dialogElements = currentDialogElements(for: pending.pid) else {
            retryDismissal(pending)
            return
        }
        let stillPresent = dialogElements.contains(where: { CFEqual($0, pending.element) })
        var updated = pending
        if updated.lifecycle.verify(dialogStillPresent: stillPresent) {
            pendingDismissal = nil
            lastTriggeredAt = Date()
            let generation = pending.generation
            DispatchQueue.main.async { [weak self] in
                guard let self, self.isEnabled, self.isAccessibilityGranted,
                      self.callbackGeneration == generation, self.currentPowerPointPID == pending.pid else { return }
                self.onIntercept?()
            }
            return
        }
        retryDismissal(pending)
    }

    private func retryDismissal(_ pending: PendingDismissal) {
        guard pending.attempt < 6 else { pendingDismissal = nil; return }
        var next = pending
        next.attempt += 1
        pendingDismissal = next
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.08) { [weak self] in self?.verifyDismissal() }
    }

    private var currentPowerPointPID: pid_t? {
        NSRunningApplication.runningApplications(withBundleIdentifier: Self.pptBundleId)
            .first(where: { !$0.isTerminated })?.processIdentifier
    }

    private func currentDialogElements(for pid: pid_t) -> [AXUIElement]? {
        guard pid > 0 else { return nil }
        let app = AXUIElementCreateApplication(pid)
        var windowsValue: CFTypeRef?
        guard AXUIElementCopyAttributeValue(app, kAXWindowsAttribute as CFString, &windowsValue) == .success,
              let windows = windowsValue as? [AXUIElement] else { return nil }
        var roots: [AXUIElement] = []
        for window in windows {
            guard let windowRoots = dialogRoots(in: window) else { return nil }
            roots.append(contentsOf: windowRoots)
        }
        return roots
    }

    private func dialogRoots(in window: AXUIElement) -> [AXUIElement]? {
        if isDialogLike(window) { return [window] }
        var roots: [AXUIElement] = []
        var childrenValue: CFTypeRef?
        guard AXUIElementCopyAttributeValue(window, kAXChildrenAttribute as CFString, &childrenValue) == .success,
              let children = childrenValue as? [AXUIElement] else { return nil }
        roots.append(contentsOf: children.prefix(80).filter(isDialogLike))
        return roots
    }

    private func isDialogLike(_ element: AXUIElement) -> Bool {
        let role = copyStringAttribute(element, kAXRoleAttribute as CFString)
        let subrole = copyStringAttribute(element, kAXSubroleAttribute as CFString)
        return copyBoolAttribute(element, kAXModalAttribute as CFString) ||
            role == "AXSheet" || role == "AXDialog" || role == "AXSystemDialog" ||
            subrole == "AXDialog" || subrole == "AXSystemDialog"
    }

    private func snapshot(_ element: AXUIElement, elements: inout [Int: AXUIElement], nextID: inout Int,
                          defaultButton: AXUIElement?) -> PPTAlertPolicy.Node {
        let id = nextID; nextID += 1; elements[id] = element
        let role = copyStringAttribute(element, kAXRoleAttribute as CFString)
        let subrole = copyStringAttribute(element, kAXSubroleAttribute as CFString)
        let title = copyStringAttribute(element, kAXTitleAttribute as CFString)
        let value = copyStringAttribute(element, kAXValueAttribute as CFString)
        let description = copyStringAttribute(element, kAXDescriptionAttribute as CFString)
        let modal = copyBoolAttribute(element, kAXModalAttribute as CFString)
        let isDefault = defaultButton.map { CFEqual(element, $0) } ?? false
        var children: [PPTAlertPolicy.Node] = []
        var childrenValue: CFTypeRef?
        if AXUIElementCopyAttributeValue(element, kAXChildrenAttribute as CFString, &childrenValue) == .success,
           let childElements = childrenValue as? [AXUIElement] {
            for child in childElements.prefix(200) {
                children.append(snapshot(child, elements: &elements, nextID: &nextID, defaultButton: defaultButton))
            }
        }
        return PPTAlertPolicy.Node(id: id, role: role, subrole: subrole, title: title, value: value,
                                   description: description, isModal: modal, isDefaultButton: isDefault, children: children)
    }

    private func snapshot(_ element: AXUIElement, elements: inout [Int: AXUIElement]) -> PPTAlertPolicy.Node {
        var defaultValue: CFTypeRef?
        let defaultButton: AXUIElement?
        if AXUIElementCopyAttributeValue(element, kAXDefaultButtonAttribute as CFString, &defaultValue) == .success,
           let defaultValue {
            defaultButton = unsafeBitCast(defaultValue, to: AXUIElement.self)
        } else {
            defaultButton = nil
        }
        var nextID = 1
        return snapshot(element, elements: &elements, nextID: &nextID, defaultButton: defaultButton)
    }

    private func isAccessible(_ element: AXUIElement) -> Bool {
        var role: CFTypeRef?; return AXUIElementCopyAttributeValue(element, kAXRoleAttribute as CFString, &role) == .success
    }

    private func copyStringAttribute(_ element: AXUIElement, _ attribute: CFString) -> String? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, attribute, &value) == .success else { return nil }
        return value as? String
    }

    private func copyBoolAttribute(_ element: AXUIElement, _ attribute: CFString) -> Bool {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, attribute, &value) == .success else { return false }
        return (value as? NSNumber)?.boolValue ?? false
    }

    public static func isAccessibilityTrusted(prompt: Bool = false) -> Bool {
        let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: prompt] as CFDictionary
        return AXIsProcessTrustedWithOptions(options)
    }

    public static func openAccessibilityPreferences() {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility") { NSWorkspace.shared.open(url) }
    }
}
