# SlideBridge

Fix PowerPoint graphics across Windows and Mac.

SlideBridge 的第一版是本機 CLI：掃描 `.pptx` 中的 EMF／WMF，使用本機轉換器產生 PNG，重新連接圖片關聯，輸出新的簡報。可處理普通圖片與 OLE 物件的預覽圖；不執行或解碼 Origin OLE。

## 使用

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

## 邊界與驗證

這是 v0.1 CLI 原型，尚非 macOS App 或 PowerPoint Add-in。已用一份真實 Origin95.Graph 簡報完成 4 張 EMF 的轉換、輸出圖片檢視與 package 完整性驗證（第 4／5 頁共 5 個 OLE 位置、4 份嵌入資料）。Inkscape 1.4.4 ARM 原生 EMF 匯入全部崩潰，libemf2svg 1.8.1 中介路徑可完成轉換。尚未在 PowerPoint 或 Windows Origin 驗證虛線、字型、上下標與雙擊編輯的實際效果。保留 OLE bytes 不等於已證明 Office 會接受所有變體；請在 Mac PowerPoint 檢視輸出，再於 Windows + Origin 驗證編輯流程。來源缺少預覽、預覽已損壞、外部 linked OLE 資料遺失時，無法重建原圖。數位簽章不會因修改後仍有效。

自動測試使用合成 OOXML 與替身 renderer，驗證封裝與保留行為；真實樣本另外執行轉換與 package 比對。樣本與產物放在忽略的 `artifacts/`，不提交 Git。

```sh
python3 -m unittest discover -s tests -v
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
