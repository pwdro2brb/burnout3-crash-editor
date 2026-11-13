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
        raise argparse.ArgumentTypeError('A porta precisa ser um número inteiro.') from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError('A porta precisa estar entre 1 e 65535.')
    return port


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description='Editor experimental do evento atual de Burnout 3 USA no PCSX2.')
    result.add_argument('--port', type=port_number, default=28011,
                        help='Porta local do PINE no PCSX2 (padrão: 28011).')
    result.add_argument('--journal-dir', type=Path,
                        default=REPOSITORY / 'outputs' / 'editor',
                        help='Pasta local para registros das operações.')
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
        print(f'Não foi possível abrir o editor: {exc}', file=sys.stderr)
        print('Use o pacote completo e Python 3.10 ou posterior com Tcl/Tk.', file=sys.stderr)
        return 2
    try:
        show_editor(EditorController(port=args.port, journal_dir=args.journal_dir))
    except OSError as exc:
        print(f'Não foi possível abrir o editor: {exc}', file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
