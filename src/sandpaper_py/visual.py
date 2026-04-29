"""Pattern-aware visual element picker.

The user clicks an element. SandPaper walks up the DOM until it finds a
parent whose direct children share a (tag, classes) signature — those are
the rows. Subsequent clicks capture fields, with the selector computed
relative to the row container. A live preview shows the resulting table.

The output is a complete preset (row_selector + per-field selectors), not
a flat selector map.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .utils import slugify_key

log = logging.getLogger("sandpaper.visual")


@dataclass
class PickResult:
    row_selector: str | None = None
    selectors: dict[str, str] = field(default_factory=dict)
    samples: dict[str, list[str]] = field(default_factory=dict)
    row_count: int = 0

    def to_preset_dict(self) -> dict[str, Any]:
        return {
            "extractor": "selector",
            "row_selector": self.row_selector,
            "selectors": self.selectors,
        }


PICKER_JS = r"""
() => {
  if (window.__sandpaperPicker) return;

  const sp = window.__sandpaperPicker = {
    rowSelector: null,
    rowElements: [],
    fields: [],     // [{label, selector, samples: [...]}]
    done: false
  };

  // ---------- styles ----------
  const style = document.createElement('style');
  style.textContent = `
    .__sp_row_outline { outline: 2px solid #16a34a !important; outline-offset: -2px !important; background: rgba(22,163,74,0.05) !important; }
    .__sp_field_outline { outline: 2px solid #f59e0b !important; outline-offset: -2px !important; }
    .__sp_hover { outline: 2px dashed #2563eb !important; outline-offset: -2px !important; }
    #__sp_panel { position: fixed; top: 16px; right: 16px; z-index: 2147483647;
      background: #0f172a; color: #e2e8f0; padding: 14px 16px; border-radius: 10px;
      font-family: ui-sans-serif, system-ui, sans-serif; font-size: 13px;
      box-shadow: 0 12px 40px rgba(0,0,0,0.45); max-width: 480px; line-height: 1.45; }
    #__sp_panel h3 { margin: 0 0 8px; font-size: 14px; font-weight: 600; color: #fff; }
    #__sp_panel button { background: #1e293b; color: #e2e8f0; border: 1px solid #334155;
      padding: 4px 10px; border-radius: 4px; cursor: pointer; font: inherit; margin-right: 4px; }
    #__sp_panel button:hover { background: #334155; }
    #__sp_panel button.primary { background: #16a34a; border-color: #16a34a; color: #fff; }
    #__sp_panel button.danger { background: #dc2626; border-color: #dc2626; color: #fff; }
    #__sp_panel table { border-collapse: collapse; width: 100%; font-size: 11px; margin-top: 6px; }
    #__sp_panel th, #__sp_panel td { border: 1px solid #334155; padding: 3px 6px; text-align: left;
      max-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    #__sp_panel th { background: #1e293b; color: #fff; font-weight: 500; }
    #__sp_panel .hint { font-size: 11px; opacity: 0.7; margin-top: 4px; }
    #__sp_panel .pill { display: inline-block; padding: 1px 7px; border-radius: 999px;
      font-size: 11px; background: #1e3a8a; color: #dbeafe; margin-right: 4px; }
    #__sp_panel code { background: #0b1220; padding: 1px 4px; border-radius: 3px; font-size: 11px; }
    #__sp_panel .field-row { display: flex; gap: 4px; align-items: center; margin: 3px 0; }
    #__sp_panel .field-row .label { flex: 1; }
  `;
  document.head.appendChild(style);

  // ---------- panel ----------
  const panel = document.createElement('div');
  panel.id = '__sp_panel';
  document.body.appendChild(panel);
  render();

  // ---------- helpers ----------
  function classSig(el) {
    if (!el || !el.classList) return '';
    return Array.from(el.classList).slice().sort().join('.');
  }

  function nodeSignature(el) {
    return el.tagName + ':' + classSig(el);
  }

  function classSelector(el) {
    if (!el.classList || !el.classList.length) return el.tagName.toLowerCase();
    const parts = Array.from(el.classList).map(c => '.' + CSS.escape(c)).join('');
    return el.tagName.toLowerCase() + parts;
  }

  function findRowContainer(target) {
    // Walk up. At each ancestor, check whether its parent has 2+ siblings
    // sharing this ancestor's signature. The first such level is the row level.
    let node = target;
    while (node && node !== document.body && node.parentElement) {
      const parent = node.parentElement;
      const sig = nodeSignature(node);
      const siblings = Array.from(parent.children).filter(c => nodeSignature(c) === sig);
      if (siblings.length >= 2 && classSig(node)) {
        return { row: node, siblings, parent };
      }
      node = parent;
    }
    return null;
  }

  function broaden(currentRow) {
    // Walk one level up: pick the parent if the parent also has siblings of same sig
    if (!currentRow || !currentRow.parentElement) return null;
    const parent = currentRow.parentElement;
    const grand = parent.parentElement;
    if (!grand) return null;
    const sig = nodeSignature(parent);
    const siblings = Array.from(grand.children).filter(c => nodeSignature(c) === sig);
    if (siblings.length >= 2) return { row: parent, siblings, parent: grand };
    return null;
  }

  function narrow(currentRow) {
    // Pick a single-element-child if it's the obvious wrapper of content
    if (!currentRow) return null;
    const children = Array.from(currentRow.children).filter(c => c.nodeType === 1);
    if (children.length === 1 && classSig(children[0])) {
      // mirror across siblings
      const parent = currentRow.parentElement;
      if (!parent) return null;
      const sig = nodeSignature(currentRow);
      const rowSiblings = Array.from(parent.children).filter(c => nodeSignature(c) === sig);
      const inner = rowSiblings.map(r => {
        const k = Array.from(r.children).filter(c => c.nodeType === 1);
        return k.length === 1 ? k[0] : null;
      });
      if (inner.every(x => x !== null)) {
        return { row: inner[0], siblings: inner, parent: currentRow };
      }
    }
    return null;
  }

  function relativeSelector(root, target) {
    const path = [];
    let node = target;
    while (node && node !== root) {
      let part = node.tagName.toLowerCase();
      if (node.classList && node.classList.length) {
        part = classSelector(node);
      } else {
        const parent = node.parentElement;
        if (parent) {
          const sameTag = Array.from(parent.children).filter(c => c.tagName === node.tagName);
          if (sameTag.length > 1) {
            part += `:nth-of-type(${sameTag.indexOf(node) + 1})`;
          }
        }
      }
      path.unshift(part);
      node = node.parentElement;
      if (path.length > 8) break;
    }
    return path.join(' > ');
  }

  function absoluteSelector(target) {
    return classSelector(target);
  }

  function suggestLabel(el) {
    const aria = el.getAttribute('aria-label');
    if (aria) return slugify(aria);
    const cls = (el.classList && el.classList[0]) || '';
    if (cls) return slugify(cls);
    return el.tagName.toLowerCase();
  }

  function slugify(s) {
    return String(s).replace(/[^a-zA-Z0-9]+/g, '_').replace(/^_+|_+$/g, '').toLowerCase() || 'field';
  }

  function clearOutlines(cls) {
    document.querySelectorAll('.' + cls).forEach(el => el.classList.remove(cls));
  }

  function applyOutline(elements, cls) {
    elements.forEach(el => el.classList.add(cls));
  }

  function render() {
    const phase = sp.rowSelector ? 'fields' : 'rows';
    let html = `<h3>SandPaper picker <span class="pill">${phase}</span></h3>`;

    if (phase === 'rows') {
      html += `<div>Click any element inside one of the repeating items (a card, a row, a result).</div>
        <div class="hint">Press Esc to cancel.</div>`;
    } else {
      const sample = sp.rowElements.slice(0, 3).map(r => (r.textContent || '').trim().slice(0, 60)).join(' / ');
      html += `<div><strong>${sp.rowElements.length}</strong> rows detected:
        <code>${escapeHtml(sp.rowSelector)}</code></div>
        <div style="margin: 6px 0;">
          <button id="__sp_broader">&uarr; Broader</button>
          <button id="__sp_narrower">&darr; Narrower</button>
          <button id="__sp_redo_row" class="danger">Reset rows</button>
        </div>
        <div class="hint">Sample: ${escapeHtml(sample)}</div>
        <div style="margin-top: 10px;"><strong>Click fields inside one row:</strong></div>`;
      if (sp.fields.length) {
        sp.fields.forEach((f, i) => {
          html += `<div class="field-row">
            <span class="label"><strong>${escapeHtml(f.label)}</strong>
              <code>${escapeHtml(f.selector)}</code></span>
            <button data-undo="${i}">x</button>
          </div>`;
        });
        html += renderPreview();
      }
      html += `<div style="margin-top: 10px;">
        <button id="__sp_done" class="primary">Done (Esc)</button>
      </div>`;
    }
    panel.innerHTML = html;

    // wire
    const broader = document.getElementById('__sp_broader');
    if (broader) broader.onclick = () => onBroader();
    const narrower = document.getElementById('__sp_narrower');
    if (narrower) narrower.onclick = () => onNarrower();
    const redo = document.getElementById('__sp_redo_row');
    if (redo) redo.onclick = () => resetRows();
    const done = document.getElementById('__sp_done');
    if (done) done.onclick = () => finish();
    panel.querySelectorAll('[data-undo]').forEach(btn => {
      btn.onclick = (e) => {
        const i = parseInt(btn.getAttribute('data-undo'), 10);
        sp.fields.splice(i, 1);
        render();
      };
    });
  }

  function renderPreview() {
    if (!sp.fields.length) return '';
    const rows = Math.min(5, sp.rowElements.length);
    const labels = sp.fields.map(f => f.label);
    let html = '<table><thead><tr>';
    labels.forEach(l => html += `<th>${escapeHtml(l)}</th>`);
    html += '</tr></thead><tbody>';
    for (let i = 0; i < rows; i++) {
      html += '<tr>';
      sp.fields.forEach(f => {
        const v = (f.samples[i] || '').slice(0, 60);
        html += `<td>${escapeHtml(v)}</td>`;
      });
      html += '</tr>';
    }
    html += '</tbody></table>';
    return html;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c =>
      ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function setRows(detection) {
    clearOutlines('__sp_row_outline');
    sp.rowElements = detection.siblings;
    sp.rowSelector = absoluteSelector(detection.row);
    applyOutline(sp.rowElements, '__sp_row_outline');
    sp.fields = [];
    render();
  }

  function resetRows() {
    clearOutlines('__sp_row_outline');
    clearOutlines('__sp_field_outline');
    sp.rowSelector = null;
    sp.rowElements = [];
    sp.fields = [];
    render();
  }

  function onBroader() {
    if (!sp.rowElements.length) return;
    const det = broaden(sp.rowElements[0]);
    if (det) setRows(det);
    else alert('No broader pattern found.');
  }

  function onNarrower() {
    if (!sp.rowElements.length) return;
    const det = narrow(sp.rowElements[0]);
    if (det) setRows(det);
    else alert('No narrower wrapper found.');
  }

  function captureField(target) {
    const containingRow = sp.rowElements.find(r => r.contains(target));
    if (!containingRow) {
      alert('Click inside one of the highlighted (green) rows.');
      return;
    }
    const rel = relativeSelector(containingRow, target);
    const suggested = suggestLabel(target);
    const label = window.prompt('Column label:', suggested);
    if (!label) return;
    const slug = slugify(label);
    const samples = sp.rowElements.map(r => {
      const found = r.querySelector(rel);
      return found ? (found.textContent || '').trim() : '';
    });
    sp.fields.push({ label: slug, selector: rel, samples });
    clearOutlines('__sp_field_outline');
    sp.rowElements.forEach(r => {
      const f = r.querySelector(rel);
      if (f) f.classList.add('__sp_field_outline');
    });
    render();
  }

  function finish() {
    sp.done = true;
  }

  // ---------- event handlers ----------
  function onMove(e) {
    if (panel.contains(e.target)) return;
    document.querySelectorAll('.__sp_hover').forEach(el => el.classList.remove('__sp_hover'));
    if (e.target && e.target.classList) e.target.classList.add('__sp_hover');
  }

  function onClick(e) {
    if (panel.contains(e.target)) return;
    e.preventDefault();
    e.stopPropagation();
    if (!sp.rowSelector) {
      const det = findRowContainer(e.target);
      if (!det) {
        alert('Could not find a repeating pattern around that element. Try a different one.');
        return;
      }
      setRows(det);
    } else {
      captureField(e.target);
    }
  }

  function onKey(e) {
    if (e.key === 'Escape') finish();
  }

  document.addEventListener('mousemove', onMove, true);
  document.addEventListener('click', onClick, true);
  document.addEventListener('keydown', onKey, true);
}
"""


def pick_pattern(
    url: str,
    timeout_seconds: int = 600,
) -> PickResult:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(f"playwright not installed: {exc}") from exc

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        try:
            context = browser.new_context()
            page = context.new_page()
            page.goto(url, timeout=60000)
            page.wait_for_load_state("networkidle")
            page.evaluate(PICKER_JS)
            log.info("Pattern picker open. Click a row, then click fields. Esc to finish.")
            page.wait_for_function(
                "() => window.__sandpaperPicker && window.__sandpaperPicker.done",
                timeout=timeout_seconds * 1000,
            )
            row_selector = page.evaluate("() => window.__sandpaperPicker.rowSelector")
            raw_fields = page.evaluate("() => window.__sandpaperPicker.fields")
            row_count = page.evaluate("() => window.__sandpaperPicker.rowElements.length")
        finally:
            browser.close()

    selectors: dict[str, str] = {}
    samples: dict[str, list[str]] = {}
    seen: dict[str, int] = {}
    for item in raw_fields or []:
        base = slugify_key(item.get("label") or "field")
        count = seen.get(base, 0) + 1
        seen[base] = count
        key = base if count == 1 else f"{base}_{count}"
        selectors[key] = item["selector"]
        samples[key] = list(item.get("samples", []))

    return PickResult(
        row_selector=row_selector,
        selectors=selectors,
        samples=samples,
        row_count=int(row_count or 0),
    )


def pick_selectors(
    url: str, save_to: Path | None = None, timeout_seconds: int = 600
) -> dict[str, str]:
    """Backward-compatible flat-map output. Internally calls pick_pattern."""
    result = pick_pattern(url, timeout_seconds=timeout_seconds)
    flat = dict(result.selectors)
    if save_to:
        save_to.parent.mkdir(parents=True, exist_ok=True)
        save_to.write_text(json.dumps(flat, indent=2), encoding="utf-8")
    return flat


LOGIN_OVERLAY_JS = r"""
() => {
  if (window.__sandpaperLogin) return;
  window.__sandpaperLogin = { done: false };

  const panel = document.createElement('div');
  panel.id = '__sp_login_panel';
  panel.style.cssText = `
    position: fixed; top: 16px; right: 16px; z-index: 2147483647;
    background: #0f172a; color: #e2e8f0; padding: 16px 18px; border-radius: 10px;
    font-family: ui-sans-serif, system-ui, sans-serif; font-size: 13px;
    box-shadow: 0 12px 40px rgba(0,0,0,0.45); max-width: 360px; line-height: 1.45;
  `;
  panel.innerHTML = `
    <div style="font-weight:600;margin-bottom:6px;color:#fff;">SandPaper login session</div>
    <div>Log in normally. When you are signed in and ready, click the button below.</div>
    <button id="__sp_login_done" style="margin-top:10px;background:#16a34a;color:#fff;border:0;padding:6px 12px;border-radius:4px;cursor:pointer;font:inherit;">
      Save session
    </button>
  `;
  document.body.appendChild(panel);
  document.getElementById('__sp_login_done').onclick = () => {
    window.__sandpaperLogin.done = true;
  };
}
"""


RECORDER_JS = r"""
() => {
  if (window.__sandpaperRecorder) return;
  const sp = window.__sandpaperRecorder = { actions: [], done: false, picking: false };

  function bestSelector(el) {
    if (!(el instanceof Element)) return '';
    if (el.id) return '#' + CSS.escape(el.id);
    const path = [];
    while (el && el.nodeType === Node.ELEMENT_NODE && el !== document.body) {
      let part = el.nodeName.toLowerCase();
      if (el.classList && el.classList.length) {
        const cls = Array.from(el.classList).slice(0, 3).map(c => '.' + CSS.escape(c)).join('');
        part += cls;
      } else {
        const parent = el.parentElement;
        if (parent) {
          const sameTag = Array.from(parent.children).filter(c => c.nodeName === el.nodeName);
          if (sameTag.length > 1) {
            part += `:nth-of-type(${sameTag.indexOf(el) + 1})`;
          }
        }
      }
      path.unshift(part);
      el = el.parentElement;
      if (path.length > 6) break;
    }
    return path.join(' > ');
  }

  function inToolbar(el) {
    return el && (el.closest && el.closest('#__sp_recorder_panel'));
  }

  // ---- panel ----
  const panel = document.createElement('div');
  panel.id = '__sp_recorder_panel';
  panel.style.cssText = `
    position: fixed; top: 16px; right: 16px; z-index: 2147483647;
    background: #0f172a; color: #e2e8f0; padding: 12px 14px; border-radius: 10px;
    font-family: ui-sans-serif, system-ui, sans-serif; font-size: 13px;
    box-shadow: 0 12px 40px rgba(0,0,0,0.45); max-width: 360px; line-height: 1.45;
  `;
  panel.innerHTML = `
    <div style="font-weight:600;color:#fff;margin-bottom:6px;">SandPaper recorder</div>
    <div>Use the page normally. Clicks, form fills, and navigations are captured.</div>
    <div style="margin-top:8px;display:flex;gap:6px;">
      <button id="__sp_capture" style="background:#16a34a;color:#fff;border:0;padding:5px 10px;border-radius:4px;cursor:pointer;font:inherit;">Capture extract</button>
      <button id="__sp_done" style="background:#2563eb;color:#fff;border:0;padding:5px 10px;border-radius:4px;cursor:pointer;font:inherit;">Save &amp; finish</button>
    </div>
    <div id="__sp_log" style="margin-top:8px;max-height:200px;overflow:auto;font-size:11px;opacity:0.85;"></div>
  `;
  document.body.appendChild(panel);

  function log(text) {
    const el = document.getElementById('__sp_log');
    const div = document.createElement('div');
    div.textContent = text;
    el.prepend(div);
  }

  function record(action) {
    sp.actions.push(action);
    log(action.action + ': ' + (action.url || action.selector || action.value || ''));
  }

  // ---- event listeners ----
  document.addEventListener('click', (e) => {
    if (inToolbar(e.target)) return;
    const sel = bestSelector(e.target);
    if (sel) record({ action: 'click', selector: sel });
  }, true);

  document.addEventListener('change', (e) => {
    if (inToolbar(e.target)) return;
    const t = e.target;
    if (!(t instanceof HTMLInputElement) && !(t instanceof HTMLTextAreaElement) && !(t instanceof HTMLSelectElement)) return;
    const sel = bestSelector(t);
    if (!sel) return;
    if (t instanceof HTMLSelectElement) {
      record({ action: 'fill', selector: sel, value: t.value });
    } else {
      record({ action: 'fill', selector: sel, value: t.value });
    }
  }, true);

  // Capture initial URL on load
  if (document.location && document.location.href) {
    record({ action: 'goto', url: document.location.href });
  }

  // navigation hook (best-effort; some SPAs use pushState)
  const _push = history.pushState;
  history.pushState = function(...args) {
    _push.apply(this, args);
    record({ action: 'goto', url: document.location.href });
  };

  // toolbar buttons
  document.getElementById('__sp_capture').onclick = () => {
    sp.picking = true;
  };
  document.getElementById('__sp_done').onclick = () => {
    sp.done = true;
  };
}
"""


def record_session(
    url: str,
    save_to: Path,
    name: str | None = None,
    timeout_seconds: int = 3600,
) -> Path:
    """Open a headful browser, record interactions, run the picker on demand, save a recipe."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(f"playwright not installed: {exc}") from exc

    save_to.parent.mkdir(parents=True, exist_ok=True)
    actions: list[dict] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        try:
            context = browser.new_context()
            page = context.new_page()
            page.goto(url, timeout=60000)
            page.evaluate(RECORDER_JS)
            log.info(
                "Recorder open. Use the page normally; click 'Capture extract' "
                "to add an extract step; click 'Save & finish' when done."
            )

            def capture_extract() -> None:
                """When picking is requested, run the pattern picker and append an extract step."""
                page.evaluate(PICKER_JS)
                page.wait_for_function(
                    "() => window.__sandpaperPicker && window.__sandpaperPicker.done",
                    timeout=timeout_seconds * 1000,
                )
                row_sel = page.evaluate("() => window.__sandpaperPicker.rowSelector")
                fields = page.evaluate("() => window.__sandpaperPicker.fields")
                page.evaluate("() => { window.__sandpaperPicker = undefined; }")
                if row_sel and fields:
                    selectors: dict[str, str] = {}
                    seen: dict[str, int] = {}
                    for item in fields:
                        from .utils import slugify_key

                        base = slugify_key(item.get("label") or "field")
                        c = seen.get(base, 0) + 1
                        seen[base] = c
                        key = base if c == 1 else f"{base}_{c}"
                        selectors[key] = item["selector"]
                    actions.append(
                        {
                            "action": "extract_paginated",
                            "row_selector": row_sel,
                            "selectors": selectors,
                            "max_pages": 1,
                        }
                    )

            # poll loop: watch for done flag, drain actions, handle picker requests
            import time

            while True:
                state = page.evaluate(
                    "() => ({ done: window.__sandpaperRecorder.done, "
                    "picking: window.__sandpaperRecorder.picking, "
                    "actions: window.__sandpaperRecorder.actions })"
                )
                if state.get("picking"):
                    page.evaluate(
                        "() => { window.__sandpaperRecorder.picking = false; "
                        "window.__sandpaperRecorder.actions = []; }"
                    )
                    actions.extend(state.get("actions", []))
                    capture_extract()
                    page.evaluate(RECORDER_JS)
                    continue
                if state.get("done"):
                    actions.extend(state.get("actions", []))
                    break
                time.sleep(0.4)
        finally:
            browser.close()

    actions = _compress_actions(actions)
    if not any(a.get("action") in {"extract", "extract_paginated"} for a in actions):
        log.warning("recorded session has no extract step; recipe will produce zero rows")

    from .recipes import Recipe, save_recipe

    recipe = Recipe(
        name=name or save_to.stem,
        steps=actions,
    )
    return save_recipe(recipe, save_to)


def _compress_actions(actions: list[dict]) -> list[dict]:
    """Squash repeated identical fills (every keystroke fires change events)."""
    out: list[dict] = []
    for action in actions:
        if (
            action.get("action") == "fill"
            and out
            and out[-1].get("action") == "fill"
            and out[-1].get("selector") == action.get("selector")
        ):
            out[-1] = action
        elif (
            action.get("action") == "goto"
            and out
            and out[-1].get("action") == "goto"
            and out[-1].get("url") == action.get("url")
        ):
            continue
        else:
            out.append(action)
    return out


def login_session(
    url: str,
    save_to: Path,
    timeout_seconds: int = 1800,
) -> Path:
    """Open a headful browser, let the user log in, save storage_state to disk."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(f"playwright not installed: {exc}") from exc

    save_to.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        try:
            context = browser.new_context()
            page = context.new_page()
            page.goto(url, timeout=60000)
            page.evaluate(LOGIN_OVERLAY_JS)
            log.info("Login session open. Sign in, then click 'Save session' or press Esc.")
            page.wait_for_function(
                "() => window.__sandpaperLogin && window.__sandpaperLogin.done",
                timeout=timeout_seconds * 1000,
            )
            context.storage_state(path=str(save_to))
        finally:
            browser.close()
    return save_to
