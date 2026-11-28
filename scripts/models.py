"""Command-line tool to replace traffic models of a Crash event (USA SLUS-21050).

  python scripts/models.py show  "Grand Slam" --game-root <extracted game>
  python scripts/models.py build "Grand Slam" --swap COMPCAR12=COMPCAR18 [--swap OLD=NEW ...]
                                 --game-root <extracted game>
                                 (--iso <original.iso> --out <new.iso> | --files-out <folder>)

``show`` lists the event's model groups and, for each model, the models of the
same group used by other events. ``build`` replaces models (group record and
every wave vehicle that uses them) and writes a verified ISO copy or the edited
resource files. The game files and the source ISO are never modified.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import add_paths, resolve_paths  # noqa: E402
from editor.catalog import classify_model, encode_identifier  # noqa: E402
from resources.crash_events import bgd_path, load_crash_events  # noqa: E402
from resources.model_swap import GROUP_LABELS, candidates_for  # noqa: E402
from resources.native_edit import export_resources, prepare_changes  # noqa: E402
from resources.native_iso import export_iso  # noqa: E402
from resources.native_traffic import read_groups  # noqa: E402
from waves import find_event  # noqa: E402


def label(model: str) -> str:
    return classify_model(encode_identifier(model))["category_label"]


def parse_swaps(values) -> dict:
    swaps = {}
    for value in values or ():
        old, sep, new = value.partition("=")
        old, new = old.strip().upper(), new.strip().upper()
        if not sep or not old or not new:
            raise SystemExit(f"Use --swap OLD=NEW, not {value!r}.")
        if old in swaps:
            raise SystemExit(f"{old} is replaced twice.")
        swaps[old] = new
    return swaps


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    add_paths(parser)
    sub = parser.add_subparsers(dest="command", required=True)
    show = sub.add_parser("show", help="List an event's models and possible replacements")
    show.add_argument("event", help="Event title or key, e.g. 'Grand Slam' or 1G0007EUC3V1")
    build = sub.add_parser("build", help="Replace models and write an ISO copy or resource files")
    build.add_argument("event")
    build.add_argument("--swap", action="append", required=True, metavar="OLD=NEW")
    build.add_argument("--iso", type=Path, help="Original USA ISO that matches the extraction")
    build.add_argument("--out", type=Path, help="New ISO file to create")
    build.add_argument("--files-out", type=Path, help="Folder that receives a new subfolder with edited files")
    for command in sub.choices.values():
        command.add_argument("--config", type=Path, default=argparse.SUPPRESS, help=argparse.SUPPRESS)
        command.add_argument("--game-root", type=Path, default=argparse.SUPPRESS, help=argparse.SUPPRESS)
        command.add_argument("--output-root", type=Path, default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    game, _ = resolve_paths(parser, args)
    events = load_crash_events(game)
    event = find_event(events, args.event)
    groups = read_groups(bgd_path(game, event.track).read_bytes(), event.event_offset)
    if args.command == "show":
        print(f"{event.title.strip()} ({event.key}, track {event.track}) loads "
              f"{sum(len(g) for g in groups)} of at most 12 models")
        for index, names in enumerate(groups):
            print(f"  {GROUP_LABELS[index]}:")
            for name in names:
                options = ", ".join(f"{m} ({label(m)})" for m in candidates_for(groups, name)) or "none"
                print(f"    {name} ({label(name)}) -> can become: {options}")
        return 0
    if bool(args.iso) != bool(args.out) or bool(args.out) == bool(args.files_out):
        parser.error("build needs either --iso and --out, or --files-out")
    swaps = parse_swaps(args.swap)
    try:
        orders = tuple(tuple(swaps.get(n, n) for n in names) for names in groups)
        changes = prepare_changes(game, event, orders, expected_orders=groups, model_swaps=swaps)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    if args.out:
        report = export_iso(args.iso, args.out, changes)
        print(f"Wrote verified ISO {args.out}")
        if isinstance(report, dict) and report.get("sha256"):
            print(f"SHA-256 {report['sha256']}")
    else:
        folder = export_resources(game, args.files_out, event, changes)
        print(f"Wrote edited files to {folder}")
    for old, new in swaps.items():
        print(f"  {old} ({label(old)}) -> {new} ({label(new)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
