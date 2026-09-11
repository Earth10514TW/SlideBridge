# SlideBridge handoff

Updated: 2026-09-11 (Asia/Taipei). Mac PowerPoint interactive integration, shape-to-OLE geometric resolution, in-place writeback, and hot reload complete.

## Current direction: Origin editing without Windows PowerPoint

The current implementation and reproducible commands are documented in [docs/origin-bridge.md](docs/origin-bridge.md).

> **Latest Update (Completed 2026-09-11):** The manual "export from Origin" step has been replaced with
> helper-driven COM automation (`Origin.ApplicationSI` + LabTalk `expGraph`). Verified on live Windows 11 VM.
> See [Origin graph export via COM Automation](#origin-graph-export-via-com-automation) at the end of this file.

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
    - One-click installer (`scripts/install_mac_integration.sh`): installs `SlideBridge.scpt` into PowerPoint's Application Scripts folder, creates macOS Quick Action Service in `~/Library/Services/`, and provides standalone `dist/SlideBridge-Edit-Active.app`.
6. **Validation & Verification**:
   - 139 Python unit tests total (`bridge` 31, `core` 13, `doctor` 29, `locate` 15, `native_emf` 14, `powerpoint` 11, `vm` 21, `verify` 1), 100% pass rate.
     The 14 `native_emf` tests are skipped unless `SLIDEBRIDGE_TEST_EMF2SVG` is set; with it set, all 139 run and pass.
   - `python3 -m slidebridge doctor` preflights the Mac PowerPoint one-click flow and exits non-zero on any `[FAIL]`.
   - 4 C++ persistence fault-injection tests (100% pass rate).
   - Real presentation writeback verified via `scripts/verify_package.py` on `/Users/earth/Downloads/presentation.pptx`, with perfect CRC, relationships, and unaltered secondary OLE objects.
   - Windows smoke script (`scripts/smoke_origin_bridge.ps1`) executed via `prlctl exec` on `Windows 11 Lite` VM and passed 100%, verifying OLE roundtrip and automated EMF+PNG generation.

## User objective and constraints

Build SlideBridge to repair Windows/Origin EMF previews in PPTX for macOS while preserving the original embedded OLE objects and Windows double-click editing.

The user confirmed that the repaired PPTX displays in PowerPoint and Windows Origin double-click editing succeeds. They then explicitly required fixing the **generic automatic converter**, not substituting supplied PNGs. Use Windows PNGs only as comparison references.

User prefers agents to finish bounded assignments without repeated follow-up messages. Wait quietly when there is no independent useful work.

## Current implementation

Python CLI: `python3 -m slidebridge scan INPUT.pptx --json` and `python3 -m slidebridge fix INPUT.pptx -o OUTPUT.pptx`.

Automatic pipeline: EMF → patched libemf2svg → SVG → Inkscape → PNG. WMF uses Inkscape directly. The package patch updates slide and VML relationships, preserves existing media/OLE and slide XML, and writes a new file without overwriting. Optional `--preview MEMBER=PNG` exists from the previous fix, but is not needed for the generic pipeline.

## Status: generic renderer pen-width, text-rotation, and XPS XOR dithering/pattern fill fixes COMPLETE

### Root causes fixed

1. **Pen width**: `stroke_draw()` in `emf2svg_utils.c` switched on `stroke_mode & 0x000F0000`. Ordinary `EMR_CREATEPEN` lacked geometric type bits, matching `U_PS_COSMETIC` and hardcoding width 1. Fixed by ORing `U_PS_GEOMETRIC` when width > 0.
2. **Text rotation / Axis title alignment**: `text_style_draw()` in `emf2svg_utils.c` added a redundant `translate(0, font_height * 0.9)` and miscalculated the rotation center as `(Org.x, Org.y + font_height * 0.9)`. Origin exports axis titles with `SetTextAlign(TA_BASELINE)` where `(Org.x, Org.y)` is already the baseline origin. Because subscripts and superscripts have smaller `font_height` values than main labels (e.g. `j (mA cm^-2)`, `FE_{H_2}`, `FE_{CO}`), the font-height-dependent translation offset each fragment by a different amount, causing vertical axis labels to scatter, overlap, and distort. Fixed by aligning `pos_y` to baseline and anchoring rotation cleanly at `(pos_x, pos_y)` without extra translate.
3. **XPS Peak-fitting XOR Blocker Bars & Semi-transparent Fills**:
   - `U_EMRBITBLT_draw()` in `emf2svg_rec_bitmap.c`: Origin and Win32 GDI applications simulate semi-transparent shaded areas (e.g. XPS peak fits) using 1-bpp monochrome stipple patterns with `PATINVERT` (`0x005a0049`) or `DSTINVERT` (`0x00550009`) XOR bracketing. When `cbBitsSrc == 0`, `libemf2svg` ignored the ROP and drew opaque solid rectangular blocker boxes covering the spectra. Fixed by early return for inverting ROPs.
   - `fill_draw()` in `emf2svg_utils.c`: For `U_BS_MONOPATTERN`, `libemf2svg` emitted invalid SVG `fill="#img-X-ref"` without `url()` and ignored brush color. Fixed to render modern semi-transparent vector fills `fill="#%02X%02X%02X" fill-opacity="0.45"` when colored, and solid black when black.
   - `clipset_draw()` in `emf2svg_utils.c`: When a world transform is open (`<g transform="matrix(...)">`), attaching root-space clip paths evaluated in local element coordinates caused clip paths to scale down 4x, erroneously clipping out peak curves. Fixed by bypassing clip paths while `states->transform_open` is active.

### Patches applied

- Pen width fix: `patches/slidebridge_pen_fix.patch`
- Text rotation fix: `patches/slidebridge_text_rotation_fix.patch`
- XPS XOR dithering / monochrome pattern fill fix: `patches/slidebridge_patinvert_monopattern_fix.patch`

### Build and integration

- `scripts/build_patched_emf2svg.sh` builds a pinned patched `emf2svg-conv` at `bin/emf2svg-conv`.
- `slidebridge/core.py` prefers the project-local binary via `shutil.which(local_path)` before falling back to the system copy.

### Test results

- 6/6 native pen-width tests pass.
- 3/3 native text rotation tests pass (`test_rotated_text_rotation_center_matches_coordinates`, `test_rotated_subscript_superscript_keep_true_anchor`, `test_unrotated_text_has_no_transform`).
- 5/5 native raster and pattern tests pass (`test_bitblt_patinvert_suppressed`, `test_bitblt_dstinvert_suppressed`, `test_bitblt_patcopy_rendered`, `test_monopattern_renders_semitransparent_vector_fill`, `test_monopattern_black_renders_solid_fill`).
- 14/14 native EMF tests pass total.
- 139/139 unit tests pass across entire suite.
- Sample PPTX regenerated automatically, package verification passed with all 9 OLE binaries preserved and XPS peak charts rendered cleanly without blocker bars.

## Local samples and artifacts — private, not tracked

- Original: `/Users/earth/Downloads/presentation.pptx`
- Windows original line chart: `/Users/earth/Downloads/圖片1.png` → `ppt/media/image5.emf`
- Windows original bar chart: `/Users/earth/Downloads/圖片2.png` → `ppt/media/image8.emf`
- Sample has 4 EMFs, 5 OLE positions across slides 4/5, 4 embedded OLE binaries.
- `bin/emf2svg-conv`: patched binary (gitignored).
- `dist/origin-bridge.exe`: cross-compiled Windows helper (gitignored).
- `dist/SlideBridge.app`: native macOS desktop app (gitignored).

All sample files and generated binaries remain ignored by Git.

## Environment and verification

Installed: Inkscape 1.4.4 ARM, patched libemf2svg (from upstream commit `658a718de`), cmake, pkgconf, argp-standalone (Homebrew).

Normal tests:

```sh
python3 -m unittest discover -s tests -q
```

Native regression (patched binary):

```sh
SLIDEBRIDGE_TEST_EMF2SVG=bin/emf2svg-conv python3 -m unittest discover -s tests -p test_native_emf.py -v
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
clang++ -std=c++17 -Wall -Wextra native/origin-bridge/save_sequence_test.cpp -o build/save-sequence-test
build/save-sequence-test
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

All 129 Python unit tests pass 100% (the 9 native EMF converter regression tests are counted within
that 129 and require `SLIDEBRIDGE_TEST_EMF2SVG`); the 4 C++ persistence tests pass separately.

## Workaround in place: user-exported preview

The `OleDraw`-first change did **not** fix it -- the user reported the chart still looked unchanged.
That settles the earlier open question: **Origin will not render an edited chart for a container in
`OLEIVERB_OPEN` mode**, and it does not refresh `OlePres000/001` either. There is no way to obtain a
fresh render from the OLE object itself.

So the agreed route is the user's own suggestion: **export the graph from Origin, and let the
helper/writeback pick that file up.**

This needed almost no new machinery, because `writeback_ole`'s preview candidate list already is
`["preview.png", "preview.emf", "edited.png", "edited.emf"]` -- `preview.png` already wins over the
helper's stale `edited.png`.

Where to export (Origin's export dialog accepts a full path):

```
\\Mac\Home\Documents\ChatGPT\SlideBridge\artifacts\slidebridge-active-session-<timestamp>_<id>\preview.png
```

i.e. the session folder, as `preview.png` (or `preview.emf`).

Helper-side support added (`native/origin-bridge/main.cpp`, rebuilt):
- `GetDirectoryOf()` / `FileExists()` helpers.
- `OriginHost::ManualPreviewPath()` looks for `preview.png` / `preview.emf` in the session folder.
- The status line shown when Origin opens now prints the **exact Windows path to export to**, and the
  log repeats it.
- On Save, the status reports `Your exported preview will be used: preview.png` when present.

Guard interaction: if the user exports nothing, the helper's stale render is used and
`_reject_unchanged_preview` refuses the writeback; if they export a genuinely new image, it differs
from the deck's current preview and the guard passes. The two mechanisms complement each other.

Tests added (`ManualPreviewPrecedenceTests`), confirmed to fail if the candidate order is inverted.

## ROOT CAUSE: preview render used Origin's stale presentation cache

Follow-up to the "Origin edits not reaching the output" report. The user confirmed they *did* save
inside Origin this time, and the OLE guard passed -- so the OLE really had changed. The chart still
looked unchanged.

Stream-level evidence from the newest session
(`artifacts/slidebridge-active-session-20260911_183118_e5ee37d2`), dumping both binaries with
`olefile`:

| stream | editable.bin | edited.bin | changed |
|--------|--------------|------------|---------|
| `Ole` | 20 B `c36c8a4b` | 20 B `c36c8a4b` | no |
| `OlePres000` | 52172 B `8ceb2bdc` | 52172 B `8ceb2bdc` | **no** |
| `OlePres001` | 52114 B `0ae0a447` | 52114 B `0ae0a447` | **no** |
| `Contents` | 44024 B `281724bb` | 44118 B `183022ef` | **YES** |

`Contents` is Origin's real document -- the edit is saved there. `OlePres000/001` are the **cached
presentation** metafiles, and Origin never refreshed them.

The export chain then did this:

1. `ExportPreview` tried `IDataObject::GetData(CF_ENHMETAFILE)` first (main.cpp ~line 401). That
   returns `OlePres000` -- the stale cache -- so `emfSuccess = true` and `edited.emf` came out
   byte-identical to the pristine `ppt/media/image7.emf` (`738f32f8`) in **all four runs**.
2. The PNG is rasterised **from that EMF** (`Gdiplus::Metafile metafile(targetEmfPath)`, ~line 472),
   so the stale vector produced a stale bitmap. The live `OleDraw` path (~line 487) is only a
   fallback when the EMF export fails, so it was never reached.
3. `edited.png` came out byte-identical to the preview already in the deck (`dea0492f`), the writeback
   wrote it, and PowerPoint kept showing the old chart.

### Fixes

**C++ (`native/origin-bridge/main.cpp`), rebuilt:**
- Call `IOleObject::Update()` before exporting, to ask the server to refresh its cached presentation.
- **Invert the export preference**: live `OleDraw` into an enhanced metafile first (asks the running
  server to draw its current document), and use the cached `GetData(CF_ENHMETAFILE)` only as a
  fallback. Trusting the cache first is what produced stale previews.

**Python (`bridge._reject_unchanged_preview`):**
- Refuse a writeback whose new preview is byte-identical to the preview already in the presentation,
  with an actionable message. Also not bypassable by `force`; `--allow-unchanged` overrides.

Verified by replaying the real session: it now fails loudly instead of writing a stale image, and the
new tests were confirmed to fail when the guard is removed.

Note: `OleDraw` freshness on a real Origin install is **not yet verified** -- that needs the VM. If
previews are still stale after this change, the remaining cause is that Origin will not render live
in `OLEIVERB_OPEN` mode, and the next step would be driving Origin's own export automation.

## OPEN: Origin edits are not reaching the saved output

Symptom reported by the user: "在origin內的更改並沒有生效" -- the chart in PowerPoint
still looks unchanged after a successful-looking edit run.

Measured evidence (three real runs, all with the same chart `oleObject3.bin`):

| run | editable.bin | edited.bin | edited.png |
|-----|--------------|------------|------------|
| 180914 | ba478212 (99328) | b68e63aa (152576) | e15f71f1 (56117) |
| 181759 | ba478212 (99328) | 62ac48cf (152576) | dea0492f (39422) |
| 181907 | 62ac48cf (152576) | 7cf5262a (152576) | dea0492f (39422) |

1. **`edited.emf` is byte-identical across all three runs** (`738f32f8`, 44328 bytes) and is
   **byte-identical to the pristine `ppt/media/image7.emf`** in the untouched original deck. The EMF
   export is returning the OLE's cached metafile, not a fresh render.
2. **`edited.png` renders visually identical to the original** in all three runs (verified by
   converting the pristine `image7.emf` through `emf2svg-conv` + Inkscape and comparing). Only the
   encoding differs between runs, not the picture.
3. **Run 181907: `editable.bin` and `edited.bin` differ in exactly 5 bytes**, at offsets 1132..1136,
   with **zero** differing printable strings. That is a re-serialised, unchanged document.

So the OLE storage never carried the edit. Two candidate causes, not yet distinguished:

- **A (procedural):** the chart was edited in Origin but never saved *inside Origin* before the
  helper's Save. The helper's own status text says "Save explicitly to commit" / "Origin opened.
  Use Save to commit changes", so this step is expected. If skipped, `IPersistStorage::Save`
  serialises Origin's untouched document.
- **B (mechanical):** Origin's OLE server does not flush live `OLEIVERB_OPEN` edits through
  `IPersistStorage::Save`. The helper's sequence
  (`GetClassID -> WriteClassStg -> IPersistStorage::Save -> Commit -> SaveCompleted`) looks correct,
  and the earlier verified roundtrip did persist a real change (the `TT (hr)` axis-label test), so
  the mechanism can work.

Note also `IOleObject::Close(OLECLOSE_NOSAVE): HRESULT=0x80010105` (RPC_E_SERVERFAULT) appears in
the log before a retry that succeeds; `OLECLOSE_NOSAVE` is correct after an explicit save, but the
fault is worth watching.

### Mitigation applied: unchanged-OLE guard

`writeback_ole` now refuses a writeback that cannot produce a visible change
(`bridge._reject_unchanged_ole`):

- byte-identical OLE -> error;
- same length but < 0.1% of bytes differing (`_NEAR_IDENTICAL_RATIO`) -> error, since that is
  re-serialised metadata rather than a chart edit.

Deliberately **not** bypassed by `force=True`, because `edit-active` always passes `force=True` to
skip the *source-hash* check, which is an unrelated concern. Escape hatch: `--allow-unchanged` /
`allow_unchanged=True`.

Verified by replaying the real session 181907: the command that previously reported success now
fails with an actionable message and writes no output file.

## Fixed: preview lookup missed the mc:Fallback branch

Second real PowerPoint run: the Origin roundtrip itself succeeded (edited.bin,
edited.emf, edited.png all exported), then writeback failed with
`could not find any preview images associated with OLE member: ppt/embeddings/oleObject3.bin`.

Root cause: PowerPoint wraps each OLE object in `<mc:AlternateContent>` with **two**
branches that both carry the same `r:id`:

```xml
<mc:Choice Requires="v">
  <p:oleObj r:id="rId7"><p:embed/></p:oleObj>            <!-- no preview -->
</mc:Choice>
<mc:Fallback>
  <p:oleObj r:id="rId7"><p:embed/>
    <p:pic>...<a:blip r:embed="rId8"/>...</p:pic>         <!-- preview lives HERE -->
  </p:oleObj>
</mc:Fallback>
```

`bridge._find_preview_members` stopped at the **first** `<p:oleObj>` matching the r:id,
i.e. the preview-less `mc:Choice` branch, so it returned no previews. `core.py` already
handled this correctly (it accumulates over `root.iter()` instead of breaking) -- the
defect was isolated to `bridge.py`.

Fix: collect **every** matching `<p:oleObj>` and gather preview rids from all of them.
This also repairs the manifest, which previously recorded `preview_members: []`.

Why earlier verification missed it: the documented roundtrip passed `--ole` and
`--preview` explicitly, bypassing `_find_preview_members` entirely. `edit-active`
passes no explicit preview, which is what exposed it.

Verified against the user's real session (not a fixture):
- `_find_preview_members` now returns `['ppt/media/image7.emf']` (was `[]`).
- `writeback-ole` on the real `presentation copy.pptx` + real `edited.bin`/`edited.png`
  returns `status: success`.
- `scripts/verify_package.py ... --allow-parts ppt/embeddings/oleObject3.bin`
  reports `passed: true`: only the target OLE changed, the other 3 OLE objects are
  bit-identical, `ppt/media/image7.png` added, relationship rewritten, no dangling refs.
- Regression test added in `tests/test_bridge.py` (`AlternateContentPreviewTests`),
  confirmed to fail without the fix (`[]` vs `['ppt/media/image7.emf']`).

Note: `verify_package.py` reports `passed: false` unless the changed OLE is named via
`--allow-parts`; that is intended, not a failure.

## Fixed: one-click session path was unreachable from the guest

First real PowerPoint run reached the Windows helper and failed with
`CopyFileW (output must not already exist): HRESULT=0x80070043`, followed by
`No edited.bin found in session`.

Root cause: `edit-active` put its session in `tempfile.gettempdir()`
(`/var/folders/...`), which is outside the home folder. `mac_to_vm_path` then
emitted `\\Mac\Host\private\var\folders\...`, which the guest cannot address.
`0x80070043` is `ERROR_BAD_NET_NAME`, **not** "file exists" -- the helper's log
message asserted the wrong cause, which sent the diagnosis the wrong way.

Three fixes:
1. `powerpoint.default_session_parent()` -- sessions now default to the project's
   `artifacts/` folder (under home, and consistent with `slidebridge edit`), or
   `~/Library/Caches/SlideBridge` when the checkout is outside home. The guest
   reaches the Mac only through the home folder share.
2. `vm._require_guest_reachable()` -- fails fast with an explanatory error when a
   helper or session path is outside home, instead of letting Windows produce an
   opaque HRESULT.
3. `native/origin-bridge/main.cpp` -- `LogHr` now decodes `HRESULT_FROM_WIN32` into
   the Win32 error name, and `CopyInputToOutput()` logs both paths on failure.
   Rebuilt with `bash scripts/build_origin_bridge.sh`.

Also fixed a regression I introduced earlier: `edit_active_presentation` returned
`"vm": target_vm`, a variable my VM-backend refactor had removed (NameError on the
success path).

Verified: the session now translates to
`\\Mac\Home\Documents\ChatGPT\SlideBridge\artifacts\...`, the mapping that the
original verified roundtrip used.

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

### Origin graph export via COM Automation
 
**Completed:** 2026-09-11. **Status:** Done & Verified on live Windows 11 VM.
 
### Summary
 
Previously, Origin would not render an edited chart for a container in `OLEIVERB_OPEN` mode, and did
not refresh the `OlePres000` / `OlePres001` presentation cache.
 
Now, when the user saves in the Windows Helper (`origin-bridge.exe`), the helper automatically attaches
to the active Origin instance via COM Automation (`Origin.ApplicationSI`) and triggers LabTalk:
 
```labtalk
expGraph type:=png filename:="preview" path:="<session dir>" overwrite:=replace;
```
 
This generates a high-resolution 300+ DPI `preview.png` directly into the session folder. SlideBridge's
paired writeback pipeline automatically selects `preview.png` as top candidate, completely eliminating
any manual file export step.
 
### Verification Results
 
1. Cross-compiled with MinGW-w64 (`scripts/build_origin_bridge.sh`).
2. Verified on live Windows 11 Lite VM:
   - `Origin.ApplicationSI` successfully attaches to the open OriginPro 2021 instance.
   - `expGraph` executes with `HRESULT = 0x0`.
   - 152 KB, 13206 x 2669 300+ DPI `preview.png` generated and verified on Mac.
3. Fallback to GDI+ / OLE EMF rendering and manual export remains active if COM automation is unavailable.

### Directory Standardization Refactoring (2026-09-11)

**Status:** Done & Verified.
- Decoupled `artifacts/` into standard GitHub open-source layout:
  - `dist/`: Deliverables (`dist/SlideBridge.app`, `dist/origin-bridge.exe`, `dist/SlideBridge-Edit-Active.app`).
  - `bin/`: Dependency tools (`bin/emf2svg-conv`).
  - `.cache/sessions`: Runtime session working directory (under `$HOME`, reachable via `\\Mac\Home`).
  - `.gitignore`: Updated with `dist/`, `bin/`, `.build/`, `.cache/`, `artifacts/`.
- All Python resolvers (`core.py`, `vm.py`, `doctor.py`, `powerpoint.py`, `bridge.py`) updated with primary search in new locations and backward compatibility for legacy artifacts paths.
- All 134 Python unit tests pass 100%. `slidebridge doctor` all green.
