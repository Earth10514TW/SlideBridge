# Origin 編輯橋接原型

目標是讓 Windows 只安裝 Origin 與本專案 helper，就能編輯由 PPTX 抽出的嵌入 OLE。此階段不修改 PPTX，也尚未產生更新後的預覽圖。Word、Mac PowerPoint 雙擊攔截與 Add-in 均未實作。

## 建立測試副本

```sh
python3 -m slidebridge prepare-ole input.pptx \
  --member ppt/embeddings/oleObject1.bin -o artifacts/ole-session --json
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
cmake -S native/origin-bridge -B artifacts/origin-bridge-build
cmake --build artifacts/origin-bridge-build --config Release
```

## 在 Windows 使用

將 exe 與測試副本複製到 Windows 本機資料夾。使用已登入的桌面使用者執行，以便看到 Origin 視窗；不要用 SYSTEM 執行互動編輯。

```powershell
.\origin-bridge.exe inspect .\editable.bin
.\origin-bridge.exe edit .\editable.bin .\edited.bin --clsid '{64CC80B2-4FA1-4F7B-9D6F-1BFACF5715DC}'
```

指定的 CLSID 必須同時符合檔案與 Windows 上 `Origin95.Graph` 的註冊值；上述值來自本機測試樣本，其他類別不在此原型支援範圍。既有 output 不會覆寫。所有儲存都發生在 output 副本。

先改一個可辨識的項目（例如標題），依 Origin 的嵌入物件更新操作提交，再按 helper 的 Save／Save and Close。之後使用 `edited.bin` 作為下一次 edit 的 input，指定另一個新的 output，確認改動確實保存。只有這個實際編輯再開啟的結果，才能證明編輯往返成立。

## 雙向回寫簡報（writeback-ole）

在完成 OLE 二進位編輯與預覽圖產生後，使用 `writeback-ole` 命令將修改成對寫回簡報：

```sh
python3 -m slidebridge writeback-ole input.pptx \
  --session artifacts/ole-session \
  --ole artifacts/ole-session/reopen-verify.bin \
  --preview artifacts/ole-session/reopen-verify.png \
  -o artifacts/presentation_writeback.pptx --json
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
- **自動化測試套件**：
  - 全部 39 項 Python 單元測試（含 CLI、雜湊衝突防護、成對約束、關聯重定向、原子安全輸出）通過。
  - 全部 9 項原生 EMF 核心轉換器回歸測試通過。
  - 4 個 C++ persistence 故障注入測試通過。

故障注入測試不需 Windows 或 Origin：

```sh
clang++ -std=c++17 -Wall -Wextra native/origin-bridge/save_sequence_test.cpp -o artifacts/bin/save-sequence-test
artifacts/bin/save-sequence-test
```

Windows 冒煙測試（使用新的結果目錄）：

```powershell
.\scripts\smoke_origin_bridge.ps1 -Executable .\origin-bridge.exe -InputFile .\editable.bin -OutputDirectory .\smoke-results
```

私有測試檔及螢幕擷取存放於忽略的 `artifacts/ole-session/`；不得將它們當作發行素材。
