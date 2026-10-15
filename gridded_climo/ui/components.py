"""Streamlit components for styling: a gradient color-ramp dropdown and a MAX-style color band editor.

The HTML/CSS/JS below is copied from geotiff-to-kmz (streamlit_app.py, commit fc1f8fd). Both are `st.components.v2`
components (rendered in the page itself, themed through Streamlit's --st-* CSS variables), so they need streamlit>=1.64.
Differences from the original are only in the Python wrappers: they take and return plain values instead of reading
that app's session state, and the Stepped gradient preview samples colors the way this app does (bin centers).
"""
from __future__ import annotations

import matplotlib as mpl
import pandas as pd
import streamlit as st
from streamlit.errors import StreamlitAPIException

from ..render.legend import normalize_legend
from ..render.ramps import RAMP_CATEGORIES, RAMPS


def ramp_gradient_css(cmap_name, mode, steps, reverse):
    """CSS linear-gradient() previewing a ramp the way this app applies it: a smooth blend, or (Stepped) `steps` flat
    bands colored at their centers, exactly like render/style.py's `_ramp_colors`."""
    cmap = mpl.colormaps[f"{cmap_name}_r" if reverse else cmap_name]
    if mode == "Stepped":
        n = max(2, int(steps))
        stops = [
            f"{mpl.colors.to_hex(cmap((i + 0.5) / n))} {i * 100 / n:.4g}% {(i + 1) * 100 / n:.4g}%"
            for i in range(n)
        ]
    else:
        n = 48
        stops = [f"{mpl.colors.to_hex(cmap(i / (n - 1)))} {i * 100 / (n - 1):.4g}%" for i in range(n)]
    return "linear-gradient(90deg, " + ", ".join(stops) + ")"


@st.cache_data(show_spinner=False)
def ramp_picker_groups(mode, steps, reverse):
    return [
        {"name": category, "items": [
            {"label": label, "gradient": ramp_gradient_css(name, mode, steps, reverse)}
            for label, name in ramps.items()
        ]}
        for category, ramps in RAMP_CATEGORIES.items()
    ]


# A dropdown whose closed state and every row show the ramp's actual gradient beside its
# name, grouped under the ramp-type headings -- a native selectbox can't draw images in
# its options. Built as an st.components.v2 component (rendered in the page itself, not
# an iframe) so the open list can overflow its container and follow the app's theme
# through Streamlit's --st-* CSS variables. The list is position: fixed so it isn't
# clipped by expanders or columns; it flips upward near the bottom of the window.
RAMP_PICKER_HTML = """
<div class="rp">
  <div class="rp-label" hidden></div>
  <button type="button" class="rp-btn" aria-haspopup="listbox" aria-expanded="false">
    <span class="rp-bar"></span><span class="rp-name"></span><span class="rp-caret" aria-hidden="true"></span>
  </button>
  <div class="rp-list" role="listbox" tabindex="-1" hidden></div>
</div>
"""

RAMP_PICKER_CSS = """
.rp { position: relative; font-family: var(--st-font, sans-serif); color: var(--st-text-color); font-size: 1rem; line-height: 1.4; }
.rp-label { font-size: 0.875rem; margin-bottom: 0.25rem; }
.rp-btn { display: flex; align-items: center; gap: 0.6rem; width: 100%; box-sizing: border-box; min-height: 2.5rem;
  margin: 0; padding: 0.3rem 0.75rem; font: inherit; color: inherit; text-align: left; cursor: pointer;
  background: var(--st-secondary-background-color); border: 1px solid transparent; border-radius: var(--st-base-radius, 0.5rem); }
.rp-btn:hover, .rp-btn:focus-visible, .rp-btn[aria-expanded="true"] { outline: none; border-color: var(--st-primary-color); }
.rp-bar { flex: 1 1 auto; min-width: 3rem; height: 1.4rem; border-radius: 4px; box-shadow: inset 0 0 0 1px rgba(128, 128, 128, 0.45); }
.rp-name { flex: 0 0 7rem; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.rp-caret { flex: 0 0 auto; width: 0.45rem; height: 0.45rem; margin: -0.2rem 0.1rem 0 0; opacity: 0.6;
  border-right: 2px solid currentColor; border-bottom: 2px solid currentColor; transform: rotate(45deg); }
.rp-list { position: fixed; z-index: 1000010; box-sizing: border-box; overflow-y: auto; padding: 0.25rem 0;
  background: var(--st-background-color); border: 1px solid var(--st-border-color); border-radius: var(--st-base-radius, 0.5rem);
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.22); }
.rp-list[hidden] { display: none; }
.rp-group { padding: 0.5rem 0.75rem 0.2rem; font-size: 0.8rem; opacity: 0.6; }
.rp-opt { display: flex; align-items: center; gap: 0.6rem; padding: 0.25rem 0.75rem; cursor: pointer; }
.rp-opt[data-active="true"] { background: var(--st-secondary-background-color); }
.rp-opt[aria-selected="true"] .rp-name { font-weight: 600; }
"""

RAMP_PICKER_JS = """
export default function (component) {
  const { data, setStateValue, parentElement } = component;
  const root = parentElement.querySelector('.rp');
  const btn = root.querySelector('.rp-btn');
  const list = root.querySelector('.rp-list');
  const labelEl = root.querySelector('.rp-label');
  const S = root._rp || (root._rp = { open: false, active: -1, typed: '', typedAt: 0 });

  // Streamlit may call this again with new data while the same DOM stays mounted, so
  // every global listener is torn down and re-attached each call.
  if (S.abort) S.abort.abort();
  S.abort = new AbortController();
  const signal = S.abort.signal;

  const byLabel = {};
  data.groups.forEach((g) => g.items.forEach((it) => { byLabel[it.label] = it; }));
  let selected = byLabel[data.selected] ? data.selected : Object.keys(byLabel)[0];

  labelEl.hidden = !data.label;
  labelEl.textContent = data.label || '';
  list.setAttribute('aria-label', data.label || 'Color ramps');

  function paintButton() {
    const it = byLabel[selected];
    btn.querySelector('.rp-bar').style.background = it.gradient;
    btn.querySelector('.rp-name').textContent = it.label;
    btn.setAttribute('aria-label', (data.label ? data.label + ': ' : '') + it.label);
  }

  const opts = [];
  const keepScroll = list.scrollTop;
  list.replaceChildren();
  data.groups.forEach((g) => {
    const head = document.createElement('div');
    head.className = 'rp-group';
    head.setAttribute('role', 'presentation');
    head.textContent = g.name;
    list.appendChild(head);
    g.items.forEach((it) => {
      const row = document.createElement('div');
      row.className = 'rp-opt';
      row.id = 'rp-opt-' + opts.length;
      row.setAttribute('role', 'option');
      row.setAttribute('aria-selected', String(it.label === selected));
      row.dataset.label = it.label;
      const bar = document.createElement('span');
      bar.className = 'rp-bar';
      bar.style.background = it.gradient;
      const name = document.createElement('span');
      name.className = 'rp-name';
      name.textContent = it.label;
      row.append(bar, name);
      row.addEventListener('mouseenter', () => setActive(opts.indexOf(row), false));
      row.addEventListener('click', () => choose(it.label));
      list.appendChild(row);
      opts.push(row);
    });
  });
  list.scrollTop = keepScroll;
  paintButton();

  function setActive(i, reveal) {
    opts.forEach((o, j) => { o.dataset.active = String(j === i); });
    S.active = i;
    if (i < 0) { btn.removeAttribute('aria-activedescendant'); return; }
    btn.setAttribute('aria-activedescendant', opts[i].id);
    if (!reveal) return;
    const o = opts[i];
    const prev = o.previousElementSibling;
    const top = (prev && prev.className === 'rp-group' ? prev : o).offsetTop;
    if (top < list.scrollTop) list.scrollTop = top;
    const bottom = o.offsetTop + o.offsetHeight;
    if (bottom > list.scrollTop + list.clientHeight) list.scrollTop = bottom - list.clientHeight + 4;
  }

  function place() {
    const r = btn.getBoundingClientRect();
    const gap = 4;
    const below = window.innerHeight - r.bottom - 8;
    const above = r.top - 8;
    const down = below >= 260 || below >= above;
    list.style.left = r.left + 'px';
    list.style.width = r.width + 'px';
    list.style.maxHeight = Math.max(140, Math.min(380, (down ? below : above) - gap)) + 'px';
    list.style.top = down ? (r.bottom + gap) + 'px' : 'auto';
    list.style.bottom = down ? 'auto' : (window.innerHeight - r.top + gap) + 'px';
  }

  function openList() {
    S.open = true;
    list.hidden = false;
    btn.setAttribute('aria-expanded', 'true');
    place();
    const idx = Math.max(0, opts.findIndex((o) => o.dataset.label === selected));
    setActive(idx, false);
    list.scrollTop = Math.max(0, opts[idx].offsetTop - (list.clientHeight - opts[idx].offsetHeight) / 2);
  }

  function closeList() {
    S.open = false;
    list.hidden = true;
    btn.setAttribute('aria-expanded', 'false');
  }

  function choose(label) {
    selected = label;
    paintButton();
    opts.forEach((o) => o.setAttribute('aria-selected', String(o.dataset.label === label)));
    closeList();
    btn.focus();
    setStateValue('selected', label);
  }

  btn.onclick = () => (S.open ? closeList() : openList());
  btn.onkeydown = (e) => {
    const k = e.key;
    if (!S.open) {
      if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(k)) { e.preventDefault(); openList(); }
      return;
    }
    if (k === 'ArrowDown') { e.preventDefault(); setActive(Math.min(opts.length - 1, S.active + 1), true); }
    else if (k === 'ArrowUp') { e.preventDefault(); setActive(Math.max(0, S.active - 1), true); }
    else if (k === 'Home') { e.preventDefault(); setActive(0, true); }
    else if (k === 'End') { e.preventDefault(); setActive(opts.length - 1, true); }
    else if (k === 'Enter' || k === ' ') { e.preventDefault(); if (S.active >= 0) choose(opts[S.active].dataset.label); }
    else if (k === 'Escape') { e.preventDefault(); closeList(); }
    else if (k === 'Tab') { closeList(); }
    else if (k.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
      const now = Date.now();
      S.typed = (now - S.typedAt < 700 ? S.typed : '') + k.toLowerCase();
      S.typedAt = now;
      const from = S.typed.length === 1 ? S.active + 1 : S.active;
      for (let n = 0; n < opts.length; n++) {
        const i = (from + n) % opts.length;
        if (opts[i].dataset.label.toLowerCase().startsWith(S.typed)) { setActive(i, true); break; }
      }
    }
  };

  document.addEventListener('pointerdown', (e) => {
    if (S.open && !e.composedPath().includes(root)) closeList();
  }, { signal, capture: true });
  window.addEventListener('scroll', () => { if (S.open) place(); }, { signal, capture: true });
  window.addEventListener('resize', () => { if (S.open) place(); }, { signal });

  return () => S.abort.abort();
}
"""

_ramp_picker = st.components.v2.component(
    "ramp_picker", html=RAMP_PICKER_HTML, css=RAMP_PICKER_CSS, js=RAMP_PICKER_JS,
)


def ramp_picker(label, *, key, selected, mode, steps, reverse):
    """Dropdown of every ramp (grouped by type, each drawn as its gradient). `selected` is the label to show (a key of
    RAMPS; Python owns it). Returns the label the user just picked, or None if they haven't picked since the last call
    with this `key` -- so an imported preset can change `selected` without the dropdown's own memory overriding it.
    Use a new `key` to forget the dropdown's memory (e.g. after Reset)."""
    try:
        result = _ramp_picker(
            key=key,
            data={"label": label, "selected": selected, "groups": ramp_picker_groups(mode, int(steps), bool(reverse))},
            default={"selected": None},
            on_selected_change=lambda: None,
        )
        picked = result.selected if result.selected in RAMPS else None
    except StreamlitAPIException as e:     # custom components unavailable here (e.g. Streamlit's AppTest): plain selectbox
        if "not registered" not in str(e):
            raise
        labels = [lab for group in RAMP_CATEGORIES.values() for lab in group]
        choice = st.selectbox(label, labels, index=labels.index(selected) if selected in labels else 0, key=f"{key}_fallback")
        picked = choice if choice != selected else None
    seen = f"_{key}_seen"
    if picked == st.session_state.get(seen):
        return None
    st.session_state[seen] = picked
    return picked


# A color-table editor in the style of MAX's: one row per band (From, To, Color swatch,
# Red, Green, Blue, Transparency), a native color picker on each swatch, band editing
# that keeps neighbors contiguous, and "Ramp" actions that fill the rows between two
# selected rows with colors interpolated between theirs. An st.components.v2 component
# (same technique as ramp_picker) because st.data_editor can't draw color swatches or
# open a color picker.
#
# Hand-off with Python: Python passes the table plus a `version`; the editor keeps its own
# copy and reports every committed edit as {v: version, rows: [...]}. Python only accepts
# an edit whose v matches the current version, so an edit made before Python replaced the
# table (import, Generate bands) can't overwrite the replacement.
LEGEND_EDITOR_HTML = """
<div class="le">
  <div class="le-tools">
    <button type="button" class="le-btn" data-act="add">+ Add row</button>
    <button type="button" class="le-btn" data-act="sort" title="Order the rows by their From value">Sort by From</button>
    <span class="le-sep"></span>
    <button type="button" class="le-btn" data-act="ramp-rgb">Ramp RGB</button>
    <button type="button" class="le-btn" data-act="ramp-rgba">Ramp RGB + Transparency</button>
    <label class="le-chk" title="Editing a To also moves the next row's From (and the reverse), so bands stay edge to edge">
      <input type="checkbox" class="le-contig" checked> Keep bands contiguous</label>
  </div>
  <div class="le-scroll">
    <table class="le-tbl">
      <thead><tr>
        <th class="le-idx">#</th><th>From</th><th>To</th><th>Color</th><th>Red</th><th>Green</th><th>Blue</th>
        <th title="255 = opaque, 0 = fully see-through">Transparency</th><th></th>
      </tr></thead>
      <tbody></tbody>
    </table>
  </div>
  <div class="le-msg" role="status"></div>
  <div class="le-strip" aria-hidden="true"></div>
  <div class="le-hint">Select rows with the # column (Shift for a range, Ctrl/Cmd to add), set the colors of the first and last, then Ramp to fill the rows between.</div>
</div>
"""

LEGEND_EDITOR_CSS = """
.le { font-family: var(--st-font, sans-serif); color: var(--st-text-color); font-size: 0.9rem; }
.le-tools { display: flex; flex-wrap: wrap; gap: 0.4rem; align-items: center; margin-bottom: 0.5rem; }
.le-sep { flex: 1 1 0; }
.le-btn { font: inherit; color: inherit; cursor: pointer; padding: 0.3rem 0.65rem; border-radius: var(--st-base-radius, 0.5rem);
  background: var(--st-secondary-background-color); border: 1px solid var(--st-border-color); }
.le-btn:hover:not(:disabled) { border-color: var(--st-primary-color); }
.le-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.le-chk { display: inline-flex; align-items: center; gap: 0.3rem; cursor: pointer; margin-left: 0.4rem; }
.le-scroll { max-height: 26rem; overflow: auto; border: 1px solid var(--st-border-color); border-radius: var(--st-base-radius, 0.5rem); }
.le-tbl { width: 100%; border-collapse: collapse; }
.le-tbl th { position: sticky; top: 0; z-index: 1; padding: 0.35rem 0.4rem; text-align: left; font-weight: 600; font-size: 0.8rem;
  background: var(--st-secondary-background-color); border-bottom: 1px solid var(--st-border-color); white-space: nowrap; }
.le-tbl td { padding: 0.12rem 0.3rem; border-bottom: 1px solid var(--st-border-color); }
.le-tbl tr:last-child td { border-bottom: none; }
.le-idx { width: 1.8rem; text-align: center; cursor: pointer; user-select: none; opacity: 0.75; }
td.le-idx { padding: 0.12rem 0.2rem; }
tr.le-sel td { background: color-mix(in srgb, var(--st-primary-color) 14%, transparent); }
tr.le-sel td.le-idx { opacity: 1; font-weight: 700; color: var(--st-primary-color); }
.le-in { box-sizing: border-box; width: 100%; padding: 0.22rem 0.3rem; font: inherit; font-family: ui-monospace, Menlo, Consolas, monospace;
  color: inherit; background: transparent; border: 1px solid transparent; border-radius: 4px; }
.le-in:hover { border-color: var(--st-border-color); }
.le-in:focus { outline: none; border-color: var(--st-primary-color); background: var(--st-background-color); }
.le-in.le-bad { border-color: #d64545; }
.le-num { width: 3.6rem; } .le-val { width: 5.2rem; } .le-tr { width: 4.6rem; }
.le-sw { position: relative; display: block; width: 2.4rem; height: 1.45rem; margin: 0 auto; cursor: pointer; border-radius: 4px;
  box-shadow: inset 0 0 0 1px rgba(128, 128, 128, 0.55); overflow: hidden;
  background: conic-gradient(#c9c9c9 25%, #fff 0 50%, #c9c9c9 0 75%, #fff 0) 0 0 / 10px 10px; }
.le-chip { position: absolute; inset: 0; }
.le-sw input { position: absolute; inset: 0; width: 100%; height: 100%; opacity: 0; cursor: pointer; }
.le-act { white-space: nowrap; text-align: right; }
.le-icon { font: inherit; line-height: 1; cursor: pointer; padding: 0.15rem 0.35rem; color: inherit; opacity: 0.55; background: transparent; border: none; border-radius: 4px; }
.le-icon:hover { opacity: 1; background: var(--st-secondary-background-color); }
.le-msg { min-height: 1.2rem; margin: 0.5rem 0 0.35rem; font-size: 0.82rem; opacity: 0.85; }
.le-msg.le-warn { color: #d64545; opacity: 1; }
.le-strip { position: relative; display: flex; height: 1.9rem; margin-bottom: 1.4rem; border-radius: 4px; box-shadow: inset 0 0 0 1px rgba(128, 128, 128, 0.55);
  background: conic-gradient(#c9c9c9 25%, #fff 0 50%, #c9c9c9 0 75%, #fff 0) 0 0 / 10px 10px; }
.le-blk { position: relative; flex: 1 1 0; min-width: 1px; }
.le-lab { position: absolute; top: 100%; left: 0; margin-top: 0.15rem; font-size: 0.68rem; white-space: nowrap; opacity: 0.8; font-family: ui-monospace, Menlo, Consolas, monospace; }
.le-lab.le-end { left: auto; right: 0; }
.le-hint { font-size: 0.78rem; opacity: 0.65; }
"""

LEGEND_EDITOR_JS = """
export default function (component) {
  const { data, setStateValue, parentElement } = component;
  const root = parentElement.querySelector('.le');
  const tbody = root.querySelector('tbody');
  const msg = root.querySelector('.le-msg');
  const strip = root.querySelector('.le-strip');
  const contigBox = root.querySelector('.le-contig');
  const S = root._le || (root._le = { rows: null, ver: null, sel: new Set(), anchor: null, trs: new Map() });
  S.emit = (rows) => setStateValue('edit', { v: S.ver, rows: rows.map((r) => ({ ...r })) });

  const lo = (r) => (r.from === null ? -Infinity : r.from);
  const fmt = (v) => (v === null || v === undefined ? '' : String(+Number(v).toPrecision(10)));
  const clamp = (v) => Math.max(0, Math.min(255, Math.round(Number(v) || 0)));
  const hex2 = (n) => n.toString(16).padStart(2, '0');
  const toHex = (r) => '#' + hex2(r.r) + hex2(r.g) + hex2(r.b);
  const rgba = (r) => 'rgba(' + r.r + ',' + r.g + ',' + r.b + ',' + (r.a / 255).toFixed(3) + ')';
  const contiguous = () => contigBox.checked;
  const commit = () => S.emit(S.rows);

  // Python replaced the table (or this is the first mount): take its copy. Otherwise keep
  // the local one, which already has every edit made since.
  if (S.rows === null || S.ver !== data.version) {
    S.ver = data.version;
    S.rows = data.rows.map((r) => ({ ...r }));
    S.sel.clear();
    S.anchor = null;
    build();
  }

  function cell(tr, cls) { const td = document.createElement('td'); if (cls) td.className = cls; tr.appendChild(td); return td; }
  function input(td, col, cls, label) {
    const i = document.createElement('input');
    i.className = 'le-in ' + cls; i.dataset.col = col; i.setAttribute('aria-label', label);
    i.type = (col === 'from' || col === 'to') ? 'text' : 'number';
    if (i.type === 'text') i.inputMode = 'decimal'; else { i.min = 0; i.max = 255; i.step = 1; }
    td.appendChild(i); return i;
  }

  function build() {
    tbody.replaceChildren();
    S.trs = new Map();
    S.rows.forEach((r, n) => {
      const tr = document.createElement('tr');
      const idx = cell(tr, 'le-idx'); idx.textContent = String(n + 1); idx.title = 'Click to select this row';
      idx.addEventListener('click', (e) => select(r, e));
      for (const col of ['from', 'to']) {
        const i = input(cell(tr), col, 'le-val', 'Row ' + (n + 1) + (col === 'from' ? ' From' : ' To'));
        if (col === 'to' || n === 0) i.placeholder = 'no limit';
        i.addEventListener('change', () => editBound(r, col, i));
        i.addEventListener('keydown', (e) => { if (e.key === 'Enter') { const nx = tbody.rows[n + 1]; if (nx) { const t = nx.querySelector('[data-col=' + col + ']'); t.focus(); t.select(); } else i.blur(); } });
      }
      const sw = document.createElement('label'); sw.className = 'le-sw'; sw.title = 'Click to pick a color';
      const chip = document.createElement('span'); chip.className = 'le-chip';
      const pick = document.createElement('input'); pick.type = 'color'; pick.setAttribute('aria-label', 'Row ' + (n + 1) + ' color');
      pick.addEventListener('input', () => { const h = pick.value; r.r = parseInt(h.slice(1, 3), 16); r.g = parseInt(h.slice(3, 5), 16); r.b = parseInt(h.slice(5, 7), 16); paint(); });
      pick.addEventListener('change', () => { paint(); commit(); });
      sw.append(chip, pick); cell(tr).appendChild(sw);
      for (const [col, label, cls] of [['r', 'Red', 'le-num'], ['g', 'Green', 'le-num'], ['b', 'Blue', 'le-num'], ['a', 'Transparency', 'le-tr']]) {
        const i = input(cell(tr), col, cls, 'Row ' + (n + 1) + ' ' + label);
        i.addEventListener('change', () => { r[col] = clamp(i.value); paint(); commit(); });
        i.addEventListener('keydown', (e) => { if (e.key === 'Enter') { const nx = tbody.rows[n + 1]; if (nx) { const t = nx.querySelector('[data-col=' + col + ']'); t.focus(); t.select(); } else i.blur(); } });
      }
      const act = cell(tr, 'le-act');
      for (const [sym, title, fn] of [['⇥', 'Split this band in two', () => split(r)], ['✕', 'Delete this row', () => remove(r)]]) {
        const b = document.createElement('button'); b.type = 'button'; b.className = 'le-icon'; b.textContent = sym; b.title = title;
        b.setAttribute('aria-label', title + ' (row ' + (n + 1) + ')'); b.addEventListener('click', fn); act.appendChild(b);
      }
      S.trs.set(r, tr); tbody.appendChild(tr);
    });
    paint();
  }

  function setIf(inp, v) { if (inp.value !== v) inp.value = v; }
  function paint() {
    const bad = badRows();
    S.rows.forEach((r, n) => {
      const tr = S.trs.get(r); if (!tr) return;
      tr.classList.toggle('le-sel', S.sel.has(r));
      tr.cells[0].textContent = String(n + 1);
      const fin = tr.querySelector('[data-col=from]');
      setIf(fin, fmt(r.from));
      fin.placeholder = n === 0 ? 'no limit' : '';
      setIf(tr.querySelector('[data-col=to]'), fmt(r.to));
      for (const c of ['r', 'g', 'b', 'a']) setIf(tr.querySelector('[data-col=' + c + ']'), String(r[c]));
      tr.querySelector('.le-chip').style.background = rgba(r);
      tr.querySelector('input[type=color]').value = toHex(r);
      tr.querySelector('[data-col=to]').classList.toggle('le-bad', bad.has(r));
    });
    const n = S.sel.size;
    for (const a of ['ramp-rgb', 'ramp-rgba']) {
      const b = root.querySelector('[data-act=' + a + ']');
      b.disabled = n < 2;
      b.title = n < 2 ? 'Select at least two rows (click the # column; Shift-click for a range), set the first and last colors, then ramp.'
        : 'Fill the rows between the first and last selected row with colors blended between theirs.';
    }
    message(bad); paintStrip();
  }

  function badRows() {
    const bad = new Set();
    S.rows.forEach((r) => { if (r.to !== null && !(r.to > lo(r))) bad.add(r); });
    return bad;
  }
  function message(bad) {
    const ordered = S.rows.map((r) => r).sort((a, b) => (lo(a) === lo(b) ? 0 : lo(a) < lo(b) ? -1 : 1));
    const notes = [];
    if (!S.rows.length) { msg.textContent = 'No rows: everything will be transparent. Use + Add row.'; msg.className = 'le-msg le-warn'; return; }
    if (bad.size) notes.push('To must be greater than From (check the highlighted ' + (bad.size === 1 ? 'row' : 'rows') + ').');
    const gaps = [], overlaps = [];
    for (let i = 0; i + 1 < ordered.length; i++) {
      const a = ordered[i], b = ordered[i + 1];
      if (a.to === null) { overlaps.push(fmt(a.from) + ' and up'); continue; }
      if (b.from === null) { overlaps.push('below ' + fmt(a.to)); continue; }
      if (a.to < b.from) gaps.push(fmt(a.to) + ' to ' + fmt(b.from));
      else if (a.to > b.from) overlaps.push(fmt(b.from) + ' to ' + fmt(Math.min(a.to, b.to === null ? a.to : b.to)));
    }
    if (overlaps.length) notes.push('Overlap at ' + overlaps.slice(0, 3).join(', ') + ': where bands overlap, the one with the larger From wins.');
    if (gaps.length) notes.push('Gap: ' + gaps.slice(0, 3).join(', ') + (gaps.length > 3 ? ', ...' : '') + ' has no color (transparent).');
    if (!notes.length) {
      const openLow = ordered[0].from === null, openHigh = ordered[ordered.length - 1].to === null;
      if (openLow && openHigh) notes.push('Every value is colored.');
      else notes.push((openLow ? 'Values above the last To' : 'Values below the first From' + (openHigh ? '' : ' or above the last To')) + ' are transparent.');
    }
    msg.textContent = notes.join(' ');
    msg.className = 'le-msg' + (bad.size ? ' le-warn' : '');
  }
  function paintStrip() {
    strip.replaceChildren();
    const rows = S.rows; if (!rows.length) return;
    const room = Math.max(1, Math.floor((strip.clientWidth || 600) / 64));
    const every = Math.max(1, Math.ceil(rows.length / room));
    rows.forEach((r, i) => {
      const b = document.createElement('div'); b.className = 'le-blk'; b.style.background = rgba(r);
      if (i % every === 0) { const l = document.createElement('span'); l.className = 'le-lab'; l.textContent = r.from === null ? '\u2212\u221e' : fmt(r.from); b.appendChild(l); }
      strip.appendChild(b);
    });
    const last = rows[rows.length - 1];
    if (last.to !== null) { const l = document.createElement('span'); l.className = 'le-lab le-end'; l.textContent = fmt(last.to); strip.lastChild.appendChild(l); }
  }

  function chain(r, col, old) {
    if (!contiguous() || old === null) return;
    const i = S.rows.indexOf(r);
    if (col === 'to' && S.rows[i + 1] && S.rows[i + 1].from === old && r.to !== null) S.rows[i + 1].from = r.to;
    if (col === 'from' && S.rows[i - 1] && S.rows[i - 1].to === old) S.rows[i - 1].to = r.from;
  }
  function editBound(r, col, inp) {
    const text = inp.value.trim();
    const v = text === '' ? null : Number(text);
    if ((text !== '' && !Number.isFinite(v)) || (col === 'from' && v === null && S.rows.indexOf(r) !== 0)) { inp.value = fmt(r[col]); return; }
    const old = r[col]; r[col] = v; chain(r, col, old); paint(); commit();
  }
  function select(r, e) {
    const i = S.rows.indexOf(r);
    if (e.shiftKey && S.anchor !== null) {
      const a = Math.min(S.anchor, i), b = Math.max(S.anchor, i);
      if (!(e.ctrlKey || e.metaKey)) S.sel.clear();
      for (let k = a; k <= b; k++) S.sel.add(S.rows[k]);
    } else if (e.ctrlKey || e.metaKey) {
      if (S.sel.has(r)) S.sel.delete(r); else S.sel.add(r);
      S.anchor = i;
    } else { S.sel.clear(); S.sel.add(r); S.anchor = i; }
    paint();
  }
  function structural() { build(); commit(); }
  function split(r) {
    const i = S.rows.indexOf(r);
    const mid = r.to === null ? (r.from === null ? 0 : r.from + 1) : r.from === null ? r.to - 1 : (r.from + r.to) / 2;
    const copy = { ...r, from: mid };
    r.to = mid;
    S.rows.splice(i + 1, 0, copy);
    structural();
  }
  function remove(r) { S.sel.delete(r); S.rows.splice(S.rows.indexOf(r), 1); structural(); }
  function addRow() {
    const last = S.rows[S.rows.length - 1];
    if (!last) { S.rows.push({ from: 0, to: 1, r: 128, g: 128, b: 128, a: 255 }); return structural(); }
    const width = last.to !== null && last.from !== null && last.to > last.from ? last.to - last.from : 1;
    const from = last.to !== null ? last.to : (last.from === null ? 0 : last.from) + width;
    if (last.to === null) last.to = from;
    S.rows.push({ ...last, from, to: from + width });
    structural();
  }
  function sortRows() { S.rows.sort((a, b) => (lo(a) === lo(b) ? 0 : lo(a) < lo(b) ? -1 : 1)); structural(); }
  function ramp(withAlpha) {
    const idx = [...S.sel].map((r) => S.rows.indexOf(r)).filter((i) => i >= 0).sort((a, b) => a - b);
    if (idx.length < 2) return;
    const a = idx[0], b = idx[idx.length - 1], A = S.rows[a], B = S.rows[b];
    const mid = (r) => (r.to === null ? (r.from === null ? 0 : r.from) : r.from === null ? r.to : (r.from + r.to) / 2);
    const span = mid(B) - mid(A);
    for (let k = a + 1; k < b; k++) {
      const R = S.rows[k];
      const t = Math.max(0, Math.min(1, span !== 0 ? (mid(R) - mid(A)) / span : (k - a) / (b - a)));
      for (const c of withAlpha ? ['r', 'g', 'b', 'a'] : ['r', 'g', 'b']) R[c] = Math.round(A[c] + (B[c] - A[c]) * t);
    }
    paint(); commit();
  }

  root.querySelector('[data-act=add]').onclick = addRow;
  root.querySelector('[data-act=sort]').onclick = sortRows;
  root.querySelector('[data-act=ramp-rgb]').onclick = () => ramp(false);
  root.querySelector('[data-act=ramp-rgba]').onclick = () => ramp(true);
  paint();
}
"""

_legend_editor = st.components.v2.component(
    "legend_editor", html=LEGEND_EDITOR_HTML, css=LEGEND_EDITOR_CSS, js=LEGEND_EDITOR_JS,
)


def legend_to_js(rows):
    """Legend rows [from, to, r, g, b, a] as the editor's dicts (a blank from/to stays None)."""
    return [
        {"from": r[0], "to": r[1], "r": int(r[2]), "g": int(r[3]), "b": int(r[4]), "a": int(r[5])}
        for r in normalize_legend(rows)
    ]


def legend_from_js(rows):
    """The editor's dict rows back to [from, to, r, g, b, a] lists, in the order the user left them (not sorted)."""
    return [[r.get("from"), r.get("to"), r["r"], r["g"], r["b"], r["a"]] for r in rows]


def legend_editor(rows, *, version, key="legend_editor"):
    """Show the band editor seeded with `rows`. Returns the user's edited rows when they changed something since the
    table was last handed over, else None.

    `version` (any string) says which table this is: when it changes the editor drops its own copy and shows `rows`
    (a new map, an import, Reset). An edit that was made against an older version is ignored, so it can't overwrite a
    table Python has just replaced."""
    try:
        result = _legend_editor(
            key=key, data={"rows": legend_to_js(rows), "version": version},
            default={"edit": None}, on_edit_change=lambda: None,
        )
        edit = result.edit
    except StreamlitAPIException as e:     # custom components unavailable here (e.g. AppTest): a plain table
        if "not registered" not in str(e):
            raise
        cols = ["From", "To", "R", "G", "B", "Alpha"]
        df = pd.DataFrame(normalize_legend(rows), columns=cols)
        shown = st.data_editor(df, num_rows="dynamic", hide_index=True, key=f"{key}_{version}_fallback")
        out = [
            [None if pd.isna(rec[c]) else float(rec[c]) for c in ("From", "To")]
            + [int(rec[c]) if pd.notna(rec[c]) else (255 if c == "Alpha" else 0) for c in ("R", "G", "B", "Alpha")]
            for rec in shown.to_dict("records")
        ]
        return None if out == [list(r) for r in normalize_legend(rows)] else out
    if isinstance(edit, dict) and edit.get("v") == version:
        edited = legend_from_js(edit.get("rows") or [])
        if edited != [list(r) for r in rows]:
            return edited
    return None
