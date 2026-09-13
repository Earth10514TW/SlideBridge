"""Mac PowerPoint interaction, shape-to-OLE geometric resolution, and hot reload.

Enables seamless one-click editing of Origin OLE charts directly from
PowerPoint on macOS:
1. Detects frontmost presentation, current slide index, and selected shape.
2. Resolves selected shape to exact ppt/embeddings/oleObjectX.bin via geometric matching.
3. Automatically saves presentation in PowerPoint before extraction.
4. Orchestrates Windows VM Helper edit.
5. In-place writes back updated OLE binary and dual-format preview.
6. Automatically hot-reloads the presentation in PowerPoint back to the same slide.
"""

from __future__ import annotations

import datetime
import hashlib
import os
import posixpath
import re
import subprocess
import uuid
import zipfile
from pathlib import Path
from typing import Sequence
from xml.etree import ElementTree

from .core import SlideBridgeError, UnchangedObjectError, _path_string
from .bridge import prepare_ole, writeback_ole, list_ole_objects
from .vm import Guest, detect_guest, launch_vm_helper


_EMU_PER_PT = 12700.0
_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_P_NS = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
_A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_R_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

_COMPILED_CACHE_DIR = Path.home() / "Library/Caches/SlideBridge/compiled_scripts"

_STATE_SCRIPT_SOURCE = """on run argv
    set saveFirst to (item 1 of argv is "true")
    tell application "Microsoft PowerPoint"
        if not running then
            return "ERROR:NOT_RUNNING"
        end if
        if (count of presentations) is 0 then
            return "ERROR:NO_PRESENTATION"
        end if
        if saveFirst then
            save active presentation
        end if
        set pres to active presentation
        set presPath to full name of pres as text
        set w to active window
        set curSlide to slide index of (slide of view of w)
        set sel to selection of w
        set selType to selection type of sel as text
        
        if selType is "selection type shapes" then
            set sr to shape range of sel
            set s to shape 1 of sr
            set vName to name of s as text
            set vTop to (top of s) as text
            set vLeft to (left position of s) as text
            set vW to (width of s) as text
            set vH to (height of s) as text
            return "OK|" & presPath & "|" & curSlide & "|SHAPE|" & vName & "|" & vLeft & "|" & vTop & "|" & vW & "|" & vH
        else
            return "OK|" & presPath & "|" & curSlide & "|NONE"
        end if
    end tell
end run"""

_RELOAD_SCRIPT_SOURCE = """on run argv
    set absPath to item 1 of argv
    set slideIdx to (item 2 of argv) as integer
    tell application "Microsoft PowerPoint"
        try
            set p to active presentation
            close p
        end try
        set newP to open (POSIX file absPath)
        try
            set v to view of active window
            go to slide v number slideIdx
        end try
    end tell
end run"""


def default_session_parent() -> Path:
    """Return a directory the Windows guest can actually reach."""
    home = Path.home().resolve()
    project = Path(__file__).resolve().parent.parent
    cache_dir = project / ".cache" / "sessions"
    try:
        cache_dir.resolve().relative_to(home)
    except ValueError:
        cache_dir = home / "Library" / "Caches" / "SlideBridge" / "sessions"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _run_applescript(script: str) -> str:
    """Execute an AppleScript snippet and return standard output."""
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout.strip()
    except FileNotFoundError as exc:
        raise SlideBridgeError("osascript executable not found on this system.") from exc
    except subprocess.CalledProcessError as exc:
        err = exc.stderr.strip() or str(exc)
        raise SlideBridgeError(f"AppleScript error: {err}") from exc


def _get_compiled_script(name: str, source: str) -> Path | None:
    """Compile AppleScript source to a cached .scpt file to eliminate runtime parsing overhead."""
    try:
        source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]
        _COMPILED_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        target = _COMPILED_CACHE_DIR / f"{name}_{source_hash}.scpt"
        if target.is_file():
            return target
        tmp_target = target.with_suffix(f".tmp_{os.getpid()}")
        proc = subprocess.run(
            ["osacompile", "-e", source, "-o", str(tmp_target)],
            capture_output=True,
            timeout=10,
        )
        if proc.returncode == 0 and tmp_target.is_file():
            os.replace(tmp_target, target)
            return target
        return None
    except Exception:
        return None


def _run_compiled_or_raw(
    name: str,
    compiled_source: str,
    raw_script: str,
    args: Sequence[str] = (),
) -> str:
    """Execute precompiled .scpt bytecode if available, falling back to raw AppleScript."""
    compiled_path = _get_compiled_script(name, compiled_source)
    if compiled_path is not None:
        try:
            proc = subprocess.run(
                ["osascript", str(compiled_path), *args],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            return proc.stdout.strip()
        except subprocess.CalledProcessError as exc:
            err = exc.stderr.strip() or str(exc)
            raise SlideBridgeError(f"AppleScript error: {err}") from exc
        except Exception:
            pass
    return _run_applescript(raw_script)


def get_active_powerpoint_state(save_first: bool = False) -> dict:
    """Query Microsoft PowerPoint on Mac for the active presentation and selection.

    If save_first is True, saves the active presentation within the same AppleScript
    transaction, eliminating extra process dispatch latency.

    Returns dict with keys:
      - presentation_path: str
      - slide_index: int (1-based)
      - has_selection: bool
      - shape_name: str or None
      - shape_bounds: tuple (left, top, width, height) in points or None
    """
    save_stmt = "save active presentation" if save_first else ""
    script = f"""
    tell application "Microsoft PowerPoint"
        if not running then
            return "ERROR:NOT_RUNNING"
        end if
        if (count of presentations) is 0 then
            return "ERROR:NO_PRESENTATION"
        end if
        {save_stmt}
        set pres to active presentation
        set presPath to full name of pres as text
        set w to active window
        set curSlide to slide index of (slide of view of w)
        set sel to selection of w
        set selType to selection type of sel as text
        
        if selType is "selection type shapes" then
            set sr to shape range of sel
            set s to shape 1 of sr
            set vName to name of s as text
            set vTop to (top of s) as text
            set vLeft to (left position of s) as text
            set vW to (width of s) as text
            set vH to (height of s) as text
            return "OK|" & presPath & "|" & curSlide & "|SHAPE|" & vName & "|" & vLeft & "|" & vTop & "|" & vW & "|" & vH
        else
            return "OK|" & presPath & "|" & curSlide & "|NONE"
        end if
    end tell
    """
    out = _run_compiled_or_raw(
        "query_state",
        _STATE_SCRIPT_SOURCE,
        script,
        args=["true" if save_first else "false"],
    )
    if out == "ERROR:NOT_RUNNING":
        raise SlideBridgeError("Microsoft PowerPoint is not running.")
    if out == "ERROR:NO_PRESENTATION":
        raise SlideBridgeError("No presentation is currently open in Microsoft PowerPoint.")
    if not out.startswith("OK|"):
        raise SlideBridgeError(f"Unexpected response from PowerPoint: {out}")

    parts = out.split("|")
    pres_path = parts[1]
    slide_idx = int(parts[2])
    status = parts[3]

    state: dict = {
        "presentation_path": pres_path,
        "slide_index": slide_idx,
        "has_selection": False,
        "shape_name": None,
        "shape_bounds": None,
    }

    if status == "SHAPE" and len(parts) >= 8:
        state["has_selection"] = True
        state["shape_name"] = parts[4]
        try:
            left = float(parts[5])
            top = float(parts[6])
            w = float(parts[7])
            h = float(parts[8])
            state["shape_bounds"] = (left, top, w, h)
        except ValueError:
            pass

    return state


def save_active_presentation() -> None:
    """Tell Microsoft PowerPoint to save the active presentation."""
    script = """
    tell application "Microsoft PowerPoint"
        if running and (count of presentations) > 0 then
            save active presentation
        end if
    end tell
    """
    _run_applescript(script)


def reload_presentation(pptx_path: str, slide_index: int = 1) -> None:
    """Close and re-open the presentation in Microsoft PowerPoint, navigating back to slide_index."""
    abs_path = os.path.abspath(pptx_path)
    script = f"""
    tell application "Microsoft PowerPoint"
        try
            set p to active presentation
            close p
        end try
        set newP to open (POSIX file "{abs_path}")
        try
            set v to view of active window
            go to slide v number {slide_index}
        end try
    end tell
    """
    _run_compiled_or_raw(
        "reload",
        _RELOAD_SCRIPT_SOURCE,
        script,
        args=[abs_path, str(slide_index)],
    )


def _get_ordered_slide_parts(archive: zipfile.ZipFile) -> list[str]:
    """Parse presentation.xml and its rels to return slide part names in 1-based display order."""
    pres_tree = ElementTree.fromstring(archive.read("ppt/presentation.xml"))
    pres_rels_tree = ElementTree.fromstring(archive.read("ppt/_rels/presentation.xml.rels"))

    rel_map = {}
    for rel in pres_rels_tree.findall(f"{_REL_NS}Relationship"):
        target = rel.attrib.get("Target", "").lstrip("/")
        rel_map[rel.attrib["Id"]] = posixpath.normpath(posixpath.join("ppt", target))

    sld_id_lst = pres_tree.find(f"{_P_NS}sldIdLst")
    if sld_id_lst is None:
        return []

    slides_in_order = []
    for sld_id in sld_id_lst:
        r_id = sld_id.attrib.get(f"{_R_NS}id")
        if r_id and r_id in rel_map:
            slides_in_order.append(rel_map[r_id])

    return slides_in_order


def resolve_ole_from_selection(
    pptx_path: os.PathLike[str] | str,
    slide_index: int,
    sel_bounds: tuple[float, float, float, float] | None = None,
    sel_name: str | None = None,
) -> dict:
    """Match a PowerPoint selection (by bounds or name) on a slide to an embedded OLE member.

    Returns dict containing:
      - member: str (e.g. "ppt/embeddings/oleObject3.bin")
      - shape_name: str
      - shape_id: str
      - slide_part: str
      - bounds: tuple (left, top, width, height) in points
      - diff: float (geometric distance, 0.0 for exact match)
    """
    path_val = _path_string(pptx_path)
    if not os.path.isfile(path_val):
        raise SlideBridgeError(f"presentation file not found: {path_val}")

    with zipfile.ZipFile(path_val, "r") as archive:
        slides_in_order = _get_ordered_slide_parts(archive)
        if slide_index < 1 or slide_index > len(slides_in_order):
            raise SlideBridgeError(
                f"slide index {slide_index} out of range (presentation has {len(slides_in_order)} slides)"
            )

        slide_part = slides_in_order[slide_index - 1]
        slide_tree = ElementTree.fromstring(archive.read(slide_part))

        rels_part = posixpath.dirname(slide_part) + "/_rels/" + posixpath.basename(slide_part) + ".rels"
        slide_rels = {}
        if rels_part in archive.namelist():
            rels_tree = ElementTree.fromstring(archive.read(rels_part))
            for r in rels_tree.findall(f"{_REL_NS}Relationship"):
                target = r.attrib.get("Target", "")
                resolved = posixpath.normpath(posixpath.join(posixpath.dirname(slide_part), target))
                slide_rels[r.attrib["Id"]] = resolved

        candidates = []
        for gf in slide_tree.iter(f"{_P_NS}graphicFrame"):
            ole_obj = gf.find(f".//{_P_NS}oleObj")
            if ole_obj is None:
                continue

            r_id = ole_obj.attrib.get(f"{_R_NS}id")
            member = slide_rels.get(r_id)
            if not member or not member.startswith("ppt/embeddings/"):
                continue

            c_nv_pr = gf.find(f".//{_P_NS}cNvPr")
            sh_name = c_nv_pr.attrib.get("name", "") if c_nv_pr is not None else ""
            sh_id = c_nv_pr.attrib.get("id", "") if c_nv_pr is not None else ""

            xfrm = gf.find(f".//{_P_NS}xfrm")
            if xfrm is None:
                xfrm = gf.find(f".//{_A_NS}xfrm")
            top = left = width = height = 0.0
            if xfrm is not None:
                off = xfrm.find(f"{_A_NS}off")
                ext = xfrm.find(f"{_A_NS}ext")
                if off is not None:
                    left = float(off.attrib.get("x", 0)) / _EMU_PER_PT
                    top = float(off.attrib.get("y", 0)) / _EMU_PER_PT
                if ext is not None:
                    width = float(ext.attrib.get("cx", 0)) / _EMU_PER_PT
                    height = float(ext.attrib.get("cy", 0)) / _EMU_PER_PT

            diff = 999999.0
            if sel_bounds:
                diff = (
                    abs(left - sel_bounds[0])
                    + abs(top - sel_bounds[1])
                    + abs(width - sel_bounds[2])
                    + abs(height - sel_bounds[3])
                )

            candidates.append({
                "member": member,
                "shape_name": sh_name,
                "shape_id": sh_id,
                "slide_part": slide_part,
                "bounds": (left, top, width, height),
                "diff": diff,
            })

    if not candidates:
        raise SlideBridgeError(f"No Origin OLE charts found on slide {slide_index}.")

    # Strategy 1: Geometric bounds match (tolerance within 15 pt)
    if sel_bounds is not None:
        candidates.sort(key=lambda c: c["diff"])
        best = candidates[0]
        if best["diff"] <= 15.0:
            return best

    # Strategy 2: Shape name match (e.g. matching "Object 10" or "物件 10")
    if sel_name:
        for c in candidates:
            if c["shape_name"].strip() == sel_name.strip():
                return c
        # Match trailing digits (e.g. "10" from "Object 10" and "物件 10")
        digits_sel = re.findall(r"\d+", sel_name)
        if digits_sel:
            for c in candidates:
                digits_cand = re.findall(r"\d+", c["shape_name"])
                if digits_cand == digits_sel:
                    return c

    # Strategy 3: If only 1 candidate exists on this slide, auto-select it
    if len(candidates) == 1:
        return candidates[0]

    # Ambiguous: multiple candidates on slide, none cleanly matched
    names_summary = ", ".join(f"'{c['shape_name']}' ({c['member']})" for c in candidates)
    raise SlideBridgeError(
        f"Multiple OLE objects on slide {slide_index} ({names_summary}). "
        "Please select the specific chart shape in PowerPoint before editing."
    )


def edit_active_presentation(
    in_place: bool = True,
    vm_name: str | None = None,
    reload_after: bool = True,
    session_dir: os.PathLike[str] | str | None = None,
    vm_backend: str | None = None,
    allow_unchanged: bool = False,
) -> dict:
    """Full end-to-end workflow: detect selection, save, edit in VM, writeback, and reload."""
    # 1. Query PowerPoint (atomic save + query in one transaction)
    state = get_active_powerpoint_state(save_first=True)
    pptx_path = state["presentation_path"]
    slide_index = state["slide_index"]

    # 2. Auto-save in PowerPoint so presentation on disk is fresh (retains mock hook)
    save_active_presentation()

    # 3. Resolve selected shape to OLE member
    resolved = resolve_ole_from_selection(
        pptx_path=pptx_path,
        slide_index=slide_index,
        sel_bounds=state.get("shape_bounds"),
        sel_name=state.get("shape_name"),
    )
    member = resolved["member"]

    # 4. Create Session path (must not exist yet; prepare_ole creates it atomically)
    if session_dir is not None:
        chosen_session = Path(_path_string(session_dir))
    else:
        unique_id = f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        chosen_session = default_session_parent() / f"slidebridge-active-session-{unique_id}"

    prep_report = prepare_ole(
        input_path=pptx_path,
        member=member,
        output_dir=chosen_session,
    )

    # 5. Detect and Launch VM Helper
    if vm_name:
        guest = Guest(vm_backend or "parallels", vm_name)
    else:
        guest = detect_guest(vm_backend)
    ret = launch_vm_helper(guest, session_dir=chosen_session)

    edited_bin = chosen_session / "edited.bin"
    if not edited_bin.is_file():
        if ret == 0:
            return {
                "presentation": pptx_path,
                "slide_index": slide_index,
                "shape_name": resolved["shape_name"],
                "member": member,
                "vm": guest.name,
                "session": str(chosen_session),
                "in_place": in_place,
                "backup": None,
                "preview_format": None,
                "status": "cancelled",
                "message": "Edit was cancelled by user; presentation left unchanged.",
            }
        raise SlideBridgeError("No edited.bin found in session; edit was cancelled or failed.")

    # 6. Writeback
    try:
        writeback_report = writeback_ole(
            source_path=pptx_path,
            session_dir=chosen_session,
            force=True,  # Bypass SHA256 check because PowerPoint just saved it
            in_place=in_place,
            allow_unchanged=allow_unchanged,
        )
    except UnchangedObjectError as exc:
        return {
            "presentation": pptx_path,
            "slide_index": slide_index,
            "shape_name": resolved["shape_name"],
            "member": member,
            "vm": guest.name,
            "session": str(chosen_session),
            "in_place": in_place,
            "backup": None,
            "preview_format": None,
            "status": "unchanged",
            "message": str(exc),
            "is_near_identical": exc.is_near_identical,
        }

    # 7. Hot-reload in PowerPoint
    if reload_after:
        reload_presentation(pptx_path, slide_index)

    return {
        "presentation": pptx_path,
        "slide_index": slide_index,
        "shape_name": resolved["shape_name"],
        "member": member,
        "vm": guest.name,
        "session": str(chosen_session),
        "in_place": in_place,
        "backup": writeback_report.get("backup"),
        "preview_format": writeback_report.get("preview_format"),
        "status": "success",
    }
