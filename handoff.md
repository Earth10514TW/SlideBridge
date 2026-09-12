# SlideBridge handoff（開發交接）

Updated: 2026-09-12. 使用者面向的說明在 [README.md](README.md)，Origin 橋接的架構與安全不變量在 [docs/origin-bridge.md](docs/origin-bridge.md)。本檔只記錄「接手時需要知道、但讀程式碼看不出來」的事。

## UI 與 ⌘O 修正與驗收（2026-09-12 已完成）

已完成 macOS SwiftUI 介面重構與全域 ⌘O 快捷鍵驗收，並通過自動化 AX 測試：

### ⌘O 與 Commands 重構
- `SlideBridgeApp`（App 頂層）持有 `AppState` 與各頁 ViewModel（`BatchRepairViewModel`、`OriginEditViewModel`、`DoctorViewModel`），直接傳入 `PresentationCommands` 與 `ContentView`。
- 徹底解決依賴 `FocusedValue` 導致焦點遺失或彈窗關閉後選單命令失效的問題。
- File 選單命令「選擇簡報檔案...」（⌘O）在以下情境全數實測驗證通過：
  - 批次修復空白頁：按 ⌘O 正常彈出原生選檔視窗，取消後回復就緒。
  - Origin 互動編輯頁：按 ⌘O 自動導航切回批次修復頁並彈出選檔視窗，取消後維持在批次修復頁。
  - 系統環境診斷頁：按 ⌘O 自動導航切回批次修復頁並彈出選檔視窗，取消後維持在批次修復頁。
  - 忙碌狀態保護：掃描中、修復中或選檔視窗開啟時，選單命令與 ⌘O 自動禁用（disabled）。
  - 繁中／英文切換：選單命令名稱（「選擇簡報檔案...」與 "Choose Presentation..."）及各頁面內容即時雙向更新。

### 文案清理與細節修正
- 清理 `Localization.swift` 中殘留的「快速動作 / Quick Actions」字樣，與已廢除 Finder Quick Action、僅保留 PowerPoint 服務選單的現況完全對齊。
- 診斷頁移除系統整合改用原生 macOS `.alert` sheet，文案與確認行為符合 Apple Design 規範。
- `scripts/build_mac_app.sh` 增加 `xattr -cr` 與 ad-hoc code sign（`codesign --force --deep --sign -`），確保產出的 App 簽名合規。

### 驗證結果
- Python 147 項單元測試全綠通過（含 14 項 patched emf2svg-conv 測試）。
- AX 自動化巡檢三頁面切換、⌘O 觸發與取消、語言即時切換皆正常。

## 初次引導設定精靈與系統診斷整合（2026-09-12 新增）

- **架構設計**：
  - 引導設定（`OnboardingView`）為一次性（One-time）或手動喚起的 4 步驟設定精靈：
    1. 歡迎與語言偏好（繁體中文 / English / 跟隨系統）。
    2. 使用模式選擇（純批次修復 `batchOnly` vs Origin 雙向編輯 `fullBridge`）。
    3. 系統整合（一鍵安裝 PowerPoint 服務選單腳本）與 macOS 輔助使用權限引導（`PPTAlertInterceptor.openAccessibilityPreferences()`）。
    4. 完成設定與跳轉（自動導向選擇的使用模式分頁）。
  - 狀態儲存於 `AppState` 之 `@AppStorage("has_completed_onboarding")` 與 `@AppStorage("selected_usage_mode")`。首次啟動若未完成則自動彈出原生 Sheet。
  - 診斷（`DoctorView`）保留作為動態體檢與日常排錯中心，並於頂部新增「重新執行引導設定」按鈕（`rerunOnboardingButton`）；macOS 頂層「輔助說明 (Help)」選單亦加入「設定引導精靈...」快捷命令，兩者相輔相成。
- **編譯注意**：
  - 命令列 `swiftc` 編譯時避開 Swift 5.9+ `@State` 巨集外掛缺失問題，`OnboardingView` 採用專屬 `OnboardingViewModel: ObservableObject` 與 `@StateObject` 管理狀態與輪詢計時器。

## PPT 雙擊圖表自動接管機制（2026-09-12 新增）

- **背景與原理**：Mac 版 PowerPoint 雙擊 Windows Origin OLE 圖表時，因本機無對應伺服器會彈出「找不到此物件的伺服器應用程式」錯誤 Sheet。
- **實作**：`mac/SlideBridgeApp/Utilities/PPTAlertInterceptor.swift`
  - 使用 macOS `AXObserver` 專注監聽 PowerPoint（`com.microsoft.Powerpoint`）之 `kAXSheetCreatedNotification` 與 `kAXWindowCreatedNotification`。
  - 當建立的視窗／Sheet 含有「伺服器應用程式」或 "server application" 時，於數十毫秒內自動透過 `AXPress` 點擊「確定」關閉視窗，並呼叫 `editActive()` 跨機開啟圖表編輯。
  - 具備 2.5 秒防抖（debounce）保護，防止連續事件觸發多次編輯。
  - 透過 `NSWorkspace` 自動監聽 PowerPoint 啟動與終止事件，動態掛載與解除 Observer。
- **UI 整合**：於「Origin 互動編輯」頁面新增專屬控制卡片，即時反映監聽狀態（🟢 監聽中、🟡 PowerPoint 未開啟、⚪ 已停用），並提供 Toggle 開關讓使用者隨時啟用／停用。已完成中英文雙語支援。

## 目標與限制

修復 Mac PowerPoint 上顯示異常的 Windows／Origin EMF 圖形，並保留原始嵌入 OLE（Windows 端雙擊仍能用 Origin 編輯）。使用者要求修的是**通用自動轉換器本身**，不能用提供的 Windows PNG 取代——那些圖只能當比對參考。

## 目前的組成

- **Python 核心 `slidebridge/`**：`core` 掃描／修復、`bridge` OLE 橋接、`powerpoint` 選取定位與熱重載、`vm` Parallels 後端、`doctor` 環境預檢、`locate` GUI 啟動時的 PATH 重建、`cli`。
- **Windows 原生 OLE host `native/origin-bridge/`**（MinGW 交叉編譯成 `dist/origin-bridge.exe`）：載入 Origin 編輯、顯示預覽、存檔時匯出預覽圖。
- **macOS SwiftUI App `mac/SlideBridgeApp/`** → `dist/SlideBridge.app`：批次修復、互動編輯、環境診斷。
- **修補過的轉換器**：`patches/` 三支 patch，`scripts/build_patched_emf2svg.sh` 編成 `bin/emf2svg-conv`。

## 踩過的坑（不要重蹈）

1. **Origin 不會刷新 OLE 的簡報快取。** 實測 `Contents` 串流有變、`OlePres000/001` 完全沒變：Origin 在 `OLEIVERB_OPEN` 模式下不會重繪，也不更新簡報快取。任何從 OLE 物件本身取圖的路徑（`IDataObject(CF_ENHMETAFILE)`、`OleDraw`）都拿不到新畫面。
   → 現在的做法：helper 存檔時用 COM 掛上執行中的 Origin（`Origin.ApplicationSI`），跑 LabTalk `expGraph type:=png filename:="preview" path:="<session>" overwrite:=replace;`（`overwrite:=replace` 必要，預設會彈對話框卡住自動化）。預覽候選順序 `preview.png > preview.emf > edited.png > edited.emf`。已在 Windows 11 Lite VM + OriginPro 2021 實測：13206×2669、300+ DPI 的 `preview.png`。
2. **兩道 guard 擋住「假成功」**：`bridge._reject_unchanged_ole`（OLE 完全相同、或同長度但差異 < 0.1% 即拒）與 `_reject_unchanged_preview`（新預覽與簡報內既有預覽完全相同即拒）。兩者都**不能被 `force` 繞過**——`edit-active` 一定傳 `force=True`，但那是為了跳過來源雜湊檢查，是另一件事。逃生門是 `--allow-unchanged`。
3. **session 目錄必須在 `$HOME` 下**，guest 只能透過 `\\Mac\Home` 看到 Mac。曾因放到 `tempfile.gettempdir()` 而拿到 `HRESULT=0x80070043`（其實是 `ERROR_BAD_NET_NAME`，不是「檔案已存在」）。`vm._require_guest_reachable()` 現在會提前擋下並說明原因。
4. **預覽圖關聯要查 `mc:Fallback` 分支。** PowerPoint 用 `<mc:AlternateContent>` 包 OLE，兩個分支帶同一個 `r:id`，預覽只存在 `mc:Fallback` 裡。`bridge._find_preview_members` 以前只取第一個符合的 `<p:oleObj>`，導致 `edit-active` 找不到預覽（手動流程會明確傳 `--preview`，所以以前沒暴露）。
5. **libemf2svg 的三個渲染缺陷已修**：筆寬（`stroke_draw` 把一般 `EMR_CREATEPEN` 當 cosmetic 強制 width 1）、旋轉文字（`text_style_draw` 多加了 font-height 相關位移，讓上下標散開）、XPS 擬合（1-bpp `PATINVERT`/`DSTINVERT` 被畫成不透明遮蓋方塊、`U_BS_MONOPATTERN` 吐出無效 `fill="#img-X-ref"`、世界座標轉換下 clip path 被縮小 4 倍）。
6. **Finder 右鍵快速動作已移除**（2026-09-12）。Automator 沙箱會因 `com.apple.provenance` 擋下 shell 呼叫，且功能與 App 拖放重疊。安裝腳本會清除舊機器上的殘留 workflow 與 `SlideBridgeFix.scpt`。
7. **doctor 檢查的是 PowerPoint 服務選單**，不是快速動作（雖然常數以前那樣命名）。

## 已驗證

- 真實 Origin95.Graph 簡報：EMF 轉換、輸出檢視、`scripts/verify_package.py` 完整性比對（4 份嵌入 OLE 中只有目標那份改變，其餘 bit-identical、關係重寫、無懸空參照）。
- Windows 11 Lite VM 上的 PowerShell smoke test（`scripts/smoke_origin_bridge.ps1`）100% 通過。
- Mac PowerPoint 熱重載、停留在原投影片、`.sb_backup.pptx` 備份。
- 147 項 Python 單元測試全綠（14 項原生 EMF 需 `SLIDEBRIDGE_TEST_EMF2SVG`），4 項 C++ 持久化測試通過。

注意：`verify_package.py` 若沒有用 `--allow-parts` 指名被改動的 OLE，會回報 `passed: false`，那是預期行為不是失敗。

## 常用指令

```sh
python3 -m unittest discover -s tests -q                                              # 133 項
SLIDEBRIDGE_TEST_EMF2SVG=bin/emf2svg-conv python3 -m unittest discover -s tests -v     # 147 項
bash scripts/build_patched_emf2svg.sh                                                 # 重建修補版轉換器
bash scripts/build_origin_bridge.sh                                                   # 交叉編譯 Windows helper
bash scripts/build_mac_app.sh                                                         # 重建 SwiftUI App
bash scripts/install_mac_integration.sh                                               # 安裝 Mac 系統整合
clang++ -std=c++17 -Wall -Wextra native/origin-bridge/save_sequence_test.cpp -o .build/save-sequence-test
```

## 私有樣本（不進 Git）

`/Users/earth/Downloads/presentation.pptx`（4 個 EMF、第 4/5 頁共 5 個 OLE 位置、4 份嵌入資料）、`/Users/earth/Downloads/圖片1.png` → `ppt/media/image5.emf`、`圖片2.png` → `ppt/media/image8.emf`。`bin/`、`dist/`、`.cache/`、`artifacts/` 皆已忽略。修補後的 libemf2svg 屬 GPLv2，散布時要保留授權與原始碼／patch 取得方式。

## Origin 多版本自動相容性增強（2026-09-12 已完成）

已完成 Windows Helper 與 Python VM 模組之 Origin 多版本自動動態適配：
- **動態 OLE 類別偵測（CheckOriginClass）**：
  - 移除單一 CLSID `{64CC80B2...}` 之硬編碼閘門，支援 `--clsid auto`。
  - 動態查詢 Windows 註冊表中的各版本 Origin ProgID（`Origin95.Graph`、`Origin.Graph`、`Origin.Graph.9` 等）與 `ProgIDFromCLSID`。
  - 讀取 OLE 根目錄 `\CompObj` 使用者型態名稱（User Type Name）與 `Contents` 專屬串流，確認為 Origin 家族物件即自動放行，非 Origin 物件依舊阻擋（安全隔離）。
- **COM Automation 實例掛接優化（AutoExportOriginGraph）**：
  - 優先使用 Windows COM ROT（Running Object Table）之 `GetActiveObject` 連接當前正在編輯圖表之活躍 Origin 實例（`Origin.Application` / `Origin.ApplicationSI`）。
  - 避免舊版或無 `SI` 註冊環境下 `CoCreateInstance` 誤開空白 Origin 視窗的問題。
- **測試覆蓋**：新增 `test_custom_clsid_is_passed_to_helper` 等測試，148 項 Python 單元測試全綠通過。

## 純 CLI 渲染器 resvg 整合（2026-09-12 已完成）

- 核心渲染管線正式整合純命令列工具 **`resvg`**（Rust 開發）：
  - 自動偵測系統 `resvg`，取代原本會喚醒 macOS GUI Dock 圖示彈跳的 Inkscape。
  - 原生支援 RGBA 透明背景，並透過 `png_white_to_transparent` 消除外部白邊。
  - 支援 `--renderer`、`--transparent`、`--no-transparent`，同時保留 `--inkscape` 舊版參數相容性。
  - 160 項單元測試全數通過。

## 待辦

- PowerPoint Add-in（未開始）。
- 移植到 Office WebView 需設計轉換服務或 WASM 後端。
