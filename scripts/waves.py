"""Command-line tool for Burnout 3 Crash traffic waves (USA SLUS-21050).

  python scripts/waves.py list   --game-root <extracted game>
  python scripts/waves.py show   "Grand Slam" --game-root <extracted game>
  python scripts/waves.py export "Grand Slam" grand-slam.waves.json --game-root <extracted game>
  python scripts/waves.py build  my-level.waves.json [more.waves.json ...] --game-root <extracted game>
                                 (--iso <original.iso> --out <new.iso> | --files-out <folder>)

A ``.waves.json`` file names its event (``"event": "1G0007EUC3V1"``) and lists
every wave, lane and vehicle. ``build`` applies one or more files (several
events may share a track file) and writes either a verified ISO copy or the
edited resource files. The game files and the source ISO are never modified.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import add_paths, resolve_paths  # noqa: E402
from resources.crash_events import bgd_path, load_crash_events  # noqa: E402
from resources.native_edit import export_resources  # noqa: E402
from resources.native_iso import export_iso  # noqa: E402
from resources.traffic_waves import (  # noqa: E402
    density_warning, describe, read_waves, vehicle_total, waves_from_dict, waves_to_dict, write_waves,
)


def find_event(events, name):
    wanted = name.strip().casefold()
    matches = [e for e in events if wanted in (e.key.casefold(), e.title.strip().casefold())]
    if len(matches) != 1:
        close = [e.title.strip() for e in events if wanted in e.title.casefold()]
        hint = f" Did you mean: {', '.join(close[:5])}?" if close else ""
        raise SystemExit(f"No single Crash event called {name!r}.{hint}")
    return matches[0]


def plan_build(game: Path, events, documents) -> dict:
    """Apply wave documents in memory. Returns relative path -> (original, edited)."""
    by_key = {e.key: e for e in events}
    tracks = {}
    seen = set()
    for source, data in documents:
        key = data.get("event") if isinstance(data, dict) else None
        if key not in by_key:
            raise SystemExit(f"{source}: the file must name a known event key (\"event\").")
        if key in seen:
            raise SystemExit(f"{source}: event {key} appears in more than one file.")
        seen.add(key)
        event = by_key[key]
        path = bgd_path(game, event.track)
        if path not in tracks:
            original = path.read_bytes()
            tracks[path] = [original, original]
        current = tracks[path][1]
        try:
            schedule = waves_from_dict(data, read_waves(current, event.event_offset))
            tracks[path][1] = write_waves(current, event.event_offset, schedule)
        except ValueError as error:
            raise SystemExit(f"{source}: {error}") from error
        baseline = vehicle_total(read_waves(tracks[path][0], event.event_offset))
        warning = density_warning(vehicle_total(schedule), baseline)
        if warning:
            print(f"WARNING ({event.title.strip()}): {warning}")
    return {p.relative_to(game).as_posix(): (old, new) for p, (old, new) in tracks.items() if old != new}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    add_paths(parser)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="List the 100 Crash events with their waves")
    show = sub.add_parser("show", help="Print the waves of one event")
    show.add_argument("event", help="Event title or key, e.g. 'Grand Slam' or 1G0007EUC3V1")
    export = sub.add_parser("export", help="Write the waves of one event to a JSON file")
    export.add_argument("event")
    export.add_argument("file", type=Path)
    build = sub.add_parser("build", help="Apply wave files and write an ISO copy or resource files")
    build.add_argument("files", type=Path, nargs="+")
    build.add_argument("--iso", type=Path, help="Original USA ISO that matches the extraction")
    build.add_argument("--out", type=Path, help="New ISO file to create")
    build.add_argument("--files-out", type=Path, help="Folder that receives a new subfolder with edited files")
    for command in (sub.choices.values()):
        # Accept the path options after the command too, without overriding earlier ones.
        command.add_argument("--config", type=Path, default=argparse.SUPPRESS, help=argparse.SUPPRESS)
        command.add_argument("--game-root", type=Path, default=argparse.SUPPRESS, help=argparse.SUPPRESS)
        command.add_argument("--output-root", type=Path, default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    game, _ = resolve_paths(parser, args)
    events = load_crash_events(game)
    if args.command == "list":
        tracks = {}
        for event in events:
            data = tracks.setdefault(event.track, bgd_path(game, event.track).read_bytes())
            schedule = read_waves(data, event.event_offset)
            starts = ", ".join(f"{w.start:g}" for w in schedule.waves)
            total = vehicle_total(schedule)
            flag = ""
            print(f"{event.key}  {event.track:<9} {event.title.strip():<20} waves at [{starts}] s"
                  f"  {total:>3} vehicles{flag}  ~{schedule.free_bytes // 32} free vehicle slots")
        return 0
    if args.command in ("show", "export"):
        event = find_event(events, args.event)
        schedule = read_waves(bgd_path(game, event.track).read_bytes(), event.event_offset)
        if args.command == "show":
            print(f"{event.title.strip()} ({event.key}, track {event.track})")
            print("\n".join(describe(schedule)))
            return 0
        if args.file.exists():
            raise SystemExit(f"Refusing to overwrite {args.file}")
        data = waves_to_dict(schedule, event_key=event.key)
        data["title"] = event.title.strip()
        args.file.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        print(f"Wrote {args.file}")
        return 0
    if bool(args.iso) != bool(args.out) or bool(args.out) == bool(args.files_out):
        parser.error("build needs either --iso and --out, or --files-out")
    documents = []
    for path in args.files:
        try:
            documents.append((path, json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError) as error:
            raise SystemExit(f"{path}: {error}") from error
    changes = plan_build(game, events, documents)
    if not changes:
        raise SystemExit("The wave files match the original game; nothing to write.")
    if args.out:
        report = export_iso(args.iso, args.out, changes)
        print(f"Wrote verified ISO {args.out}")
        if isinstance(report, dict) and report.get("sha256"):
            print(f"SHA-256 {report['sha256']}")
    else:
        first = next(e for e in events if e.key == documents[0][1]["event"])
        folder = export_resources(game, args.files_out, first, changes)
        print(f"Wrote edited files to {folder}")
    for rel in changes:
        print(f"  changed {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
