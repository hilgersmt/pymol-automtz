---
name: reference-pymol-installs-mtz
description: load_mtz (auto 2Fo-Fc/Fo-Fc maps) is Incentive-only and already works in the GUI app
type: reference
---

**`cmd.load_mtz(filename)` is Incentive-only.** In the open-source PyMOL build it just does `raise pymol.IncentiveOnlyException()`. In the Incentive GUI app (tested 3.1.6.1, bundled Python 3.10) it is fully implemented and verified end-to-end on a real refmac MTZ:
- Auto-guesses columns via settings `default_refmac_names` (`FWT PHWT DELFWT PHDELWT`), `default_phenix_names` / `default_buster_names` (`2FOFCWT PH2FOFCWT FOFCWT PHFOFCWT`), and `default_phenix_no_fill_names`.
- Synthesizes 2Fo-Fc + Fo-Fc via PyMOL's built-in cctbx FFT (`cmd.map_generate`) — **no CCP4 needed**.
- Creates two map objects `<prefix>.2fofc` and `<prefix>.fofc`, **normalized to σ=1** (contour level 1.0 == 1σ).
- The map it synthesizes spans one full **unit cell**, not a single ASU.
- GAP vs Coot "Auto Open MTZ": `load_mtz` makes the map OBJECTS but draws NO mesh and has no live sigma slider. That gap IS the plugin ([[project-pymol-mtz-plugin]]).

Design template: a Coot-side "auto open MTZ" file-router that reads 2Fo-Fc + Fo-Fc via Coot's `auto_read_make_and_draw_maps` — this plugin brings the same convenience to PyMOL.
