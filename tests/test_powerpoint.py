import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from xml.etree import ElementTree

from slidebridge import backup
from slidebridge.bridge import prepare_ole, writeback_ole
from slidebridge.core import SlideBridgeError
from slidebridge.powerpoint import (
    _get_ordered_slide_parts,
    default_session_parent,
    edit_active_presentation,
    resolve_ole_from_selection,
)
from slidebridge.vm import Guest


REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OLE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/oleObject"
IMAGE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"


def _cfb_payload(variant: int = 0) -> bytes:
    data = bytearray(512)
    data[:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    data[24:32] = (0x0003003E + variant).to_bytes(8, "little")
    return bytes(data)


def _minimal_png() -> bytes:
    data = bytearray(24)
    data[:8] = b"\x89PNG\r\n\x1a\n"
    data[16:20] = (10).to_bytes(4, "big")
    data[20:24] = (10).to_bytes(4, "big")
    return bytes(data)


def _make_test_presentation(target_path: Path) -> Path:
    """Create a multi-slide test presentation with 2 OLE objects on slide 1 and 1 on slide 2."""
    pres_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<p:sldIdLst>'
        '<p:sldId id="256" r:id="rId1"/>'
        '<p:sldId id="257" r:id="rId2"/>'
        '</p:sldIdLst>'
        '</p:presentation>'
    ).encode("utf-8")

    pres_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{REL_NS}">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide2.xml"/>'
        '</Relationships>'
    ).encode("utf-8")

    # Slide 1: contains two OLE objects at different coordinates
    # Shape A: left=50 pt (635000 EMU), top=50 pt, w=200 pt (2540000 EMU), h=100 pt (1270000 EMU) -> oleObject1.bin
    # Shape B: left=50 pt (635000 EMU), top=200 pt (2540000 EMU), w=200 pt, h=100 pt -> oleObject2.bin
    slide1_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<p:cSld><p:spTree>'
        '<p:graphicFrame>'
        '<p:nvGraphicFramePr><p:cNvPr id="2" name="物件 1"/></p:nvGraphicFramePr>'
        '<p:xfrm><a:off x="635000" y="635000"/><a:ext cx="2540000" cy="1270000"/></p:xfrm>'
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/presentationml/2006/ole">'
        '<p:oleObj r:id="rId10"><p:embed/><p:pic><p:blipFill><a:blip r:embed="img1"/></p:blipFill></p:pic></p:oleObj>'
        '</a:graphicData></a:graphic>'
        '</p:graphicFrame>'
        '<p:graphicFrame>'
        '<p:nvGraphicFramePr><p:cNvPr id="3" name="物件 2"/></p:nvGraphicFramePr>'
        '<p:xfrm><a:off x="635000" y="2540000"/><a:ext cx="2540000" cy="1270000"/></p:xfrm>'
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/presentationml/2006/ole">'
        '<p:oleObj r:id="rId11"><p:embed/><p:pic><p:blipFill><a:blip r:embed="img2"/></p:blipFill></p:pic></p:oleObj>'
        '</a:graphicData></a:graphic>'
        '</p:graphicFrame>'
        '</p:spTree></p:cSld></p:sld>'
    ).encode("utf-8")

    slide1_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{REL_NS}">'
        f'<Relationship Id="rId10" Type="{OLE_REL}" Target="../embeddings/oleObject1.bin"/>'
        f'<Relationship Id="rId11" Type="{OLE_REL}" Target="../embeddings/oleObject2.bin"/>'
        f'<Relationship Id="img1" Type="{IMAGE_REL}" Target="../media/image1.png"/>'
        f'<Relationship Id="img2" Type="{IMAGE_REL}" Target="../media/image2.png"/>'
        '</Relationships>'
    ).encode("utf-8")

    # Slide 2: contains single OLE object
    slide2_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<p:cSld><p:spTree>'
        '<p:graphicFrame>'
        '<p:nvGraphicFramePr><p:cNvPr id="5" name="Chart Only"/></p:nvGraphicFramePr>'
        '<p:xfrm><a:off x="1270000" y="1270000"/><a:ext cx="3810000" cy="2540000"/></p:xfrm>'
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/presentationml/2006/ole">'
        '<p:oleObj r:id="rId20"><p:embed/><p:pic><p:blipFill><a:blip r:embed="img3"/></p:blipFill></p:pic></p:oleObj>'
        '</a:graphicData></a:graphic>'
        '</p:graphicFrame>'
        '</p:spTree></p:cSld></p:sld>'
    ).encode("utf-8")

    slide2_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{REL_NS}">'
        f'<Relationship Id="rId20" Type="{OLE_REL}" Target="../embeddings/oleObject3.bin"/>'
        f'<Relationship Id="img3" Type="{IMAGE_REL}" Target="../media/image3.png"/>'
        '</Relationships>'
    ).encode("utf-8")

    cfb = _cfb_payload()
    png = _minimal_png()

    with zipfile.ZipFile(target_path, "w") as z:
        z.writestr("ppt/presentation.xml", pres_xml)
        z.writestr("ppt/_rels/presentation.xml.rels", pres_rels)
        z.writestr("ppt/slides/slide1.xml", slide1_xml)
        z.writestr("ppt/slides/_rels/slide1.xml.rels", slide1_rels)
        z.writestr("ppt/slides/slide2.xml", slide2_xml)
        z.writestr("ppt/slides/_rels/slide2.xml.rels", slide2_rels)
        z.writestr("ppt/embeddings/oleObject1.bin", cfb)
        z.writestr("ppt/embeddings/oleObject2.bin", cfb)
        z.writestr("ppt/embeddings/oleObject3.bin", cfb)
        z.writestr("ppt/media/image1.png", png)
        z.writestr("ppt/media/image2.png", png)
        z.writestr("ppt/media/image3.png", png)

    return target_path


class PowerPointIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.pptx = _make_test_presentation(self.tmp_path / "test.pptx")
        # Point the backup store at the sandbox: in-place writeback snapshots
        # the presentation, and a test must never touch the real
        # ~/Library/Application Support/SlideBridge store.
        self._backup_env = patch.dict(
            os.environ, {"SLIDEBRIDGE_BACKUP_DIR": str(self.tmp_path / "backup-store")}
        )
        self._backup_env.start()

    def tearDown(self):
        self._backup_env.stop()
        self.tmp.cleanup()

    def test_ordered_slides(self):
        with zipfile.ZipFile(self.pptx) as z:
            slides = _get_ordered_slide_parts(z)
            self.assertEqual(slides, ["ppt/slides/slide1.xml", "ppt/slides/slide2.xml"])

    def test_geometric_matching_exact(self):
        # Shape A on Slide 1: left=50, top=50, w=200, h=100
        res = resolve_ole_from_selection(
            self.pptx,
            slide_index=1,
            sel_bounds=(50.0, 50.0, 200.0, 100.0),
            sel_name="Object 1",
        )
        self.assertEqual(res["member"], "ppt/embeddings/oleObject1.bin")
        self.assertEqual(res["shape_name"], "物件 1")
        self.assertAlmostEqual(res["diff"], 0.0, places=3)

    def test_geometric_matching_second_shape(self):
        # Shape B on Slide 1: left=50, top=200, w=200, h=100
        res = resolve_ole_from_selection(
            self.pptx,
            slide_index=1,
            sel_bounds=(50.0, 200.0, 200.0, 100.0),
            sel_name="Object 2",
        )
        self.assertEqual(res["member"], "ppt/embeddings/oleObject2.bin")
        self.assertEqual(res["shape_name"], "物件 2")
        self.assertAlmostEqual(res["diff"], 0.0, places=3)

    def test_single_chart_on_slide_auto_selects(self):
        # Slide 2 only has 1 chart. Even without bounds or name, it should resolve automatically.
        res = resolve_ole_from_selection(
            self.pptx,
            slide_index=2,
            sel_bounds=None,
            sel_name=None,
        )
        self.assertEqual(res["member"], "ppt/embeddings/oleObject3.bin")
        self.assertEqual(res["shape_name"], "Chart Only")

    def test_multiple_charts_unselected_raises(self):
        # Slide 1 has 2 charts. If user selected nothing, it must raise with helpful message.
        with self.assertRaises(SlideBridgeError) as ctx:
            resolve_ole_from_selection(
                self.pptx,
                slide_index=1,
                sel_bounds=None,
                sel_name=None,
            )
        self.assertIn("Multiple OLE objects on slide 1", str(ctx.exception))

    def test_slide_index_out_of_range(self):
        with self.assertRaises(SlideBridgeError) as ctx:
            resolve_ole_from_selection(self.pptx, slide_index=99)
        self.assertIn("out of range", str(ctx.exception))

    def test_in_place_writeback_with_backup(self):
        # Test writeback_ole with in_place=True
        session = self.tmp_path / "session"
        prepare_ole(self.pptx, "ppt/embeddings/oleObject1.bin", session)

        # Create updated OLE and updated preview in session. The OLE must differ
        # from the original, otherwise the unchanged-OLE guard rejects it.
        new_cfb = _cfb_payload(variant=1)
        (session / "edited.bin").write_bytes(new_cfb)
        new_png = _minimal_png() + b"extra_png_bytes"
        (session / "edited.png").write_bytes(new_png)

        orig_sha = hashlib.sha256(self.pptx.read_bytes()).hexdigest()

        rep = writeback_ole(
            source_path=self.pptx,
            session_dir=session,
            force=True,
            in_place=True,
        )

        self.assertTrue(rep["in_place"])
        backup_path = Path(rep["backup"])
        self.assertTrue(backup_path.is_file())
        self.assertEqual(hashlib.sha256(backup_path.read_bytes()).hexdigest(), orig_sha)

        # The snapshot must be restorable but invisible: the only presentation
        # in the user's own folder is the one they put there.
        self.assertNotEqual(backup_path.parent, self.pptx.parent)
        self.assertEqual(
            sorted(p.name for p in self.pptx.parent.iterdir() if p.suffix == ".pptx"),
            ["test.pptx"],
        )
        self.assertEqual(rep["backup_retention_days"], backup.default_retention_days())
        self.assertEqual(
            [entry["id"] for entry in backup.list_backups(self.pptx)["backups"]],
            [backup_path.name],
        )

        # Confirm source presentation was modified in-place
        self.assertEqual(Path(rep["output"]).resolve(), self.pptx.resolve())
        with zipfile.ZipFile(self.pptx) as z:
            self.assertEqual(z.read("ppt/embeddings/oleObject1.bin"), new_cfb)

    def test_edit_active_presentation_allow_unchanged(self):
        state = {
            "presentation_path": str(self.pptx),
            "slide_index": 1,
            "shape_bounds": (50.0, 50.0, 200.0, 100.0),
            "shape_name": "Shape A",
        }
        session1 = self.tmp_path / "custom_sess1"
        session2 = self.tmp_path / "custom_sess2"

        def mock_launch(guest, session_dir, **kwargs):
            # Write identical OLE back (simulate no edits)
            (session_dir / "edited.bin").write_bytes(_cfb_payload(variant=0))
            (session_dir / "preview.png").write_bytes(_minimal_png() + b"extra")
            return 0

        with patch("slidebridge.powerpoint.get_active_powerpoint_state", return_value=state), \
             patch("slidebridge.powerpoint.save_active_presentation"), \
             patch("slidebridge.powerpoint.reload_presentation"), \
             patch("slidebridge.powerpoint.detect_guest", return_value=Guest("parallels", "Win11")), \
             patch("slidebridge.powerpoint.launch_vm_helper", side_effect=mock_launch):

            # Without allow_unchanged, returns status 'unchanged' gracefully without raising
            rep_unchanged = edit_active_presentation(session_dir=session1, reload_after=False, allow_unchanged=False)
            self.assertEqual(rep_unchanged["status"], "unchanged")
            self.assertEqual(rep_unchanged["member"], "ppt/embeddings/oleObject1.bin")

            # With allow_unchanged=True, succeeds
            rep = edit_active_presentation(session_dir=session2, reload_after=False, allow_unchanged=True)
            self.assertEqual(rep["status"], "success")
            self.assertEqual(rep["member"], "ppt/embeddings/oleObject1.bin")

    def test_state_script_compilation(self):
        from slidebridge.powerpoint import _STATE_SCRIPT_SOURCE, _get_compiled_script
        compiled_path = _get_compiled_script("query_state_test", _STATE_SCRIPT_SOURCE)
        self.assertIsNotNone(compiled_path)
        self.assertTrue(compiled_path.is_file())


class DefaultSessionParentTests(unittest.TestCase):
    """The session must live under the home folder so the guest can reach it.

    Regression: it used to be tempfile.gettempdir() (/var/folders/...), which
    the Windows guest cannot address -- the helper failed with an opaque
    ERROR_BAD_NET_NAME and no edited.bin was ever produced.
    """

    def test_uses_project_cache_when_the_checkout_is_under_home(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            project = home / "code" / "SlideBridge"
            project.mkdir(parents=True)
            with patch("pathlib.Path.home", return_value=home), patch(
                "slidebridge.powerpoint.__file__", str(project / "slidebridge" / "powerpoint.py")
            ):
                parent = default_session_parent()
        # Compared resolved: on macOS /var resolves to /private/var.
        self.assertEqual(parent, (project / ".cache" / "sessions").resolve())

    def test_falls_back_to_a_cache_dir_when_the_checkout_is_outside_home(self):
        with tempfile.TemporaryDirectory() as home_td, tempfile.TemporaryDirectory() as other_td:
            home = Path(home_td)
            project = Path(other_td) / "SlideBridge"
            project.mkdir()
            with patch("pathlib.Path.home", return_value=home), patch(
                "slidebridge.powerpoint.__file__", str(project / "slidebridge" / "powerpoint.py")
            ):
                parent = default_session_parent()
        self.assertEqual(parent, (home / "Library" / "Caches" / "SlideBridge" / "sessions").resolve())

    def test_result_is_always_under_home(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            with patch("pathlib.Path.home", return_value=home):
                parent = default_session_parent()
            parent.resolve().relative_to(home.resolve())

    def test_never_returns_the_system_temp_directory(self):
        parent = default_session_parent()
        self.assertNotEqual(str(parent), tempfile.gettempdir())


if __name__ == "__main__":
    unittest.main()
