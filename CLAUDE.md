# pymol-automtz — project instructions

A **PyMOL plugin that auto-opens MTZ files** (Coot "Auto Open MTZ" style): drop in
a `.mtz` → auto 2Fo-Fc + Fo-Fc maps at sensible σ, as new objects, with a Qt panel
to dial σ live and display modes for where density is drawn. Full spec in
`DESIGN.md`; deeper engineering notes in `docs/memory/`.

## Key facts
- **Target the Incentive PyMOL only:** `/Applications/PyMOL.app` (tested 3.1.6.1).
  Its bundled Python is `/Applications/PyMOL.app/Contents/bin/python`. The
  open-source build cannot do this — `load_mtz` raises `IncentiveOnlyException`.
- The heavy lifting already exists: `cmd.load_mtz(file, prefix=...)` parses the MTZ,
  auto-detects refmac/phenix/buster columns, FFT-synthesizes σ-normalized `.2fofc`
  and `.fofc` map objects (no CCP4 needed). The plugin adds auto-mesh + σ panel +
  display modes + menu on top of it.
- **Default contour levels:** 2Fo-Fc +1.5σ (blue); Fo-Fc +3.0σ green / −3.0σ red.

## Env quirks (worth knowing for further dev)
- Never name a PyMOL script `inspect.py` (shadows stdlib `inspect`).
- `pymol -cq -d "..."` eats `%` (variable substitution) — use `.format`/`{}` in
  prints, or run a pure-Python script file.
- A `.py` passed to `run` / as a script arg is `execfile`'d as pure Python, so the
  PyMOL `python` / `python end` block markers are invalid there — use a `.pml`.
- Headless map synthesis must run in the Incentive app's Python, not open-source.

## Test data
Any refmac/phenix `.mtz` (optionally with its `.pdb`). Load the model first so the
maps can carve around it. Test data is intentionally kept out of the repo
(see `.gitignore`).
