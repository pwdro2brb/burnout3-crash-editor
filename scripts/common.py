"""Path and output guards shared by the standalone research scripts."""
import argparse
import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

def add_paths(parser):
    parser.add_argument('--config', type=Path, help='Optional local JSON configuration')
    parser.add_argument('--game-root', type=Path, help='Extracted game directory; or B3_GAME_ROOT')
    parser.add_argument('--output-root', type=Path, help='Generated output directory; or B3_OUTPUT_ROOT')

def resolve_paths(parser, args, *, require_game=True):
    config = {}
    if args.config:
        try:
            config = json.loads(args.config.read_text(encoding='utf-8'))
            if not isinstance(config, dict): raise ValueError('configuration must be a JSON object')
        except (OSError, ValueError) as error:
            parser.error(str(error))
    raw_game = args.game_root or os.environ.get('B3_GAME_ROOT') or config.get('game_root')
    if require_game and not raw_game:
        parser.error('Provide --game-root, B3_GAME_ROOT, or game_root in a local config')
    game = Path(raw_game).expanduser().resolve() if raw_game else None
    if game is not None and not game.is_dir():
        parser.error('Game root is not an existing directory')
    raw_out = args.output_root or os.environ.get('B3_OUTPUT_ROOT') or config.get('output_root') or REPO/'outputs'
    output = Path(raw_out).expanduser().resolve()
    if game is not None and (output.is_relative_to(game) or game.is_relative_to(output)):
        parser.error('Game and output directories must be separate, non-overlapping trees')
    return game, output

def prepare_outputs(output, names):
    for name in names:
        target = (output/name).resolve()
        if not target.is_relative_to(output): raise ValueError('Output escapes the selected output root')
        if target.exists(): raise FileExistsError('Refusing to overwrite existing report: '+str(target))
    output.mkdir(parents=True,exist_ok=True)
