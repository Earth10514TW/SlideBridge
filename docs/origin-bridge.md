# Origin 編輯橋接原型

目標是讓 Windows 只安裝 Origin 與本專案 helper，就能編輯由 PPTX 抽出的嵌入 OLE。Windows Helper 內建即時圖表預覽畫布（所見即所得），並於儲存時自動匯出成對的向量 EMF 與 300 DPI 高保真 PNG 預覽圖。Word、Mac PowerPoint 雙擊攔截與 Add-in 均未實作。

## 建立測試副本

```sh
python3 -m slidebridge prepare-ole input.pptx \
  --member ppt/embeddings/oleObject1.bin -o .cache/ole-session --json
```

輸出 `original.bin`、`editable.bin` 與 `manifest.json`。目錄必須不存在；原始簡報不變。manifest 記錄來源與 OLE 的 SHA-256、來源 member 及投影片關聯。CLSID 由 Windows 的 `IStorage::Stat` 讀取；CFB 檔案 header 並不直接存放根 storage 的 CLSID。

## 編譯

在 macOS 交叉編譯 Windows x64 可執行檔：

```sh
brew install mingw-w64
bash scripts/build_origin_bridge.sh
```

或在 Windows 的 Visual Studio C++ 開發命令列：

```powershell
cmake -S native/origin-bridge -B build/origin-bridge-build
cmake --build build/origin-bridge-build --config Release
```

## 在 Windows 使用

將 exe 與測試副本複製到 Windows 本機資料夾。使用已登入的桌面使用者執行，以便看到 Origin 視窗；不要用 SYSTEM 執行互動編輯。

```powershell
.\origin-bridge.exe inspect .\editable.bin
.\origin-bridge.exe edit .\editable.bin .\edited.bin --clsid '{64CC80B2-4FA1-4F7B-9D6F-1BFACF5715DC}'
```

指定的 CLSID 必須同時符合檔案與 Windows 上 `Origin95.Graph` 的註冊值；上述值來自本機測試樣本，其他類別不在此原型支援範圍。既有 output 不會覆寫。所有儲存都發生在 output 副本。

- **即時視覺預覽（所見即所得）**：Helper 視窗下方設有圖表預覽畫布，透過 `IAdviseSink` 監聽 Origin 的更新事件，並以 `OleDraw` 即時將圖表以正確長寬比繪製至視窗中央，修改結果立即可見。
- **儲存時自動匯出預覽圖**：按下 Save 或 Save and Close 時，Helper 會同時輸出：
  - `edited.bin`（OLE 二進位儲存檔）
  - `edited.emf`（原始向量圖，由 `IDataObject` 或 `OleDraw` 產出）
  - `edited.png`（由 Windows GDI+ 原生渲染的 300 DPI 點陣圖）
- 只有實際編輯再開啟的結果，才能證明編輯往返成立。儲存後可使用 `edited.bin` 作為下一次 edit 的 input，指定另一個新的 output 進行二次驗證。

## Mac 端一鍵式無縫編輯工作流（slidebridge edit）

若本機安裝有 Parallels Desktop 且虛擬機運行中，可直接在 Mac 端透過 `edit` 子命令達成全自動化跨 VM 編輯與回寫：

```sh
python3 -m slidebridge edit presentation.pptx
# 或使用包裝腳本：
./scripts/edit_presentation.sh presentation.pptx
```

**自動執行流程：**
1. **自動探測**：自動掃描簡報中的所有 Origin OLE 物件；若有多個圖表會以終端機清單提示選擇編號。
2. **自動抽出**：在背景建立 session 安全副本。
3. **自動喚醒與置頂**：自動透過 Parallels CLI（`prlctl`）喚起運行中的 Windows VM（如 `Windows 11 Lite`），並將 Windows Helper 與 Origin 視窗拉至最前景。
4. **即時編輯與預覽**：在 Origin 編輯圖表並存檔，Helper 畫面即時連動並自動生成 `edited.emf` 與 300 DPI `edited.png`。
5. **自動成對回寫**：使用者點擊 Helper 的 Save and Close 後，Mac 端自動偵測存檔完成，立即成對寫回簡報，產出 `presentation_updated.pptx`，全程不需手動指定任何路徑。

## 獨立步驟：手動分步操作與雙向回寫

若偏好手動管理 session 或進行細部除錯，亦可透過分步命令：

```sh
# 1. 抽出 session
python3 -m slidebridge prepare-ole input.pptx \
  --member ppt/embeddings/oleObject1.bin -o .cache/ole-session --json

# 2. 在 Windows 編輯後，手動回寫
python3 -m slidebridge writeback-ole input.pptx \
  --session .cache/ole-session \
  -o .cache/presentation_writeback.pptx --json
```

### 回寫安全不變量與防護

1. **成對回寫強制不變量（Strict Paired Writeback）**：
   OLE 二進位與預覽圖必須成對更新。若未提供或未在 session 目錄找到合格的預覽圖（PNG 或 EMF），指令將立即中止並報錯，防止簡報內出現「預覽畫面與底層資料不同步」的情況。
2. **來源衝突檢查（Conflict Detection）**：
   比對目標簡報的 SHA-256 與 session `manifest.json` 中記錄的 `source_sha256`。若簡報在抽出後被外部修改，預設拒絕回寫並提示使用 `--force`。同時檢驗簡報內目標 OLE member 的雜湊是否符合抽取時的狀態。
3. **安全原子輸出（Atomic Safe Assembly）**：
   不允許原地覆寫；輸出路徑不可與來源相同。所有零件重組均先寫入暫存檔，通過驗證後才進行原子替換。
4. **關聯與型態無縫更新（Relationship & Content-Type Rewriting）**：
   當使用 PNG 取代原本的 EMF 預覽圖時，自動重寫投影片 DrawingML（`<a:blip r:embed="...">`）與 VML（`<v:imagedata o:relid="...">`）中的關聯目標，並在 `[Content_Types].xml` 自動補齊 PNG 內容類型宣告。

## 虛擬機後端與 GUI 環境

`slidebridge/vm.py` 以 backend 抽象隔離 hypervisor 差異，`BACKENDS` 註冊 Parallels、UTM、VMware Fusion 與 VirtualBox。只有 Parallels 具備 `supports_one_click`：一鍵流程需要「無需 guest 帳密的程式執行」（`prlctl exec --current-user`）與「可預期的共享資料夾路徑對應」（`\\Mac\Home\...`）兩者兼具，其餘後端各缺其一。偵測到執行中的 guest 但後端不支援時，會拋出指名該 hypervisor 與原因的錯誤，而非誤報 Parallels 未安裝。

`edit` 與 `edit-active` 皆接受 `--vm-backend`，預設自動偵測。

### GUI 啟動時的 PATH 問題

從 PowerPoint（服務選單／VBA）或雙擊 `.app` 觸發時，行程繼承的是 launchd 的精簡環境，PATH 通常為 `/usr/bin:/bin:/usr/sbin:/sbin`，**不含 `/usr/local/bin` 與 `/opt/homebrew/bin`**。這會讓 `shutil.which("prlctl")` 回傳 `None`，並產生「Parallels Desktop 似乎未安裝」的誤導訊息。

`slidebridge/locate.py` 解決此問題：

- `login_path_dirs()` 依 `/usr/libexec/path_helper` 的規則重建 login PATH（先讀 `/etc/paths`，再依檔名順序讀 `/etc/paths.d/*`）。
- `find_executable()` 依序嘗試：絕對路徑 → `shutil.which` → 已知安裝位置 → `search_dirs()`（顯式目錄、現行 PATH、login PATH、常見安裝目錄）。
- `ensure_login_path()` 在 CLI 啟動時把缺少的目錄補進 `os.environ["PATH"]`，讓後續子行程一併受惠。

`scripts/edit_active_presentation.sh` 另外在進入點重建 PATH，並挑選 Python 3.10+（GUI 環境下 `python3` 會解析到 `/usr/bin/python3`，macOS 上為 3.9）。候選順序為 `SLIDEBRIDGE_PYTHON` → Homebrew → `/usr/local/bin` → python.org framework（版本新到舊）→ MacPorts → PATH 上的 `python3`，因此使用者既有的較新解譯器會被直接採用，不需額外安裝。`--print-python` 會印出實際選用的解譯器，`slidebridge doctor` 即以此為準而非以執行 doctor 的解譯器為準。

### 專案路徑的可攜性

`scripts/SlideBridge.applescript` 是模板，內含 `__SLIDEBRIDGE_PROJECT_ROOT__` 佔位符；`install_mac_integration.sh` 於安裝時替換為實際路徑，並寫入 `~/.slidebridge/project-root`。執行時解析順序為 `SLIDEBRIDGE_PROJECT_ROOT` → `~/.slidebridge/project-root` → 安裝時寫入值。因此 repo 內不含機器專屬路徑，搬移後重跑安裝腳本即可。

### Session 目錄必須位於家目錄下

Windows guest 只能透過家目錄共享（`\\Mac\Home`）存取 Mac，因此 session 目錄必須位於家目錄之內。`edit-active` 預設使用專案的 `.cache/sessions`；若 checkout 本身不在家目錄下，則改用 `~/Library/Caches/SlideBridge/sessions`。`launch_vm_helper` 在 helper 或 session 路徑不在家目錄時會直接報錯並說明原因，而不是讓 Windows 端產生難以解讀的 HRESULT。

歷史教訓：早期版本使用 `tempfile.gettempdir()`（`/var/folders/...`），會產生 `\\Mac\Host\private\var\...` 這種 guest 無法存取的路徑。helper 回報 `ERROR_BAD_NET_NAME`（`0x80070043`）卻誤標為「output must not already exist」，導致診斷方向完全錯誤。helper 現已會解碼 Win32 錯誤名稱並在失敗時印出完整的 input／output 路徑。

### 預覽圖關聯的解析（mc:AlternateContent）

PowerPoint 會把每個 OLE 物件包在 `<mc:AlternateContent>` 內，且**兩個分支帶有相同的 `r:id`**：

```xml
<mc:Choice Requires="v">
  <p:oleObj r:id="rId7"><p:embed/></p:oleObj>            <!-- 沒有預覽圖 -->
</mc:Choice>
<mc:Fallback>
  <p:oleObj r:id="rId7"><p:embed/>
    <p:pic>...<a:blip r:embed="rId8"/>...</p:pic>         <!-- 預覽圖在這裡 -->
  </p:oleObj>
</mc:Fallback>
```

因此比對 `r:id` 時必須收集**所有**符合的 `<p:oleObj>`，只取第一個會拿到沒有預覽圖的 `mc:Choice` 分支。`bridge._find_preview_members` 早期版本正是如此，導致回寫時報 `could not find any preview images associated with OLE member`。（`core.py` 的掃描本來就是以累積方式處理，不受影響。）

`scripts/verify_package.py` 的 `passed` 需搭配 `--allow-parts <被改動的 OLE>` 才有意義；未指定時會把目標 OLE 的變動列為 `unexpected_changes`，這是預期行為而非失敗。

### 未變更的 OLE 會被拒絕寫回

`writeback_ole` 會拒絕「不可能產生任何視覺變化」的回寫：

- 編輯後的 OLE 與簡報內現有的位元完全相同 → 報錯。
- 長度相同但相異位元低於 0.1%（`_NEAR_IDENTICAL_RATIO`）→ 報錯，因為那通常是重新序列化的中介資料，而非圖表編輯。

這道檢查**刻意不受 `force` 影響**：`edit-active` 一律傳入 `force=True` 以略過來源雜湊比對，那是另一件事，不該連帶關閉這道防護。需要刻意寫回未變更內容時使用 `--allow-unchanged`。

**在 Origin 內必須先存檔。** helper 的狀態文字已寫明「Save explicitly to commit」——若只在 Origin 修改卻未在 Origin 內存檔，`IPersistStorage::Save` 只會序列化 Origin 那份未變更的文件，回寫結果看起來便毫無變化。此檢查會把這種靜默失敗轉為明確錯誤。

### 預覽圖的來源：不可信任 Origin 的展示快取

OLE 儲存內有兩類內容：`Contents` 是 Origin 真正的文件，`OlePres000` / `OlePres001` 則是**展示快取**（快取的 metafile）。Origin 存檔時會更新 `Contents`，但**不保證重寫展示快取**。若直接取用快取，就會拿到編輯前的圖。

因此 helper 的匯出順序為：

1. 先呼叫 `IOleObject::Update()`，請 server 更新展示快取。
2. **優先以 `OleDraw` 即時繪製**成 EMF（要求正在執行的 server 依目前文件繪製）。
3. 只有在即時繪製失敗時，才退回讀取快取的 `IDataObject(CF_ENHMETAFILE)`。

PNG 是**由 EMF 點陣化**而來，所以 EMF 若為舊圖，PNG 必然也是舊圖——這也是為何過去 EMF 與 PNG 會同時過期。

`writeback_ole` 另有一道防護：若新的預覽圖與簡報內現有者位元完全相同，代表回寫後畫面不會有任何變化，直接報錯（`--allow-unchanged` 可覆寫）。

#### 自動匯出高解析預覽圖（Origin COM Automation 整合）

實測確認：**Origin 在 `OLEIVERB_OPEN` 模式下不會為容器即時繪製**，也不會更新 `OlePres000` / `OlePres001` 展示快取。

**現已完全自動化**：Helper 在按下「Save」或「Save and Close」時，會透過 COM Automation 掛接目前正在執行的 Origin 實例（`Origin.ApplicationSI`），並透過 LabTalk X-Function 直接驅動 Origin 內部渲染引擎：

```labtalk
expGraph type:=png filename:="preview" path:="<SessionDir>" overwrite:=replace;
```

此機制會自動在 session 資料夾內生成 `preview.png`（300+ DPI 無失真點陣圖），`writeback_ole` 的預覽候選順序優先選取 `preview.png`，**完全移除使用者需要手動匯出圖檔的步驟**！

若使用者在特定特殊環境仍需自行手動匯出，亦可手動將圖檔匯出至 session 目錄為 `preview.png` 或 `preview.emf`，系統會無縫相容。

## 實作邊界與架構說明

helper 使用 STA 訊息迴圈、`IOleClientSite`、`OleLoad` 與 `OLEIVERB_OPEN`。儲存明確執行 `GetClassID → WriteClassStg → IPersistStorage::Save → Commit → SaveCompleted`，對應 `OleSave` 的流程，並在 Save／Commit 失敗後仍完成必要清理。若 `SaveCompleted` 失敗，停止重試並啟用需確認的 Discard and Close 按鈕。未使用 PowerPoint Automation。此原型只接受根 storage 就是 Origin 物件的 CFB；不搜尋未知子 storage、不處理 linked OLE。

技術依據：[OleLoad](https://learn.microsoft.com/en-us/windows/win32/api/ole2/nf-ole2-oleload)、[IOleClientSite::SaveObject](https://learn.microsoft.com/en-us/windows/win32/api/oleidl/nf-oleidl-ioleclientsite-saveobject)、[OleSave](https://learn.microsoft.com/en-us/windows/win32/api/ole2/nf-ole2-olesave)、[SaveCompleted](https://learn.microsoft.com/en-us/windows/win32/api/objidl/nf-objidl-ipersiststorage-savecompleted)、[DoVerb](https://learn.microsoft.com/en-us/windows/win32/api/oleidl/nf-oleidl-ioleobject-doverb)。

## 驗證紀錄（2026-09-10）

- **完整編輯往返驗證通過**：
  在 Windows 11 VM 中透過 helper 開啟 OriginPro 2021，將真實圖表 X 軸標籤由 `Time (hr)` 修改為 `TT (hr)` 並儲存，二次開啟驗證二進位檔 `reopen-verify.bin` 確認改動確實持久化保存（`\b(TT (hr))` SHA-256: `267d50b4...`），達成無需 PowerPoint 的完整 Origin OLE 編輯往返。
- **雙向成對回寫驗證通過**：
  使用 `writeback-ole` 將 `reopen-verify.bin` 與新產生的預覽圖（EMF 及 PNG 格式均測試通過）回寫至真實簡報 `presentation.pptx`。經 `scripts/verify_package.py` 嚴格校驗：
  - 封裝 CRC 完整無損。
  - DrawingML 與 VML 關聯正確重定向至新預覽。
  - `[Content_Types].xml` 格式宣告完全吻合。
  - 目標 `oleObject1.bin` 成功更新，其餘 3 個 OLE 物件保持 100% 位元級原始不變。
- **自動化測試套件**（2026-09-11 重新實測）：
  - 全部 134 項 Python 單元測試通過（`bridge` 31、`core` 13、`doctor` 29、`locate` 15、`native_emf` 9、`powerpoint` 11、`vm` 21、`verify` 1），涵蓋 CLI、雜湊衝突防護、成對約束、關聯重定向、原子安全輸出、VM 後端選擇與一鍵流程預檢。
  - 其中 9 項原生 EMF 回歸測試需設定 `SLIDEBRIDGE_TEST_EMF2SVG=bin/emf2svg-conv`，否則會被 skip；設定後 134 項全數執行且零失敗。
  - `python3 -m slidebridge doctor` 為一鍵流程的預檢指令，任何 `[FAIL]` 都會附修復指令並以非零狀態結束。所有檢查皆在 macOS 端執行：`Running Windows guest` 僅查詢 hypervisor 目前有哪些 VM 在執行，不需要在 guest 內安裝 Python 或任何工具。該項失敗時區分三種情況——找不到 hypervisor、hypervisor 裝了但無法查詢（`VmQueryError`）、hypervisor 正常但無 VM 在跑（`NoRunningGuestError`）——並分別給出對應建議。
  - 4 個 C++ persistence 故障注入測試通過。

故障注入測試不需 Windows 或 Origin：

```sh
clang++ -std=c++17 -Wall -Wextra native/origin-bridge/save_sequence_test.cpp -o build/save-sequence-test
build/save-sequence-test
```

Windows 冒煙測試（使用新的結果目錄）：

```powershell
.\scripts\smoke_origin_bridge.ps1 -Executable .\origin-bridge.exe -InputFile .\editable.bin -OutputDirectory .\smoke-results
```

私有測試檔及螢幕擷取存放於忽略的 `.cache/` 或 `artifacts/`；不得將它們當作發行素材。
