"""Command line entry point for SlideBridge."""
import argparse
import json
from pathlib import Path
import shutil
import sys

from .core import SlideBridgeError, repair, scan
from .bridge import prepare_ole, writeback_ole


def find_inkscape():
    executable = shutil.which("inkscape")
    if executable:
        return executable
    mac = Path("/Applications/Inkscape.app/Contents/MacOS/inkscape")
    return str(mac) if mac.is_file() else "inkscape"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Repair PPTX graphics while preserving OLE data.")
    parser.add_argument("--version", action="version", version="SlideBridge 0.1.0")
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("scan", help="List EMF/WMF assets and OLE previews")
    inspect.add_argument("input", type=Path)
    inspect.add_argument("--json", action="store_true")
    bridge = commands.add_parser("prepare-ole", help="Extract an embedded OLE copy for the Windows Origin helper")
    bridge.add_argument("input", type=Path)
    bridge.add_argument("--member", required=True, help="Exact ppt/embeddings member to extract")
    bridge.add_argument("-o", "--output", type=Path, required=True, help="New session directory")
    bridge.add_argument("--json", action="store_true")
    writeback = commands.add_parser(
        "writeback-ole",
        help="Pair-write an edited OLE binary and updated preview back into a presentation",
    )
    writeback.add_argument("input", type=Path, help="Target presentation to update")
    writeback.add_argument("--session", type=Path, required=True, help="Session directory containing manifest.json")
    writeback.add_argument("-o", "--output", type=Path, default=None, help="Output presentation path")
    writeback.add_argument("--ole", type=Path, default=None, help="Path to edited OLE binary")
    writeback.add_argument("--preview", type=Path, default=None, help="Path to updated preview image (PNG/EMF)")
    writeback.add_argument("--force", action="store_true", help="Bypass source presentation SHA-256 conflict check")
    writeback.add_argument("--json", action="store_true")
    fix = commands.add_parser("fix", help="Write a repaired copy with PNG previews")
    fix.add_argument("input", type=Path)
    fix.add_argument("-o", "--output", type=Path)
    fix.add_argument("--dpi", type=int, default=300)
    fix.add_argument("--inkscape", default=None, help="Path to Inkscape executable")
    fix.add_argument("--json", action="store_true")
    fix.add_argument("--preview", action="append", default=[], metavar="MEMBER=PNG",
                     help="Use an exact Windows PNG export for a package EMF/WMF member; repeatable")
    args = parser.parse_args(argv)
    try:
        if args.command == "scan":
            report = scan(args.input)
        elif args.command == "prepare-ole":
            report = prepare_ole(args.input, args.member, args.output)
        elif args.command == "writeback-ole":
            report = writeback_ole(
                args.input,
                args.session,
                output_path=args.output,
                ole_path=args.ole,
                preview_path=args.preview,
                force=args.force,
            )
        else:
            output = args.output or args.input.with_name(args.input.stem + "_fixed.pptx")
            previews = {}
            for value in args.preview:
                member, separator, filename = value.partition("=")
                if not separator or not member or not filename or member in previews:
                    raise ValueError("--preview requires a unique package MEMBER=PNG path")
                previews[member] = filename
            report = repair(args.input, output, inkscape=args.inkscape or find_inkscape(),
                            dpi=args.dpi, reference_previews=previews)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "prepare-ole":
            print(f"OLE session: {args.output.resolve()}\nOriginal presentation unchanged.")
        elif args.command == "writeback-ole":
            print(f"Updated presentation: {report['output']}\nOLE member: {report['member']} (SHA-256: {report['ole_sha256_after'][:8]}...)\nPreview: {report['preview_source']} ({report['preview_format'].upper()})")
        elif args.command == "scan":
            print(f"{report['source']}\nOLE objects: {report['ole_objects']}")
            for item in report['media']:
                label = "OLE preview" if item['ole_preview'] else "image"
                print(f"  {item['format'].upper():4} {item['path']} ({label})")
            print("Scan identifies candidate formats; it does not verify visual fidelity.")
        else:
            print(f"Saved: {output}\nConverted assets: {len(report['converted'])}")
        return 0
    except (SlideBridgeError, OSError, ValueError) as exc:
        print(f"SlideBridge: {exc}", file=sys.stderr)
        return 1
