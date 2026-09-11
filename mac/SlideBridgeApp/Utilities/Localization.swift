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
    case processingError

    // Origin Edit
    case originEditTitle
    case originEditSubtitle
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
        // Branding & Common
        case .appName:
            return "SlideBridge"
        case .appSubtitle:
            return isEn ? "PPTX Chart Repair & Origin Bridge" : "PPTX 圖表修復與跨機橋接"
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
            return isEn ? "Batch Presentation Chart Repair" : "批次簡報圖表修復"
        case .repairSubtitle:
            return isEn
                ? "Scans EMF/WMF charts, fixes broken stroke weights and rotated text, renders crisp 300 DPI images, and preserves double-click OLE data."
                : "自動掃描整份簡報中的 EMF/WMF 向量圖表，修補線條粗細與文字旋轉跑版，渲染為 300 DPI 高畫質影像並保留 OLE 雙擊編輯數據。"
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
            return isEn ? "Scan Results & Asset Statistics" : "掃描結果與資產統計"
        case .brokenVectorCharts:
            return isEn ? "Broken Vector Charts (EMF/WMF)" : "損壞向量圖 (EMF/WMF)"
        case .emfCharts:
            return isEn ? "EMF Vector Charts" : "EMF 向量圖"
        case .embeddedOle:
            return isEn ? "Embedded OLE Objects" : "嵌入 OLE 二進位"
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
                ? "Rendering high-res charts via patched engine & Inkscape, updating XML relationships..."
                : "正在透過修補版引擎與 Inkscape 渲染高畫質圖表，並重寫 XML 關係..."
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
            return isEn ? "Interactive Origin Chart Editing" : "Origin 圖表互動編輯"
        case .originEditSubtitle:
            return isEn
                ? "Select any Origin chart in Mac PowerPoint, launch Windows VM OriginPro with one click, edit precisely, and auto-reload presentation in place."
                : "在 Mac PowerPoint 中選取任何 Origin 圖表，一鍵跨機喚醒 Windows VM 開啟 OriginPro 進行精確繪圖編輯，自動原地回寫並熱重載簡報。"
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
            return isEn ? "System Diagnostics & Settings" : "系統環境診斷與設定"
        case .doctorSubtitle:
            return isEn
                ? "Verify local Python, PowerPoint, Inkscape, Parallels VM, and integration scripts readiness."
                : "檢查本機 Python、PowerPoint、Inkscape、Parallels 虛擬機以及整合腳本的就緒狀態。"
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
                ? "Manage Finder Quick Actions and PowerPoint Services menus registered in macOS for quick access directly from Finder or PowerPoint."
                : "管理註冊於 macOS 系統中的「Finder 右鍵快速動作」與「PowerPoint 應用服務選單」，讓您平常在 Finder 或簡報中即可一鍵調用。"
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
                ? "✔ System integration installed successfully! Registered in PowerPoint and Quick Actions."
                : "✔ 系統整合安裝成功！已註冊至 PowerPoint 與系統服務。"
        case .uninstallSuccess:
            return isEn
                ? "✔ Successfully removed all macOS system integration services (Quick Actions & menus)."
                : "✔ 已成功移除所有 macOS 系統整合服務（右鍵快速動作與選單）。"
        case .doctorFailedAlert:
            return isEn ? "Diagnostics Execution Failed" : "診斷執行失敗"
        case .interfaceLanguage:
            return isEn ? "Interface Language" : "介面語言"
        }
    }
}
