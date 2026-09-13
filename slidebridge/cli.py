"""Command line entry point for SlideBridge."""
import argparse
import datetime
import json
from pathlib import Path
import sys

from .core import SlideBridgeError, UnchangedObjectError, repair, scan
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


def _human_size(count: int) -> str:
    """Format a byte count for people who are deciding whether to free space."""
    size = float(count)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


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
    writeback.add_argument("--in-place", action="store_true", help="Overwrite the input presentation in-place (a restorable backup is kept in the app's private store)")
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
    edit.add_argument("--in-place", action="store_true", help="Overwrite presentation in-place (a restorable backup is kept in the app's private store)")
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
    backups = commands.add_parser(
        "backups",
        help="Inspect, restore, or discard the automatic in-place writeback backups",
    )
    backups_actions = backups.add_subparsers(dest="backups_action", required=True)
    backups_list = backups_actions.add_parser("list", help="List retained backups and how much space they use")
    backups_list.add_argument("input", type=Path, nargs="?", default=None,
                              help="Presentation to list backups for (omit to list every presentation)")
    backups_list.add_argument("--json", action="store_true")
    backups_restore = backups_actions.add_parser("restore", help="Put a backup back over the presentation")
    backups_restore.add_argument("input", type=Path, help="Presentation to restore")
    backups_restore.add_argument("--id", default=None,
                                 help="Backup id to restore, as shown by 'backups list' (default: newest)")
    backups_restore.add_argument("--json", action="store_true")
    backups_clear = backups_actions.add_parser("clear", help="Delete backups once you are happy with the result")
    backups_clear.add_argument("input", type=Path, nargs="?", default=None,
                               help="Presentation to clear backups for (omit to clear every backup)")
    backups_clear.add_argument("--json", action="store_true")
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
            try:
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
            except UnchangedObjectError as exc:
                report = {
                    "status": "unchanged",
                    "input": str(args.input),
                    "session": str(args.session),
                    "message": str(exc),
                    "is_near_identical": exc.is_near_identical,
                }
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
        elif args.command == "backups":
            from . import backup as backup_store
            if args.backups_action == "list":
                report = backup_store.list_backups(args.input)
            elif args.backups_action == "restore":
                report = backup_store.restore_backup(args.input, args.id)
            else:
                report = backup_store.clear_backups(args.input)
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
            if report.get("status") == "unchanged":
                print(f"ℹ️  [Notice] No changes detected; presentation not modified: {report.get('input', args.input)}")
                if report.get("is_near_identical"):
                    print("  The edited OLE has only metadata differences (<0.1%) and no chart data change.")
                    print("  Tip: In Origin, press Ctrl+S (or File -> Save) to commit your chart changes.")
                print("  To force writing back this session anyway, pass --allow-unchanged.")
            else:
                print(f"Updated presentation: {report['output']}\nOLE member: {report['member']} (SHA-256: {report['ole_sha256_after'][:8]}...)\nPreview: {report['preview_source']} ({report['preview_format'].upper()})")
        elif args.command == "edit-active":
            if report.get("status") == "cancelled":
                print(f"ℹ️  [Notice] Edit cancelled by user; presentation left unchanged: {report['presentation']}")
            elif report.get("status") == "unchanged":
                print(f"ℹ️  [Notice] No chart changes detected; presentation left unchanged: {report['presentation']}")
                print(f"  Slide: {report['slide_index']} (Shape: {report['shape_name']})")
                print(f"  OLE object: {report['member']}")
                if report.get("is_near_identical"):
                    print("  The chart was not saved inside Origin before closing the helper (or produced no data/graph change).")
                    print("  Tip: In Origin, press Ctrl+S (or File -> Save) to commit your chart changes before clicking 'Save and Close'.")
                print("  To force writing back this session anyway, pass --allow-unchanged.")
            else:
                print(f"✔ Active chart updated successfully: {report['presentation']}")
                print(f"  Slide: {report['slide_index']} (Shape: {report['shape_name']})")
                print(f"  OLE object: {report['member']}")
                if report.get("backup"):
                    days = report.get("backup_retention_days")
                    suffix = f" (kept {days} days)" if days else ""
                    print(f"  Backup kept: {Path(report['backup']).name}{suffix} — restore it from the app, or run 'backups restore'")
                print(f"  Preview format: {report.get('preview_format', '').upper()}")
                print("  PowerPoint presentation reloaded.")
        elif args.command == "edit":
            if report.get("status") == "cancelled":
                print(f"ℹ️  [Notice] Edit cancelled by user; presentation left unchanged: {report.get('source', args.input)}")
            elif report.get("status") == "unchanged":
                print(f"ℹ️  [Notice] No chart changes detected; presentation left unchanged: {report.get('source', args.input)}")
                print(f"  OLE object: {report['member']}")
                if report.get("is_near_identical"):
                    print("  The chart was not saved inside Origin before closing the helper (or produced no data/graph change).")
                    print("  Tip: In Origin, press Ctrl+S (or File -> Save) to commit your chart changes before clicking 'Save and Close'.")
                print("  To force writing back this session anyway, pass --allow-unchanged.")
            else:
                print(f"✔ Presentation updated successfully: {report['output']}")
                print(f"  OLE object: {report['member']}")
                print(f"  Preview format: {report['preview_format'].upper()} ({report['preview_source']})")
        elif args.command == "backups":
            if args.backups_action == "list":
                entries = report["backups"]
                scope = report["presentation"] or "all presentations"
                if not entries:
                    print(f"No backups retained for {scope}.")
                else:
                    print(f"Backups for {scope} (kept {report['retention_days']} days, "
                          f"at most {report['max_per_presentation']} per presentation):")
                    for entry in entries:
                        print(f"  {entry['created']}  {_human_size(entry['bytes']):>9}  {entry['id']}")
                    print(f"  Total: {report['count']} backup(s), {_human_size(report['total_bytes'])}")
                print("  Backups live in the app's private store, not next to your presentation.")
            elif args.backups_action == "restore":
                if report.get("status") == "unchanged":
                    print(f"ℹ️  [Notice] Presentation already matches that backup; nothing restored: {report['presentation']}")
                else:
                    print(f"✔ Restored {report['restored']['id']} over {report['presentation']}")
                    previous = report.get("previous_backup")
                    if previous:
                        print(f"  The version you just replaced was kept as {previous['id']}, so this is undoable.")
            else:
                print(f"Cleared {report['removed_count']} backup(s), freeing {_human_size(report['removed_bytes'])}.")
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


if __name__ == "__main__":
    sys.exit(main())
