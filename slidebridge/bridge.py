"""Prepare a package-local OLE object for a Windows editing helper.

This module deliberately treats the embedded OLE payload as opaque bytes.  It
only verifies the relationship that selects it, checks the Compound File
signature, and copies the bytes into a new handoff directory.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import posixpath
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from .core import (
    SlideBridgeError,
    UnchangedObjectError,
    _CT_NS,
    _PNG_SIGNATURE,
    _SLIDE_RE,
    _check_archive,
    _copy_archive_member,
    _local_name,
    _path_string,
    _png_content_type,
    _png_is_basic,
    _read_relationships,
    _relationship_part_for,
    _replacement_target,
    _resolve_target,
    _shape_id_matches,
    _slide_ole_ids,
    png_white_to_transparent,
)
from .locate import find_executable


_CFB_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_CFB_MIN_SIZE = 512
_OLE_RELATIONSHIP_NAME = "oleobject"
_EMBEDDINGS_PREFIX = "ppt/embeddings/"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_RESVG_CANDIDATES = (
    str(_PROJECT_ROOT / "bin" / "resvg"),
    str(_PROJECT_ROOT / "artifacts" / "bin" / "resvg"),
    "/opt/homebrew/bin/resvg",
    "/usr/local/bin/resvg",
    "/opt/local/bin/resvg",
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _member_string(member: os.PathLike[str] | str) -> str:
    try:
        value = os.fspath(member)
    except TypeError as exc:
        raise SlideBridgeError("OLE member must be a string or path-like object") from exc
    if isinstance(value, bytes):
        value = os.fsdecode(value)
    if not value:
        raise SlideBridgeError("OLE member must not be empty")
    # ZIP package names use POSIX separators.  Refusing alternate spellings
    # keeps relationship validation exact and prevents traversal aliases.
    parts = value.split("/")
    if (
        "\\" in value
        or "\x00" in value
        or value.startswith("/")
        or any(part in {"", ".", ".."} for part in parts)
        or posixpath.normpath(value) != value
        or not value.startswith(_EMBEDDINGS_PREFIX)
        or value == _EMBEDDINGS_PREFIX
    ):
        raise SlideBridgeError(f"unsafe OLE member path: {value}")
    return value


def _is_ole_relationship(rel_type: str) -> bool:
    return rel_type.rsplit("/", 1)[-1].lower() == _OLE_RELATIONSHIP_NAME


def _index_ole_references(
    archive: zipfile.ZipFile,
) -> dict[str, list[dict[str, str]]]:
    """Index every internal OLE relationship in an archive by target member.

    Slide and relationship parts are read once per archive.  Keeping this
    index local to the archive preserves the existing validation behavior
    while allowing callers that enumerate several OLE members to reuse the
    scan.
    """
    names = {info.filename for info in archive.infolist() if not info.is_dir()}
    references_by_member: dict[str, list[dict[str, str]]] = {}
    for slide in sorted(name for name in names if _SLIDE_RE.fullmatch(name)):
        rels_part = _relationship_part_for(slide)
        if rels_part not in names:
            continue
        ole_ids = _slide_ole_ids(archive.read(slide))
        if not ole_ids:
            continue
        relationships = _read_relationships(archive.read(rels_part), rels_part)
        for relationship_id, _target, resolved, rel_type in relationships:
            if (
                relationship_id in ole_ids
                and resolved is not None
                and _is_ole_relationship(rel_type)
            ):
                references_by_member.setdefault(resolved, []).append(
                    {"slide": slide, "relationship_id": relationship_id}
                )
    return references_by_member


def _find_references(archive: zipfile.ZipFile, member: str) -> list[dict[str, str]]:
    references = _index_ole_references(archive).get(member, [])
    if not references:
        raise SlideBridgeError(
            f"OLE member is not referenced by an internal OLE relationship on a slide: {member}"
        )
    return references


def _find_preview_members(archive: zipfile.ZipFile, references: list[dict[str, str]]) -> list[str]:
    names = {info.filename for info in archive.infolist() if not info.is_dir()}
    previews: set[str] = set()

    for ref in references:
        slide = ref["slide"]
        ole_rid = ref["relationship_id"]
        if slide not in names:
            continue
        slide_xml = archive.read(slide)
        try:
            root = ElementTree.fromstring(slide_xml)
        except ElementTree.ParseError:
            continue

        # PowerPoint emits each OLE object twice inside <mc:AlternateContent>:
        # an <mc:Choice> branch and an <mc:Fallback> branch, both carrying the
        # same r:id. Only the Fallback branch holds the preview <p:pic> -- the
        # Choice branch is a bare <p:oleObj><p:embed/></p:oleObj>. Taking the
        # first match therefore picks the branch with no preview, and the
        # writeback fails with "no preview images associated with OLE member".
        # Collect every match and gather previews from all of them.
        targets = [
            element
            for element in root.iter()
            if _local_name(element.tag) in {"oleobj", "oleobject"}
            and any(
                val == ole_rid and attr.rsplit("}", 1)[-1].lower() in {"id", "embed", "link"}
                for attr, val in element.attrib.items()
            )
        ]

        if not targets:
            continue

        preview_rids: set[str] = set()
        spid = None
        for target_ole in targets:
            for child in target_ole.iter():
                if child is target_ole:
                    continue
                for attr, val in child.attrib.items():
                    if attr.rsplit("}", 1)[-1].lower() in {"id", "embed", "link"} and val != ole_rid:
                        preview_rids.add(val)

            if spid is None:
                for attr, val in target_ole.attrib.items():
                    if attr.rsplit("}", 1)[-1].lower() in {"spid", "shapeid"}:
                        spid = val
                        break

        rels_part = _relationship_part_for(slide)
        if rels_part in names:
            relationships = _read_relationships(archive.read(rels_part), rels_part)
            vml_parts: list[str] = []
            for rid, _target, resolved, rtype in relationships:
                if rid in preview_rids and resolved:
                    previews.add(resolved)
                if "vmldrawing" in rtype.lower() and resolved:
                    vml_parts.append(resolved)

            if spid and vml_parts:
                for vml in vml_parts:
                    if vml not in names:
                        continue
                    vml_rels_part = _relationship_part_for(vml)
                    if vml_rels_part not in names:
                        continue
                    vml_rels = _read_relationships(archive.read(vml_rels_part), vml_rels_part)
                    vml_rel_map = {rid: resolved for rid, _target, resolved, _rtype in vml_rels if resolved}
                    try:
                        vml_root = ElementTree.fromstring(archive.read(vml))
                    except ElementTree.ParseError:
                        continue
                    for shape in vml_root.iter():
                        if _local_name(shape.tag) != "shape":
                            continue
                        shape_ids = {
                            val
                            for attr, val in shape.attrib.items()
                            if val and attr.rsplit("}", 1)[-1].lower() in {"id", "spid"}
                        }
                        if not any(_shape_id_matches(val, {spid}) for val in shape_ids):
                            continue
                        for img in shape.iter():
                            if _local_name(img.tag) == "imagedata":
                                for attr, val in img.attrib.items():
                                    if attr.rsplit("}", 1)[-1].lower() in {"relid", "id", "embed", "link"}:
                                        if val in vml_rel_map:
                                            previews.add(vml_rel_map[val])

    return sorted(previews)


def _validate_cfb(data: bytes, member: str) -> None:
    if not data.startswith(_CFB_SIGNATURE):
        raise SlideBridgeError(f"OLE member is not a Compound File: {member}")
    if len(data) < _CFB_MIN_SIZE:
        raise SlideBridgeError(f"OLE member has an incomplete Compound File header: {member}")


#: Fraction of differing bytes below which a "new" OLE is treated as an
#: untouched document. Origin rewrites a handful of metadata bytes even when the
#: chart was never modified, so an exact comparison alone would miss the most
#: common failure: the user edits the chart but never saves inside Origin, and
#: the server serialises its unchanged document.
_NEAR_IDENTICAL_RATIO = 0.001


def _reject_unchanged_preview(
    new_bytes: bytes,
    archive: zipfile.ZipFile,
    preview_members: list[str],
    allow_unchanged: bool,
) -> None:
    """Refuse a writeback whose preview would look identical to the current one.

    The Windows helper renders the preview from the OLE object's *cached*
    presentation (``OlePres000``). Origin does not always refresh that cache --
    its real document lives in ``Contents`` -- so the render can be a stale
    image of the chart as it looked before the edit. Writing that back silently
    makes the presentation appear unchanged even though the OLE binary really
    did change. Catching it here turns a silent no-op into an explicit failure.
    """
    if allow_unchanged:
        return

    for name in preview_members:
        try:
            current = archive.read(name)
        except KeyError:
            continue
        if current == new_bytes:
            raise UnchangedObjectError(
                "the new preview image is byte-identical to the one already in the "
                f"presentation ({name}), so the chart would still look unchanged.\n"
                "This usually means the renderer returned a cached image instead of the "
                "edited chart. Re-open the chart in Origin, make a visible change, press "
                "Save inside Origin, then use the helper's Save.\n"
                "Pass --allow-unchanged to write it back anyway.",
                is_near_identical=False,
                differing_bytes=0,
                total_bytes=len(new_bytes),
            )


def _reject_unchanged_ole(
    new_bytes: bytes, current_bytes: bytes, path: str | Path, allow_unchanged: bool
) -> None:
    """Refuse a writeback that cannot produce a visible change.

    Deliberately independent of ``force``: ``edit-active`` always passes
    ``force=True`` to skip the source-hash check, and that must not also
    silence this one. Use ``allow_unchanged`` to override on purpose.
    """
    if allow_unchanged:
        return

    if new_bytes == current_bytes:
        raise UnchangedObjectError(
            f"the edited OLE is byte-identical to the one already in the presentation: {path}\n"
            "Nothing changed, so writing it back would have no visible effect.\n"
            "In Origin, edit the chart and press Save before closing the helper "
            "(the helper's own message is 'Save explicitly to commit').",
            is_near_identical=False,
            differing_bytes=0,
            total_bytes=len(new_bytes),
        )

    if len(new_bytes) != len(current_bytes):
        return

    differing = sum(1 for a, b in zip(new_bytes, current_bytes) if a != b)
    ratio = differing / len(new_bytes)
    if ratio < _NEAR_IDENTICAL_RATIO:
        raise UnchangedObjectError(
            f"the edited OLE differs from the current one in only {differing} of "
            f"{len(new_bytes)} bytes ({ratio:.4%}): {path}\n"
            "That looks like re-serialised metadata rather than a chart edit. "
            "This usually means the chart was not saved inside Origin before closing the helper "
            "(or the edit produced no data/graph change).\n"
            "Tip: In Origin, press Ctrl+S (or File -> Save) to commit your chart changes before "
            "clicking 'Save and Close' in the helper window.\n"
            "To force writing back this session anyway, pass --allow-unchanged.",
            is_near_identical=True,
            differing_bytes=differing,
            total_bytes=len(new_bytes),
        )


def _validate_preview(data: bytes, path: str | Path) -> str:
    """Validate preview bytes and return format ('png' or 'emf')."""
    if not data:
        raise SlideBridgeError(f"preview image is empty: {path}")
    if data.startswith(_PNG_SIGNATURE):
        if not _png_is_basic(data):
            raise SlideBridgeError(f"invalid PNG preview image: {path}")
        return "png"
    if len(data) >= 88:
        record_type = int.from_bytes(data[0:4], "little")
        signature = data[40:44]
        if record_type == 1 and signature == b" EMF":
            return "emf"
    raise SlideBridgeError(f"unsupported preview image format (must be PNG or EMF): {path}")


def _render_svg_preview(preview_svg: Path, session_path: Path) -> Path | None:
    """Render an SVG preview using resvg.

    A unique temporary output is used and the published preview is replaced
    only after the output has been read and validated, so a failed attempt
    cannot make a stale or partial image look successful.
    """
    renderer = find_executable("resvg", absolute_candidates=_RESVG_CANDIDATES)
    if not renderer:
        return None

    published_path = session_path / "preview_from_svg.png"
    temporary_path: Path | None = None
    try:
        fd, temporary_name = tempfile.mkstemp(
            prefix=".slidebridge-svg-", suffix=".png", dir=session_path
        )
        os.close(fd)
        temporary_path = Path(temporary_name)
        command = [
            renderer,
            str(preview_svg),
            str(temporary_path),
            "--dpi=300",
        ]
        completed = subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
        )
        if getattr(completed, "returncode", 0) != 0:
            return None
        rendered = temporary_path.read_bytes()
        if not _png_is_basic(rendered):
            return None
        os.replace(temporary_path, published_path)
        temporary_path = None
        return published_path
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                pass
    return None


# Note: png_white_to_transparent is imported from .core above for backward compatibility.


def _write_new_file(path: Path, data: bytes) -> None:
    # Exclusive creation also protects against a concurrent replacement after
    # the destination directory was created.
    with path.open("xb") as handle:
        handle.write(data)


def prepare_ole(
    input_path: os.PathLike[str] | str,
    member: os.PathLike[str] | str,
    output_dir: os.PathLike[str] | str,
) -> dict:
    """Copy one verified embedded OLE object into a new handoff directory.

    The source presentation is opened read-only and never rewritten.  The
    returned report has the same metadata written to ``manifest.json`` plus
    the absolute handoff directory path.
    """
    try:
        source_value = os.fspath(input_path)
        destination_value = os.fspath(output_dir)
    except TypeError as exc:
        raise SlideBridgeError("input and output paths must be strings or path-like objects") from exc
    if isinstance(source_value, bytes):
        source_value = os.fsdecode(source_value)
    if isinstance(destination_value, bytes):
        destination_value = os.fsdecode(destination_value)
    member_value = _member_string(member)
    source_path = os.path.abspath(source_value)
    destination = Path(os.path.abspath(destination_value))

    created = False
    completed = False
    archive: zipfile.ZipFile | None = None
    try:
        try:
            destination.mkdir(exist_ok=False)
        except FileExistsError as exc:
            raise SlideBridgeError(f"output directory already exists: {destination}") from exc
        except OSError as exc:
            raise SlideBridgeError(f"could not create output directory: {destination}") from exc
        created = True

        archive = _check_archive(source_path)
        names = {info.filename for info in archive.infolist() if not info.is_dir()}
        if member_value not in names:
            raise SlideBridgeError(f"OLE member is missing from the presentation: {member_value}")
        references = _find_references(archive, member_value)
        preview_members = _find_preview_members(archive, references)
        ole_data = archive.read(member_value)
        _validate_cfb(ole_data, member_value)
        source_hash = _source_sha256(source_path)
        ole_hash = _sha256(ole_data)
        manifest = {
            "schema_version": 1,
            "source": source_path,
            "source_sha256": source_hash,
            "member": member_value,
            "ole_sha256": ole_hash,
            "references": references,
            "preview_members": preview_members,
        }

        _write_new_file(destination / "original.bin", ole_data)
        _write_new_file(destination / "editable.bin", ole_data)
        manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        _write_new_file(destination / "manifest.json", manifest_bytes)
        report = dict(manifest)
        report["output_dir"] = str(destination)
        completed = True
        return report
    except SlideBridgeError:
        raise
    except (OSError, KeyError, RuntimeError, zipfile.BadZipFile) as exc:
        raise SlideBridgeError(f"could not prepare OLE member: {member_value}") from exc
    finally:
        if archive is not None:
            archive.close()
        if created and not completed and destination.exists():
            try:
                shutil.rmtree(destination)
            except OSError:
                # Preserve the original extraction error.  A cleanup failure
                # is still visible to the caller through the remaining path.
                pass


def writeback_ole(
    source_path: os.PathLike[str] | str,
    session_dir: os.PathLike[str] | str,
    output_path: os.PathLike[str] | str | None = None,
    ole_path: os.PathLike[str] | str | None = None,
    preview_path: os.PathLike[str] | str | None = None,
    force: bool = False,
    in_place: bool = False,
    allow_unchanged: bool = False,
) -> dict:
    """Pair-write an edited OLE binary and its updated preview back into a presentation.

    Enforces:
    1. Source presentation SHA-256 conflict detection against the session manifest (bypassable with force=True).
    2. Embedded OLE member SHA-256 integrity check.
    3. Valid CFB header for the new OLE binary.
    4. Strict paired writeback: a valid PNG or EMF preview image must be provided.
    5. Atomic publication: writes to a temporary file in the destination folder, never overwriting existing files (unless in_place=True).
    """
    source_value = _path_string(source_path)
    session_value = _path_string(session_dir)
    source_full = os.path.abspath(source_value)
    session_path = Path(os.path.abspath(session_value))

    if not session_path.is_dir():
        raise SlideBridgeError(f"session directory does not exist: {session_path}")

    manifest_file = session_path / "manifest.json"
    if not manifest_file.is_file():
        raise SlideBridgeError(f"manifest.json not found in session directory: {session_path}")

    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise SlideBridgeError(f"corrupt manifest.json: {manifest_file}") from exc

    required_keys = {"source_sha256", "member", "ole_sha256", "references"}
    if not required_keys.issubset(manifest.keys()):
        raise SlideBridgeError("manifest.json is missing required schema fields")

    # Output path setup
    if in_place:
        output_full = source_full
    elif output_path is None:
        p = Path(source_full)
        output_full = str(p.with_name(f"{p.stem}_writeback{p.suffix}"))
    else:
        output_full = os.path.abspath(_path_string(output_path))

    if not in_place:
        if os.path.realpath(source_full) == os.path.realpath(output_full):
            raise SlideBridgeError("source and output must be different paths")
        if os.path.exists(output_full):
            raise SlideBridgeError(f"output already exists: {output_full}")

    parent_dir = os.path.dirname(output_full) or os.curdir
    if not os.path.isdir(parent_dir):
        raise SlideBridgeError(f"output directory does not exist: {parent_dir}")

    # Conflict check 1: Source presentation hash
    current_source_hash = _source_sha256(source_full)
    if current_source_hash != manifest["source_sha256"] and not force:
        raise SlideBridgeError(
            f"source presentation has been modified since extraction: "
            f"expected {manifest['source_sha256']}, got {current_source_hash}. "
            "Use --force to proceed."
        )

    # Open archive to inspect member
    archive = _check_archive(source_full)
    temporary_output = None
    try:
        member = manifest["member"]
        infos = archive.infolist()
        all_names = {info.filename for info in infos if not info.is_dir()}
        if member not in all_names:
            raise SlideBridgeError(f"OLE member is missing from the presentation: {member}")

        # Conflict check 2: Target OLE member hash
        current_ole_data = archive.read(member)
        current_ole_hash = _sha256(current_ole_data)
        if current_ole_hash != manifest["ole_sha256"] and not force:
            raise SlideBridgeError(
                f"OLE member in presentation has been modified since extraction: "
                f"expected {manifest['ole_sha256']}, got {current_ole_hash}. "
                "Use --force to proceed."
            )

        # Locate edited OLE binary
        chosen_ole_path: Path | None = None
        if ole_path is not None:
            chosen_ole_path = Path(_path_string(ole_path))
            if not chosen_ole_path.is_file():
                raise SlideBridgeError(f"specified OLE binary not found: {chosen_ole_path}")
        else:
            candidates = ["reopen-verify.bin", "manual-edit.bin", "edited.bin", "editable.bin"]
            for cand in candidates:
                cand_p = session_path / cand
                if cand_p.is_file():
                    chosen_ole_path = cand_p
                    if cand != "editable.bin":
                        break
            if chosen_ole_path is None or not chosen_ole_path.is_file():
                raise SlideBridgeError(f"no edited OLE binary found in session: {session_path}")

        new_ole_bytes = chosen_ole_path.read_bytes()
        _validate_cfb(new_ole_bytes, str(chosen_ole_path))
        _reject_unchanged_ole(new_ole_bytes, current_ole_data, chosen_ole_path, allow_unchanged)

        # Locate preview image (ENFORCE PAIRED WRITEBACK)
        chosen_preview_path: Path | None = None
        is_transparent_svg = False
        if preview_path is not None:
            chosen_preview_path = Path(_path_string(preview_path))
            if not chosen_preview_path.is_file():
                raise SlideBridgeError(f"specified preview image not found: {chosen_preview_path}")
        else:
            # Check if Origin exported preview.svg and render high-res transparent PNG via resvg
            preview_svg = session_path / "preview.svg"
            if preview_svg.is_file():
                chosen_preview_path = _render_svg_preview(preview_svg, session_path)
                if chosen_preview_path is not None:
                    is_transparent_svg = True

            if chosen_preview_path is None:
                candidates = ["preview.png", "preview.emf", "edited.png", "edited.emf"]
                for cand in candidates:
                    cand_p = session_path / cand
                    if cand_p.is_file():
                        chosen_preview_path = cand_p
                        break
            if chosen_preview_path is None:
                raise SlideBridgeError(
                    "paired writeback requires a preview image for the modified OLE object. "
                    "None was provided or found in session."
                )

        new_preview_bytes = chosen_preview_path.read_bytes()
        preview_format = _validate_preview(new_preview_bytes, chosen_preview_path)
        if preview_format == "png" and not is_transparent_svg:
            new_preview_bytes = png_white_to_transparent(new_preview_bytes)

        # Resolve preview members in presentation
        preview_members = manifest.get("preview_members")
        if not preview_members:
            preview_members = _find_preview_members(archive, manifest["references"])
        if not preview_members:
            raise SlideBridgeError(f"could not find any preview images associated with OLE member: {member}")

        _reject_unchanged_preview(new_preview_bytes, archive, preview_members, allow_unchanged)

        updated_parts: dict[str, bytes] = {}
        new_members: dict[str, bytes] = {}
        changed_relationships: list[str] = []
        replacements: dict[str, str] = {}

        # 1. Update OLE binary
        updated_parts[member] = new_ole_bytes

        # 2. Update preview images
        for pm in preview_members:
            if pm not in all_names:
                continue
            pm_ext = posixpath.splitext(pm)[1].lower()
            if pm_ext == f".{preview_format}":
                updated_parts[pm] = new_preview_bytes
            elif pm_ext in {".emf", ".wmf"} and preview_format == "png":
                new_pm = f"{posixpath.splitext(pm)[0]}.png"
                new_members[new_pm] = new_preview_bytes
                replacements[pm] = new_pm
            elif pm_ext == ".png" and preview_format == "emf":
                new_pm = f"{posixpath.splitext(pm)[0]}.emf"
                new_members[new_pm] = new_preview_bytes
                replacements[pm] = new_pm

        # If relationships need updating (format switch)
        if replacements:
            for info in infos:
                if not info.filename.lower().endswith(".rels"):
                    continue
                relationships_xml = archive.read(info)
                try:
                    root = ElementTree.fromstring(relationships_xml)
                except ElementTree.ParseError as exc:
                    raise SlideBridgeError(f"invalid relationship XML: {info.filename}") from exc
                changed = False
                for element in root.iter():
                    if _local_name(element.tag) != "relationship":
                        continue
                    target = element.attrib.get("Target", "")
                    if element.attrib.get("TargetMode", "").lower() == "external":
                        continue
                    resolved = _resolve_target(info.filename, target)
                    if resolved in replacements:
                        element.attrib["Target"] = _replacement_target(info.filename, target, replacements[resolved])
                        changed = True
                if changed:
                    updated_parts[info.filename] = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
                    changed_relationships.append(info.filename)

            if preview_format == "png":
                content_types_name = "[Content_Types].xml"
                if content_types_name in all_names:
                    updated_parts[content_types_name] = _png_content_type(archive.read(content_types_name))

        # Write new presentation atomically
        fd, temporary_output = tempfile.mkstemp(prefix=".slidebridge-writeback-", suffix=".pptx", dir=parent_dir)
        os.close(fd)
        with zipfile.ZipFile(temporary_output, "w", compression=zipfile.ZIP_DEFLATED) as destination:
            for info in infos:
                payload = updated_parts.get(info.filename)
                if payload is None:
                    _copy_archive_member(archive, destination, info, prefer_raw=True)
                else:
                    destination.writestr(copy.copy(info), payload)
            for member_name, payload in new_members.items():
                destination.writestr(member_name, payload)

        archive.close()
        archive = None

        backup_path: str | None = None
        if in_place:
            p_src = Path(source_full)
            backup_p = p_src.with_name(f"{p_src.stem}.sb_backup{p_src.suffix}")
            shutil.copy2(source_full, backup_p)
            backup_path = str(backup_p)
            os.replace(temporary_output, output_full)
            temporary_output = None
        else:
            try:
                os.link(temporary_output, output_full)
            except FileExistsError as exc:
                raise SlideBridgeError(f"output already exists: {output_full}") from exc

            published_temp = temporary_output
            temporary_output = None
            try:
                os.unlink(published_temp)
            except OSError:
                pass

        report = {
            "source": source_full,
            "output": output_full,
            "member": member,
            "ole_sha256_before": manifest["ole_sha256"],
            "ole_sha256_after": _sha256(new_ole_bytes),
            "ole_source": str(chosen_ole_path),
            "preview_members": preview_members,
            "preview_format": preview_format,
            "preview_source": str(chosen_preview_path),
            "preview_sha256": _sha256(new_preview_bytes),
            "updated_relationships": changed_relationships,
            "status": "success",
        }
        if in_place:
            report["in_place"] = True
            report["backup"] = backup_path
        return report
    except SlideBridgeError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise SlideBridgeError(f"could not write presentation: {output_full}") from exc
    finally:
        if archive is not None:
            archive.close()
        if temporary_output is not None:
            try:
                os.unlink(temporary_output)
            except OSError:
                pass


def list_ole_objects(input_path: os.PathLike[str] | str) -> list[dict]:
    """Scan a presentation and return a list of all embedded OLE objects with slide & preview metadata."""
    source_value = _path_string(input_path)
    archive = _check_archive(source_value)
    try:
        infos = {
            info.filename: info
            for info in archive.infolist()
            if not info.is_dir()
        }
        ole_members = sorted(
            name
            for name in infos
            if name.startswith(_EMBEDDINGS_PREFIX) and name != _EMBEDDINGS_PREFIX
        )

        # A malformed slide or relationship part used to make every
        # per-member _find_references call fail.  Keep that behavior: no
        # object is returned from a package whose reference scan is invalid.
        try:
            references_by_member = _index_ole_references(archive)
        except SlideBridgeError:
            references_by_member = None

        results: list[dict] = []
        for member in ole_members:
            try:
                info = infos[member]
                with archive.open(info) as handle:
                    signature = handle.read(len(_CFB_SIGNATURE))
                if signature != _CFB_SIGNATURE:
                    continue
                if references_by_member is None:
                    continue
                references = references_by_member.get(member, [])
                if not references:
                    # Match _find_references' behavior for an unreferenced
                    # member without rescanning the archive.
                    continue
                previews = _find_preview_members(archive, references)
                slides = sorted({ref["slide"] for ref in references})
                results.append({
                    "member": member,
                    "slides": slides,
                    "previews": previews,
                    "references": references,
                    "bytes": info.file_size,
                })
            except SlideBridgeError:
                continue
        return results
    finally:
        archive.close()


def default_session_parent() -> Path:
    """Return a directory the Windows guest can reach under the user's home directory."""
    home = Path.home().resolve()
    project = Path(__file__).resolve().parent.parent
    cache_dir = project / ".cache" / "sessions"
    try:
        cache_dir.resolve().relative_to(home)
    except ValueError:
        cache_dir = home / "Library" / "Caches" / "SlideBridge" / "sessions"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def edit_presentation(
    input_path: os.PathLike[str] | str,
    member: str | None = None,
    output_path: os.PathLike[str] | str | None = None,
    in_place: bool = False,
    vm_name: str | None = None,
    vm_backend: str | None = None,
    session_dir: os.PathLike[str] | str | None = None,
    force: bool = False,
    allow_unchanged: bool = False,
    interactive: bool = False,
    on_status: typing.Callable[[str], None] | None = None,
) -> dict:
    """End-to-end presentation editing via the Windows Origin helper.

    Deep module that orchestrates:
    1. Scanning OLE objects in the presentation and selecting the target chart.
    2. Atomic session preparation in a guest-reachable location.
    3. Cross-VM invocation of the Windows Origin helper.
    4. Integrity checks of the edited binary and exported previews.
    5. Atomic paired writeback with conflict and unchanged data protection.
    """
    import datetime
    import sys
    import uuid

    source_path = Path(_path_string(input_path))
    if not source_path.is_file():
        raise SlideBridgeError(f"presentation file not found: {source_path}")

    ole_list = list_ole_objects(source_path)
    if not ole_list:
        raise SlideBridgeError(f"No embedded OLE objects found in presentation: {source_path}")

    selected_member = member
    if selected_member is None:
        if len(ole_list) == 1:
            selected_member = ole_list[0]["member"]
            if on_status:
                on_status(f"Found 1 Origin OLE object: {selected_member}")
        else:
            if interactive and sys.stdin.isatty():
                if on_status:
                    on_status(f"Found {len(ole_list)} Origin OLE objects in {source_path.name}:")
                    for idx, item in enumerate(ole_list, start=1):
                        slides_str = ", ".join(
                            s.replace("ppt/slides/", "").replace(".xml", "") for s in item["slides"]
                        )
                        previews_str = ", ".join(p.replace("ppt/media/", "") for p in item["previews"])
                        on_status(f"  [{idx}] {item['member']} (Slide {slides_str}, Preview: {previews_str})")

                choice = None
                try:
                    raw = input(f"Select object to edit [1-{len(ole_list)}] (default: 1): ").strip()
                    if raw:
                        choice = int(raw)
                except (ValueError, EOFError):
                    pass
                if not choice or choice < 1 or choice > len(ole_list):
                    choice = 1
                selected_member = ole_list[choice - 1]["member"]
                if on_status:
                    on_status(f"Selected: {selected_member}")
            else:
                selected_member = ole_list[0]["member"]
                if on_status:
                    on_status(f"Defaulting to first Origin OLE object: {selected_member}")

    if session_dir is not None:
        chosen_session = Path(_path_string(session_dir))
    else:
        unique_id = f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        chosen_session = default_session_parent() / f"slidebridge-edit-session-{unique_id}"

    if on_status:
        on_status(f"Preparing OLE session: {chosen_session}")
    prepare_ole(source_path, selected_member, chosen_session)

    from .vm import Guest, detect_guest, launch_vm_helper

    if vm_name:
        guest = Guest(vm_backend or "parallels", vm_name)
    else:
        guest = detect_guest(vm_backend)

    if on_status:
        on_status(f"Launching Windows Helper in {guest.backend} VM '{guest.name}'...")
        on_status("Please edit the chart in Origin, then click 'Save and Close' in the Helper window.")

    ret = launch_vm_helper(guest, chosen_session)
    if ret != 0 and on_status:
        on_status(f"Notice: Helper process exited with code {ret}.")

    edited_bin = chosen_session / "edited.bin"
    if not edited_bin.is_file():
        if ret == 0:
            if on_status:
                on_status("Notice: Edit was cancelled by user; presentation left unchanged.")
            return {
                "status": "cancelled",
                "source": str(source_path),
                "output": str(chosen_output),
                "member": selected_member,
                "vm": guest.name,
                "session": str(chosen_session),
                "message": "Edit was cancelled by user; presentation left unchanged.",
            }
        raise SlideBridgeError("No edited.bin found in session; edit was cancelled or failed.")

    if in_place:
        chosen_output = source_path
    elif output_path:
        chosen_output = Path(_path_string(output_path))
    else:
        counter = 1
        cand = source_path.with_name(f"{source_path.stem}_updated{source_path.suffix}")
        while cand.exists():
            cand = source_path.with_name(f"{source_path.stem}_updated_{counter}{source_path.suffix}")
            counter += 1
        chosen_output = cand

    if on_status:
        on_status("Detected saved OLE object. Writing back into presentation...")

    try:
        report = writeback_ole(
            source_path,
            chosen_session,
            output_path=chosen_output,
            force=force,
            in_place=in_place,
            allow_unchanged=allow_unchanged,
        )
        report["session"] = str(chosen_session)
        report["member"] = selected_member
        report["vm"] = guest.name
        return report
    except UnchangedObjectError as exc:
        if on_status:
            on_status("Notice: No chart changes detected; presentation left unchanged.")
        return {
            "status": "unchanged",
            "source": str(source_path),
            "output": str(chosen_output),
            "member": selected_member,
            "vm": guest.name,
            "session": str(chosen_session),
            "message": str(exc),
            "is_near_identical": exc.is_near_identical,
        }


__all__ = [
    "prepare_ole",
    "writeback_ole",
    "list_ole_objects",
    "default_session_parent",
    "edit_presentation",
    "UnchangedObjectError",
]
