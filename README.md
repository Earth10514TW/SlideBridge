# SlideBridge

Fix PowerPoint graphics across Windows and Mac.

另有已完成雙向驗證的 [Origin OLE 編輯橋接功能](docs/origin-bridge.md)：從簡報抽出 OLE 副本（`prepare-ole`），由 Windows 原生 helper 載入 Origin 進行本機編輯，並在產出更新後預覽圖時，以安全成對約束回寫簡報（`writeback-ole`），全程無需 Windows PowerPoint。

SlideBridge 的第一版是本機 CLI：掃描 `.pptx` 中的 EMF／WMF，使用本機轉換器產生 PNG，重新連接圖片關聯，輸出新的簡報。可處理普通圖片與 OLE 物件的預覽圖；不執行或解碼 Origin OLE。

## 快速上手：macOS 原生應用程式與系統整合 (GUI)

除了指令列之外，SlideBridge 提供基於 **SwiftUI 原生打造的 macOS 桌面應用程式** 與 **Finder 右鍵快速動作**：

1. **原生桌面 App (`dist/SlideBridge.app`)**：
   - **批次修復**：直接拖曳 `.pptx` 進入視窗，一鍵將損壞的 EMF 渲染為 300 DPI 高畫質 PNG，完整保留原始 OLE 二進位檔。
   - **Origin 互動編輯**：在 Mac PowerPoint 選取圖表後，點擊按鈕直接喚醒 Windows VM 進行繪圖修改並自動熱重載。
   - **環境診斷**：一鍵檢測 Python、PowerPoint、Inkscape、Parallels 虛擬機狀態，並可一鍵重新安裝系統整合。
   - 啟動方式：雙擊 `dist/SlideBridge.app`（或在終端機輸入 `open dist/SlideBridge.app`）。

2. **Finder 右鍵快速動作 (Quick Action)**：
   - 在 Finder 對任意 `.pptx` 檔案點右鍵 ➔ **快速動作 (Quick Actions)** ➔ **修復 PPT 圖片 (SlideBridge)**。
   - 自動在同目錄產出 `<檔名>_fixed.pptx` 並發出系統通知，完全無須開啟終端機。

3. **一鍵安裝所有 Mac 系統整合**：
   ```sh
   bash scripts/install_mac_integration.sh
   ```

---

## 指令列使用 (CLI)

需要 Python 3.10+。掃描不需額外依賴；修復需要另行安裝 [Inkscape](https://inkscape.org/release/)，EMF 建議同時安裝 libemf2svg；偵測到 `emf2svg-conv` 時，會先轉成 SVG 再交給 Inkscape 輸出 PNG，避開部分 macOS Inkscape 版本的 EMF 匯入崩潰。WMF 仍由 Inkscape 直接讀取。

```sh
brew install --cask inkscape
brew install libemf2svg
```

```sh
python3 -m slidebridge scan input.pptx
python3 -m slidebridge scan input.pptx --json
python3 -m slidebridge fix input.pptx
python3 -m slidebridge fix input.pptx -o repaired.pptx --dpi 600
```

預設輸出 `input_fixed.pptx`，不覆寫原稿或現有檔案。自動尋找 PATH 與 macOS `/Applications/Inkscape.app`，亦可指定：

```sh
python3 -m slidebridge fix input.pptx --inkscape /path/to/inkscape
```

可選：`python3 -m pip install -e .` 後使用 `slidebridge` 指令。

## 處理方式

1. 檢查 ZIP package，列出 metafile 圖片及 OLE 預覽圖。
2. 在暫存目錄逐一產生 PNG，預設 300 dpi（依 metafile 原始尺寸，非投影片上的實際尺寸）。libemf2svg 路徑的輸出最長邊上限為 4096 px，避免 Origin 的超大原始尺寸消耗大量記憶體。
3. 更新 package 內部圖片 relationships 與 PNG content type。
4. 保留原有 OLE `.bin`、投影片 XML 與其他未修改項目的內容，寫入新檔。

保留原始 metafile，因此修復檔仍可能含有未被使用的 EMF／WMF；scan 顯示的是 package 庫存，不是視覺問題判定。PNG 是點陣圖，放大仍受解析度限制。

## Origin OLE 編輯橋接

除了替換預覽圖，SlideBridge 也能直接編輯嵌入的 Origin OLE 物件，全程不需 Windows PowerPoint。架構、安全不變量與驗證紀錄見 [docs/origin-bridge.md](docs/origin-bridge.md)。

| 指令 | 用途 |
| --- | --- |
| `prepare-ole` | 抽出 OLE 安全副本（`original.bin`、`editable.bin`、`manifest.json`），記錄來源與 OLE 的 SHA-256 及投影片關聯。 |
| `writeback-ole` | 將編輯後的 OLE 二進位與對應預覽圖成對寫回簡報。 |
| `edit` | 以清單選取圖表，自動跨 Parallels Windows VM 編輯並回寫。 |
| `edit-active` | 編輯 Mac PowerPoint 目前選取的圖表，完成後熱重載並停留在原投影片。 |

Windows 端需有 `origin-bridge.exe`（交叉編譯：`bash scripts/build_origin_bridge.sh`）；Mac 端一鍵整合安裝：`bash scripts/install_mac_integration.sh`。

```sh
# 一鍵：編輯目前選取的圖表（需 Parallels Desktop 與執行中的 Windows VM）
python3 -m slidebridge edit-active

# 指定簡報，從清單選擇圖表
python3 -m slidebridge edit presentation.pptx

# 手動分步：抽出 → 於 Windows 編輯 → 回寫
python3 -m slidebridge prepare-ole input.pptx \
  --member ppt/embeddings/oleObject1.bin -o .cache/ole-session --json
python3 -m slidebridge writeback-ole input.pptx \
  --session .cache/ole-session -o .cache/presentation_writeback.pptx --json
```

`writeback-ole` 強制成對回寫（OLE 與預覽圖缺一即中止），比對 `manifest.json` 的 `source_sha256` 偵測來源衝突並預設拒絕，輸出採暫存檔原子替換。加 `--in-place` 可原地更新，並自動保留 `.sb_backup.pptx` 備份。

### 支援的虛擬機與路徑

一鍵編輯需要兩個條件同時成立：能在不儲存 guest 帳密的前提下於 guest 內執行程式，以及能把 macOS 路徑自動轉成 guest 路徑。**目前只有 Parallels Desktop 同時具備這兩項**（`prlctl exec --current-user` 搭配 `\\Mac\Home` 共享資料夾對應）。

其他 hypervisor 會被自動偵測，但不會被誤用——若偵測到執行中的 guest 卻無法透過它編輯，會明確指出是哪一個、以及為什麼，而不是籠統回報「找不到 Parallels」：

| Hypervisor | 偵測 | 一鍵編輯 | 原因 |
| --- | --- | --- | --- |
| Parallels Desktop | 是 | **支援** | 無需帳密，且有可預期的共享資料夾對應 |
| UTM | 是 | 尚不支援 | 共享資料夾機制不同，無法自動轉換路徑 |
| VMware Fusion | 是 | 尚不支援 | `vmrun` 需 guest 帳密（`-gu`／`-gp`） |
| VirtualBox | 是 | 尚不支援 | `VBoxManage guestcontrol` 需 guest 帳密 |

可用 `--vm-backend`（`edit` 與 `edit-active` 皆支援）指定要驅動的 hypervisor，預設為自動偵測。

**路徑不需要手寫。** 安裝腳本會把實際的 checkout 路徑寫入 `~/.slidebridge/project-root`；AppleScript 執行時依序讀取 `SLIDEBRIDGE_PROJECT_ROOT` 環境變數、該設定檔，最後才退回安裝時寫入的值。因此把專案搬到別的位置後重跑 `bash scripts/install_mac_integration.sh` 即可，repo 本身不含任何機器專屬路徑。

從 PowerPoint 或雙擊 `.app` 觸發時，程式繼承的是 launchd 的精簡 PATH（通常不含 `/usr/local/bin` 與 Homebrew），工具會自行重建 login PATH。

解譯器則依序尋找 `SLIDEBRIDGE_PYTHON` → Homebrew → `/usr/local/bin` → python.org framework 安裝（版本新到舊）→ MacPorts → PATH 上的 `python3`，且只接受 3.10 以上。**不需要額外安裝任何東西**：你原本就有的較新 python3 會被直接採用。`scripts/edit_active_presentation.sh --print-python` 會印出實際選用的解譯器，`slidebridge doctor` 也以此為準。

編輯過程的中介檔（session）**必須位於家目錄下**，因為 Windows guest 只能透過家目錄共享（`\\Mac\Home`）看到 Mac。預設放在專案的 `.cache/sessions`；若 checkout 不在家目錄下則改用 `~/Library/Caches/SlideBridge/sessions`。用 `--session` 指定其他位置時同樣受此限制，路徑不在家目錄下會直接報錯並說明原因。

### 驗證一鍵流程

先在終端機跑預檢，確認每個環節就緒：

```sh
python3 -m slidebridge doctor
```

它依實際失敗順序檢查：Python 版本、專案路徑、已安裝的 handler 是否指向這份 checkout、PowerPoint、Quick Action 服務、hypervisor CLI、執行中的 Windows guest、Windows helper。任何 `[FAIL]` 都會附上修復指令，並以非零狀態結束；`--json` 輸出機器可讀格式。

**所有檢查都在 macOS 端執行。** `Running Windows guest` 這一項只是向 Parallels 詢問「目前有哪些 VM 在執行中」，**不需要在 Windows 裡面安裝 Python 或任何東西**——Windows 端只需要原本就有的 Origin 與 `origin-bridge.exe`。這一項失敗時有三種不同意義，doctor 會分開回報：找不到 hypervisor、Parallels 裝了但無法查詢（通常是 Parallels Desktop 尚未啟動過）、以及 hypervisor 正常但沒有 VM 在跑。

預檢全綠後，在 PowerPoint 端實測：

1. **先複製一份簡報再測。** `edit-active` 預設原地覆寫，雖然會保留 `.sb_backup.pptx`，但別拿本尊當白老鼠。
2. 用 Mac PowerPoint 開啟該副本，**點選**要編輯的 Origin 圖表（務必是選取狀態，工具靠選取範圍定位 OLE 物件）。
3. 觸發：選單 `Microsoft PowerPoint → 服務 (Services) → 在 Origin 編輯 (SlideBridge)`。
4. 首次執行 macOS 會詢問自動化權限（「PowerPoint 想要控制…」），選允許。
5. Parallels VM 躍至前台，Helper 與 Origin 視窗開啟；在 Origin 改一個明顯可見的東西，例如把軸標題文字改掉。
6. **在 Origin 內按 Save（Ctrl+S）存檔。** 這步不能省略——helper 狀態列寫著「Save explicitly to commit」。若只在 Origin 修改卻沒在 Origin 內存檔，序列化出來的仍是未變更的文件。
7. **點 Helper 的 Save and Close（自動觸發 COM 匯出）：**
   - Helper 會自動透過 COM Automation 掛接執行中的 Origin（`Origin.ApplicationSI`），驅動 LabTalk `expGraph` 在 session 目錄即時輸出高畫質 `preview.png`（300+ DPI）。**完全無須手動匯出檔案**！
   - （備用方案）：若特殊環境下未啟用 COM 自動化，亦可手動在 Origin 匯出至 session 目錄並命名為 `preview.png`。
8. PowerPoint 自動熱重載、停留在原投影片並顯示更新，同目錄自動出現 `.sb_backup.pptx` 備份檔。

若出現 `the new preview image is byte-identical` 或 `the edited OLE is byte-identical` 的錯誤，代表未在 Origin 內存檔或圖表未產生變化——這道防護存在的目的就是不讓「毫無變化的回寫」假裝成功。

若在服務選單找不到該項目，到 `系統設定 → 鍵盤 → 鍵盤快速鍵 → 服務` 確認已勾選。

## 邊界與驗證

本專案提供跨平台混合管線：Python 核心引擎、Windows 原生 OLE Helper (`dist/origin-bridge.exe`)，以及 macOS 原生 SwiftUI 桌面 App (`dist/SlideBridge.app`)。已用真實 Origin95.Graph 簡報完成 EMF 轉換、輸出圖片檢視與 package 完整性驗證（第 4／5 頁共 5 個 OLE 位置、4 份嵌入資料）。Inkscape 1.4.4 ARM 原生 EMF 匯入全部崩潰，libemf2svg 1.8.1 中介路徑可完成轉換。修復後的簡報已在 Mac PowerPoint 正常顯示，Windows Origin 的雙擊編輯亦已驗證成功；線寬與旋轉文字（軸標題、上下標）的偏差已在原生回歸測試中修正。保留 OLE bytes 不等於已證明 Office 會接受所有變體；請在 Mac PowerPoint 檢視輸出，再於 Windows + Origin 驗證編輯流程。來源缺少預覽、預覽已損壞、外部 linked OLE 資料遺失時，無法重建原圖。數位簽章不會因修改後仍有效。

自動測試使用合成 OOXML 與替身 renderer，驗證封裝與保留行為；真實樣本另外執行轉換與 package 比對。樣本與產物放在忽略的 `dist/`、`bin/` 與 `.cache/`，不提交 Git。目前共 134 項 Python 單元測試（含 9 項原生 EMF 渲染測試）。

```sh
# 預設執行 125 項；9 項原生 EMF 測試會因未指定後端而 skip
python3 -m unittest discover -s tests -v

# 指定專案內已修補的轉換器後，134 項全數執行
SLIDEBRIDGE_TEST_EMF2SVG=bin/emf2svg-conv python3 -m unittest discover -s tests -v
```

後續階段：真實 Origin 樣本回歸 → SVG + PNG fallback → macOS 拖放介面 → PowerPoint Add-in。核心目前依賴本機 Inkscape；移植到 Office WebView 尚需設計轉換服務或 WASM 後端。

## 技術依據

- [Microsoft OleObject 結構](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.presentation.oleobject)：OLE 物件可含預覽圖片。
- [Inkscape CLI](https://wiki.inkscape.org/wiki/Using_the_Command_Line)：PNG 匯出與解析度參數。

真實樣本完整性比對：

```sh
python3 scripts/verify_package.py input.pptx input_fixed.pptx
```

- [libemf2svg](https://github.com/kakwa/libemf2svg)：EMF → SVG 本機解析器。

## 使用 Windows 原圖保留外觀

自動 EMF → SVG 轉換可能改變線寬、矩形邊框或上下標位置；ZIP／OLE 檢查通過不代表外觀一致。若有 Windows／Origin 匯出的正確 PNG，可指定它作為對應 metafile 的預覽。PNG bytes、解析度、透明度完整保留，跳過該圖片的 renderer，OLE 與投影片的位置／尺寸保持原樣。

先使用 `scan --json` 找到 package 內的圖片路徑，再依圖形內容確認對應關係：

```sh
python3 -m slidebridge fix input.pptx -o windows-previews.pptx \
  --preview 'ppt/media/image5.emf=/path/to/windows-line-chart.png' \
  --preview 'ppt/media/image8.emf=/path/to/windows-bar-chart.png'
```

`--preview` 可重複使用；它只接受來源 package 已存在的 EMF／WMF 路徑。未指定的 metafile 仍使用自動轉換。同一圖片若被多張投影片或 VML 分支共用，所有內部關聯會一起更新。請使用完整圖框且長寬比相符的 Windows 匯出圖，因為工具保留既有投影片上的圖片大小與裁切，不會自動重新排版。

`--json` 報告以 `method: reference-png` 區分原圖置入與 `method: rendered` 的自動轉換。這是高保真預覽替換功能，並未修正通用 EMF 解析器的所有渲染差異。
