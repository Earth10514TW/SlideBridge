import Foundation
import AppKit
import ApplicationServices

/// Monitors Microsoft PowerPoint for the "server application cannot be found" OLE alert sheet.
/// When detected, automatically dismisses the dialog within milliseconds and triggers the active edit pipeline.
public final class PPTAlertInterceptor: ObservableObject {
    public static let shared = PPTAlertInterceptor()
    public static let pptBundleId = "com.microsoft.Powerpoint"

    @Published public private(set) var isPowerPointRunning = false
    @Published public private(set) var isMonitoring = false
    @Published public var isEnabled: Bool = true {
        didSet {
            if isEnabled {
                startMonitoring()
            } else {
                stopMonitoring()
            }
        }
    }

    private var observer: AXObserver?
    private var observedPid: pid_t = 0
    private var runLoopSource: CFRunLoopSource?
    private var lastTriggeredAt: Date = .distantPast
    private let debounceInterval: TimeInterval = 2.5
    private var onIntercept: (@MainActor () -> Void)?

    public init(onIntercept: (@MainActor () -> Void)? = nil) {
        self.onIntercept = onIntercept
        setupWorkspaceNotifications()
        checkInitialPowerPointState()
    }

    deinit {
        stopMonitoring()
        NotificationCenter.default.removeObserver(self)
        NSWorkspace.shared.notificationCenter.removeObserver(self)
    }

    public func setOnIntercept(_ callback: @escaping @MainActor () -> Void) {
        self.onIntercept = callback
    }

    public func startMonitoring() {
        guard isEnabled else { return }
        checkInitialPowerPointState()
    }

    public func stopMonitoring() {
        detachObserver()
    }

    private func setupWorkspaceNotifications() {
        let ws = NSWorkspace.shared.notificationCenter
        ws.addObserver(
            self,
            selector: #selector(applicationDidLaunch(_:)),
            name: NSWorkspace.didLaunchApplicationNotification,
            object: nil
        )
        ws.addObserver(
            self,
            selector: #selector(applicationDidTerminate(_:)),
            name: NSWorkspace.didTerminateApplicationNotification,
            object: nil
        )
    }

    private func checkInitialPowerPointState() {
        let apps = NSRunningApplication.runningApplications(withBundleIdentifier: Self.pptBundleId)
        if let ppt = apps.first(where: { !$0.isTerminated }) {
            DispatchQueue.main.async {
                self.isPowerPointRunning = true
            }
            attachObserver(to: ppt.processIdentifier)
        } else {
            DispatchQueue.main.async {
                self.isPowerPointRunning = false
            }
            detachObserver()
        }
    }

    @objc private func applicationDidLaunch(_ note: Notification) {
        guard let app = note.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication,
              app.bundleIdentifier == Self.pptBundleId else { return }

        DispatchQueue.main.async {
            self.isPowerPointRunning = true
        }
        if isEnabled {
            attachObserver(to: app.processIdentifier)
        }
    }

    @objc private func applicationDidTerminate(_ note: Notification) {
        guard let app = note.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication,
              app.bundleIdentifier == Self.pptBundleId else { return }

        DispatchQueue.main.async {
            self.isPowerPointRunning = false
        }
        detachObserver()
    }

    private func attachObserver(to pid: pid_t) {
        guard pid > 0, pid != observedPid else { return }
        detachObserver()

        var newObserver: AXObserver?
        let err = AXObserverCreate(pid, { (obs, element, notification, refcon) in
            guard let refcon = refcon else { return }
            let interceptor = Unmanaged<PPTAlertInterceptor>.fromOpaque(refcon).takeUnretainedValue()
            interceptor.handleNotification(element: element, notification: notification as String)
        }, &newObserver)

        guard err == .success, let obs = newObserver else {
            print("SlideBridge [PPTAlertInterceptor]: Failed to create AXObserver for PowerPoint (PID \(pid)): \(err.rawValue)")
            return
        }

        let appElement = AXUIElementCreateApplication(pid)
        let ref = Unmanaged.passUnretained(self).toOpaque()
        AXObserverAddNotification(obs, appElement, kAXSheetCreatedNotification as CFString, ref)
        AXObserverAddNotification(obs, appElement, kAXWindowCreatedNotification as CFString, ref)

        let source = AXObserverGetRunLoopSource(obs)
        CFRunLoopAddSource(CFRunLoopGetMain(), source, CFRunLoopMode.commonModes)

        self.observer = obs
        self.observedPid = pid
        self.runLoopSource = source
        DispatchQueue.main.async {
            self.isMonitoring = true
        }
        print("SlideBridge [PPTAlertInterceptor]: Successfully attached to PowerPoint (PID \(pid))")
    }

    private func detachObserver() {
        if let obs = observer, let source = runLoopSource {
            CFRunLoopRemoveSource(CFRunLoopGetMain(), source, CFRunLoopMode.commonModes)
            if observedPid > 0 {
                let appElement = AXUIElementCreateApplication(observedPid)
                AXObserverRemoveNotification(obs, appElement, kAXSheetCreatedNotification as CFString)
                AXObserverRemoveNotification(obs, appElement, kAXWindowCreatedNotification as CFString)
            }
        }
        observer = nil
        runLoopSource = nil
        observedPid = 0
        DispatchQueue.main.async {
            self.isMonitoring = false
        }
    }

    private func handleNotification(element: AXUIElement, notification: String) {
        guard isEnabled else { return }
        guard Date().timeIntervalSince(lastTriggeredAt) > debounceInterval else { return }

        // Give PowerPoint ~20ms to populate sub-elements of newly created sheet/dialog
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.02) { [weak self] in
            guard let self = self else { return }
            guard Date().timeIntervalSince(self.lastTriggeredAt) > self.debounceInterval else { return }

            if self.containsServerAppSignature(element) {
                self.lastTriggeredAt = Date()
                print("SlideBridge [PPTAlertInterceptor]: OLE server alert detected! Auto-dismissing sheet...")

                // Dismiss alert sheet
                self.dismissAlert(element)

                // Trigger active edit pipeline
                DispatchQueue.main.async {
                    self.onIntercept?()
                }
            }
        }
    }

    private func containsServerAppSignature(_ root: AXUIElement) -> Bool {
        var queue: [AXUIElement] = [root]
        var inspected = 0

        while !queue.isEmpty && inspected < 120 {
            let curr = queue.removeFirst()
            inspected += 1

            if let val = copyStringAttribute(curr, kAXValueAttribute as CFString), matchesSignature(val) {
                return true
            }
            if let title = copyStringAttribute(curr, kAXTitleAttribute as CFString), matchesSignature(title) {
                return true
            }
            if let desc = copyStringAttribute(curr, kAXDescriptionAttribute as CFString), matchesSignature(desc) {
                return true
            }

            var childrenVal: CFTypeRef?
            if AXUIElementCopyAttributeValue(curr, kAXChildrenAttribute as CFString, &childrenVal) == .success,
               let children = childrenVal as? [AXUIElement] {
                queue.append(contentsOf: children)
            }
        }
        return false
    }

    private func matchesSignature(_ text: String) -> Bool {
        let lower = text.lowercased()
        return lower.contains("伺服器應用程式")
            || lower.contains("服务器应用程序")
            || lower.contains("server application")
            || lower.contains("serveranwendung")
    }

    private func dismissAlert(_ root: AXUIElement) {
        // Attempt 1: Look for an AXButton in the alert sheet and perform AXPress
        var queue: [AXUIElement] = [root]
        var pressed = false

        while !queue.isEmpty && !pressed {
            let curr = queue.removeFirst()
            var roleVal: CFTypeRef?
            if AXUIElementCopyAttributeValue(curr, kAXRoleAttribute as CFString, &roleVal) == .success,
               let role = roleVal as? String, role == (kAXButtonRole as String) {
                let res = AXUIElementPerformAction(curr, kAXPressAction as CFString)
                if res == .success {
                    pressed = true
                    print("SlideBridge [PPTAlertInterceptor]: Successfully pressed alert button")
                    break
                }
            }

            var childrenVal: CFTypeRef?
            if AXUIElementCopyAttributeValue(curr, kAXChildrenAttribute as CFString, &childrenVal) == .success,
               let children = childrenVal as? [AXUIElement] {
                queue.append(contentsOf: children)
            }
        }

        // Attempt 2: Fallback to keyboard Escape / Return
        if !pressed {
            postKey(keyCode: 36) // Return
            postKey(keyCode: 53) // Escape
        }
    }

    private func postKey(keyCode: CGKeyCode) {
        let src = CGEventSource(stateID: .hidSystemState)
        let keyDown = CGEvent(keyboardEventSource: src, virtualKey: keyCode, keyDown: true)
        let keyUp = CGEvent(keyboardEventSource: src, virtualKey: keyCode, keyDown: false)
        keyDown?.post(tap: .cghidEventTap)
        keyUp?.post(tap: .cghidEventTap)
    }

    private func copyStringAttribute(_ element: AXUIElement, _ attribute: CFString) -> String? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, attribute, &value) == .success,
              let str = value as? String else { return nil }
        return str
    }
}
