# Converter fidelity checkpoint — 2026-09-10

Paused at the user's request before implementation of the native parser fix.

## Confirmed by the user

PowerPoint displays the repaired presentation and Windows Origin opens the embedded objects on double-click. The reference-PNG repair is useful evidence for package/OLE preservation, but the user explicitly requires automatic conversion from the original EMF, without substituting other images.

## Reproduced defect

`tests/emf_fixture.py` generates a minimal standalone EMF with an ordinary `EMR_CREATEPEN` solid pen of logical width 46. Installed libemf2svg 1.8.1 produces SVG `stroke-width="1.0000"`. This reproduces the thin curves independently of any private Origin data.

Run the real parser regression (currently expected to FAIL the positive-width test):

```sh
SLIDEBRIDGE_TEST_EMF2SVG="$(command -v emf2svg-conv)" python3 -m unittest discover -s tests -p test_native_emf.py -v
```

The native tests are explicitly opt-in. Ordinary package tests remain green; native tests being skipped is not evidence that the renderer is fixed.

## Root cause and next implementation

Upstream checkout is locally cached at ignored `artifacts/upstream`, commit `658a718de180666d342a78fd4046ec1f41e65e17`.

- `src/lib/emf2svg_rec_object_creation.c` lines 146–163 stores ordinary CREATEPEN style/width; lines 210–226 handles EXTCREATEPEN.
- `src/lib/emf2svg_utils.c` lines 880–908 treats zero type bits as cosmetic and forces width 1, losing the ordinary CREATEPEN logical width.
- Preserve an explicit ordinary/extended pen distinction through object selection and saved DC state. Use ordinary CreatePen width semantics while retaining real extended cosmetic hairlines. Normalize wide ordinary dashed styles to solid as required by CreatePen behavior. Do not globally widen all SVG strokes or indiscriminately mark every pen geometric.
- Add tests for wide solid pens, zero-width hairlines, ordinary wide dashed normalization, extended cosmetic pens and geometric pens, plus pen selection/save/restore. Existing native tests cover the first subset only.
- Build a pinned patched libemf2svg separately from the Homebrew installation, wire it into the automatic renderer, regenerate the original PPTX without `--preview`, and compare against the Windows references only as validation.
- Verify OLE hashes, relationships and actual output images; obtain PowerPoint confirmation for this new automatically converted output separately.

Microsoft CreatePen allows nonzero logical widths; the MS-EMF LogPen description has stricter cosmetic constraints. The intended behavior here is Windows-compatible rendering of real exported EMFs, as explicitly requested by the user.

## Environment and files

Installed build prerequisites this session: Homebrew `cmake` and `pkgconf`. No native library patched or replaced. No new repaired PPTX generated this session.

Private sample: `/Users/earth/Downloads/presentation.pptx`. Windows references: `/Users/earth/Downloads/圖片1.png` and `圖片2.png`. These remain outside Git. Reference images must not become runtime replacements in this fix.

The native library and bundled libuemf are GPLv2. Preserve license notices and source/patch availability when distributing a modified converter. No upstream source or binary is committed in this checkpoint.

Sources:

- https://github.com/kakwa/libemf2svg/blob/658a718de180666d342a78fd4046ec1f41e65e17/src/lib/emf2svg_utils.c
- https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-createpen
- https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-emf/93ce3f45-37ac-4aff-b6e8-2f6db054c4c4
