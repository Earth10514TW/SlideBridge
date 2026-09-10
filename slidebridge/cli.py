"""Command line entry point for SlideBridge."""
import argparse
import json
from pathlib import Path
import shutil
import sys

from .core import SlideBridgeError, repair, scan


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
