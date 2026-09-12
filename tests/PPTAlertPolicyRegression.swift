import Foundation

@main
struct PPTAlertPolicyRegression {
    private typealias Node = PPTAlertPolicy.Node

    static func main() {
        let exactTW = "找不到伺服器應用程式、來源檔案或項目，或是傳回未知的錯誤。可能需要重新安裝伺服器應用程式。"
        let delayedEmpty = Node(id: 1, role: "AXWindow", children: [
            Node(id: 2, role: "AXSheet", children: [Node(id: 3, role: "AXStaticText", value: nil), Node(id: 4, role: "AXButton", title: "確定")])
        ])
        expect(PPTAlertPolicy.dismissalCandidates(in: delayedEmpty).isEmpty, "delayed text is ignored before it exists")

        let delayedText = Node(id: 1, role: "AXWindow", children: [
            Node(id: 2, role: "AXSheet", children: [Node(id: 3, role: "AXStaticText", value: exactTW), Node(id: 4, role: "AXButton", title: "確定")])
        ])
        expect(PPTAlertPolicy.dismissalCandidates(in: delayedText) == [.init(dialogID: 2, buttonID: 4)], "delayed text is matched on a later scan")

        let documentContent = Node(id: 10, role: "AXWindow", children: [Node(id: 11, role: "AXStaticText", value: exactTW), Node(id: 12, role: "AXButton", title: "確定")])
        expect(PPTAlertPolicy.dismissalCandidates(in: documentContent).isEmpty, "normal document content is never scanned")

        let modal = Node(id: 20, role: "AXWindow", isModal: true, children: [Node(id: 21, role: "AXStaticText", value: exactTW), Node(id: 22, role: "AXButton", title: "OK")])
        expect(PPTAlertPolicy.dismissalCandidates(in: modal) == [.init(dialogID: 20, buttonID: 22)], "explicit modal dialog is matched")

        let defaultButton = Node(id: 30, role: "AXDialog", children: [
            Node(id: 31, role: "AXStaticText", value: "The server application, source file, or item could not be found."),
            Node(id: 32, role: "AXButton", title: "Proceed", isDefaultButton: true)
        ])
        expect(PPTAlertPolicy.dismissalCandidates(in: defaultButton) == [.init(dialogID: 30, buttonID: 32)], "default button is accepted even with an unfamiliar title")
        expect(!PPTAlertPolicy.matchesServerApplicationContext("The server application could not be found."), "generic server text is not enough")
        expect(PPTAlertPolicy.matchesServerApplicationContext("Die Serveranwendung, die Quelldatei oder das Element wurde nicht gefunden."), "German context is matched")

        var failedPress = PPTAlertPolicy.DismissalLifecycle()
        failedPress.recordPress(success: false)
        expect(!failedPress.verify(dialogStillPresent: false), "failed press never triggers callback")

        var lifecycle = PPTAlertPolicy.DismissalLifecycle()
        lifecycle.recordPress(success: true)
        expect(!lifecycle.verify(dialogStillPresent: true), "callback waits for dialog closure")
        expect(lifecycle.verify(dialogStillPresent: false), "callback fires after verified closure")
        expect(!lifecycle.verify(dialogStillPresent: false), "duplicate verification is suppressed")

        let now = Date()
        expect(PPTAlertPolicy.isWithinDebounce(lastTrigger: now, now: now.addingTimeInterval(1)), "recent trigger is debounced")
        expect(!PPTAlertPolicy.isWithinDebounce(lastTrigger: now, now: now.addingTimeInterval(3)), "old trigger is allowed")
        print("PPTAlertPolicy regression tests passed")
    }

    private static func expect(_ condition: @autoclosure () -> Bool, _ message: String) {
        guard condition() else { fatalError("FAIL: \(message)") }
    }
}
