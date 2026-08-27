---
name: project-pymol-mtz-plugin
description: PyMOL plugin to auto-open MTZ (Coot-style 2Fo-Fc/Fo-Fc maps + live sigma dialing) — scope, decisions, gotchas
type: project
---

**Project:** `pymol-automtz`. Design doc: `DESIGN.md`; project instructions: `CLAUDE.md`.

**Goal:** a PyMOL plugin making electron density convenient like Coot "Auto Open MTZ": take a `.mtz` on the command line AND via GUI, auto-make 2Fo-Fc + Fo-Fc maps at sensible σ, display as new objects, and dial σ live.

**Decisions:**
- **Incentive build ONLY.** No CCP4/gemmi fallback for open-source PyMOL. Target `/Applications/PyMOL.app/Contents/bin/python`. See [[reference-pymol-installs-mtz]].
- **Default contour levels (Coot-style):** 2Fo-Fc `+1.5σ` (blue); Fo-Fc `+3.0σ` green / `−3.0σ` red. (Maps are σ-normalized so level == σ.)

**Architecture.** Heavy lifting (MTZ parse, refmac/phenix/buster column auto-detect, FFT synthesis, σ-normalization) is done by `cmd.load_mtz`. The plugin is a convenience layer:
1. `auto_mtz` command = `load_mtz` + auto `isomesh` (2fofc blue +1.5σ; fofc green +3σ / red −3σ) + group under `<prefix>`.
2. Qt panel with sliders/spinboxes → `cmd.isolevel(mesh, value)` for live re-contour.
3. `__init_plugin__(app)` menu registration + `.mtz` CLI/File→Open routing.

**Gotchas (keep in mind):**
- **Panel is PyQt5, NOT Tkinter.** The Incentive build's bundled Tkinter is dead on macOS — its `_tkinter.so` links against an absent X11 `libX11.6.dylib`, so `import tkinter` fails at load. Use `pymol.Qt` (PyQt5), which the app GUI runs on.
- **Keyboard σ shortcuts — the macOS saga (solved).** `cmd.set_key` and `QShortcut` never fire for the needed keys. Diagnosed with a logging event filter: (a) the GL viewport never takes keyboard focus (focus stays on the command line); (b) the OS never delivers the Option/Alt modifier; (c) Ctrl+arrows are eaten by Mission Control. The ONE modified-arrow delivered app-wide is **Command+arrow**, which Qt reports as **ControlModifier** (macOS swaps Ctrl↔Meta). **Fix: a `QApplication.installEventFilter` catching KeyPress with ControlModifier (± Shift), no Alt/Meta, and `return True`.** Bindings: **Cmd-Up/Down = 2Fo-Fc, Shift-Cmd-Up/Down = Fo-Fc**, ±0.1 σ; toggle `auto_mtz_keys on/off`. The panel's mouse-wheel-over-spinbox (0.02 σ) remains for fine tweaks. (PyMOL's `cmd.button` only maps to fixed built-in view actions, so no scroll-to-contour on the 3D view itself.)
- **Headless rendering:** `ray=0` (offscreen OpenGL) does NOT render isomesh — use `ray=1` for any headless frame containing mesh. The demo GIF composites the real panel by rendering `_SigmaPanel` offscreen (`QT_QPA_PLATFORM=offscreen`, fresh widget per state, `win.grab()`).
- **Headless driving quirks:** `pymol -cq -d "..."` eats `%` (variable substitution) — use `.format`/`{}` in prints, or a pure-Python script file. A `.py` passed to `run`/as a script arg is `execfile`'d as pure Python, so `python`/`python end` block markers are invalid there (use a `.pml`).

**Display modes:** the panel has 3 radios for where density draws — (1) **Sphere @ center of rotation** (DEFAULT, 15 Å, radius slider 2–40); (2) **Model** (carve); (3) **Unit cell** (whole map). The map `load_mtz` synthesizes spans one full unit cell (verified: mesh extent = cell a,b,c), so "whole map" = all symmetry copies, NOT one ASU. A true ASU wedge can't be clipped natively (needs gemmi/cctbx, which we keep out) — hence the honest "Unit cell" label. Sphere follows the pivot: PyMOL fires no view-change event, so a Qt poll timer (`_FOLLOW`, 40 ms) watches `get_view()[12:15]`. Default is **chase** (recontour continuously as the pivot moves); a panel checkbox toggles to **settle** (recontour only when the view stops) — `_FOLLOW['chase']`. Each isomesh rebuild ~0.2 s (main thread), so chase updates ~4–5×/s. The sphere itself = a throwaway pseudoatom `<prefix>.vc` at the view center + `isomesh(..., carve=R, buffer=R)` (PyMOL has no native sphere), deleted right after. Per-map σ steps: wheel/spin nudge 0.02 σ; levels persist in `_MTZ_SETS` so mode/radius rebuilds keep them.
