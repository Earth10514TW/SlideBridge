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
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from .core import (
    SlideBridgeError,
    _CT_NS,
    _PNG_SIGNATURE,
    _SLIDE_RE,
    _check_archive,
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
)


_CFB_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_CFB_MIN_SIZE = 512
_OLE_RELATIONSHIP_NAME = "oleobject"
_EMBEDDINGS_PREFIX = "ppt/embeddings/"


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


def _find_references(archive: zipfile.ZipFile, member: str) -> list[dict[str, str]]:
    names = {info.filename for info in archive.infolist() if not info.is_dir()}
    references: list[dict[str, str]] = []
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
                and resolved == member
                and _is_ole_relationship(rel_type)
            ):
                references.append({"slide": slide, "relationship_id": relationship_id})
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

        target_ole = None
        for element in root.iter():
            if _local_name(element.tag) in {"oleobj", "oleobject"}:
                for attr, val in element.attrib.items():
                    if val == ole_rid and attr.rsplit("}", 1)[-1].lower() in {"id", "embed", "link"}:
                        target_ole = element
                        break
                if target_ole is not None:
                    break

        if target_ole is None:
            continue

        preview_rids: set[str] = set()
        for child in target_ole.iter():
            if child is target_ole:
                continue
            for attr, val in child.attrib.items():
                if attr.rsplit("}", 1)[-1].lower() in {"id", "embed", "link"} and val != ole_rid:
                    preview_rids.add(val)

        spid = None
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
) -> dict:
    """Pair-write an edited OLE binary and its updated preview back into a presentation.

    Enforces:
    1. Source presentation SHA-256 conflict detection against the session manifest (bypassable with force=True).
    2. Embedded OLE member SHA-256 integrity check.
    3. Valid CFB header for the new OLE binary.
    4. Strict paired writeback: a valid PNG or EMF preview image must be provided.
    5. Atomic publication: writes to a temporary file in the destination folder, never overwriting existing files.
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
    if output_path is None:
        p = Path(source_full)
        output_full = str(p.with_name(f"{p.stem}_writeback{p.suffix}"))
    else:
        output_full = os.path.abspath(_path_string(output_path))

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

        # Locate preview image (ENFORCE PAIRED WRITEBACK)
        chosen_preview_path: Path | None = None
        if preview_path is not None:
            chosen_preview_path = Path(_path_string(preview_path))
            if not chosen_preview_path.is_file():
                raise SlideBridgeError(f"specified preview image not found: {chosen_preview_path}")
        else:
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

        # Resolve preview members in presentation
        preview_members = manifest.get("preview_members")
        if not preview_members:
            preview_members = _find_preview_members(archive, manifest["references"])
        if not preview_members:
            raise SlideBridgeError(f"could not find any preview images associated with OLE member: {member}")

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
                    payload = archive.read(info)
                destination.writestr(copy.copy(info), payload)
            for member_name, payload in new_members.items():
                destination.writestr(member_name, payload)

        archive.close()
        archive = None

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

        return {
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


__all__ = ["prepare_ole", "writeback_ole"]
