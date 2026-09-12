import SwiftUI
import Combine

public enum AppLanguage: String, CaseIterable, Identifiable {
    case system = "system"
    case zhTW = "zh_TW"
    case en = "en"

    public var id: String { rawValue }

    public var displayName: String {
        switch self {
        case .system: return "跟隨系統 / System"
        case .zhTW: return "繁體中文"
        case .en: return "English"
        }
    }
}

public enum L10nKey {
    // Branding & Common
    case appName
    case appSubtitle
    case version
    case nativeArch
    case ok
    case cancel
    case error
    case unknownError
    case language
    case systemDefault
    case languageMenu

    // Tabs
    case tabBatchRepair
    case tabOriginEdit
    case tabDoctor

    // Batch Repair
    case repairTitle
    case repairSubtitle
    case dropTitle
    case dropSubtitle
    case selectFileButton
    case invalidPptxError
    case scanningMessage
    case scanResultsTitle
    case brokenVectorCharts
    case emfCharts
    case embeddedOle
    case noBrokenNotice
    case previewDpiLabel
    case dpi150
    case dpi300
    case dpi600
    case fixingMessage
    case startRepairButton
    case changeFileButton
    case repairCompleteTitle
    case repairCompleteDesc(count: Int, dpi: Int)
    case outputFileLabel
    case revealInFinder
    case openInPowerPoint
    case repairAnother
    case retryScan
    case scanFailed
    case uninstallConfirmation
    case uninstallExplanation
    case statusPassed
    case statusWarning
    case statusFailed
    case statusInfo
    case processingError

    // Origin Edit
    case originEditTitle
    case originEditSubtitle
    case doubleClickInterceptTitle
    case doubleClickInterceptDesc
    case interceptorActiveStatus
    case interceptorInactiveStatus
    case interceptorPptNotRunning
    case interceptorToggle
    case crossMachineHeader
    case crossMachineHint
    case editingConnecting
    case editingInstruction
    case editSelectedChartButton
    case editSuccessTitle
    case presFileLabel
    case slideAndShapeLabel
    case oleBinaryLabel
    case backupPresLabel
    case hotReloadNotice
    case guideTitle
    case step1Title
    case step1Desc
    case step2Title
    case step2Desc
    case step3Title
    case step3Desc
    case step4Title
    case step4Desc
    case editFailedAlert

    // Doctor & Settings
    case doctorTitle
    case doctorSubtitle
    case refreshButton
    case envReady
    case envNeedConfig
    case envStats(passed: Int, warns: Int, fails: Int)
    case diagnosingProgress
    case checkListTitle
    case suggestionPrefix
    case integrationTitle
    case integrationDesc
    case installingMsg
    case uninstallingMsg
    case installButton
    case uninstallButton
    case installSuccess
    case uninstallSuccess
    case doctorFailedAlert
    case interfaceLanguage

    // Onboarding & Setup Wizard
    case onboardingWelcomeTitle
    case onboardingWelcomeDesc
    case onboardingNext
    case onboardingBack
    case onboardingFinish
    case onboardingStepModeTitle
    case onboardingStepModeDesc
    case modeBatchOnlyTitle
    case modeBatchOnlyDesc
    case modeBatchOnlyReq
    case modeFullBridgeTitle
    case modeFullBridgeDesc
    case modeFullBridgeReq
    case recommendedBadge
    case onboardingStepSetupTitle
    case onboardingStepSetupDesc
    case integrationItemTitle
    case integrationItemDesc
    case integrationInstalled
    case integrationNotInstalled
    case accessibilityItemTitle
    case accessibilityItemDesc
    case grantPermissionButton
    case permissionGranted
    case permissionNeeded
    case onboardingDoneTitle
    case onboardingDoneDesc
    case onboardingDoneHint
    case startUsingApp
    case rerunOnboardingButton
    case setupGuideMenu
}

@MainActor
public class LanguageManager: ObservableObject {
    public static let shared = LanguageManager()

    @AppStorage("app_language") public var storedLanguage: String = AppLanguage.system.rawValue {
        didSet {
            objectWillChange.send()
        }
    }

    public var currentLanguage: AppLanguage {
        get {
            AppLanguage(rawValue: storedLanguage) ?? .system
        }
        set {
            storedLanguage = newValue.rawValue
        }
    }

    public var effectiveLanguage: AppLanguage {
        if currentLanguage == .system {
            let pref = Locale.preferredLanguages.first?.lowercased() ?? ""
            if pref.hasPrefix("zh") {
                return .zhTW
            } else {
                return .en
            }
        }
        return currentLanguage
    }

    public init() {}

    public func t(_ key: L10nKey) -> String {
        let isEn = (effectiveLanguage == .en)

        switch key {
        case .retryScan: return isEn ? "Scan again" : "重新掃描"
        case .scanFailed: return isEn ? "Couldn't scan this presentation" : "無法掃描這份簡報"
        case .uninstallConfirmation: return isEn ? "Remove system integration?" : "移除系統整合？"
        case .uninstallExplanation: return isEn ? "This removes SlideBridge's PowerPoint Services menu. You can install it again here." : "將移除 SlideBridge 的 PowerPoint 服務選單。你可以隨時在這裡重新安裝。"
        case .statusPassed: return isEn ? "Passed" : "通過"
        case .statusWarning: return isEn ? "Warning" : "注意"
        case .statusFailed: return isEn ? "Failed" : "未通過"
        case .statusInfo: return isEn ? "Information" : "資訊"
        // Branding & Common
        case .appName:
            return "SlideBridge"
        case .appSubtitle:
            return isEn ? "PowerPoint & Origin" : "PowerPoint 與 Origin"
        case .version:
            return isEn ? "Version 0.1.0" : "版本 0.1.0"
        case .nativeArch:
            return isEn ? "macOS Native Architecture" : "macOS 原生架構"
        case .ok:
            return isEn ? "OK" : "確定"
        case .cancel:
            return isEn ? "Cancel" : "取消"
        case .error:
            return isEn ? "Error" : "錯誤"
        case .unknownError:
            return isEn ? "Unknown error occurred" : "未知錯誤"
        case .language:
            return isEn ? "Language" : "語言"
        case .systemDefault:
            return isEn ? "System Default" : "跟隨系統"
        case .languageMenu:
            return isEn ? "Language" : "語言 (Language)"

        // Tabs
        case .tabBatchRepair:
            return isEn ? "Batch Repair" : "批次修復"
        case .tabOriginEdit:
            return isEn ? "Origin Edit" : "Origin 編輯"
        case .tabDoctor:
            return isEn ? "Diagnostics" : "系統診斷"

        // Batch Repair
        case .repairTitle:
            return isEn ? "Repair presentation charts" : "修復簡報圖表"
        case .repairSubtitle:
            return isEn
                ? "Repair chart appearance throughout your presentation while keeping embedded Origin data editable."
                : "修復整份簡報中的圖表顯示問題，並保留可編輯的 Origin 內嵌資料。"
        case .dropTitle:
            return isEn ? "Drop PowerPoint (.pptx) file here" : "拖曳 PowerPoint (.pptx) 檔案至此處"
        case .dropSubtitle:
            return isEn ? "or click the button below to browse" : "或點擊下方按鈕選取簡報檔案"
        case .selectFileButton:
            return isEn ? "Choose Presentation..." : "選擇簡報檔案..."
        case .invalidPptxError:
            return isEn ? "Please select a PowerPoint file with a .pptx extension." : "請選取副檔名為 .pptx 的 PowerPoint 簡報檔案。"
        case .scanningMessage:
            return isEn ? "Scanning presentation structure and OLE vector charts..." : "正在深入掃描簡報結構與 OLE 向量圖表..."
        case .scanResultsTitle:
            return isEn ? "Scan results" : "掃描結果與資產統計"
        case .brokenVectorCharts:
            return isEn ? "Vector charts" : "損壞向量圖 (EMF/WMF)"
        case .emfCharts:
            return isEn ? "EMF charts" : "EMF 向量圖"
        case .embeddedOle:
            return isEn ? "Editable objects" : "嵌入 OLE 二進位"
        case .noBrokenNotice:
            return isEn
                ? "💡 Notice: No broken EMF/WMF images found. You can still proceed if you wish to re-render charts."
                : "💡 提示：本簡報未發現損壞的 EMF/WMF 圖片，若仍需重新編譯圖表可繼續執行。"
        case .previewDpiLabel:
            return isEn ? "Preview Resolution:" : "修復預覽圖解析度："
        case .dpi150:
            return isEn ? "150 DPI (Fast / Screen)" : "150 DPI (快速/簡報用)"
        case .dpi300:
            return isEn ? "300 DPI (Recommended / Standard)" : "300 DPI (推薦標準品質)"
        case .dpi600:
            return isEn ? "600 DPI (Ultra High Res)" : "600 DPI (極致高解析度)"
        case .fixingMessage:
            return isEn
                ? "Rendering high-res charts via patched engine & resvg, updating XML relationships..."
                : "正在透過修補版引擎與 resvg 渲染高畫質圖表，並重寫 XML 關係..."
        case .startRepairButton:
            return isEn ? "Start High-Res Repair" : "開始高畫質修復"
        case .changeFileButton:
            return isEn ? "Change File" : "更換簡報"
        case .repairCompleteTitle:
            return isEn ? "Presentation Charts Repaired Successfully!" : "簡報圖表修復完成！"
        case let .repairCompleteDesc(count, dpi):
            return isEn
                ? "Successfully replaced \(count) chart(s) with \(dpi) DPI crisp PNG images while preserving all original OLE data."
                : "已成功將 \(count) 張圖表替換為 \(dpi) DPI 高畫質 PNG，並完整保留所有原始 OLE 資料。"
        case .outputFileLabel:
            return isEn ? "Output File:" : "輸出檔案："
        case .revealInFinder:
            return isEn ? "Show in Finder" : "在 Finder 中顯示"
        case .openInPowerPoint:
            return isEn ? "Open in PowerPoint" : "在 PowerPoint 開啟"
        case .repairAnother:
            return isEn ? "Repair Another File" : "修復另一份簡報"
        case .processingError:
            return isEn ? "An error occurred during processing" : "處理過程發生錯誤"

        // Origin Edit
        case .originEditTitle:
            return isEn ? "Edit Origin charts" : "編輯 Origin 圖表"
        case .originEditSubtitle:
            return isEn
                ? "Edit a selected chart in Windows OriginPro, then update your Mac PowerPoint presentation."
                : "在 Windows OriginPro 編輯選取的圖表，再將變更更新至 Mac PowerPoint 簡報。"
        case .doubleClickInterceptTitle:
            return isEn ? "Double-Click Auto-Intercept" : "雙擊圖表自動接管"
        case .doubleClickInterceptDesc:
            return isEn
                ? "Double-clicking an Origin chart in PowerPoint automatically dismisses the error dialog and launches Windows Origin."
                : "在 PowerPoint 中對 Origin 圖表點兩下時，自動關閉系統錯誤彈窗並喚醒 Windows Origin。"
        case .interceptorActiveStatus:
            return isEn ? "Active (Double-click in PPT to edit)" : "監聽中（在 PPT 雙擊圖表即可編輯）"
        case .interceptorInactiveStatus:
            return isEn ? "Disabled" : "已停用"
        case .interceptorPptNotRunning:
            return isEn ? "PowerPoint Not Running" : "PowerPoint 未開啟"
        case .interceptorToggle:
            return isEn ? "Enable double-click auto-edit" : "啟用雙擊圖表自動編輯"
        case .crossMachineHeader:
            return "Mac PowerPoint ➔ Windows 11 VM Origin"
        case .crossMachineHint:
            return isEn
                ? "Please open the presentation in Mac PowerPoint and select the chart you want to edit"
                : "請先在 Mac PowerPoint 開啟簡報並點選欲編輯的圖表"
        case .editingConnecting:
            return isEn
                ? "Connecting to Parallels VM and launching Windows Origin Helper..."
                : "正在連線 Parallels VM 並啟動 Windows Origin Helper..."
        case .editingInstruction:
            return isEn
                ? "Please switch to Windows to edit. When finished, click 'Save and Close' in Helper"
                : "請切換至 Windows 視窗編輯圖表，完成後點擊 Helper 的「Save and Close」"
        case .editSelectedChartButton:
            return isEn ? "Edit Selected Chart in Origin" : "在 Origin 編輯目前選取的圖表"
        case .editSuccessTitle:
            return isEn ? "Chart Edited & Reloaded Successfully!" : "圖表編輯與回寫成功！"
        case .presFileLabel:
            return isEn ? "Presentation File:" : "簡報檔案："
        case .slideAndShapeLabel:
            return isEn ? "Slide & Shape:" : "投影片與物件："
        case .oleBinaryLabel:
            return isEn ? "OLE Binary:" : "OLE 二進位："
        case .backupPresLabel:
            return isEn ? "Backup Presentation:" : "備份簡報："
        case .hotReloadNotice:
            return isEn
                ? "✨ Mac PowerPoint has automatically hot-reloaded and navigated back to the original slide. You can view the updated chart immediately."
                : "✨ Mac PowerPoint 已自動熱重載並跳轉回原投影片，您可以立即檢視更新後的圖表。"
        case .guideTitle:
            return isEn ? "💡 Workflow & Step-by-Step Guide" : "💡 操作指南與流程說明"
        case .step1Title:
            return isEn ? "Select Chart" : "選取圖表"
        case .step1Desc:
            return isEn
                ? "Select any Origin chart shape in Mac PowerPoint."
                : "在 Mac PowerPoint 點選任何由 Windows/Origin 產生的圖表形狀。"
        case .step2Title:
            return isEn ? "Cross-VM Launch" : "跨機喚醒"
        case .step2Desc:
            return isEn
                ? "Click the button above; Parallels Windows 11 VM will focus and launch OriginPro."
                : "點擊上方按鈕，Parallels Windows 11 VM 會自動切換至前台並啟動 Origin。"
        case .step3Title:
            return isEn ? "Edit & Save" : "編輯與存檔"
        case .step3Desc:
            return isEn
                ? "Adjust data, labels, or styling in Origin and press Ctrl+S to save."
                : "在 Origin 內調整文字、標籤或數據，依提示確認儲存。"
        case .step4Title:
            return isEn ? "Auto Hot-Reload" : "自動熱重載"
        case .step4Desc:
            return isEn
                ? "Click 'Save and Close' in Helper. Origin auto-exports preview and PowerPoint reloads in place."
                : "點擊 Helper 視窗的「Save and Close」，自動驅動匯出並即時重載回原投影片。"
        case .editFailedAlert:
            return isEn ? "Origin Edit Failed" : "Origin 編輯失敗"

        // Doctor & Settings
        case .doctorTitle:
            return isEn ? "Diagnostics & settings" : "系統診斷與設定"
        case .doctorSubtitle:
            return isEn
                ? "Verify local Python, PowerPoint, resvg, Parallels VM, and integration scripts readiness."
                : "檢查本機 Python、PowerPoint、resvg、Parallels 虛擬機以及整合腳本的就緒狀態。"
        case .refreshButton:
            return isEn ? "Refresh" : "重新整理"
        case .envReady:
            return isEn ? "System Environment Fully Ready" : "系統環境已完全就緒"
        case .envNeedConfig:
            return isEn ? "Configuration Required" : "部分環境需要配置"
        case let .envStats(passed, warns, fails):
            return isEn
                ? "Passed: \(passed), Warnings: \(warns), Failures: \(fails)"
                : "通過檢查：\(passed) 項，警告：\(warns) 項，失敗：\(fails) 項"
        case .diagnosingProgress:
            return isEn ? "Diagnosing system dependencies and VM status..." : "正在診斷系統依賴與虛擬機狀態..."
        case .checkListTitle:
            return isEn ? "Diagnostic Checklist" : "檢查清單"
        case .suggestionPrefix:
            return isEn ? "💡 Suggestion: " : "💡 建議："
        case .integrationTitle:
            return isEn ? "macOS System Integration Services" : "macOS 系統整合服務管理"
        case .integrationDesc:
            return isEn
                ? "Install or remove the PowerPoint Services menu item registered in macOS, so you can edit a selected chart without leaving PowerPoint."
                : "安裝或移除註冊於 macOS 的「PowerPoint 應用服務選單」，讓您在簡報中直接一鍵編輯選取的圖表。"
        case .installingMsg:
            return isEn ? "Installing integration scripts to system folders..." : "正在安裝整合腳本至系統資料夾..."
        case .uninstallingMsg:
            return isEn ? "Removing integration services from macOS..." : "正在從系統移除整合服務..."
        case .installButton:
            return isEn ? "Install / Update Integration" : "安裝 / 更新系統整合服務"
        case .uninstallButton:
            return isEn ? "Uninstall Integration" : "移除系統整合服務"
        case .installSuccess:
            return isEn
                ? "✔ System integration installed successfully! Registered in the PowerPoint Services menu."
                : "✔ 系統整合安裝成功！已註冊至 PowerPoint 服務選單。"
        case .uninstallSuccess:
            return isEn
                ? "✔ Successfully removed macOS system integration (PowerPoint Services menu)."
                : "✔ 已成功移除 macOS 系統整合服務（PowerPoint 服務選單）。"
        case .doctorFailedAlert:
            return isEn ? "Diagnostics Execution Failed" : "診斷執行失敗"
        case .interfaceLanguage:
            return isEn ? "Interface Language" : "介面語言"

        // Onboarding & Setup Wizard
        case .onboardingWelcomeTitle:
            return isEn ? "Welcome to SlideBridge" : "歡迎使用 SlideBridge"
        case .onboardingWelcomeDesc:
            return isEn
                ? "The bridge between PowerPoint and Origin on macOS. Complete a few simple steps to get the best experience."
                : "專為 macOS 打造的 PowerPoint 與 Origin 跨平台圖表橋接工具。只需簡單幾步，即可完成最佳使用環境配置。"
        case .onboardingNext:
            return isEn ? "Next" : "下一步"
        case .onboardingBack:
            return isEn ? "Back" : "上一步"
        case .onboardingFinish:
            return isEn ? "Get Started" : "開始使用"
        case .onboardingStepModeTitle:
            return isEn ? "Choose Usage Mode" : "選擇主要使用模式"
        case .onboardingStepModeDesc:
            return isEn
                ? "Select the mode that best fits your workflow. You can switch between them at any time:"
                : "根據您的工作流程挑選最合適的模式，後續可隨時在各分頁自由切換："
        case .modeBatchOnlyTitle:
            return isEn ? "Batch Repair" : "批次修復圖形"
        case .modeBatchOnlyDesc:
            return isEn
                ? "Fix broken, blurry, or missing Origin/EMF charts in presentations with high-quality SVG or crisp previews."
                : "在 Mac 開啟含有 Origin 圖表的 PPT 破圖、模糊或顯示紅叉時，快速將 EMF 轉換為高畫質向量 SVG 或清晰點陣圖。"
        case .modeBatchOnlyReq:
            return isEn
                ? "✓ Fully local, no Windows virtual machine required"
                : "✓ 僅需本機環境，無須安裝或啟動 Windows 虛擬機"
        case .modeFullBridgeTitle:
            return isEn ? "Origin Interactive Bridge" : "Origin 雙向互動編輯"
        case .modeFullBridgeDesc:
            return isEn
                ? "Double-click charts in PowerPoint to seamlessly edit them inside Origin on Windows, with instant hot-reload."
                : "在 Mac 上雙擊 PPT 圖表時自動接管錯誤彈窗，喚醒 Windows VM 內的 Origin 進行編輯，存檔後自動熱重載回 PPT。"
        case .modeFullBridgeReq:
            return isEn
                ? "✓ Requires Parallels Desktop, a Windows VM, and Origin"
                : "✓ 需安裝 Parallels Desktop、Windows 虛擬機與 Origin"
        case .recommendedBadge:
            return isEn ? "Recommended" : "推薦"
        case .onboardingStepSetupTitle:
            return isEn ? "System Integration & Permissions" : "系統整合與權限配置"
        case .onboardingStepSetupDesc:
            return isEn
                ? "Configure macOS and PowerPoint integration for a seamless workflow:"
                : "設定 macOS 與 PowerPoint 整合，體驗更流暢的操作流程："
        case .integrationItemTitle:
            return isEn ? "PowerPoint Services Integration" : "PowerPoint 服務選單整合"
        case .integrationItemDesc:
            return isEn
                ? "Registers SlideBridge in PowerPoint's Services menu and installs helper scripts."
                : "在 PowerPoint 的「服務」選單中加入 SlideBridge 動作，並編譯本機輔助腳本。"
        case .integrationInstalled:
            return isEn ? "Installed" : "已安裝完成"
        case .integrationNotInstalled:
            return isEn ? "Not Installed" : "尚未安裝"
        case .accessibilityItemTitle:
            return isEn ? "macOS Accessibility Permission" : "macOS 輔助使用權限"
        case .accessibilityItemDesc:
            return isEn
                ? "Required to intercept PowerPoint's 'server not found' dialog when double-clicking charts."
                : "雙擊 PPT 圖表時，自動關閉『找不到伺服器』彈窗並跨機喚醒 Origin 所需（僅雙向編輯需要）。"
        case .grantPermissionButton:
            return isEn ? "Open System Settings..." : "開啟系統設定..."
        case .permissionGranted:
            return isEn ? "Granted" : "已獲授權"
        case .permissionNeeded:
            return isEn ? "Permission Required" : "需要授權"
        case .onboardingDoneTitle:
            return isEn ? "All Set!" : "一切就緒！"
        case .onboardingDoneDesc:
            return isEn
                ? "Initial setup is complete. You are ready to start bridging PowerPoint and Origin."
                : "您已完成初次引導設定。現在即可開始使用 SlideBridge 處理您的簡報圖表。"
        case .onboardingDoneHint:
            return isEn
                ? "💡 Tip: If you ever encounter VM or dependency issues, visit 'Doctor' in the sidebar for a full diagnostic check."
                : "💡 提示：若日後虛擬機未啟動或遇到任何環境異常，可隨時前往側邊欄的「系統環境診斷」進行完整體檢。"
        case .startUsingApp:
            return isEn ? "Launch SlideBridge" : "進入 SlideBridge"
        case .rerunOnboardingButton:
            return isEn ? "Run Setup Wizard" : "重新執行引導設定"
        case .setupGuideMenu:
            return isEn ? "Setup Wizard..." : "設定引導精靈..."
        }
    }
}
