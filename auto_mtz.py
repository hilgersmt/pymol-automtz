'''
auto_mtz -- Coot-style "Auto Open MTZ" for Incentive PyMOL.

Drop in a .mtz -> auto 2Fo-Fc + Fo-Fc maps, contoured at sensible sigma as new
mesh objects, with a Qt panel to dial sigma live.

Target: Incentive PyMOL (/Applications/PyMol.app, v3.1.6.1, Python 3.10). The
open-source build's load_mtz raises IncentiveOnlyException and is unsupported.

The heavy lifting is cmd.load_mtz(): it reads the MTZ header, auto-guesses
refmac/phenix/buster columns, FFT-synthesizes sigma-normalized map objects
<prefix>.2fofc and <prefix>.fofc (no CCP4 needed). This plugin adds the mesh
drawing, the sigma slider, and the menu item on top of that.

Install: copy or symlink this file into the PyMOL startup dir, e.g.
  /Applications/PyMol.app/Contents/lib/python3.10/site-packages/pmg_tk/startup/
Then restart PyMOL. Or run once:  run /path/to/auto_mtz.py

Command:
  auto_mtz filename [, prefix [, selection [, carve
      [, level_2fofc [, level_fofc ]]]]]
'''

from __future__ import print_function

import os

from pymol import cmd, CmdException

# Default contour levels (Coot-style). Maps are sigma-normalized by
# load_mtz, so contour level == sigma directly.
DEFAULT_LEVEL_2FOFC = 1.5   # blue,  positive
DEFAULT_LEVEL_FOFC = 3.0    # green (+) / red (-)
DEFAULT_CARVE = 2.0         # Angstrom carve radius around the selection (model mode)

# Display modes for where density is drawn:
#   'sphere' -> a radius-R ball that follows the center of rotation (Coot-style)
#   'model'  -> carved around the loaded model
#   'cell'   -> the whole map == one unit cell (all symmetry copies; the map
#              load_mtz synthesizes spans a full cell, not a single ASU wedge)
DEFAULT_MODE = 'sphere'
DEFAULT_SPHERE_RADIUS = 15.0   # Angstrom, adjustable via the panel slider

# Colors
COLOR_2FOFC = 'skyblue'
COLOR_FOFC_POS = 'green'
COLOR_FOFC_NEG = 'red'

# Registry of loaded map sets so the sigma panel can find them.
# prefix -> dict(map2fofc, mapfofc, mesh_2fofc, mesh_pos, mesh_neg,
#                l_2fofc, l_pos, l_neg, selection, carve, filename)
_MTZ_SETS = {}


def _num(x, default):
    '''Parse a PyMOL command-line arg (str) to float, tolerating '' / None.'''
    if x is None:
        return default
    if isinstance(x, str):
        x = x.strip()
        if x == '' or x.lower() == 'none':
            return default
    return float(x)


def _default_selection(prefix):
    '''Pick a sensible selection to carve maps around.

    Prefer polymer/organic atoms in loaded structure objects (not the maps we
    just made). Fall back to everything, else no carve.
    '''
    map_objs = set()
    for s in _MTZ_SETS.values():
        map_objs.update([s['map2fofc'], s['mapfofc']])

    models = [o for o in cmd.get_object_list('all')
              if o not in map_objs and cmd.get_type(o) == 'object:molecule']
    if not models:
        return ''
    sel = '(' + ' or '.join(models) + ') and (polymer or organic)'
    if cmd.count_atoms(sel) == 0:
        sel = '(' + ' or '.join(models) + ')'
    return sel


def _mode_carve_kw(prefix):
    '''isomesh carve/selection kwargs for the set's current display mode.

    Returns (kwargs, cleanup). PyMOL has no native "sphere of density", so
    sphere mode drops a throwaway pseudoatom at the center of rotation and
    carves a radius-R ball around it (buffer=R makes the generation box big
    enough to contain the ball). cleanup() removes that pseudoatom.
    '''
    s = _MTZ_SETS[prefix]
    mode = s.get('mode', DEFAULT_MODE)

    if mode == 'sphere':
        r = float(s.get('sphere_radius', DEFAULT_SPHERE_RADIUS))
        c = cmd.get_view()[12:15]            # origin of rotation (view center)
        vc = prefix + '.vc'
        cmd.pseudoatom(vc, pos=[c[0], c[1], c[2]])
        return dict(selection=vc, carve=r, buffer=r), (lambda: cmd.delete(vc))

    if mode == 'model':
        sel = s.get('selection') or ''
        carve = s.get('carve')
        if sel and carve:
            return dict(selection=sel, carve=float(carve)), (lambda: None)
        if sel:
            return dict(selection=sel), (lambda: None)
        return {}, (lambda: None)            # no model loaded -> whole map

    return {}, (lambda: None)                # 'cell' -> whole map (unit cell)


def _build_meshes(prefix, quiet=1):
    '''(Re)build the three mesh objects for a loaded map set, per its mode.'''
    s = _MTZ_SETS[prefix]
    map2 = s['map2fofc']
    mapf = s['mapfofc']
    l_2fofc = s.get('l_2fofc', DEFAULT_LEVEL_2FOFC)
    l_pos = abs(s.get('l_pos', DEFAULT_LEVEL_FOFC))
    l_neg = -abs(s.get('l_neg', -DEFAULT_LEVEL_FOFC))

    mesh_2fofc = prefix + '.2fofc.mesh'
    mesh_pos = prefix + '.fofc.mesh_pos'
    mesh_neg = prefix + '.fofc.mesh_neg'

    have_2fofc = map2 in cmd.get_names('objects')
    have_fofc = mapf in cmd.get_names('objects')

    carve_kw, cleanup = _mode_carve_kw(prefix)
    try:
        if have_2fofc:
            cmd.isomesh(mesh_2fofc, map2, l_2fofc, **carve_kw)
            cmd.color(COLOR_2FOFC, mesh_2fofc)
        if have_fofc:
            cmd.isomesh(mesh_pos, mapf, l_pos, **carve_kw)
            cmd.color(COLOR_FOFC_POS, mesh_pos)
            cmd.isomesh(mesh_neg, mapf, l_neg, **carve_kw)
            cmd.color(COLOR_FOFC_NEG, mesh_neg)
    finally:
        cleanup()

    # Group everything (maps + meshes) under <prefix>.
    members = [o for o in (map2, mapf, mesh_2fofc, mesh_pos, mesh_neg)
               if o in cmd.get_names('all')]
    if members:
        cmd.group(prefix, ' '.join(members))

    s.update(dict(mesh_2fofc=mesh_2fofc, mesh_pos=mesh_pos, mesh_neg=mesh_neg,
                  l_2fofc=l_2fofc, l_pos=l_pos, l_neg=l_neg,
                  have_2fofc=have_2fofc, have_fofc=have_fofc))

    if not quiet:
        mode = s.get('mode', DEFAULT_MODE)
        where = {'sphere': '%.0f A sphere @ view center'
                 % s.get('sphere_radius', DEFAULT_SPHERE_RADIUS),
                 'model': 'around model'
                 + ((' (carve %.1f A)' % s['carve']) if s.get('carve') else ''),
                 'cell': 'whole unit cell'}.get(mode, mode)
        print(' auto_mtz: %s%s%s at 2Fo-Fc %+.2f / Fo-Fc %+.2f/%+.2f sigma [%s]'
              % (mesh_2fofc if have_2fofc else '',
                 ' ' if have_2fofc and have_fofc else '',
                 (mesh_pos + '/' + mesh_neg) if have_fofc else '',
                 l_2fofc, l_pos, l_neg, where))


# --- sphere-follows-center-of-rotation timer (Coot-style) -----------------
# PyMOL fires no "view changed" event, so we poll get_view() on a Qt timer and
# recontour as the center of rotation moves. Default is 'chase' (recontour
# continuously); the panel can switch to 'settle' (recontour only once the view
# stops) since each isomesh rebuild takes ~0.2 s on the main thread.
_FOLLOW = {'timer': None, 'last_seen': None, 'last_built': None, 'chase': True}
# 'chase' True  -> recontour continuously as the pivot moves (default);
#         False -> recontour only once the view settles. Toggled from the panel.
_FOLLOW_INTERVAL_MS = 40   # poll cadence (ms) for both chase and settle
_FOLLOW_EPS = 0.15         # Angstrom; movement threshold to trigger a recontour


def _dist3(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def _sphere_prefixes():
    return [p for p, s in _MTZ_SETS.items()
            if s.get('mode', DEFAULT_MODE) == 'sphere']


def _follow_tick():
    try:
        prefixes = _sphere_prefixes()
        if not prefixes:
            _stop_follow()
            return
        c = tuple(cmd.get_view()[12:15])
        if not _FOLLOW['chase']:
            last_seen = _FOLLOW['last_seen']
            _FOLLOW['last_seen'] = c
            if last_seen is None or _dist3(c, last_seen) > _FOLLOW_EPS:
                return   # settle mode: wait for the view to stop moving
        built = _FOLLOW['last_built']
        if built is not None and _dist3(c, built) <= _FOLLOW_EPS:
            return   # already contoured at this center
        for p in prefixes:
            _build_meshes(p, quiet=1)
        _FOLLOW['last_built'] = c
    except Exception:
        pass


def _ensure_follow():
    '''Start the follow timer if any set is in sphere mode, else stop it.'''
    if not _sphere_prefixes():
        _stop_follow()
        return
    if _FOLLOW['timer'] is not None:
        return
    try:
        from pymol.Qt import QtCore
        import pymol
        parent = pymol.gui.get_qtwindow() if hasattr(pymol, 'gui') else None
        t = QtCore.QTimer(parent)
        t.timeout.connect(_follow_tick)
        t.start(_FOLLOW_INTERVAL_MS)
        _FOLLOW['timer'] = t
    except Exception:
        _FOLLOW['timer'] = None   # headless / no Qt -> no live follow


def _stop_follow():
    t = _FOLLOW['timer']
    if t is not None:
        try:
            t.stop()
        except Exception:
            pass
    _FOLLOW.update(timer=None, last_seen=None, last_built=None)


def auto_mtz(filename, prefix='', selection='', carve=DEFAULT_CARVE,
             level_2fofc=DEFAULT_LEVEL_2FOFC, level_fofc=DEFAULT_LEVEL_FOFC,
             quiet=0, _self=cmd):
    '''
DESCRIPTION

    Auto-load an MTZ and draw 2Fo-Fc + Fo-Fc electron density meshes at
    coot-style default contour levels. Wraps cmd.load_mtz (Incentive PyMOL).

USAGE

    auto_mtz filename [, prefix [, selection [, carve
        [, level_2fofc [, level_fofc ]]]]]

ARGUMENTS

    filename = str: path to the .mtz file

    prefix = str: object name prefix {default: filename without extension}

    selection = str: atoms to carve the maps around {default: loaded model}

    carve = float: carve radius in Angstrom, 0/none to disable {default: 2.0}

    level_2fofc = float: 2Fo-Fc contour in sigma {default: 1.5}

    level_fofc = float: Fo-Fc contour in sigma (+/-) {default: 3.0}

EXAMPLES

    auto_mtz data.mtz
    auto_mtz data.mtz, mymap, chain A, 1.8
    '''
    filename = cmd.exp_path(filename)
    if not os.path.exists(filename):
        raise CmdException('no such file: %s' % filename)

    if not prefix:
        prefix = os.path.basename(filename).rsplit('.', 1)[0]

    carve = _num(carve, None)
    l_2fofc = _num(level_2fofc, DEFAULT_LEVEL_2FOFC)
    l_fofc = _num(level_fofc, DEFAULT_LEVEL_FOFC)

    # load_mtz makes <prefix>.2fofc and <prefix>.fofc sigma-normalized maps.
    try:
        cmd.load_mtz(filename, prefix=prefix, quiet=quiet)
    except Exception as e:
        raise CmdException('load_mtz failed (Incentive PyMOL required): %s' % e)

    map2fofc = prefix + '.2fofc'
    mapfofc = prefix + '.fofc'
    objs = cmd.get_names('objects')
    if map2fofc not in objs and mapfofc not in objs:
        raise CmdException('load_mtz made no map objects for %s' % filename)

    if selection == '':
        selection = _default_selection(prefix)

    _MTZ_SETS[prefix] = dict(
        map2fofc=map2fofc, mapfofc=mapfofc, filename=filename,
        mode=DEFAULT_MODE, sphere_radius=DEFAULT_SPHERE_RADIUS,
        selection=selection, carve=carve,
        l_2fofc=l_2fofc, l_pos=abs(l_fofc), l_neg=-abs(l_fofc))

    _build_meshes(prefix, quiet=quiet)

    # Sphere mode follows the center of rotation -- start the poll timer.
    _ensure_follow()

    # Refresh the sigma panel if it is open.
    try:
        if _PANEL['win'] is not None:
            _PANEL['win'].refresh_sets()
    except Exception:
        pass

    return prefix


cmd.extend('auto_mtz', auto_mtz)
cmd.auto_arg[0]['auto_mtz'] = [
    lambda: cmd.Shortcut(['*.mtz']), 'filename', '']


def set_isolevel(mesh, level, _self=cmd):
    '''Live-update a mesh contour level (sigma). Thin wrapper over isolevel.'''
    cmd.isolevel(mesh, float(level))


cmd.extend('set_isolevel', set_isolevel)


# ---------------------------------------------------------------------------
# Sigma panel (PyQt)
# ---------------------------------------------------------------------------
#
# Incentive PyMOL's GUI is Qt (pmg_qt) and its bundled Tkinter is unusable on
# macOS (its _tkinter.so is linked against an absent X11 libX11.6.dylib). So
# the panel is built with pymol.Qt (PyQt5), the toolkit the app already runs.
#
# QSlider is integer-only, so sigma is scaled by _SLIDER_SCALE for the slider
# and paired with a QDoubleSpinBox that carries the true float value.

_PANEL = {'win': None}
_SLIDER_SCALE = 100  # slider ticks per 1.0 sigma
_STEP_2FOFC = 0.02   # sigma per wheel-notch / spin-arrow / key on 2Fo-Fc
_STEP_FOFC = 0.02    # sigma per wheel-notch / spin-arrow / key on Fo-Fc


class _SigmaPanel(object):
    '''A floating Qt window with per-map sigma sliders + toggles.'''

    def __init__(self, parent=None):
        from pymol.Qt import QtWidgets, QtCore
        self.QtWidgets = QtWidgets
        self.QtCore = QtCore

        self.win = QtWidgets.QWidget(parent)
        self.win.setWindowFlags(QtCore.Qt.Window)
        self.win.setWindowTitle('Auto MTZ - sigma panel')
        # Route the window-close (X) button through our cleanup.
        self.win.closeEvent = lambda ev: (self.close(), ev.accept())

        outer = QtWidgets.QVBoxLayout(self.win)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel('Map set:'))
        self.combo = QtWidgets.QComboBox()
        self.combo.currentIndexChanged.connect(lambda _i: self._load_set())
        top.addWidget(self.combo, 1)
        outer.addLayout(top)

        # Body grid gets rebuilt whenever the selected set changes.
        self.body = QtWidgets.QGridLayout()
        outer.addLayout(self.body)

        btns = QtWidgets.QHBoxLayout()
        b_reset = QtWidgets.QPushButton('Reset defaults')
        b_reset.clicked.connect(self.reset_defaults)
        b_zoom = QtWidgets.QPushButton('Zoom set')
        b_zoom.clicked.connect(self.zoom_set)
        b_close = QtWidgets.QPushButton('Close')
        b_close.clicked.connect(self.win.close)
        btns.addWidget(b_reset)
        btns.addWidget(b_zoom)
        btns.addStretch(1)
        btns.addWidget(b_close)
        outer.addLayout(btns)

        self._rows = []
        self.carve_edit = None
        self.refresh_sets()
        self.win.show()
        self.win.raise_()

    # -- set selection ------------------------------------------------------
    def refresh_sets(self):
        names = sorted(_MTZ_SETS.keys())
        keep = self.combo.currentText()
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems(names)
        if names:
            idx = names.index(keep) if keep in names else len(names) - 1
            self.combo.setCurrentIndex(idx)
        self.combo.blockSignals(False)
        self._load_set()

    def _clear_body(self):
        while self.body.count():
            item = self.body.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._rows = []
        self.carve_edit = None

    def _load_set(self):
        self._clear_body()
        prefix = self.combo.currentText()
        s = _MTZ_SETS.get(prefix)
        if not s:
            return
        QtWidgets, QtCore = self.QtWidgets, self.QtCore
        grow = 0

        # --- display mode radios ---------------------------------------
        self.body.addWidget(QtWidgets.QLabel('Show:'), grow, 0)
        modes = QtWidgets.QWidget()
        hb = QtWidgets.QHBoxLayout(modes)
        hb.setContentsMargins(0, 0, 0, 0)
        self._mode_group = QtWidgets.QButtonGroup(self.win)
        cur = s.get('mode', DEFAULT_MODE)
        for key, lbl in (('sphere', 'Sphere @ center'),
                         ('model', 'Model'), ('cell', 'Unit cell')):
            rb = QtWidgets.QRadioButton(lbl)
            rb.setChecked(cur == key)
            rb.clicked.connect(lambda _c=False, k=key: self.set_mode(k))
            self._mode_group.addButton(rb)
            hb.addWidget(rb)
        self.body.addWidget(modes, grow, 1, 1, 3)
        grow += 1

        # --- context control for the current mode ----------------------
        if cur == 'sphere':
            self.body.addWidget(QtWidgets.QLabel('Radius (A):'), grow, 0)
            rad = float(s.get('sphere_radius', DEFAULT_SPHERE_RADIUS))
            rsl = QtWidgets.QSlider(QtCore.Qt.Horizontal)
            rsl.setMinimum(2)
            rsl.setMaximum(40)
            rsl.setValue(int(round(rad)))
            rsl.setFixedWidth(180)
            rsp = QtWidgets.QDoubleSpinBox()
            rsp.setRange(2, 40)
            rsp.setDecimals(0)
            rsp.setSingleStep(1)
            rsp.setValue(round(rad))

            def on_rsl(v, sp=rsp):
                sp.blockSignals(True)
                sp.setValue(v)
                sp.blockSignals(False)
                self.set_radius(float(v))

            def on_rsp(v, sl=rsl):
                sl.blockSignals(True)
                sl.setValue(int(round(v)))
                sl.blockSignals(False)
                self.set_radius(float(v))

            rsl.valueChanged.connect(on_rsl)
            rsp.valueChanged.connect(on_rsp)
            self.body.addWidget(rsl, grow, 2)
            self.body.addWidget(rsp, grow, 3)
            grow += 1

            chase = QtWidgets.QCheckBox('Chase density live (off = update on settle)')
            chase.setChecked(bool(_FOLLOW.get('chase', True)))
            chase.toggled.connect(self.set_chase)
            self.body.addWidget(chase, grow, 1, 1, 3)
            grow += 1
        elif cur == 'model':
            self.body.addWidget(QtWidgets.QLabel('Carve (A):'), grow, 0)
            carve = s.get('carve')
            self.carve_edit = QtWidgets.QLineEdit(
                '' if not carve else '%g' % carve)
            self.carve_edit.setFixedWidth(60)
            self.body.addWidget(self.carve_edit, grow, 2)
            b_carve = QtWidgets.QPushButton('Apply carve')
            b_carve.clicked.connect(self.apply_carve)
            self.body.addWidget(b_carve, grow, 3)
            grow += 1

        # --- per-map sigma rows ----------------------------------------
        rows = []
        if s.get('have_2fofc'):
            rows.append(('2Fo-Fc', s['mesh_2fofc'], 'l_2fofc',
                         s.get('l_2fofc', DEFAULT_LEVEL_2FOFC),
                         0.0, 5.0, _STEP_2FOFC))
        if s.get('have_fofc'):
            rows.append(('Fo-Fc (+)', s['mesh_pos'], 'l_pos',
                         s.get('l_pos', DEFAULT_LEVEL_FOFC),
                         0.0, 8.0, _STEP_FOFC))
            rows.append(('Fo-Fc (-)', s['mesh_neg'], 'l_neg',
                         s.get('l_neg', -DEFAULT_LEVEL_FOFC),
                         -8.0, 0.0, _STEP_FOFC))

        for (label, mesh, lvlkey, level, lo, hi, step) in rows:
            self._make_row(grow, prefix, label, mesh, lvlkey,
                           level, lo, hi, step)
            grow += 1

    def _make_row(self, grow, prefix, label, mesh, lvlkey, level, lo, hi, step):
        QtWidgets, QtCore = self.QtWidgets, self.QtCore
        self.body.addWidget(QtWidgets.QLabel(label), grow, 0)

        chk = QtWidgets.QCheckBox()
        chk.setChecked(True)

        def toggle(state, m=mesh):
            cmd.set('mesh_visible', 1)
            cmd.enable(m) if state else cmd.disable(m)
        chk.toggled.connect(toggle)
        self.body.addWidget(chk, grow, 1)

        # Mouse-wheel over slider/spinbox nudges by `step` sigma (scroll-to-
        # contour, Coot-style) -- the reliable channel on macOS, where global
        # modified-key hotkeys get intercepted by the OS before PyMOL sees them.
        tick = max(1, int(round(step * _SLIDER_SCALE)))
        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        slider.setMinimum(int(lo * _SLIDER_SCALE))
        slider.setMaximum(int(hi * _SLIDER_SCALE))
        slider.setSingleStep(tick)
        slider.setPageStep(tick)
        slider.setValue(int(round(level * _SLIDER_SCALE)))
        slider.setFixedWidth(180)
        self.body.addWidget(slider, grow, 2)

        spin = QtWidgets.QDoubleSpinBox()
        spin.setRange(lo, hi)
        spin.setSingleStep(step)
        spin.setDecimals(2)
        spin.setValue(round(level, 2))
        self.body.addWidget(spin, grow, 3)

        # Persist the level into _MTZ_SETS so mode/radius rebuilds keep it.
        def apply(fv):
            st = _MTZ_SETS.get(prefix)
            if st is not None:
                st[lvlkey] = fv
            set_isolevel(mesh, fv)

        # Keep slider <-> spinbox in sync without an infinite signal loop.
        def on_slider(v, sp=spin):
            fv = v / float(_SLIDER_SCALE)
            sp.blockSignals(True)
            sp.setValue(fv)
            sp.blockSignals(False)
            apply(fv)

        def on_spin(fv, sl=slider):
            sl.blockSignals(True)
            sl.setValue(int(round(fv * _SLIDER_SCALE)))
            sl.blockSignals(False)
            apply(fv)

        slider.valueChanged.connect(on_slider)
        spin.valueChanged.connect(on_spin)

        self._rows.append(dict(mesh=mesh, spin=spin, slider=slider, chk=chk))

    # -- mode / radius ------------------------------------------------------
    def set_mode(self, mode):
        prefix = self.combo.currentText()
        s = _MTZ_SETS.get(prefix)
        if not s:
            return
        s['mode'] = mode
        _build_meshes(prefix, quiet=1)
        _ensure_follow()
        self._load_set()

    def set_radius(self, r):
        prefix = self.combo.currentText()
        s = _MTZ_SETS.get(prefix)
        if not s:
            return
        s['sphere_radius'] = float(r)
        _FOLLOW['last_built'] = None      # force the follow timer to recontour
        _build_meshes(prefix, quiet=1)

    def set_chase(self, on):
        _FOLLOW['chase'] = bool(on)
        if on:
            _FOLLOW['last_built'] = None   # recontour at the current center now

    # -- buttons ------------------------------------------------------------
    def reset_defaults(self):
        s = _MTZ_SETS.get(self.combo.currentText())
        if not s:
            return
        defaults = {s.get('mesh_2fofc'): DEFAULT_LEVEL_2FOFC,
                    s.get('mesh_pos'): DEFAULT_LEVEL_FOFC,
                    s.get('mesh_neg'): -DEFAULT_LEVEL_FOFC}
        for row in self._rows:
            d = defaults.get(row['mesh'])
            if d is None:
                continue
            row['spin'].setValue(d)  # cascades to slider + set_isolevel

    def apply_carve(self):
        prefix = self.combo.currentText()
        s = _MTZ_SETS.get(prefix)
        if not s or self.carve_edit is None:
            return
        txt = self.carve_edit.text().strip()
        s['carve'] = None if txt in ('', '0') else float(txt)
        _build_meshes(prefix, quiet=1)

    def sync_levels(self):
        '''Push stored _MTZ_SETS levels into this set's widgets, no re-contour.

        Used by the keyboard bindings so the sliders/spinboxes track live
        without firing another set_isolevel (the mesh is already updated).
        '''
        s = _MTZ_SETS.get(self.combo.currentText())
        if not s:
            return
        levels = {s.get('mesh_2fofc'): s.get('l_2fofc'),
                  s.get('mesh_pos'): s.get('l_pos'),
                  s.get('mesh_neg'): s.get('l_neg')}
        for row in self._rows:
            lv = levels.get(row['mesh'])
            if lv is None:
                continue
            row['spin'].blockSignals(True)
            row['slider'].blockSignals(True)
            row['spin'].setValue(lv)
            row['slider'].setValue(int(round(lv * _SLIDER_SCALE)))
            row['spin'].blockSignals(False)
            row['slider'].blockSignals(False)

    def zoom_set(self):
        prefix = self.combo.currentText()
        s = _MTZ_SETS.get(prefix)
        if not s:
            return
        sel = s.get('selection') or prefix
        try:
            cmd.zoom(sel, buffer=3)
        except Exception:
            cmd.zoom(prefix)

    def close(self):
        _PANEL['win'] = None
        try:
            self.win.deleteLater()
        except Exception:
            pass


def sigma_panel(_self=cmd):
    '''Open (or raise) the Auto MTZ sigma panel.'''
    if _PANEL['win'] is not None:
        try:
            _PANEL['win'].win.show()
            _PANEL['win'].win.raise_()
            _PANEL['win'].refresh_sets()
            return
        except Exception:
            _PANEL['win'] = None

    parent = None
    try:
        import pymol
        parent = pymol.gui.get_qtwindow() if hasattr(pymol, 'gui') else None
    except Exception:
        parent = None

    try:
        _PANEL['win'] = _SigmaPanel(parent)
    except Exception as e:
        print(' auto_mtz: could not open Qt panel: %s' % e)
        _PANEL['win'] = None


cmd.extend('sigma_panel', sigma_panel)


# ---------------------------------------------------------------------------
# Keyboard sigma stepping (Coot-like live contouring)
# ---------------------------------------------------------------------------
#
# PyMOL's mouse binding (cmd.button) only maps buttons/modifiers to a fixed set
# of built-in view actions, so Coot-style scroll-to-contour on the mouse isn't
# possible. cmd.set_key CAN bind keys to Python callbacks (valid modifiers:
# CTRL and ALT only -- SHIFT is rejected), so we drive sigma from the keyboard:
#   Alt-Up   / Alt-Down   -> 2Fo-Fc  +/- step
#   Alt-Right/ Alt-Left   -> Fo-Fc   +/- step (magnitude; +/- meshes stay symmetric)
# All on the Option (Alt) modifier: Ctrl-arrows are grabbed by macOS Mission
# Control, and plain arrows are PyMOL's movie-frame keys. Keys act on the
# "active" set: the one selected in the sigma panel, else the most recent.

_KEYS = {'enabled': False}


def _active_prefix():
    '''Map set the keys act on: panel selection, else last-loaded set.'''
    try:
        if _PANEL['win'] is not None:
            p = _PANEL['win'].combo.currentText()
            if p in _MTZ_SETS:
                return p
    except Exception:
        pass
    return list(_MTZ_SETS)[-1] if _MTZ_SETS else None


def _sync_panel(prefix):
    '''Reflect stored levels in the open panel if it is showing this set.'''
    try:
        panel = _PANEL['win']
        if panel is not None and panel.combo.currentText() == prefix:
            panel.sync_levels()
    except Exception:
        pass


def _step_2fofc(delta):
    prefix = _active_prefix()
    if not prefix:
        return
    s = _MTZ_SETS[prefix]
    if not s.get('have_2fofc'):
        return
    lvl = max(0.0, round(s.get('l_2fofc', DEFAULT_LEVEL_2FOFC) + delta, 2))
    s['l_2fofc'] = lvl
    set_isolevel(s['mesh_2fofc'], lvl)
    _sync_panel(prefix)


def _step_fofc(delta):
    prefix = _active_prefix()
    if not prefix:
        return
    s = _MTZ_SETS[prefix]
    if not s.get('have_fofc'):
        return
    mag = max(0.0, round(s.get('l_pos', DEFAULT_LEVEL_FOFC) + delta, 2))
    s['l_pos'] = mag
    s['l_neg'] = -mag
    set_isolevel(s['mesh_pos'], mag)
    set_isolevel(s['mesh_neg'], -mag)
    _sync_panel(prefix)


_SIGMA_KEYS = ('ALT-UP', 'ALT-DOWN', 'ALT-RIGHT', 'ALT-LEFT')


def enable_mtz_keys(quiet=1):
    '''Bind Option(Alt)-arrows to live sigma stepping.'''
    cmd.set_key('ALT-UP', lambda: _step_2fofc(+_STEP_2FOFC))
    cmd.set_key('ALT-DOWN', lambda: _step_2fofc(-_STEP_2FOFC))
    cmd.set_key('ALT-RIGHT', lambda: _step_fofc(+_STEP_FOFC))
    cmd.set_key('ALT-LEFT', lambda: _step_fofc(-_STEP_FOFC))
    _KEYS['enabled'] = True
    if not quiet:
        print(' auto_mtz: sigma keys ON  (Alt-Up/Down = 2Fo-Fc, '
              'Alt-Right/Left = Fo-Fc). NOTE: macOS intercepts modified '
              'arrows -- use the panel mouse-wheel instead.')


def disable_mtz_keys(quiet=1):
    '''Unbind the sigma keys (rebinds them to no-ops -- PyMOL has no true unset).'''
    for k in _SIGMA_KEYS:
        try:
            cmd.set_key(k, lambda *a: None)
        except Exception:
            pass
    _KEYS['enabled'] = False
    if not quiet:
        print(' auto_mtz: sigma keys OFF')


def auto_mtz_keys(state='toggle', _self=cmd):
    '''
DESCRIPTION

    Toggle keyboard sigma stepping for the active map set.
      Alt-Up   / Alt-Down   raise/lower 2Fo-Fc by 0.1 sigma
      Alt-Right/ Alt-Left   raise/lower Fo-Fc  by 0.1 sigma (+/- stay symmetric)

USAGE

    auto_mtz_keys [ on | off | toggle ]
    '''
    s = str(state).strip().lower()
    if s in ('toggle', ''):
        s = 'off' if _KEYS['enabled'] else 'on'
    if s in ('on', '1', 'true', 'yes'):
        enable_mtz_keys(quiet=0)
    else:
        disable_mtz_keys(quiet=0)


cmd.extend('auto_mtz_keys', auto_mtz_keys)


# ---------------------------------------------------------------------------
# File->Open routing (Coot-style: opening a .mtz auto-builds maps + meshes)
# ---------------------------------------------------------------------------
#
# Two funnels cover every way PyMOL opens a file:
#   * cmd.load / command-line `pymol x.mtz`  -> importing.loadfunctions['mtz']
#   * GUI File->Open, Ctrl+O, recent files, macOS drag-drop / file-open events
#       -> pmg_qt.file_dialogs.load_dialog -> load_mtz_dialog(parent, fname)
# We patch both so a plain "open" of a .mtz runs auto_mtz instead of just
# making bare map objects (CLI) or popping the column-picker form (GUI).

_ROUTING = {'orig_loadfunc': None, 'orig_dialog': None, 'enabled': False}


def _route_load_mtz(filename, prefix='', quiet=1, _self=cmd, **kwargs):
    '''loadfunctions['mtz'] replacement: route cmd.load(*.mtz) to auto_mtz.'''
    return auto_mtz(filename, prefix=prefix, quiet=quiet, _self=_self)


def _route_mtz_dialog(parent, filename):
    '''load_mtz_dialog replacement: route GUI open of a .mtz to auto_mtz.'''
    try:
        auto_mtz(filename, quiet=0)
    except Exception as e:
        try:
            from pymol.Qt import QtWidgets
            QtWidgets.QMessageBox.critical(parent, 'Auto MTZ error', str(e))
        except Exception:
            print(' auto_mtz: %s' % e)
        return
    # Open/refresh the sigma panel next to the freshly loaded maps.
    try:
        sigma_panel()
    except Exception:
        pass


def enable_mtz_routing(quiet=1):
    '''Route every .mtz open through auto_mtz (CLI + GUI).'''
    import pymol.importing as importing
    if _ROUTING['orig_loadfunc'] is None:
        _ROUTING['orig_loadfunc'] = importing.loadfunctions.get('mtz')
    importing.loadfunctions['mtz'] = _route_load_mtz

    try:
        import pmg_qt.file_dialogs as fd
        if _ROUTING['orig_dialog'] is None:
            _ROUTING['orig_dialog'] = getattr(fd, 'load_mtz_dialog', None)
        fd.load_mtz_dialog = _route_mtz_dialog
    except Exception:
        pass  # no Qt GUI (e.g. headless) -- CLI routing still active

    _ROUTING['enabled'] = True
    if not quiet:
        print(' auto_mtz: .mtz File->Open routing ON')


def disable_mtz_routing(quiet=1):
    '''Restore PyMOL's stock .mtz open behavior.'''
    import pymol.importing as importing
    if _ROUTING['orig_loadfunc'] is not None:
        importing.loadfunctions['mtz'] = _ROUTING['orig_loadfunc']
    try:
        import pmg_qt.file_dialogs as fd
        if _ROUTING['orig_dialog'] is not None:
            fd.load_mtz_dialog = _ROUTING['orig_dialog']
    except Exception:
        pass
    _ROUTING['enabled'] = False
    if not quiet:
        print(' auto_mtz: .mtz File->Open routing OFF')


def auto_mtz_route(state='toggle', _self=cmd):
    '''
DESCRIPTION

    Turn auto_mtz File->Open routing on/off. When on, opening any .mtz
    (menu, drag-drop, command line) auto-builds 2Fo-Fc/Fo-Fc meshes.

USAGE

    auto_mtz_route [ on | off | toggle ]
    '''
    s = str(state).strip().lower()
    if s in ('toggle', ''):
        s = 'off' if _ROUTING['enabled'] else 'on'
    if s in ('on', '1', 'true', 'yes'):
        enable_mtz_routing(quiet=0)
    else:
        disable_mtz_routing(quiet=0)


cmd.extend('auto_mtz_route', auto_mtz_route)


# ---------------------------------------------------------------------------
# Plugin integration
# ---------------------------------------------------------------------------

def __init_plugin__(app=None):
    '''Add menu items and enable .mtz File->Open routing.'''
    try:
        enable_mtz_routing(quiet=1)
    except Exception as e:
        print(' auto_mtz: routing setup failed: %s' % e)

    try:
        enable_mtz_keys(quiet=1)
    except Exception as e:
        print(' auto_mtz: key setup failed: %s' % e)

    try:
        from pymol.plugins import addmenuitemqt
        addmenuitemqt('Load MTZ (auto maps)...', _menu_load_mtz)
        addmenuitemqt('Auto MTZ: sigma panel', sigma_panel)
        addmenuitemqt('Auto MTZ: toggle .mtz open routing',
                      lambda: auto_mtz_route('toggle'))
        addmenuitemqt('Auto MTZ: toggle sigma keys (Alt-arrows)',
                      lambda: auto_mtz_keys('toggle'))
        return
    except Exception:
        pass
    # Legacy Tk menu fallback
    try:
        app.menuBar.addmenuitem('Plugin', 'command',
                                'Load MTZ (auto maps)...',
                                label='Load MTZ (auto maps)...',
                                command=_menu_load_mtz)
    except Exception:
        pass


def _menu_load_mtz():
    '''File-dialog entry point used by the menu item.'''
    filename = None
    # Prefer Qt dialog when available.
    try:
        from pymol.Qt import QtWidgets
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            None, 'Open MTZ', '', 'MTZ files (*.mtz);;All files (*)')
    except Exception:
        try:
            import tkinter.filedialog as fd
            filename = fd.askopenfilename(
                title='Open MTZ',
                filetypes=[('MTZ files', '*.mtz'), ('All files', '*')])
        except Exception as e:
            print(' auto_mtz: no file dialog available: %s' % e)
            return

    if not filename:
        return
    auto_mtz(filename, quiet=0)
    sigma_panel()


if __name__ == 'pymol':
    # `run auto_mtz.py` inside PyMOL registers the command without the menu.
    print(' auto_mtz loaded. Try: auto_mtz your.mtz   (then: sigma_panel)')
    print('   sigma keys: auto_mtz_keys on  '
          '(Alt-Up/Down = 2Fo-Fc, Alt-Right/Left = Fo-Fc)')
