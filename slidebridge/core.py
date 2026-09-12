"""Scan and repair a narrow class of PowerPoint package problems.

The implementation deliberately works on the ZIP package directly.  It does
not unpack a presentation, invoke a shell, or inspect targets outside the
package.  Repair keeps the source media and appends PNG replacements, updating
only package relationships which point at an EMF or WMF member.
"""

from __future__ import annotations

import concurrent.futures
import copy
import math
import os
import posixpath
import re
import shutil
import struct
import subprocess
import tempfile
import urllib.parse
import zipfile
import zlib
from collections import deque
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree

from .locate import find_executable
from .svg_cleaner import optimize_emf_svg


class SlideBridgeError(Exception):
    """Base exception raised for unreadable or unrepairable presentations."""


class ScanError(SlideBridgeError):
    """Raised when a presentation cannot be safely scanned."""


class RepairError(SlideBridgeError):
    """Raised when a presentation cannot be safely repaired."""


_MAX_UNCOMPRESSED = 512 * 1024 * 1024
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_REL_NS_STRICT = "http://purl.oclc.org/ooxml/officeDocument/relationships"
_CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_SLIDE_RE = re.compile(r"^ppt/slides/slide[^/]*\.xml$", re.IGNORECASE)


def _path_string(path: os.PathLike[str] | str) -> str:
    try:
        value = os.fspath(path)
    except TypeError as exc:
        raise SlideBridgeError("path must be a string or path-like object") from exc
    if isinstance(value, bytes):
        return os.fsdecode(value)
    return value


def _check_archive(path: str) -> zipfile.ZipFile:
    """Open *path* after applying package-size, duplicate, and encryption checks."""
    try:
        archive = zipfile.ZipFile(path, "r")
    except (OSError, zipfile.BadZipFile, ValueError) as exc:
        raise ScanError(f"invalid ZIP presentation: {path}") from exc

    try:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise ScanError("presentation contains duplicate ZIP members")
        total = 0
        for info in infos:
            if info.flag_bits & 0x1:
                raise ScanError("encrypted ZIP presentations are not supported")
            if info.file_size < 0:
                raise ScanError("presentation contains an invalid ZIP member size")
            total += info.file_size
            if total > _MAX_UNCOMPRESSED:
                raise ScanError("presentation exceeds the 512 MiB uncompressed limit")
        # Check CRCs while the archive is still closed over the source path.
        bad = archive.testzip()
        if bad is not None:
            raise ScanError(f"ZIP member failed CRC validation: {bad}")
        return archive
    except Exception:
        archive.close()
        raise


def _copy_archive_member(
    archive: zipfile.ZipFile, destination: zipfile.ZipFile, info: zipfile.ZipInfo
) -> None:
    """Copy an unchanged member with bounded memory, retaining its metadata."""
    # ZipFile.open mutates the output ZipInfo as it writes; keep the source
    # record intact so subsequent reads still use its original CRC and sizes.
    with archive.open(info) as source, destination.open(copy.copy(info), "w") as target:
        shutil.copyfileobj(source, target, length=1024 * 1024)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _relationship_part_for(source_part: str) -> str:
    directory, filename = posixpath.split(source_part)
    return posixpath.join(directory, "_rels", filename + ".rels")


def _source_part_for_relationships(rels_part: str) -> str | None:
    marker = "/_rels/"
    if marker not in rels_part or not rels_part.lower().endswith(".rels"):
        return None
    directory, filename = rels_part.rsplit(marker, 1)
    if not filename:
        return None
    source_name = filename[:-5]
    return posixpath.join(directory, source_name) if directory else source_name


def _resolve_target(rels_part: str, target: str) -> str | None:
    """Resolve an OOXML internal relationship target to a safe ZIP member."""
    if not target or "\\" in target:
        return None
    source_part = _source_part_for_relationships(rels_part)
    if source_part is None:
        return None
    # Query strings/fragments are not package member names.  External targets
    # are filtered by TargetMode before this function is called.
    target = urllib.parse.unquote(target)
    if "#" in target or "?" in target:
        return None
    if target.startswith("/"):
        member = posixpath.normpath(target[1:])
    else:
        member = posixpath.normpath(posixpath.join(posixpath.dirname(source_part), target))
    if not member or member == "." or member.startswith("../") or member.startswith("/"):
        return None
    return member


def _read_relationships(xml_bytes: bytes, rels_part: str) -> list[tuple[str, str, str | None, str]]:
    """Return (id, target, resolved-target, type) tuples from a .rels part."""
    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError as exc:
        raise ScanError(f"invalid relationship XML: {rels_part}") from exc
    relationships = []
    for element in root.iter():
        if _local_name(element.tag) != "relationship":
            continue
        rid = element.attrib.get("Id", "")
        target = element.attrib.get("Target", "")
        mode = element.attrib.get("TargetMode", "").lower()
        resolved = None if mode == "external" else _resolve_target(rels_part, target)
        relationships.append((rid, target, resolved, element.attrib.get("Type", "")))
    return relationships


def _slide_relationship_refs(slide_xml: bytes) -> set[str]:
    try:
        root = ElementTree.fromstring(slide_xml)
    except ElementTree.ParseError as exc:
        raise ScanError("invalid slide XML") from exc
    refs: set[str] = set()
    relationship_namespaces = {_REL_NS, _REL_NS_STRICT}

    def add_relationship_attributes(element: ElementTree.Element) -> None:
        for attribute, value in element.attrib.items():
            if not value:
                continue
            if attribute.startswith("{"):
                namespace, _, local = attribute[1:].partition("}")
                if namespace in relationship_namespaces and local in {"id", "embed", "link"}:
                    refs.add(value)
            # A few producers use an unqualified r:id in otherwise malformed
            # slides.  It is still safe to use it only for identifying a
            # package-local preview relationship.
            elif attribute.lower() in {"r:id", "r:embed", "r:link"}:
                refs.add(value)

    # The relationship on an ordinary picture is not an OLE preview.  Limit
    # the normal r:id/r:embed/r:link scan to each OLE object's complete
    # subtree; this also covers AlternateContent fallback branches.
    ole_spids: set[str] = set()
    for element in root.iter():
        if _local_name(element.tag) not in {"oleobj", "oleobject"}:
            continue
        add_relationship_attributes(element)
        for attribute, value in element.attrib.items():
            if attribute.rsplit("}", 1)[-1].lower() in {"spid", "shapeid", "id"}:
                ole_spids.add(value)
        for descendant in element.iter():
            add_relationship_attributes(descendant)

    # Legacy VML previews can sit beside the OLE element.  If the OLE spid
    # identifies the containing VML shape, its imagedata relationship is a
    # preview as well.  Scanning imagedata without a matching spid would mark
    # unrelated VML images, so those are intentionally left alone.
    if ole_spids:
        parents = {child: parent for parent in root.iter() for child in parent}
        for element in root.iter():
            if _local_name(element.tag) != "imagedata":
                continue
            shape = element
            while shape is not None:
                if any(value in ole_spids for attribute, value in shape.attrib.items() if attribute.rsplit("}", 1)[-1].lower() in {"id", "spid"}):
                    add_relationship_attributes(element)
                    break
                shape = parents.get(shape)
    return refs


def _slide_ole_ids(slide_xml: bytes) -> set[str]:
    """Return relationship IDs on OLE elements, deduplicated per slide."""
    try:
        root = ElementTree.fromstring(slide_xml)
    except ElementTree.ParseError as exc:
        raise ScanError("invalid slide XML") from exc
    ids: set[str] = set()
    for element in root.iter():
        if _local_name(element.tag) not in {"oleobj", "oleobject"}:
            continue
        for attribute, value in element.attrib.items():
            local = attribute.rsplit("}", 1)[-1].lower()
            if value and local == "id":
                ids.add(value)
    return ids


def _slide_ole_spids(slide_xml: bytes) -> set[str]:
    """Return shape IDs advertised by OLE elements in a slide."""
    try:
        root = ElementTree.fromstring(slide_xml)
    except ElementTree.ParseError as exc:
        raise ScanError("invalid slide XML") from exc
    spids: set[str] = set()
    for element in root.iter():
        if _local_name(element.tag) not in {"oleobj", "oleobject"}:
            continue
        for attribute, value in element.attrib.items():
            if value and attribute.rsplit("}", 1)[-1].lower() in {"spid", "shapeid"}:
                spids.add(value)
    return spids


def _shape_id_matches(shape_id: str, ole_spids: set[str]) -> bool:
    """Match the common ``123`` and ``_x0000_s123`` VML spellings."""
    if shape_id in ole_spids:
        return True
    normalized = shape_id.lower().replace("_x0000_s", "")
    return any(normalized == value.lower().replace("_x0000_s", "") for value in ole_spids)


def _vml_preview_targets(
    archive: zipfile.ZipFile,
    vml_part: str,
    ole_spids: set[str],
) -> set[str]:
    """Resolve VML imagedata relationships belonging to OLE shapes."""
    if not ole_spids:
        return set()
    try:
        root = ElementTree.fromstring(archive.read(vml_part))
    except KeyError:
        return set()
    except ElementTree.ParseError as exc:
        raise ScanError(f"invalid VML drawing XML: {vml_part}") from exc
    rels_part = _relationship_part_for(vml_part)
    try:
        relationships = _read_relationships(archive.read(rels_part), rels_part)
    except KeyError:
        return set()
    by_id = {rid: resolved for rid, _target, resolved, _type in relationships if resolved is not None}
    targets: set[str] = set()
    for shape in root.iter():
        if _local_name(shape.tag) != "shape":
            continue
        shape_ids = {
            value
            for attribute, value in shape.attrib.items()
            if value and attribute.rsplit("}", 1)[-1].lower() in {"id", "spid"}
        }
        if not any(_shape_id_matches(value, ole_spids) for value in shape_ids):
            continue
        for element in shape.iter():
            if _local_name(element.tag) != "imagedata":
                continue
            for attribute, rid in element.attrib.items():
                local = attribute.rsplit("}", 1)[-1].lower()
                if local not in {"relid", "id", "embed", "link"}:
                    continue
                target = by_id.get(rid)
                if target and posixpath.splitext(target)[1].lower() in {".emf", ".wmf"}:
                    targets.add(target)
    return targets


def _inspect(path: str) -> tuple[dict, zipfile.ZipFile, list[zipfile.ZipInfo]]:
    archive = _check_archive(path)
    try:
        infos = archive.infolist()
        names = {info.filename for info in infos}
        if "[Content_Types].xml" not in names or "ppt/presentation.xml" not in names:
            raise ScanError("ZIP is not a PPTX package (required package parts are missing)")
        media_infos = [
            info
            for info in infos
            if not info.is_dir() and posixpath.splitext(info.filename)[1].lower() in {".emf", ".wmf"}
        ]

        preview_targets: set[str] = set()
        ole_relationship_targets: set[str] = set()
        logical_ole_objects: set[tuple[str, str]] = set()
        for info in infos:
            if _SLIDE_RE.match(info.filename):
                ids = _slide_ole_ids(archive.read(info))
                logical_ole_objects.update((info.filename, rid) for rid in ids)
        for info in infos:
            if not info.filename.lower().endswith(".rels"):
                continue
            relationships = _read_relationships(archive.read(info), info.filename)
            source_part = _source_part_for_relationships(info.filename)
            slide_refs: set[str] = set()
            slide_spids: set[str] = set()
            if source_part and _SLIDE_RE.match(source_part):
                slide_xml = archive.read(source_part)
                slide_refs = _slide_relationship_refs(slide_xml)
                slide_spids = _slide_ole_spids(slide_xml)
            for rid, _target, resolved, relationship_type in relationships:
                if resolved is None:
                    continue
                if "oleobject" in relationship_type.lower():
                    ole_relationship_targets.add(resolved)
                if not source_part or not _SLIDE_RE.match(source_part):
                    continue
                if "vmldrawing" in relationship_type.lower() or resolved.lower().endswith(".vml"):
                    preview_targets.update(_vml_preview_targets(archive, resolved, slide_spids))
                if resolved not in {item.filename for item in media_infos}:
                    continue
                if rid in slide_refs:
                    preview_targets.add(resolved)

        embedding_names = {
            info.filename
            for info in infos
            if not info.is_dir()
            and info.filename.lower().startswith("ppt/embeddings/oleobject")
        }
        # A producer may repeat the same OLE element in AlternateContent
        # branches.  Count the logical reference once per slide and ID.
        # Package embeddings remain a useful fallback for packages that omit
        # slide XML relationships altogether.
        ole_objects = len(logical_ole_objects) or len(embedding_names | ole_relationship_targets)
        report = {
            "source": path,
            "media": [
                {
                    "path": info.filename,
                    "format": posixpath.splitext(info.filename)[1][1:].lower(),
                    "bytes": info.file_size,
                    "ole_preview": info.filename in preview_targets,
                }
                for info in media_infos
            ],
            "ole_objects": ole_objects,
        }
        return report, archive, infos
    except Exception:
        archive.close()
        raise


def scan(path: os.PathLike[str] | str) -> dict:
    """Scan a PPTX ZIP and return EMF/WMF media and OLE counts.

    ``path`` must identify an unencrypted, non-duplicated ZIP whose declared
    uncompressed contents total at most 512 MiB.  :class:`SlideBridgeError`
    (or a subclass) is raised when those safety checks or XML parsing fail.
    """
    source = _path_string(path)
    report, archive, _infos = _inspect(source)
    archive.close()
    return report


def _png_is_basic(data: bytes) -> bool:
    if len(data) < 24 or not data.startswith(_PNG_SIGNATURE):
        return False
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    return width > 0 and height > 0


def _unique_png_name(source_name: str, existing: set[str]) -> str:
    directory, filename = posixpath.split(source_name)
    stem = posixpath.splitext(filename)[0]
    candidate = posixpath.join(directory, stem + ".png")
    index = 1
    while candidate in existing:
        candidate = posixpath.join(directory, f"{stem}-{index}.png")
        index += 1
    return candidate


def _replacement_target(rels_part: str, old_target: str, new_member: str) -> str:
    if old_target.startswith("/"):
        return "/" + new_member
    source_part = _source_part_for_relationships(rels_part) or ""
    relative = posixpath.relpath(new_member, posixpath.dirname(source_part) or ".")
    return relative


def _png_content_type(content_types: bytes) -> bytes:
    try:
        root = ElementTree.fromstring(content_types)
    except ElementTree.ParseError as exc:
        raise RepairError("invalid [Content_Types].xml") from exc
    found = False
    for element in root.iter():
        if _local_name(element.tag) == "default" and element.attrib.get("Extension", "").lower() == "png":
            found = True
            break
    if not found:
        namespace = root.tag[1:].split("}", 1)[0] if root.tag.startswith("{") else _CT_NS
        ElementTree.SubElement(root, f"{{{namespace}}}Default", {"Extension": "png", "ContentType": "image/png"})
    return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)


_RESVG_CANDIDATES = (
    "/opt/homebrew/bin/resvg",
    "/usr/local/bin/resvg",
    "/opt/local/bin/resvg",
)


def png_white_to_transparent(data: bytes, tolerance: int = 10) -> bytes:
    """Convert white border background of a PNG image to transparent alpha (RGBA).

    Uses flood fill starting from the four outer image boundaries to make exterior
    margins transparent while preserving axes, text, plot curves, and enclosed
    white elements (e.g. data points or text labels).
    Uses only Python standard library (struct, zlib). Returns unmodified bytes
    on any unsupported format or decompression failure.
    """
    if not data.startswith(_PNG_SIGNATURE):
        return data
    try:
        pos = 8
        chunks = []
        width = height = bit_depth = color_type = None
        idat_data = bytearray()

        while pos < len(data):
            if pos + 8 > len(data):
                return data
            length = struct.unpack(">I", data[pos : pos + 4])[0]
            ctype = data[pos + 4 : pos + 8]
            cdata = data[pos + 8 : pos + 8 + length]
            pos += 12 + length

            if ctype == b"IHDR":
                width, height, bit_depth, color_type = struct.unpack(">IIBB", cdata[:10])
                if bit_depth != 8 or color_type not in (2, 6):
                    return data
            elif ctype == b"IDAT":
                idat_data.extend(cdata)
            elif ctype == b"IEND":
                break
            else:
                chunks.append((ctype, cdata))

        if not idat_data or not width or not height:
            return data

        raw = zlib.decompress(bytes(idat_data))
        bpp = 3 if color_type == 2 else 4
        stride = width * bpp
        reconstructed = bytearray(height * stride)

        src_pos = 0
        for y in range(height):
            if src_pos >= len(raw):
                return data
            filter_type = raw[src_pos]
            src_pos += 1
            if src_pos + stride > len(raw):
                return data
            line = bytearray(raw[src_pos : src_pos + stride])
            src_pos += stride
            prior = reconstructed[(y - 1) * stride : y * stride] if y > 0 else None

            if filter_type == 1:
                for x in range(bpp, stride):
                    line[x] = (line[x] + line[x - bpp]) & 0xFF
            elif filter_type == 2:
                if prior:
                    for x in range(stride):
                        line[x] = (line[x] + prior[x]) & 0xFF
            elif filter_type == 3:
                for x in range(stride):
                    left = line[x - bpp] if x >= bpp else 0
                    up = prior[x] if prior else 0
                    line[x] = (line[x] + ((left + up) >> 1)) & 0xFF
            elif filter_type == 4:
                for x in range(stride):
                    a = line[x - bpp] if x >= bpp else 0
                    b = prior[x] if prior else 0
                    c = prior[x - bpp] if (prior and x >= bpp) else 0
                    p = a + b - c
                    pa = abs(p - a)
                    pb = abs(p - b)
                    pc = abs(p - c)
                    pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                    line[x] = (line[x] + pr) & 0xFF
            reconstructed[y * stride : (y + 1) * stride] = line

        threshold = 255 - tolerance
        n_pixels = width * height
        is_bg = bytearray(n_pixels)

        if bpp == 3:
            for i in range(n_pixels):
                off = i * 3
                if reconstructed[off] >= threshold and reconstructed[off + 1] >= threshold and reconstructed[off + 2] >= threshold:
                    is_bg[i] = 1
        else:
            for i in range(n_pixels):
                off = i * 4
                if reconstructed[off + 3] == 0 or (reconstructed[off] >= threshold and reconstructed[off + 1] >= threshold and reconstructed[off + 2] >= threshold):
                    is_bg[i] = 1

        mask = bytearray(n_pixels)
        queue = deque()

        for x in range(width):
            if is_bg[x]:
                mask[x] = 1
                queue.append(x)
            bottom_idx = (height - 1) * width + x
            if is_bg[bottom_idx] and not mask[bottom_idx]:
                mask[bottom_idx] = 1
                queue.append(bottom_idx)

        for y in range(height):
            left_idx = y * width
            if is_bg[left_idx] and not mask[left_idx]:
                mask[left_idx] = 1
                queue.append(left_idx)
            right_idx = y * width + (width - 1)
            if is_bg[right_idx] and not mask[right_idx]:
                mask[right_idx] = 1
                queue.append(right_idx)

        while queue:
            curr = queue.popleft()
            cx = curr % width
            cy = curr // width

            if cx > 0:
                n = curr - 1
                if is_bg[n] and not mask[n]:
                    mask[n] = 1
                    queue.append(n)
            if cx + 1 < width:
                n = curr + 1
                if is_bg[n] and not mask[n]:
                    mask[n] = 1
                    queue.append(n)
            if cy > 0:
                n = curr - width
                if is_bg[n] and not mask[n]:
                    mask[n] = 1
                    queue.append(n)
            if cy + 1 < height:
                n = curr + width
                if is_bg[n] and not mask[n]:
                    mask[n] = 1
                    queue.append(n)

        new_raw = bytearray((width * 4 + 1) * height)
        dest_pos = 0
        pixel_idx = 0

        for y in range(height):
            new_raw[dest_pos] = 0
            dest_pos += 1
            for x in range(width):
                if mask[pixel_idx]:
                    new_raw[dest_pos : dest_pos + 4] = b"\xff\xff\xff\x00"
                else:
                    src_off = pixel_idx * bpp
                    new_raw[dest_pos] = reconstructed[src_off]
                    new_raw[dest_pos + 1] = reconstructed[src_off + 1]
                    new_raw[dest_pos + 2] = reconstructed[src_off + 2]
                    new_raw[dest_pos + 3] = reconstructed[src_off + 3] if bpp == 4 else 255
                dest_pos += 4
                pixel_idx += 1

        new_idat = zlib.compress(bytes(new_raw), 6)
        out = bytearray(b"\x89PNG\r\n\x1a\n")
        ihdr_payload = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
        out.extend(struct.pack(">I", len(ihdr_payload)))
        out.extend(b"IHDR")
        out.extend(ihdr_payload)
        out.extend(struct.pack(">I", zlib.crc32(b"IHDR" + ihdr_payload)))

        for ctype, cdata in chunks:
            if ctype in (b"sRGB", b"gAMA", b"pHYs"):
                out.extend(struct.pack(">I", len(cdata)))
                out.extend(ctype)
                out.extend(cdata)
                out.extend(struct.pack(">I", zlib.crc32(ctype + cdata)))

        out.extend(struct.pack(">I", len(new_idat)))
        out.extend(b"IDAT")
        out.extend(new_idat)
        out.extend(struct.pack(">I", zlib.crc32(b"IDAT" + new_idat)))

        out.extend(struct.pack(">I", 0))
        out.extend(b"IEND")
        out.extend(struct.pack(">I", zlib.crc32(b"IEND")))
        return bytes(out)
    except Exception:
        return data


def _convert_single_item(
    idx: int,
    source_name: str,
    output_name: str,
    raw_bytes: bytes,
    temporary_dir: str,
    dpi: int | float,
    project_dir: str,
    renderer: str | None = None,
    transparent: bool = True,
) -> tuple[str, str, bytes, dict]:
    suffix = posixpath.splitext(source_name)[1].lower() or ".emf"
    if suffix != ".emf":
        raise RepairError(
            f"unsupported format for conversion: {source_name}. Only EMF is supported."
        )
    item_dir = os.path.join(temporary_dir, f"media_{idx}")
    os.makedirs(item_dir, exist_ok=True)
    source_temp = os.path.join(item_dir, "source" + suffix)
    output_temp = os.path.join(item_dir, "rendered.png")

    try:
        with open(source_temp, "wb") as handle:
            handle.write(raw_bytes)

        # libemf2svg avoids native EMF importer crashes on some macOS builds.
        # Keep this intermediate private; only the rendered PNG enters PPTX.
        local_bin = (
            shutil.which(os.path.join(project_dir, "bin", "emf2svg-conv"))
            or shutil.which(os.path.join(project_dir, "artifacts", "bin", "emf2svg-conv"))
        )
        emf_converter = local_bin or shutil.which("emf2svg-conv")
        if not emf_converter:
            raise RepairError(f"emf2svg-conv not found to convert {source_name}")

        scale_width = False
        scale_height = False
        svg_temp = os.path.join(item_dir, "intermediate.svg")
        try:
            result = subprocess.run(
                [emf_converter, "-i", source_temp, "-o", svg_temp],
                capture_output=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RepairError(f"EMF to SVG conversion failed for {source_name}") from exc
        if result.returncode != 0 or not os.path.isfile(svg_temp):
            raise RepairError(f"EMF to SVG conversion failed for {source_name}")

        raw_svg = Path(svg_temp).read_text(encoding="utf-8", errors="replace")
        try:
            cleaned_svg = optimize_emf_svg(raw_svg)
            Path(svg_temp).write_text(cleaned_svg, encoding="utf-8")
            svg_content = cleaned_svg
        except Exception:
            svg_content = raw_svg

        try:
            # Direct in-memory parsing avoids redundant disk re-reads
            svg_root = ElementTree.fromstring(svg_content)
            bounds = [float(x) for x in svg_root.get("viewBox", "").replace(",", " ").split()]
            if len(bounds) != 4:
                bounds = [0, 0, float(svg_root.get("width", "0")), float(svg_root.get("height", "0"))]
            if len(bounds) == 4 and bounds[2] > 0 and bounds[3] > 0:
                longest = max(bounds[2:]) * dpi / 96
                if longest > 4096:
                    if bounds[2] >= bounds[3]:
                        scale_width = True
                    else:
                        scale_height = True
        except (ElementTree.ParseError, ValueError) as exc:
            raise RepairError(f"Invalid intermediate SVG for {source_name}") from exc

        # Determine renderer: resvg is the only supported renderer
        if renderer:
            active_renderer = renderer
        else:
            resvg_bin = shutil.which("resvg")
            if not resvg_bin:
                for candidate in _RESVG_CANDIDATES:
                    resvg_bin = shutil.which(candidate)
                    if resvg_bin:
                        break
            active_renderer = resvg_bin

        if not active_renderer:
            raise RepairError(
                "resvg executable not found. Please install it with 'brew install resvg' or specify --renderer."
            )

        cmd = [
            active_renderer,
            svg_temp,
            output_temp,
            "--dpi",
            str(int(round(dpi))),
        ]
        if scale_width:
            cmd.extend(["--width", "4096"])
        elif scale_height:
            cmd.extend(["--height", "4096"])

        try:
            completed = subprocess.run(
                cmd,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RepairError(f"failed to convert {source_name} with resvg") from exc

        if completed.returncode != 0 or not os.path.isfile(output_temp):
            stderr = completed.stderr or ""
            detail = (
                stderr.decode("utf-8", "replace")
                if isinstance(stderr, bytes)
                else str(stderr)
            ).strip()
            suffix_detail = f": {detail[:300]}" if detail else ""
            raise RepairError(f"failed to convert {source_name} with resvg{suffix_detail}")

        try:
            with open(output_temp, "rb") as handle:
                png = handle.read()
        except OSError as exc:
            raise RepairError(f"failed to read rendered PNG for {source_name}") from exc

        if not _png_is_basic(png):
            raise RepairError(f"resvg produced an invalid PNG for {source_name}")

        if transparent:
            png = png_white_to_transparent(png)

        return (
            source_name,
            output_name,
            png,
            {"source": source_name, "path": output_name, "bytes": len(png), "method": "rendered", "engine": "resvg"},
        )
    finally:
        # Immediate cleanup of temporary intermediate files
        shutil.rmtree(item_dir, ignore_errors=True)


def _convert_media(
    archive: zipfile.ZipFile,
    media_infos: Iterable[zipfile.ZipInfo],
    existing_names: set[str],
    dpi: int | float,
    temporary_dir: str,
    reference_previews: dict[str, bytes],
    concurrency: int | None = None,
    renderer: str | None = None,
    transparent: bool = True,
) -> tuple[dict[str, str], dict[str, bytes], list[dict], list[dict]]:
    replacements: dict[str, str] = {}
    generated: dict[str, bytes] = {}
    converted: list[dict] = []
    skipped: list[dict] = []
    allocated = set(existing_names)

    items_to_render: list[tuple[int, str, str, zipfile.ZipInfo]] = []
    project_dir = os.path.dirname(os.path.dirname(__file__))

    for idx, info in enumerate(media_infos):
        source_name = info.filename
        if source_name in reference_previews:
            output_name = _unique_png_name(source_name, allocated)
            allocated.add(output_name)
            png = reference_previews[source_name]
            replacements[source_name] = output_name
            generated[output_name] = png
            converted.append({"source": source_name, "path": output_name,
                              "bytes": len(png), "method": "reference-png"})
            continue

        ext = posixpath.splitext(source_name)[1].lower()
        if ext != ".emf":
            skipped.append({
                "path": source_name,
                "reason": f"unsupported {ext.upper().lstrip('.')} format (legacy 16-bit metafile is not auto-converted; supply --preview to replace)",
            })
            continue

        output_name = _unique_png_name(source_name, allocated)
        allocated.add(output_name)
        items_to_render.append((idx, source_name, output_name, info))

    if not items_to_render:
        return replacements, generated, converted, skipped

    max_workers = concurrency if concurrency is not None else min(os.cpu_count() or 4, 8)

    if len(items_to_render) == 1 or max_workers <= 1:
        for idx, src, out, info in items_to_render:
            source_name, output_name, png, entry = _convert_single_item(
                idx,
                src,
                out,
                archive.read(info),
                temporary_dir,
                dpi,
                project_dir,
                renderer=renderer,
                transparent=transparent,
            )
            replacements[source_name] = output_name
            generated[output_name] = png
            converted.append(entry)
    else:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(max_workers, len(items_to_render))
        ) as executor:
            # Keep raw metafiles bounded by the worker count. Read ZIP data
            # on this thread only; workers own conversion and temporary files.
            remaining = iter(items_to_render)
            pending = {}
            results = {}

            def submit_next() -> None:
                item = next(remaining, None)
                if item is None:
                    return
                idx, src, out, info = item
                future = executor.submit(
                    _convert_single_item, idx, src, out, archive.read(info),
                    temporary_dir, dpi, project_dir, renderer, transparent,
                )
                pending[future] = idx

            try:
                for _ in range(min(max_workers, len(items_to_render))):
                    submit_next()
                while pending:
                    done, _ = concurrent.futures.wait(
                        pending, return_when=concurrent.futures.FIRST_COMPLETED,
                    )
                    for future in done:
                        results[pending.pop(future)] = future.result()
                    for _ in done:
                        submit_next()
            except Exception:
                for future in pending:
                    future.cancel()
                raise

            # Completion order must not change the report or ZIP member order.
            for idx in sorted(results):
                source_name, output_name, png, entry = results[idx]
                replacements[source_name] = output_name
                generated[output_name] = png
                converted.append(entry)

    return replacements, generated, converted, skipped


def repair(
    source: os.PathLike[str] | str,
    output: os.PathLike[str] | str,
    renderer: str | None = None,
    dpi: int | float = 300,
    reference_previews: dict[str, os.PathLike[str] | str] | None = None,
    concurrency: int | None = None,
    transparent: bool = True,
) -> dict:
    """Convert package EMF media to PNG and write a new PPTX atomically.

    The source and output must be different, and output must not already
    exist. EMF members are converted with resvg; relationship
    targets are updated to collision-safe PNG members while original media,
    OLE binaries, and unrelated ZIP member payloads are retained. A failed
    conversion or invalid output leaves no output file behind.
    ``reference_previews`` maps exact EMF/WMF package paths to trusted PNG
    exports, which are embedded byte-for-byte without resizing or rendering.
    """
    source_path = _path_string(source)
    output_path = _path_string(output)
    source_real = os.path.realpath(source_path)
    output_real = os.path.realpath(output_path)
    if source_real == output_real:
        raise RepairError("source and output must be different paths")
    if os.path.exists(output_path):
        raise RepairError(f"output already exists: {output_path}")
    if (
        not isinstance(dpi, (int, float))
        or isinstance(dpi, bool)
        or not math.isfinite(dpi)
        or dpi <= 0
        or dpi > 2400
    ):
        raise RepairError("dpi must be a positive finite number no greater than 2400")
    parent = os.path.dirname(os.path.abspath(output_path)) or os.curdir
    if not os.path.isdir(parent):
        raise RepairError(f"output directory does not exist: {parent}")

    report, archive, infos = _inspect(source_path)
    media_infos = [
        info
        for info in infos
        if not info.is_dir() and posixpath.splitext(info.filename)[1].lower() in {".emf", ".wmf"}
    ]
    all_names = {info.filename for info in infos}
    temporary_output: str | None = None
    try:
        reference_bytes: dict[str, bytes] = {}
        candidates = {info.filename for info in media_infos}
        for member, reference in (reference_previews or {}).items():
            if member not in candidates:
                raise RepairError(f"Reference target is not an EMF/WMF member: {member}")
            reference_path = Path(reference)
            if reference_path.stat().st_size > 64 * 1024 * 1024:
                raise RepairError(f"Reference PNG exceeds 64 MiB: {reference_path}")
            png = reference_path.read_bytes()
            if not _png_is_basic(png):
                raise RepairError(f"Invalid reference PNG: {reference_path}")
            reference_bytes[member] = png
        with tempfile.TemporaryDirectory(prefix="slidebridge-", dir=parent) as temporary_dir:
            replacements, generated, converted, skipped = _convert_media(
                archive,
                media_infos,
                all_names,
                dpi,
                temporary_dir,
                reference_bytes,
                concurrency=concurrency,
                renderer=renderer,
                transparent=transparent,
            )
            changed_relationships: list[str] = []
            updated_parts: dict[str, bytes] = {}
            for info in infos:
                if not info.filename.lower().endswith(".rels"):
                    continue
                relationships_xml = archive.read(info)
                try:
                    root = ElementTree.fromstring(relationships_xml)
                except ElementTree.ParseError as exc:
                    archive.close()
                    raise RepairError(f"invalid relationship XML: {info.filename}") from exc
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

            content_types_name = "[Content_Types].xml"
            if content_types_name in all_names:
                updated_parts[content_types_name] = _png_content_type(archive.read(content_types_name))
            else:
                root = ElementTree.Element(f"{{{_CT_NS}}}Types")
                ElementTree.SubElement(root, f"{{{_CT_NS}}}Default", {"Extension": "png", "ContentType": "image/png"})
                updated_parts[content_types_name] = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)

            fd, temporary_output = tempfile.mkstemp(prefix=".slidebridge-", suffix=".pptx", dir=parent)
            os.close(fd)
            with zipfile.ZipFile(temporary_output, "w", compression=zipfile.ZIP_DEFLATED) as destination:
                for info in infos:
                    payload = updated_parts.get(info.filename)
                    if payload is None:
                        _copy_archive_member(archive, destination, info)
                    else:
                        destination.writestr(copy.copy(info), payload)
                for member_name, payload in generated.items():
                    destination.writestr(member_name, payload)
            archive.close()
            # A hard link makes publication atomic and cannot overwrite a
            # concurrently-created destination.  Both files are in parent.
            try:
                os.link(temporary_output, output_path)
            except FileExistsError as exc:
                raise RepairError(f"output already exists: {output_path}") from exc
            # The link is the publication point.  From here on, cleanup must
            # not turn a successful repair into a reported failure or cause
            # the finally block to touch the published file.
            published_temp = temporary_output
            temporary_output = None
            try:
                os.unlink(published_temp)
            except OSError:
                pass
            result = {
                "source": source_path,
                "output": output_path,
                "converted": converted,
                "updated_relationships": changed_relationships,
            }
            if skipped:
                result["skipped"] = skipped
            return result
    except SlideBridgeError:
        if not archive.fp is None:
            archive.close()
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        if not archive.fp is None:
            archive.close()
        raise RepairError(f"could not write repaired presentation: {output_path}") from exc
    finally:
        if temporary_output is not None:
            try:
                os.unlink(temporary_output)
            except FileNotFoundError:
                pass


__all__ = ["SlideBridgeError", "ScanError", "RepairError", "scan", "repair"]
