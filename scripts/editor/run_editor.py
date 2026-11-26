"""Launch the current-event companion; importing this module opens nothing."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPOSITORY = Path(__file__).resolve().parents[2]


def port_number(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('The port must be a whole number.') from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError('The port must be between 1 and 65535.')
    return port


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description='Experimental editor for the current Burnout 3 USA event in PCSX2.')
    result.add_argument('--port', type=port_number, default=28011,
                        help="PCSX2's local PINE port (default: 28011).")
    result.add_argument('--journal-dir', type=Path,
                        default=REPOSITORY / 'outputs' / 'editor',
                        help='Local folder for operation logs.')
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    # Support both `python scripts/editor/run_editor.py` and package imports.
    scripts = str(Path(__file__).resolve().parents[1])
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    try:
        from editor.controller import EditorController
        from editor.gui import main as show_editor
    except ImportError as exc:
        print(f'Could not open the editor: {exc}', file=sys.stderr)
        print('Use the complete package and Python 3.10 or later with Tcl/Tk.', file=sys.stderr)
        return 2
    try:
        show_editor(EditorController(port=args.port, journal_dir=args.journal_dir))
    except OSError as exc:
        print(f'Could not open the editor: {exc}', file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
