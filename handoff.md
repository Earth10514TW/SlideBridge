# SlideBridge handoff

Updated: 2026-09-10 (Asia/Taipei). Origin OLE bidirectional writeback complete.

## Current direction: Origin editing without Windows PowerPoint

The current implementation and reproducible commands are documented in [docs/origin-bridge.md](docs/origin-bridge.md).

Completed components:
1. **`prepare-ole`**: Extracts embedded OLE storage safely to session directory with source SHA-256 and relationship manifest.
2. **Native Windows x64 OLE host (`native/origin-bridge/`)**: Cross-compiled with MinGW `-static`. Verified interactive roundtrip on Parallels Windows 11 VM with OriginPro 2021: user edited X-axis label from `Time (hr)` to `TT (hr)`, saved, and reopened verifying binary persistence (`reopen-verify.bin`, SHA-256: `267d50b4...`).
3. **`writeback-ole`**: Implemented in `slidebridge/bridge.py` and `slidebridge/cli.py`. Enforces strict paired writeback (OLE binary + matching preview image), source presentation & target OLE SHA-256 conflict detection (`--force` bypass), atomic temp-file assembly, DrawingML / VML relationship rewriting (e.g. EMF to PNG redirection), and `[Content_Types].xml` maintenance.
4. **Validation & Verification**:
   - 39 Python unit tests (100% pass rate).
   - 9 native EMF converter tests (100% pass rate).
   - 4 C++ persistence fault-injection tests (100% pass rate).
   - Real presentation writeback verified via `scripts/verify_package.py` on `/Users/earth/Downloads/presentation.pptx` (`artifacts/presentation_writeback_png.pptx`), with perfect CRC, relationships, and unaltered secondary OLE objects.

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

## Git and shutdown state

Branch: main. Latest commits:

- `f4e7550` initial CLI and OLE-preserving repair.
- `0ab6834` exact Windows PNG preview support.
- `6d7c91e` minimal generic pen-width regression and diagnostic checkpoint.
- `64b383d` fix: patch libemf2svg CREATEPEN pen-width bug and integrate patched build.

## Previous converter verification follow-up

1. Open `artifacts/presentation_auto.pptx` in PowerPoint and compare the 4 converted images against Windows references (`圖片1.png`, `圖片2.png`). Pen widths should now match; font/positioning differences are expected.
2. Verify Windows Origin double-click editing still works on the new output.
3. Decide whether the remaining font/positioning fidelity is acceptable or needs further work.
