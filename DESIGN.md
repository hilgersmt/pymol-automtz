# pymol-automtz — design

Make electron density in PyMOL as convenient as Coot's "Auto Open MTZ": drop in a
`.mtz`, get 2Fo-Fc + Fo-Fc maps auto-contoured at sensible σ as new objects, with
a panel to dial σ live and choose where density is drawn.

## Scope decisions
- **Incentive PyMOL only.** Target `/Applications/PyMOL.app` (tested 3.1.6.1,
  bundled Python 3.10 at `/Applications/PyMOL.app/Contents/bin/python`). No
  CCP4/gemmi fallback for the open-source build (its `load_mtz` raises
  `IncentiveOnlyException`).
- **Default contour levels (Coot-style):**
  - 2Fo-Fc: **+1.5 σ**, blue
  - Fo-Fc:  **+3.0 σ** green (positive) / **−3.0 σ** red (negative)
  - Maps are σ-normalized by `load_mtz`, so contour level == σ directly.

## What already exists (do NOT reimplement)
`cmd.load_mtz(filename, prefix=...)` in the Incentive build already:
- reads the MTZ header, auto-guesses columns for refmac / phenix / phenix_no_fill /
  buster via the `default_refmac_names` (`FWT PHWT DELFWT PHDELWT`),
  `default_phenix_names` / `default_buster_names` (`2FOFCWT PH2FOFCWT FOFCWT PHFOFCWT`)
  settings;
- synthesizes maps with PyMOL's built-in cctbx FFT (`cmd.map_generate`) — no CCP4;
- creates two σ-normalized map objects: `<prefix>.2fofc` and `<prefix>.fofc`.

**The gap vs Coot:** `load_mtz` makes the map *objects* but draws no mesh, and there
is no σ slider. That gap is this plugin.

## Components
1. **`auto_mtz` command** (`cmd.extend`) — calls `load_mtz`, then builds `isomesh`
   objects: `<prefix>.2fofc.mesh` (blue +1.5), `<prefix>.fofc.mesh_pos` (green +3.0),
   `<prefix>.fofc.mesh_neg` (red −3.0), grouped under `<prefix>`.
2. **Sigma / display panel** (PyQt5 via `pymol.Qt` — the Incentive GUI is Qt; the
   bundled Tkinter is unusable on macOS). Per-map slider + spinbox + visibility
   toggle; mouse-wheel over a widget contours (0.02 σ). Three display modes:
   - **Sphere @ center** *(default, 15 Å)* — a ball that **follows the center of
     rotation**, recontoured by a Qt poll timer (PyMOL fires no view-change event).
     Chase (continuous) by default; a checkbox switches to settle (on stop).
   - **Model** — carved around the loaded model.
   - **Unit cell** — the whole synthesized map (one unit cell = all symmetry copies;
     a true single-ASU wedge can't be clipped without gemmi/cctbx).
3. **Integration** — `__init_plugin__(app)` adds menu items and routes `.mtz`
   File→Open (and the `pymol x.mtz` command line) through `auto_mtz`.

## Reference
- The design template is a Coot-side "auto open MTZ" file-router that reads
  2Fo-Fc+Fo-Fc via Coot's `auto_read_make_and_draw_maps` — this plugin brings the
  same convenience to PyMOL.
