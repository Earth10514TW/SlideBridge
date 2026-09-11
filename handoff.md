# SlideBridge handoff

Updated: 2026-09-11 (Asia/Taipei). Mac PowerPoint interactive integration, shape-to-OLE geometric resolution, in-place writeback, and hot reload complete.

## Current direction: Origin editing without Windows PowerPoint

The current implementation and reproducible commands are documented in [docs/origin-bridge.md](docs/origin-bridge.md).

Completed components:
1. **`prepare-ole`**: Extracts embedded OLE storage safely to session directory with source SHA-256 and relationship manifest.
2. **Native Windows x64 OLE host (`native/origin-bridge/`)**: Cross-compiled with MinGW `-static`.
   - Verified interactive roundtrip on Parallels Windows 11 VM with OriginPro 2021: user edited X-axis label from `Time (hr)` to `TT (hr)`, saved, and reopened verifying binary persistence (`reopen-verify.bin`, SHA-256: `267d50b4...`).
   - Added live visual preview canvas directly in the Helper UI via `IAdviseSink` and `OleDraw`, rendering Origin chart changes in real-time.
   - Added automated dual-format preview export on save: exports both raw vector `edited.emf` (via `IDataObject(CF_ENHMETAFILE)` / `OleDraw`) and 300 DPI high-fidelity `edited.png` (via GDI+).
3. **`writeback-ole`**: Implemented in `slidebridge/bridge.py` and `slidebridge/cli.py`. Enforces strict paired writeback (OLE binary + matching preview image), source presentation & target OLE SHA-256 conflict detection (`--force` bypass), atomic temp-file assembly, DrawingML / VML relationship rewriting (e.g. EMF to PNG redirection), and `[Content_Types].xml` maintenance. Supports `--in-place` with automatic `.sb_backup.pptx` backup and atomic replacement.
4. **Seamless Mac-to-VM workflow (`slidebridge edit` & `slidebridge/vm.py`)**:
   - Automated Parallels Desktop VM discovery (`detect_running_vm`) and path translation to `\\Mac\Home\...`.
   - Automatic VM foreground activation and Helper launch via `prlctl exec`.
   - Interactive chart discovery with slide and preview metadata (`list_ole_objects`).
   - End-to-end orchestration: extracts OLE, pops up Windows Origin/Helper, waits for user save, and automatically writes back updated presentation.
5. **Mac PowerPoint Interactive Integration (`slidebridge/powerpoint.py` & `slidebridge edit-active`)**:
   - Query frontmost PowerPoint state via AppleScript (`get_active_powerpoint_state`).
   - Sub-millipoint geometric resolution (`resolve_ole_from_selection`) matching selected PowerPoint shapes against PPTX DrawingML `xfrm` and OLE relationships, with fallback to shape names and single-chart auto-selection.
   - Auto-save prior to extraction, atomic in-place writeback, and hot reload of presentation in PowerPoint navigating straight back to the edited slide.
   - One-click installer (`scripts/install_mac_integration.sh`): installs `SlideBridge.scpt` into PowerPoint's Application Scripts folder, creates macOS Quick Action Service in `~/Library/Services/`, and provides standalone `artifacts/SlideBridge-Edit-Active.app`.
6. **Validation & Verification**:
   - 52 Python unit tests (100% pass rate).
   - 9 native EMF converter tests (100% pass rate).
   - 4 C++ persistence fault-injection tests (100% pass rate).
   - Real presentation writeback verified via `scripts/verify_package.py` on `/Users/earth/Downloads/presentation.pptx` (`artifacts/presentation_writeback_png.pptx`), with perfect CRC, relationships, and unaltered secondary OLE objects.
   - Windows smoke script (`scripts/smoke_origin_bridge.ps1`) executed via `prlctl exec` on `Windows 11 Lite` VM and passed 100%, verifying OLE roundtrip and automated EMF+PNG generation.

## User objective and constraints

Build SlideBridge to repair Windows/Origin EMF previews in PPTX for macOS while preserving the original embedded OLE objects and Windows double-click editing.

The user confirmed that the repaired PPTX displays in PowerPoint and Windows Origin double-click editing succeeds. They then explicitly required fixing the **generic automatic converter**, not substituting supplied PNGs. Use Windows PNGs only as comparison references.

User prefers agents to finish bounded assignments without repeated follow-up messages. Wait quietly when there is no independent useful work.

## Current implementation

Python CLI: `python3 -m slidebridge scan INPUT.pptx --json` and `python3 -m slidebridge fix INPUT.pptx -o OUTPUT.pptx`.

Automatic pipeline: EMF → patched libemf2svg → SVG → Inkscape → PNG. WMF uses Inkscape directly. The package patch updates slide and VML relationships, preserves existing media/OLE and slide XML, and writes a new file without overwriting. Optional `--preview MEMBER=PNG` exists from the previous fix, but is not needed for the generic pipeline.

## Status: generic renderer pen-width & text-rotation fixes COMPLETE

### Root causes fixed

1. **Pen width**: `stroke_draw()` in `emf2svg_utils.c` switched on `stroke_mode & 0x000F0000`. Ordinary `EMR_CREATEPEN` lacked geometric type bits, matching `U_PS_COSMETIC` and hardcoding width 1. Fixed by ORing `U_PS_GEOMETRIC` when width > 0.
2. **Text rotation / Axis title alignment**: `text_style_draw()` in `emf2svg_utils.c` added a redundant `translate(0, font_height * 0.9)` and miscalculated the rotation center as `(Org.x, Org.y + font_height * 0.9)`. Origin exports axis titles with `SetTextAlign(TA_BASELINE)` where `(Org.x, Org.y)` is already the baseline origin. Because subscripts and superscripts have smaller `font_height` values than main labels (e.g. `j (mA cm^-2)`, `FE_{H_2}`, `FE_{CO}`), the font-height-dependent translation offset each fragment by a different amount, causing vertical axis labels to scatter, overlap, and distort. Fixed by aligning `pos_y` to baseline and anchoring rotation cleanly at `(pos_x, pos_y)` without extra translate.

### Patches applied

- Pen width fix: `patches/slidebridge_pen_fix.patch`
- Text rotation fix: `patches/slidebridge_text_rotation_fix.patch`

### Build and integration

- `scripts/build_patched_emf2svg.sh` builds a pinned patched `emf2svg-conv` at `artifacts/bin/emf2svg-conv`.
- `slidebridge/core.py` prefers the project-local binary via `shutil.which(local_path)` before falling back to the system copy.

### Test results

- 6/6 native pen-width tests pass.
- 3/3 native text rotation tests pass (`test_rotated_text_rotation_center_matches_coordinates`, `test_rotated_subscript_superscript_keep_true_anchor`, `test_unrotated_text_has_no_transform`).
- 14/14 package tests pass.
- Sample PPTX regenerated automatically (`artifacts/presentation_auto.pptx`), package verification passed with all 4 OLE binaries preserved and vertical axis titles aligned.

## Local samples and artifacts — private, not tracked

- Original: `/Users/earth/Downloads/presentation.pptx`
- Windows original line chart: `/Users/earth/Downloads/圖片1.png` → `ppt/media/image5.emf`
- Windows original bar chart: `/Users/earth/Downloads/圖片2.png` → `ppt/media/image8.emf`
- Sample has 4 EMFs, 5 OLE positions across slides 4/5, 4 embedded OLE binaries.
- `artifacts/presentation_auto.pptx`: automatic output with patched renderer (current).
- `artifacts/presentation_fixed.pptx`: first automatic output (before pen fix; thin lines).
- `artifacts/presentation_windows_previews.pptx`: previous output using two Windows PNGs.
- `artifacts/bin/emf2svg-conv`: patched binary (gitignored).

All sample files and generated artifacts remain ignored by Git.

## Environment and verification

Installed: Inkscape 1.4.4 ARM, patched libemf2svg (from upstream commit `658a718de`), cmake, pkgconf, argp-standalone (Homebrew).

Normal tests:

```sh
python3 -m unittest discover -s tests -q
```

Native regression (patched binary):

```sh
SLIDEBRIDGE_TEST_EMF2SVG=artifacts/bin/emf2svg-conv python3 -m unittest discover -s tests -p test_native_emf.py -v
```

Package verification:

```sh
python3 scripts/verify_package.py ORIGINAL.pptx OUTPUT.pptx
```

Rebuild patched converter:

```sh
bash scripts/build_patched_emf2svg.sh
```

Build native Windows Origin Helper (cross-compile on macOS):

```sh
bash scripts/build_origin_bridge.sh
```

Native C++ persistence test:

```sh
clang++ -std=c++17 -Wall -Wextra native/origin-bridge/save_sequence_test.cpp -o artifacts/bin/save-sequence-test
artifacts/bin/save-sequence-test
```

Windows smoke test (PowerShell in Windows VM):

```powershell
.\scripts\smoke_origin_bridge.ps1 -Executable .\origin-bridge.exe -InputFile .\editable.bin -OutputDirectory .\smoke-results
```

## Git and current working state

Branch: main. Working copy includes:
- Windows Helper visual live preview canvas (`WM_PAINT`, `IAdviseSink`, `OleDraw`).
- Dual-format preview auto-export on save (`edited.emf` + 300 DPI `edited.png`).
- `-lgdi32 -lgdiplus` build integration and updated PowerShell smoke test.

All 52 Python unit tests, 9 native EMF converter tests, and 4 C++ persistence tests pass 100%.

## User Operation Guide (操作指南)

### 方式一：Mac PowerPoint 內直覺跳轉編輯（推薦！）
1. **在 Mac PowerPoint 點選任一 Origin 圖表**。
2. 觸發方式任選一種：
   - **快捷鍵**：按下你設定的快捷鍵（例如 `Cmd + Option + O`）。
   - **應用選單**：點擊選單 `Microsoft PowerPoint -> 服務 (Services) -> 在 Origin 編輯 (SlideBridge)`。
   - **獨立應用程式**：雙擊 `artifacts/SlideBridge-Edit-Active.app`（可放於 Dock 或 Raycast/Alfred）。
   - **終端機**：執行 `./scripts/edit_active_presentation.sh`（或 `python3 -m slidebridge edit-active`）。
3. **自動跨機編輯**：
   - Parallels Windows 11 VM 自動躍升至前台，彈出 Helper 與 Origin 編輯視窗。
   - 在 Origin 修改圖表（文字、樣式、數據），Helper 即時更新畫布。
   - 點擊 Helper 的 **Save and Close**。
4. **自動熱重載**：
   - Mac PowerPoint 自動同步原地更新簡報並熱重載，畫面停留在原投影片，立即看到最新圖表！
   - 原簡報自動於同目錄保留 `.sb_backup.pptx` 備份。

### 方式二：終端機指定簡報編輯
```sh
python3 -m slidebridge edit /Users/earth/Downloads/presentation.pptx
# 或使用包裝腳本：
./scripts/edit_presentation.sh /Users/earth/Downloads/presentation.pptx
```
