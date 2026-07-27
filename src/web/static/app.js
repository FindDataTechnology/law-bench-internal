// Minimal client-side behavior for the evaluation-rules UI:
//  1. Confirm destructive (delete) actions.
//  2. Dynamic criterion rows on the create-rubric form.
//  3. Toggle inline criterion editing on the rubric detail page.
//
// UI strings are read from window.__LOCALE__, bootstrapped by base.html from
// the same catalog the server renders. Every tr() call takes an English
// fallback so the page degrades gracefully (never throws) if the bootstrap is
// absent.
const L = window.__LOCALE__ || {};
// Data-label catalog (machine keys -> display labels), bootstrapped by
// base.html alongside __LOCALE__. Degrades to raw keys if absent.
const LABELS = window.__LABELS__ || {};

function tr(path, fallback) {
  let node = L;
  for (const part of String(path).split('.')) {
    if (node && Object.prototype.hasOwnProperty.call(node, part)) node = node[part];
    else return fallback != null ? fallback : String(path);
  }
  return typeof node === 'string' ? node : (fallback != null ? fallback : String(path));
}

function fmt(template, obj) {
  return String(template).replace(/\{(\w+)\}/g, (m, k) => (obj[k] != null ? String(obj[k]) : m));
}

// Resolve a data-value machine key to a localized display label. Returns the
// raw value when the kind/value is unmapped (mirrors src/web/i18n.py::label_for).
function labelFor(kind, value) {
  const cat = LABELS[kind] || {};
  return Object.prototype.hasOwnProperty.call(cat, value) ? cat[value] : value;
}

// Localized display title for a seeded prompt name draft_<type_key> (zh:
// "<type>起草", en: "<type> Drafting"). A versioned variant draft_<type>_v<N>
// appends " v<N>" to disambiguate the law-refined variant from baseline.
// Falls back to the raw name otherwise.
function titleForPrompt(name) {
  name = name || '';
  const m = /^draft_([a-z_]+?)(?:_v(\d+))?$/.exec(name);
  if (!m) return name;
  const ct = LABELS['contract_type'] || {};
  if (!Object.prototype.hasOwnProperty.call(ct, m[1])) return name;
  const base = (window.__LANG__ === 'zh') ? ct[m[1]] + '起草' : ct[m[1]] + ' Drafting';
  return m[2] ? base + ' v' + m[2] : base;
}

// Localized display title for a seeded rubric name contract_<type_key>_vN (zh:
// "<type>评价规则 vN", en: "<type> Rubric vN"). The " vN" suffix always appears
// so v1 and v2 variants are distinguishable. Falls back to the raw name otherwise.
function titleForRubric(name) {
  name = name || '';
  const m = /^contract_([a-z_]+?)_v(\d+)$/.exec(name);
  if (!m) return name;
  const ct = LABELS['contract_type'] || {};
  if (!Object.prototype.hasOwnProperty.call(ct, m[1])) return name;
  const base = (window.__LANG__ === 'zh') ? ct[m[1]] + '评价规则' : ct[m[1]] + ' Rubric';
  return base + ' v' + m[2];
}

document.addEventListener('DOMContentLoaded', () => {
  // 1. Confirm before destructive submits.
  document.querySelectorAll('form[data-confirm]').forEach((form) => {
    form.addEventListener('submit', (e) => {
      if (!window.confirm(form.dataset.confirm)) e.preventDefault();
    });
  });

  // 2. Dynamic criteria editor on the create form.
  const addBtn = document.getElementById('add-criterion');
  if (addBtn) {
    const wrap = document.getElementById('criteria-list');
    addBtn.addEventListener('click', () => wrap.appendChild(makeCriterionRow()));
    if (!wrap.children.length) wrap.appendChild(makeCriterionRow());
  }

  // 3. Toggle inline edit forms on the detail page.
  document.querySelectorAll('[data-toggle-edit]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const row = btn.closest('.criterion-row');
      row.querySelector('.crit-edit').classList.toggle('open');
    });
  });
});

function makeCriterionRow() {
  const div = document.createElement('div');
  div.className = 'criterion-row';
  div.innerHTML =
    '<div class="crow-head">' +
    '<strong>' + tr('crit_row.new', 'New criterion') + '</strong>' +
    '<button type="button" class="btn btn-sm btn-danger" data-remove-row>' + tr('crit_row.remove', 'Remove') + '</button>' +
    '</div>' +
    '<div class="row"><label>' + tr('crit_row.name', 'Name') + '</label><input type="text" name="criteria_name" required placeholder="' + tr('crit_row.name_placeholder', 'e.g. party_identification') + '"></div>' +
    '<div class="grid2">' +
    '<div class="row"><label>' + tr('crit_row.description', 'Description') + '</label><textarea name="criteria_description" required></textarea></div>' +
    '<div class="row"><label>' + tr('crit_row.guidance', 'Guidance') + '</label><textarea name="criteria_guidance" required></textarea></div>' +
    '</div>';
  div.querySelector('[data-remove-row]').addEventListener('click', () => div.remove());
  return div;
}

// === Prompt compare: WIP form state, async run, localStorage mirror =========
//
// DB is the source of truth; localStorage mirrors (1) the in-progress compare
// form (so a refresh does not lose config) and (2) a compact result per compare
// (matrix + verdicts + reasoning, NO draft_text) under a byte-budget LRU cap.
// draft_text is lazy-fetched on demand. Cache key is versioned; DB wins on load.
const CACHE_PREFIX = 'lawcmp:v1:';
const CACHE_INDEX_KEY = CACHE_PREFIX + 'index';   // compare ids, most-recent last
const CACHE_BUDGET = 4 * 1024 * 1024;             // ~4 MB ceiling
const WIP_KEY = CACHE_PREFIX + 'wip';

function lsGetJSON(key, fallback) {
  try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; }
  catch (e) { return fallback; }
}
function lsSetJSON(key, val) {
  try { localStorage.setItem(key, JSON.stringify(val)); }
  catch (e) { /* ignore quota on small metadata keys */ }
}
function lsSetRaw(key, val) {
  localStorage.setItem(key, val);   // may throw QuotaExceededError; caller evicts
}
function lsCachedBytes() {
  let n = 0;
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i);
    if (k && k.startsWith(CACHE_PREFIX)) n += (localStorage.getItem(k) || '').length;
  }
  return n;
}
function cacheKey(id) { return CACHE_PREFIX + 'compare:' + id; }

function bumpLru(id) {
  const idx = lsGetJSON(CACHE_INDEX_KEY, []);
  const i = idx.indexOf(id);
  if (i !== -1) idx.splice(i, 1);
  idx.push(id);
  lsSetJSON(CACHE_INDEX_KEY, idx);
}
function evictToFit(needed) {
  const idx = lsGetJSON(CACHE_INDEX_KEY, []);
  let guard = 0;
  while (idx.length && (lsCachedBytes() + needed > CACHE_BUDGET) && guard++ < 1000) {
    const oldId = idx.shift();
    try { localStorage.removeItem(cacheKey(oldId)); } catch (e) {}
  }
  lsSetJSON(CACHE_INDEX_KEY, idx);
}
function mirrorCompare(compare) {
  // Compact mirror: everything the matrix needs, excluding draft_text.
  const compact = {
    id: compare.id, label: compare.label, contract_type: compare.contract_type,
    rubric_name: compare.rubric_name, task_desc: compare.task_desc,
    gen_mode: compare.gen_mode, n_drafts: compare.n_drafts, created_at: compare.created_at,
    runs: (compare.runs || []).map(r => ({
      id: r.id, prompt_name: r.prompt_name, prompt_type: r.prompt_type,
      variant_label: r.variant_label, score: r.score, all_pass: r.all_pass,
      n_passed: r.n_passed, n_criteria: r.n_criteria,
      criteria_results: (r.criteria_results || []).map(c => ({
        criterion_id: c.criterion_id, verdict: c.verdict, reasoning: c.reasoning,
      })),
    })),
    matrix: compare.matrix,
    _v: 1,
  };
  let payload;
  try { payload = JSON.stringify(compact); } catch (e) { return; }
  evictToFit(payload.length);
  try {
    lsSetRaw(cacheKey(compare.id), payload);
  } catch (e) {
    evictToFit(payload.length + 1024);
    try { lsSetRaw(cacheKey(compare.id), payload); } catch (e2) { /* DB remains truth */ }
  }
  bumpLru(compare.id);
}
function readMirror(id) {
  const m = lsGetJSON(cacheKey(id), null);
  return (m && m._v === 1) ? m : null;
}
function dropMirror(id) {
  try { localStorage.removeItem(cacheKey(id)); } catch (e) {}
  const idx = lsGetJSON(CACHE_INDEX_KEY, []);
  const i = idx.indexOf(id);
  if (i !== -1) { idx.splice(i, 1); lsSetJSON(CACHE_INDEX_KEY, idx); }
}

function escapeHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// --- compare form: WIP persistence + async submit -------------------------- #
function initCompareForm() {
  const form = document.getElementById('compare-form');
  if (!form) return;

  const wip = lsGetJSON(WIP_KEY, null);
  if (wip) {
    if (wip.task) document.getElementById('f-task').value = wip.task;
    if (wip.contract_type) document.getElementById('f-contract_type').value = wip.contract_type;
    if (wip.rubric_name) document.getElementById('f-rubric_name').value = wip.rubric_name;
    if (wip.mode) document.getElementById('f-mode').value = wip.mode;
    if (wip.n_drafts) document.getElementById('f-n_drafts').value = wip.n_drafts;
    if (wip.label) document.getElementById('f-label').value = wip.label;
    if (Array.isArray(wip.prompts)) {
      document.querySelectorAll('input[name="prompts"]').forEach(cb => {
        cb.checked = wip.prompts.indexOf(cb.value) !== -1;
      });
    }
  }

  const saveWip = () => {
    const prompts = Array.from(document.querySelectorAll('input[name="prompts"]:checked'))
      .map(cb => cb.value);
    lsSetJSON(WIP_KEY, {
      task: document.getElementById('f-task').value,
      contract_type: document.getElementById('f-contract_type').value,
      rubric_name: document.getElementById('f-rubric_name').value,
      mode: document.getElementById('f-mode').value,
      n_drafts: document.getElementById('f-n_drafts').value,
      label: document.getElementById('f-label').value,
      prompts,
    });
  };
  form.addEventListener('input', saveWip);
  form.addEventListener('change', saveWip);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const status = document.getElementById('compare-status');
    const btn = document.getElementById('compare-submit');
    const prompts = Array.from(document.querySelectorAll('input[name="prompts"]:checked'))
      .map(cb => cb.value);
    if (prompts.length < 2) { status.textContent = tr('matrix.select_min', 'Select at least 2 prompts.'); return; }
    const body = {
      contract_type: document.getElementById('f-contract_type').value,
      rubric_name: document.getElementById('f-rubric_name').value,
      task_desc: document.getElementById('f-task').value,
      prompts,
      mode: document.getElementById('f-mode').value,
      n_drafts: parseInt(document.getElementById('f-n_drafts').value || '1', 10),
      label: document.getElementById('f-label').value || null,
    };
    btn.disabled = true;
    status.textContent = tr('matrix.running', 'Running compare… this may take a minute.');
    try {
      const r = await fetch('/api/compare', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.error || ('HTTP ' + r.status));
      }
      const data = await r.json();
      mirrorCompare(data);            // cache before navigating
      saveWip();                       // keep WIP so re-running is one edit
      window.location.href = '/compare/' + data.id;
    } catch (err) {
      status.textContent = tr('matrix.error', 'Error: ') + err.message;
      btn.disabled = false;
    }
  });
}

// --- compare detail: paint from cache, reconcile with DB, render matrix ---- #
function initCompareDetail() {
  const id = window.LAWCMP_COMPARE_ID;
  if (id === undefined) return;

  const loading = document.getElementById('compare-loading');
  const errBox = document.getElementById('compare-error');
  const result = document.getElementById('compare-result');
  const headline = document.getElementById('compare-headline');
  const meta = document.getElementById('compare-meta');
  const table = document.getElementById('compare-matrix');
  const legend = document.getElementById('compare-legend');
  const reasonBox = document.getElementById('compare-reasoning');
  const reasonTitle = document.getElementById('compare-reasoning-title');
  const reasonText = document.getElementById('compare-reasoning-text');

  document.getElementById('compare-reasoning-close').addEventListener('click', () => {
    reasonBox.style.display = 'none';
  });
  document.getElementById('compare-draft-close').addEventListener('click', () => {
    document.getElementById('compare-draft').style.display = 'none';
  });

  function render(compare) {
    loading.style.display = 'none';
    result.style.display = '';
    meta.textContent = fmt(tr('matrix.meta', '{ct} · {rubric} · {mode} · N={n}'), {
      ct: labelFor('contract_type', compare.contract_type || '-'),
      rubric: titleForRubric(compare.rubric_name || '-'),
      mode: labelFor('mode', compare.gen_mode || '-'),
      n: compare.n_drafts || 1,
    });
    const runs = compare.runs || [];
    const passed = runs.reduce((a, r) => a + (r.n_passed || 0), 0);
    const total = runs.reduce((a, r) => a + (r.n_criteria || 0), 0);
    headline.textContent = fmt(tr('matrix.headline', '{n} run(s); {passed}/{total} criteria passed (last-draft counts).'), {
      n: runs.length, passed, total,
    });
    renderMatrix(compare);
    legend.textContent = (compare.n_drafts > 1)
      ? tr('matrix.legend_multi', 'Cells show pass-rate (k/N). Click a cell for judge reasoning.')
      : tr('matrix.legend_single', 'Cells show pass/fail. Click a cell for judge reasoning.');
  }

  function renderMatrix(compare) {
    const m = compare.matrix || { criteria: [], columns: [], cells: {} };
    const runIdByPrompt = {};
    (compare.runs || []).forEach(r => { runIdByPrompt[r.prompt_name] = r.id; });

    const passLabel = tr('matrix.pass', 'pass');
    const failLabel = tr('matrix.fail', 'fail');
    let html = '<thead><tr><th>' + escapeHtml(tr('matrix.criterion', 'criterion')) + '</th>';
    m.columns.forEach(col => {
      const head = col.prompt_type ? labelFor('prompt_type', col.prompt_type) : titleForPrompt(col.prompt_name);
      html += `<th>${escapeHtml(head)}<br><span class="muted">${escapeHtml(col.prompt_name)}</span></th>`;
    });
    html += '</tr></thead><tbody>';
    m.criteria.forEach(crit => {
      html += `<tr><td><strong>${escapeHtml(crit.id)}</strong><div class="muted">${escapeHtml(crit.title || '')}</div></td>`;
      m.columns.forEach(col => {
        const cell = (m.cells[col.prompt_name] || {})[crit.id] || {};
        const reasoning = cell.reasoning || '';
        let mark, cls;
        if ('verdict' in cell) {
          mark = cell.verdict === 'pass' ? '✓ ' + passLabel : '✗ ' + failLabel;
          cls = cell.verdict === 'pass' ? 'pass' : 'fail';
        } else {
          mark = `${cell.n_pass || 0}/${cell.n || 0}`;
          cls = 'rate';
        }
        html += `<td class="cell ${cls}" data-reasoning="${escapeHtml(reasoning)}" `
              + `data-criterion="${escapeHtml(crit.id)}" data-prompt="${escapeHtml(col.prompt_name)}">${mark}</td>`;
      });
      html += '</tr>';
    });
    const viewDraftLabel = escapeHtml(tr('matrix.view_draft', 'view draft'));
    html += '<tr><td class="muted">' + viewDraftLabel + '</td>';
    m.columns.forEach(col => {
      const runId = runIdByPrompt[col.prompt_name];
      html += `<td><button type="button" class="btn btn-sm" data-draft-run="${runId || ''}" data-prompt="${escapeHtml(col.prompt_name)}">${viewDraftLabel}</button></td>`;
    });
    html += '</tr></tbody>';
    table.innerHTML = html;

    table.querySelectorAll('td.cell[data-reasoning]').forEach(td => {
      td.style.cursor = 'pointer';
      td.addEventListener('click', () => {
        reasonTitle.textContent = `${titleForPrompt(td.dataset.prompt)} · ${td.dataset.criterion}`;
        reasonText.textContent = td.dataset.reasoning || tr('matrix.no_reasoning', '(no reasoning recorded)');
        reasonBox.style.display = '';
      });
    });
    table.querySelectorAll('button[data-draft-run]').forEach(btn => {
      btn.addEventListener('click', () => loadDraft(id, btn.dataset.draftRun, btn.dataset.prompt));
    });
  }

  async function loadDraft(compareId, runId, promptName) {
    const box = document.getElementById('compare-draft');
    const title = document.getElementById('compare-draft-title');
    const text = document.getElementById('compare-draft-text');
    title.textContent = tr('matrix.draft_title', 'Draft · ') + titleForPrompt(promptName);
    text.textContent = tr('matrix.loading', 'Loading…');
    box.style.display = '';
    try {
      const r = await fetch(`/api/compare/${compareId}/run/${runId}/draft`);
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const d = await r.json();
      text.textContent = d.draft_text || tr('matrix.empty_draft', '(empty draft)');
    } catch (e) {
      text.textContent = tr('matrix.error', 'Error: ') + e.message;
    }
  }

  // 1. Paint from cache first (instant), if present and version-current.
  const cached = readMirror(id);
  if (cached) render(cached);

  // 2. Reconcile with the server. DB wins; drop cache if the compare was deleted.
  fetch(`/api/compare/${id}`).then(r => {
    if (r.status === 404) {
      dropMirror(id);
      loading.style.display = 'none';
      result.style.display = 'none';
      errBox.style.display = '';
      errBox.textContent = fmt(tr('matrix.not_found', 'Compare #{id} was not found on the server.'), { id });
      return null;
    }
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }).then(compare => {
    if (!compare) return;
    mirrorCompare(compare);   // refresh cache (DB wins)
    render(compare);
  }).catch(() => {
    if (!cached) {
      loading.style.display = 'none';
      errBox.style.display = '';
      errBox.textContent = tr('matrix.error_loading', 'Error loading compare (and no cached copy available).');
    }
    // else: keep the cached render; server temporarily unavailable.
  });
}

document.addEventListener('DOMContentLoaded', () => {
  initCompareForm();
  initCompareDetail();
});
