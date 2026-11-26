# Contributing

Thanks for helping! This project studies *Burnout 3: Takedown* to make new Crash events
possible. Research notes, bug reports, support for other game regions, editor features
and tests are all welcome.

## Ground rules

- **Never commit game data or derived dumps.** No ISO, ELF, BIOS, `.BGD`/`.BIN`/`.RWS`
  resources, save states (`.p2s`), memory cards, RAM dumps, screenshots of copyrighted
  assets, decompiled code or Ghidra exports. The `.gitignore` is an allowlist (only
  source code, Markdown and the example config are tracked); if you add a new kind of
  source file, extend the allowlist on purpose.
- Describe formats in your own words: offsets, field meanings, sizes and counts are
  fine; copied bytes or pseudocode from the executable are not.
- Keep the user's files safe. Tools must never modify the extracted game, the source ISO
  or existing save states; write new files and verify what you write.
- Say how sure you are. Separate what you observed (a byte dump, a savestate, a play
  test) from what you inferred. Unknown fields are preserved byte for byte, not named
  by guesswork. [docs/traffic-waves.md](docs/traffic-waves.md) shows the expected style.

## Development setup

- Python 3.10 or later; the code uses only the standard library (Tkinter for the GUI).
- Run the tests before sending a change:

  ```powershell
  python -B -m unittest discover -s scripts/editor -p "test_*.py"
  ```

- Tests must not need game files. Build small synthetic inputs instead, like
  `scripts/editor/test_traffic_waves.py` does for a track file.
- Keep user-facing text in English and error messages actionable ("what happened, what
  to do next").

## Reporting findings

Open an issue with:

1. the game region and version (for example USA `SLUS-21050`, CRC `BEBF8793`) and the
   emulator version;
2. what you did, step by step, and what you saw;
3. any evidence you can share without game data (offsets, counts, timings, a short
   description of a screenshot).

## Pull requests

- One topic per pull request, with a short description of the change and how it was
  tested (automated tests and, if relevant, what was checked in the game).
- Update the documentation when behaviour or formats change.
- By contributing you agree that your contribution is released under the
  [MIT License](LICENSE).
