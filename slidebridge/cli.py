"""Command line entry point for SlideBridge."""
import argparse
import datetime
import json
from pathlib import Path
import sys

from .core import SlideBridgeError, repair, scan
from .bridge import prepare_ole, writeback_ole, list_ole_objects, edit_presentation
from .locate import ensure_login_path, find_executable

#: Install locations for resvg, tried when it is not on PATH. Needed because
#: GUI-launched runs (PowerPoint Services menu, double-clicked .app) do not
#: inherit Homebrew's PATH.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_RESVG_CANDIDATES = (
    str(_PROJECT_ROOT / "bin" / "resvg"),
    str(_PROJECT_ROOT / "artifacts" / "bin" / "resvg"),
    "/opt/homebrew/bin/resvg",
    "/usr/local/bin/resvg",
    "/opt/local/bin/resvg",
)


def find_resvg():
    return find_executable("resvg", absolute_candidates=_RESVG_CANDIDATES)


def find_svg_renderer():
    return find_resvg()


def main(argv=None):
    # A GUI-launched run inherits launchd's minimal PATH, which omits Homebrew
    # and /usr/local/bin. Recover the login PATH up front so every subprocess
    # below resolves the same tools a terminal would.
    ensure_login_path()

    parser = argparse.ArgumentParser(description="Repair PPTX graphics while preserving OLE data.")
    parser.add_argument("--version", action="version", version="SlideBridge 0.1.0")
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("scan", help="List EMF/WMF assets and OLE previews")
    inspect.add_argument("input", type=Path)
    inspect.add_argument("--json", action="store_true")
    doctor_cmd = commands.add_parser(
        "doctor", help="Check the Mac PowerPoint one-click flow prerequisites"
    )
    doctor_cmd.add_argument("--json", action="store_true")
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
    writeback.add_argument("--in-place", action="store_true", help="Overwrite the input presentation in-place with backup")
    writeback.add_argument(
        "--allow-unchanged",
        action="store_true",
        help="Write back even when the edited OLE is identical to the current one (no visible change)",
    )
    writeback.add_argument("--json", action="store_true")
    edit = commands.add_parser(
        "edit",
        help="Interactively select an Origin chart, edit in Parallels Windows VM, and auto-writeback",
    )
    edit.add_argument("input", type=Path, help="Target presentation to edit")
    edit.add_argument("-m", "--member", default=None, help="Specific OLE member (e.g. ppt/embeddings/oleObject1.bin)")
    edit.add_argument("-o", "--output", type=Path, default=None, help="Output presentation path (default: <name>_updated.pptx)")
    edit.add_argument("--in-place", action="store_true", help="Overwrite presentation in-place with backup")
    edit.add_argument("--vm", default=None, help="Guest VM name (default: auto-detected running VM)")
    edit.add_argument(
        "--vm-backend",
        default=None,
        choices=("parallels", "utm", "vmware", "virtualbox"),
        help="VM backend to drive (default: auto-detect)",
    )
    edit.add_argument("--session", type=Path, default=None, help="Custom session directory")
    edit.add_argument("--force", action="store_true", help="Bypass source presentation SHA-256 conflict check")
    edit.add_argument(
        "--allow-unchanged",
        action="store_true",
        help="Write back even if OLE or preview appears unchanged",
    )
    edit.add_argument("--json", action="store_true")
    edit_active = commands.add_parser(
        "edit-active",
        help="Edit the chart currently selected in Mac PowerPoint in Windows VM and hot-reload",
    )
    edit_active.add_argument("--vm", default=None, help="Guest VM name (default: auto-detected running VM)")
    edit_active.add_argument(
        "--vm-backend",
        default=None,
        choices=("parallels", "utm", "vmware", "virtualbox"),
        help="VM backend to drive (default: auto-detect)",
    )
    edit_active.add_argument("--no-in-place", action="store_true", help="Do not overwrite in-place; write to <name>_updated.pptx")
    edit_active.add_argument("--no-reload", action="store_true", help="Do not reload PowerPoint after writeback")
    edit_active.add_argument("--allow-unchanged", action="store_true", help="Write back even if OLE or preview appears unchanged")
    edit_active.add_argument("--session", type=Path, default=None, help="Custom session directory")
    edit_active.add_argument("--json", action="store_true")
    fix = commands.add_parser("fix", help="Write a repaired copy with PNG previews")
    fix.add_argument("input", type=Path)
    fix.add_argument("-o", "--output", type=Path)
    fix.add_argument("--dpi", type=int, default=300)
    fix.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=None,
        dest="concurrency",
        help="Number of concurrent conversion workers (default: min(cpu_count, 8))",
    )
    fix.add_argument("--renderer", default=None, help="Path to resvg executable (default: auto-detected resvg)")
    fix.add_argument("--transparent", dest="transparent", action="store_true", default=True, help="Force transparent background for chart boundaries (default: true)")
    fix.add_argument("--no-transparent", dest="transparent", action="store_false", help="Do not force transparent background")
    fix.add_argument("--json", action="store_true")
    fix.add_argument("--preview", action="append", default=[], metavar="MEMBER=PNG",
                     help="Use an exact Windows PNG export for a package EMF/WMF member; repeatable")
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            from .doctor import doctor as run_doctor
            return 0 if run_doctor(args.json)["ready"] else 1
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
                in_place=args.in_place,
                allow_unchanged=args.allow_unchanged,
            )
        elif args.command == "edit-active":
            from .powerpoint import edit_active_presentation
            report = edit_active_presentation(
                in_place=not args.no_in_place,
                vm_name=args.vm,
                reload_after=not args.no_reload,
                session_dir=args.session,
                vm_backend=args.vm_backend,
                allow_unchanged=args.allow_unchanged,
            )
        elif args.command == "edit":
            report = edit_presentation(
                args.input,
                member=args.member,
                output_path=args.output,
                in_place=args.in_place,
                vm_name=args.vm,
                vm_backend=args.vm_backend,
                session_dir=args.session,
                force=args.force,
                allow_unchanged=args.allow_unchanged,
                interactive=not args.json,
                on_status=None if args.json else print,
            )
        else:
            output = args.output or args.input.with_name(args.input.stem + "_fixed.pptx")
            previews = {}
            for value in args.preview:
                member, separator, filename = value.partition("=")
                if not separator or not member or not filename or member in previews:
                    raise ValueError("--preview requires a unique package MEMBER=PNG path")
                previews[member] = filename
            report = repair(
                args.input,
                output,
                renderer=args.renderer,
                transparent=args.transparent,
                dpi=args.dpi,
                reference_previews=previews,
                concurrency=args.concurrency,
            )
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "prepare-ole":
            print(f"OLE session: {args.output.resolve()}\nOriginal presentation unchanged.")
        elif args.command == "writeback-ole":
            print(f"Updated presentation: {report['output']}\nOLE member: {report['member']} (SHA-256: {report['ole_sha256_after'][:8]}...)\nPreview: {report['preview_source']} ({report['preview_format'].upper()})")
        elif args.command == "edit-active":
            print(f"✔ Active chart updated successfully: {report['presentation']}")
            print(f"  Slide: {report['slide_index']} (Shape: {report['shape_name']})")
            print(f"  OLE object: {report['member']}")
            if report.get("backup"):
                print(f"  Backup created: {report['backup']}")
            print(f"  Preview format: {report.get('preview_format', '').upper()}")
            print("  PowerPoint presentation reloaded.")
        elif args.command == "edit":
            print(f"✔ Presentation updated successfully: {report['output']}")
            print(f"  OLE object: {report['member']}")
            print(f"  Preview format: {report['preview_format'].upper()} ({report['preview_source']})")
        elif args.command == "scan":
            print(f"{report['source']}\nOLE objects: {report['ole_objects']}")
            for item in report['media']:
                label = "OLE preview" if item['ole_preview'] else "image"
                print(f"  {item['format'].upper():4} {item['path']} ({label})")
            print("Scan identifies candidate formats; it does not verify visual fidelity.")
        else:
            print(f"Saved: {output}\nConverted assets: {len(report['converted'])}")
            if report.get("skipped"):
                for item in report["skipped"]:
                    print(f"  [Notice] Skipped {item['path']}: {item['reason']}")
        return 0
    except (SlideBridgeError, OSError, ValueError) as exc:
        print(f"SlideBridge: {exc}", file=sys.stderr)
        return 1
