"""Command line entry point for SlideBridge."""
import argparse
import datetime
import json
from pathlib import Path
import shutil
import sys

from .core import SlideBridgeError, repair, scan
from .bridge import prepare_ole, writeback_ole, list_ole_objects
from .vm import detect_running_vm, launch_vm_helper


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
    writeback.add_argument("--in-place", action="store_true", help="Overwrite the input presentation in-place with backup")
    writeback.add_argument("--json", action="store_true")
    edit = commands.add_parser(
        "edit",
        help="Interactively select an Origin chart, edit in Parallels Windows VM, and auto-writeback",
    )
    edit.add_argument("input", type=Path, help="Target presentation to edit")
    edit.add_argument("-m", "--member", default=None, help="Specific OLE member (e.g. ppt/embeddings/oleObject1.bin)")
    edit.add_argument("-o", "--output", type=Path, default=None, help="Output presentation path (default: <name>_updated.pptx)")
    edit.add_argument("--in-place", action="store_true", help="Overwrite presentation in-place with backup")
    edit.add_argument("--vm", default=None, help="Parallels VM name (default: auto-detected running VM)")
    edit.add_argument("--session", type=Path, default=None, help="Custom session directory")
    edit.add_argument("--force", action="store_true", help="Bypass source presentation SHA-256 conflict check")
    edit.add_argument("--json", action="store_true")
    edit_active = commands.add_parser(
        "edit-active",
        help="Edit the chart currently selected in Mac PowerPoint in Windows VM and hot-reload",
    )
    edit_active.add_argument("--vm", default=None, help="Parallels VM name (default: auto-detected running VM)")
    edit_active.add_argument("--no-in-place", action="store_true", help="Do not overwrite in-place; write to <name>_updated.pptx")
    edit_active.add_argument("--no-reload", action="store_true", help="Do not reload PowerPoint after writeback")
    edit_active.add_argument("--session", type=Path, default=None, help="Custom session directory")
    edit_active.add_argument("--json", action="store_true")
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
                in_place=args.in_place,
            )
        elif args.command == "edit-active":
            from .powerpoint import edit_active_presentation
            report = edit_active_presentation(
                in_place=not args.no_in_place,
                vm_name=args.vm,
                reload_after=not args.no_reload,
                session_dir=args.session,
            )
        elif args.command == "edit":
            ole_list = list_ole_objects(args.input)
            if not ole_list:
                raise SlideBridgeError(f"No embedded OLE objects found in presentation: {args.input}")

            selected_member = args.member
            if selected_member is None:
                if len(ole_list) == 1:
                    selected_member = ole_list[0]["member"]
                    if not args.json:
                        print(f"Found 1 Origin OLE object: {selected_member}")
                else:
                    if not args.json:
                        print(f"Found {len(ole_list)} Origin OLE objects in {args.input.name}:")
                        for idx, item in enumerate(ole_list, start=1):
                            slides_str = ", ".join(s.replace("ppt/slides/", "").replace(".xml", "") for s in item["slides"])
                            previews_str = ", ".join(p.replace("ppt/media/", "") for p in item["previews"])
                            print(f"  [{idx}] {item['member']} (Slide {slides_str}, Preview: {previews_str})")

                    choice = None
                    if sys.stdin.isatty():
                        try:
                            raw = input(f"Select object to edit [1-{len(ole_list)}] (default: 1): ").strip()
                            if raw:
                                choice = int(raw)
                        except (ValueError, EOFError):
                            pass
                    if not choice or choice < 1 or choice > len(ole_list):
                        choice = 1
                    selected_member = ole_list[choice - 1]["member"]
                    if not args.json:
                        print(f"Selected: {selected_member}")

            if args.session:
                session_dir = args.session
            else:
                project_root = Path(__file__).resolve().parent.parent
                artifacts_dir = project_root / "artifacts"
                base_dir = artifacts_dir if artifacts_dir.is_dir() else Path.cwd()
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                session_dir = base_dir / f"ole-session-{timestamp}"

            if not args.json:
                print(f"Preparing OLE session: {session_dir}")
            prepare_ole(args.input, selected_member, session_dir)

            vm_name = args.vm or detect_running_vm()
            if not args.json:
                print(f"Launching Windows Helper in Parallels VM '{vm_name}'...")
                print("Please edit the chart in Origin, then click 'Save and Close' in the Helper window.")

            ret = launch_vm_helper(vm_name, session_dir)
            if ret != 0 and not args.json:
                print(f"Notice: Helper process exited with code {ret}.")

            edited_bin = session_dir / "edited.bin"
            if not edited_bin.is_file():
                raise SlideBridgeError("No edited.bin found in session; edit was cancelled or failed.")

            if args.in_place:
                output_path = args.input
            elif args.output:
                output_path = args.output
            else:
                counter = 1
                cand = args.input.with_name(f"{args.input.stem}_updated{args.input.suffix}")
                while cand.exists():
                    cand = args.input.with_name(f"{args.input.stem}_updated_{counter}{args.input.suffix}")
                    counter += 1
                output_path = cand

            if not args.json:
                print("Detected saved OLE object. Writing back into presentation...")

            report = writeback_ole(
                args.input,
                session_dir,
                output_path=output_path,
                force=args.force,
                in_place=args.in_place,
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
        return 0
    except (SlideBridgeError, OSError, ValueError) as exc:
        print(f"SlideBridge: {exc}", file=sys.stderr)
        return 1
