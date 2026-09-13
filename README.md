# SlideBridge

修復 PowerPoint 在 Mac 上顯示異常的 Windows／Origin EMF 圖形：掃描 `.pptx` 中的 EMF／WMF，用本機轉換器產生 PNG 重新接上關聯，輸出新簡報，同時保留原始 OLE 二進位（Windows 端仍可雙擊用 Origin 編輯）。另有已驗證的 [Origin OLE 編輯橋接](docs/origin-bridge.md)：從簡報抽出 OLE、在 Windows VM 用 Origin 編輯、再成對寫回，全程不需要 Windows PowerPoint。

## 系統需求與依賴安裝 (Prerequisites & Dependencies)

SlideBridge 採**極致輕量、零多餘依賴**設計。進行圖表修復時，**不需要 `pip install` 任何 Python 第三方套件**。

### 1. 必備基礎環境（所有修復功能）

| 項目 | 需求版本 | 說明與安裝指令 |
| --- | --- | --- |
| **作業系統** | macOS 12+ | 原生支援 Apple Silicon (M 系列) 與 Intel Mac |
| **Python** | 3.10+ | 系統內建或 Homebrew 安裝均可；**純標準函式庫，零 pip 第三方依賴** |
| **resvg** | 最新版 | 純 CLI 靜音向量渲染引擎。<br>• **一鍵自動安裝**：執行 `bash scripts/install_mac_integration.sh`（或透過 App 引導精靈）會自動檢查並安裝<br>• **手動安裝**：`brew install resvg` |
| **emf2svg-conv** | 專案內建 | 修補版 EMF 轉換工具，**專案已內建於 `bin/emf2svg-conv`**，免手動安裝 |

> [!TIP]
> 隨時可執行診斷指令確認本機所有環境與依賴就緒狀態：
> ```sh
> python3 -m slidebridge doctor
> ```

### 2. 進階功能需求（選配）

- **在 Mac 上一鍵編輯 Origin 圖表（跨機雙向橋接）**：
  - **Microsoft PowerPoint for Mac**
  - **Parallels Desktop**（目前唯一支援免 guest 帳密跨機調用之虛擬機引擎）
  - **Windows 虛擬機**：已安裝 Origin / OriginPro（支援 Origin 9.5、2021 等各版本），並已啟用與 Mac 的家目錄共享（`\\Mac\Home`）
  - **Windows Helper**：`dist/origin-bridge.exe`（**專案已預先編譯**，無需手動構建）
  - **macOS 權限**：首次在 PowerPoint 觸發時，需在「系統設定 → 隱私權與安全性」允許「自動化」與「輔助使用」權限。

### 3. 開發者重新編譯工具（僅限需修改底層 C++/Swift 原始碼時）

- **重編 macOS SwiftUI App**：Xcode Command Line Tools (`xcode-select --install`)，執行 `bash scripts/build_mac_app.sh`
- **重編 Windows Helper (`origin-bridge.exe`)**：`brew install mingw-w64`，執行 `bash scripts/build_origin_bridge.sh`
- **重編修補版 `emf2svg-conv`**：`brew install cmake libpng`，執行 `bash scripts/build_patched_emf2svg.sh`

---

## 三種用法

### 1. macOS 原生 App（`dist/SlideBridge.app`）

拖曳 `.pptx` 進視窗即可批次修復（300 DPI PNG、保留 OLE），內含環境診斷與一鍵重裝系統整合。雙擊 `dist/SlideBridge.app` 或 `open dist/SlideBridge.app` 啟動。

若要在 Mac PowerPoint 雙擊 Origin 圖表編輯，請保持 SlideBridge 開啟，並在「系統設定 → 隱私權與安全性 → 輔助使用」允許 **SlideBridge**。編輯頁必須顯示「監聽中」；「需要輔助使用權限」表示尚無法接管 PowerPoint 的錯誤對話框。授權後會自動重新連線，無需重開 PowerPoint。以本機 ad-hoc 簽章重新編譯 App 後，macOS 可能要求重新授權；若設定中的舊項目已開啟但 App 仍顯示需要權限，請移除舊項目，再加入目前的 `dist/SlideBridge.app`。Windows VM 也需啟動並已安裝 Origin。

雙擊接管透過 macOS 輔助使用 API 關閉 PowerPoint 的 OLE 伺服器錯誤，再啟動編輯橋接；錯誤視窗可能短暫出現。

### 2. PowerPoint 服務選單（一鍵編輯 Origin 圖表）

安裝後在 PowerPoint 選取圖表 → `Microsoft PowerPoint → 服務 (Services) → 在 Origin 編輯 (SlideBridge)`，完成後自動熱重載並停在原投影片。

```sh
bash scripts/install_mac_integration.sh   # 安裝 / 更新；搬家後重跑即可
```

Finder 右鍵快速動作已移除：Automator 沙箱會擋下 shell 呼叫，且功能與 App 拖放重疊。

### 3. 指令列

需要 Python 3.10+；修復採用純命令列渲染器 [resvg](https://github.com/linebender/resvg)（無 GUI、背景靜音、速度快 5~10 倍且原生支援透明背景）。EMF 圖形先經由專案內建的修補版 `bin/emf2svg-conv`（基於 libemf2svg）轉為 SVG，再交由 resvg 渲染為高解析度 PNG。

```sh
brew install resvg           # 必要依賴：純 CLI 靜音渲染器

python3 -m slidebridge scan input.pptx --json
python3 -m slidebridge fix input.pptx                      # 預設輸出 input_fixed.pptx，自動調用 resvg
python3 -m slidebridge fix input.pptx -o out.pptx --dpi 600
python3 -m slidebridge fix input.pptx --renderer /path/to/resvg  # 指定自訂 resvg 執行檔路徑
python3 -m slidebridge doctor                              # 環境預檢
```

`python3 -m pip install -e .` 後可改用 `slidebridge` 指令。

WMF 為 16 位元過時格式，SlideBridge 預設略過自動轉換以避免破圖（原樣保留在簡報封裝內）；若有舊 WMF 圖片，建議在 Windows 端存為 EMF，或透過 `--preview` 指定正確的 PNG。`--no-transparent` 會略過白色邊界去背；它不會把 renderer 原本輸出的透明區域填成白色。

## 修復流程與限制

1. 檢查 ZIP package，列出 metafile 圖片與 OLE 預覽圖。
2. 逐一產生 PNG，預設 300 dpi（依 metafile 原始尺寸），libemf2svg 路徑最長邊上限 4096 px。
3. 更新圖片 relationships 與 PNG content type，保留原有 OLE `.bin`、投影片 XML 與其他內容，寫入新檔，不覆寫原稿。

保留原始 metafile，所以修復檔仍可能含有未使用的 EMF／WMF；`scan` 是 package 庫存，不是視覺判定。PNG 放大仍受解析度限制。來源缺少預覽、預覽已損壞、或外部 linked OLE 資料遺失時無法重建原圖。

## Origin OLE 編輯橋接

| 指令 | 用途 |
| --- | --- |
| `prepare-ole` | 抽出 OLE 安全副本（`original.bin`、`editable.bin`、`manifest.json`），記錄 SHA-256 與投影片關聯 |
| `writeback-ole` | 將編輯後的 OLE 與對應預覽圖成對寫回 |
| `edit` | 從清單選取圖表，自動跨 Parallels VM 編輯並回寫 |
| `edit-active` | 編輯 PowerPoint 目前選取的圖表，完成後熱重載並回到原投影片 |

```sh
python3 -m slidebridge edit-active                 # 一鍵：編輯目前選取的圖表
python3 -m slidebridge edit presentation.pptx      # 指定簡報，從清單選圖表

# 手動分步
python3 -m slidebridge prepare-ole input.pptx \
  --member ppt/embeddings/oleObject1.bin -o .cache/ole-session --json
python3 -m slidebridge writeback-ole input.pptx \
  --session .cache/ole-session -o .cache/presentation_writeback.pptx --json
```

`writeback-ole` 強制成對回寫（OLE 與預覽圖缺一即中止），比對 `manifest.json` 的 `source_sha256` 偵測來源衝突並預設拒絕，輸出採暫存檔原子替換。`--in-place` 原地更新並自動保留 `.sb_backup.pptx`。

Windows 端需 `origin-bridge.exe`（交叉編譯：`bash scripts/build_origin_bridge.sh`）。

### 環境假設

- **只有 Parallels Desktop 支援一鍵編輯**：它同時具備「免 guest 帳密執行」（`prlctl exec --current-user`）與可預期的共享資料夾（`\\Mac\Home`）。UTM／VMware Fusion／VirtualBox 會被偵測到，但明確回報不支援及原因。`--vm-backend` 可指定，預設自動偵測。
- **session 必須在家目錄下**（guest 只看得到家目錄共享）。預設 `.cache/sessions`，checkout 不在家目錄時改用 `~/Library/Caches/SlideBridge/sessions`；`--session` 指定到家目錄外會直接報錯。
- **路徑與解譯器不需手寫**：安裝腳本把 checkout 路徑寫入 `~/.slidebridge/project-root`；GUI 啟動（PowerPoint、雙擊 .app）繼承的精簡 PATH 與 python3 選擇都由 `locate.py`／`python_env.sh` 處理，只接受 3.10 以上。

### 實測一鍵流程

先 `python3 -m slidebridge doctor`：依失敗順序檢查 Python、專案路徑、handler 是否指向這份 checkout、PowerPoint、PowerPoint 服務選單、hypervisor CLI、執行中的 Windows guest、Windows helper；任何 `[FAIL]` 附修復指令並以非零結束（`--json` 可機器讀）。**檢查全在 macOS 端執行**，Windows 只需既有 Origin 與 `origin-bridge.exe`。`Running Windows guest` 失敗有三種不同意義（找不到 hypervisor／Parallels 無法查詢／沒有 VM 在跑），doctor 會分開回報。

全綠後：

1. **先用副本測**：`edit-active` 原地覆寫（會留 `.sb_backup.pptx`）。
2. 在 PowerPoint 點選圖表（必須是選取狀態），觸發服務選單項目；首次會問自動化權限，選允許。
3. VM 躍至前台，Helper 與 Origin 開啟；改一個明顯可見的東西（例如軸標題）。
4. **在 Origin 內按 Ctrl+S 存檔**——少了這步，序列化出來的仍是未變更文件。
5. 點 Helper 的 **Save and Close**：helper 透過 COM（`Origin.ApplicationSI`）驅動 LabTalk `expGraph`，在 session 目錄輸出 300+ DPI 的 `preview.png`，不必手動匯出。COM 不可用時，手動在 Origin 匯出到 session 目錄並命名 `preview.png`。
6. PowerPoint 自動熱重載、停留在原投影片。

出現 `byte-identical` 錯誤代表沒在 Origin 內存檔或圖表沒變化——這道防護就是不讓「毫無變化的回寫」假裝成功。服務選單找不到項目時，到 `系統設定 → 鍵盤 → 鍵盤快速鍵 → 服務` 確認已勾選。

## 驗證狀態

- 已用真實 Origin95.Graph 簡報完成 EMF 轉換與 package 完整性驗證（第 4／5 頁共 5 個 OLE 位置、4 份嵌入資料）；修復檔在 Mac PowerPoint 正常顯示，Windows Origin 雙擊編輯成功。
- Inkscape 1.4.4 ARM 原生 EMF 匯入全部崩潰，專案已完全廢除 Inkscape 相依，改採純 CLI 的 `libemf2svg` + `resvg` 高速管線。線寬、旋轉文字（軸標題、上下標）與 XPS 擬合的 XOR 網底已在 `patches/` 修正並編入 `bin/emf2svg-conv`。
- 保留 OLE bytes 不等於 Office 會接受所有變體；輸出仍需在 Mac PowerPoint 檢視，並在 Windows + Origin 驗證編輯流程。數位簽章修改後不再有效。
- **尚未開始**：PowerPoint Add-in。核心目前依賴本機 resvg，移植到 Office WebView 需要轉換服務或 WASM 後端。

測試：181 項 Python 單元測試（含 14 項原生 EMF 渲染測試），另有 4 項 C++ 持久化測試。

```sh
python3 -m unittest discover -s tests -v                                        # 181 項，其中 14 項原生 EMF skip
SLIDEBRIDGE_TEST_EMF2SVG=bin/emf2svg-conv python3 -m unittest discover -s tests -v   # 181 項全跑
python3 scripts/verify_package.py input.pptx input_fixed.pptx                   # 真實樣本完整性比對
```

## 使用 Windows 原圖保留外觀

若自動轉換的外觀仍不對，但有 Windows／Origin 匯出的正確 PNG，可指定它作為對應 metafile 的預覽：PNG bytes、解析度、透明度完整保留，跳過該圖片的 renderer，OLE 與投影片位置／尺寸維持原樣。

```sh
python3 -m slidebridge fix input.pptx -o windows-previews.pptx \
  --preview 'ppt/media/image5.emf=/path/to/windows-line-chart.png' \
  --preview 'ppt/media/image8.emf=/path/to/windows-bar-chart.png'
```

`--preview` 可重複，只接受來源 package 已存在的 EMF／WMF 路徑；未指定的 metafile 仍走自動轉換。共用同一圖片的多張投影片或 VML 分支會一起更新關聯。請用完整圖框且長寬比相符的匯出圖——工具保留既有大小與裁切，不會重新排版。`--json` 以 `method: reference-png`／`method: rendered` 區分兩者。

## 參考

- [Microsoft OleObject 結構](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.presentation.oleobject)
- [resvg](https://github.com/linebender/resvg)
- [libemf2svg](https://github.com/kakwa/libemf2svg)
