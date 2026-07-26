/* Thelivu Command Center — SPA.
   View registry + hash router; every view is a load(main) function.
   Adding a future surface = one entry in VIEWS + a render function. */
'use strict';

const $ = (sel, root) => (root || document).querySelector(sel);

/* ── tiny DOM/util helpers ─────────────────────────────────────────────── */
function el(html) {
  const t = document.createElement('template');
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}
function esc(s) {
  return String(s == null ? '' : s)
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
}
function ago(ts) {
  if (!ts) return 'never';
  const d = new Date(ts);
  if (isNaN(d)) return String(ts).slice(0, 16);
  const s = (Date.now() - d.getTime()) / 1000;
  if (s < 90) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}
function fdate(ts) { return ts ? String(ts).slice(0, 10) : '—'; }
function pill(status) { return `<span class="pill ${esc(status)}">${esc(status || '—')}</span>`; }
function inr(usd) { return `₹${(usd * (state.inrRate || 84)).toFixed(2)}`; }

/* Minimal markdown → HTML for drafts/briefs (escaped first — no injection). */
function md(text) {
  if (!text) return '<span class="muted">— empty —</span>';
  let h = esc(text);
  h = h.replace(/^### (.*)$/gm, '<h3>$1</h3>')
       .replace(/^## (.*)$/gm, '<h2>$1</h2>')
       .replace(/^# (.*)$/gm, '<h1>$1</h1>')
       .replace(/^&gt; (.*)$/gm, '<blockquote>$1</blockquote>')
       .replace(/^[-*] (.*)$/gm, '<li>$1</li>')
       .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
       .replace(/\*([^*\n]+)\*/g, '<i>$1</i>')
       .replace(/`([^`]+)`/g, '<code>$1</code>')
       .replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, '<a href="$2" target="_blank">$1</a>')
       .replace(/^---+$/gm, '<hr>');
  return h.split(/\n{2,}/).map(p =>
    /^<(h\d|li|blockquote|hr)/.test(p.trim()) ? p.replace(/\n/g, ' ') : `<p>${p.replace(/\n/g, '<br>')}</p>`
  ).join('\n');
}

/* ── API ───────────────────────────────────────────────────────────────── */
async function api(path, opts = {}) {
  if (opts.body && typeof opts.body !== 'string') {
    opts.body = JSON.stringify(opts.body);
    opts.headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers);
  }
  const r = await fetch('/api' + path, opts);
  if (r.status === 401) { showLogin(); throw new Error('unauthorized'); }
  let data = null;
  try { data = await r.json(); } catch (e) { /* empty body */ }
  if (!r.ok) {
    const msg = (data && (data.error || data.blocked || data.hint)) || `HTTP ${r.status}`;
    const err = new Error(msg);
    err.data = data;
    err.status = r.status;
    throw err;
  }
  return data;
}

/* ── Toasts ────────────────────────────────────────────────────────────── */
function toast(msg, kind = '', ms = 5000) {
  const t = el(`<div class="toast ${kind}">${esc(msg)}</div>`);
  $('#toasts').appendChild(t);
  setTimeout(() => t.remove(), ms);
}

/* ── Modals ────────────────────────────────────────────────────────────── */
function openModal(inner, { danger } = {}) {
  const back = el(`<div class="modal-back"><div class="modal ${danger ? 'danger' : ''}"></div></div>`);
  back.firstElementChild.appendChild(inner);
  back.addEventListener('click', e => { if (e.target === back) back.remove(); });
  document.getElementById('modal-root').appendChild(back);
  return () => back.remove();
}

function confirmModal(title, message, { danger = false, label = 'Confirm' } = {}) {
  return new Promise(resolve => {
    const box = el(`<div><h3>${esc(title)}</h3><p class="muted">${message}</p>
      <div class="modal-actions">
        <button class="btn" data-x="no">Cancel</button>
        <button class="btn ${danger ? 'danger' : 'primary'}" data-x="yes">${esc(label)}</button>
      </div></div>`);
    const close = openModal(box, { danger });
    box.querySelector('[data-x=no]').onclick = () => { close(); resolve(false); };
    box.querySelector('[data-x=yes]').onclick = () => { close(); resolve(true); };
  });
}

function editModal(title, initial, { mono = true, rows = 14, hint = '' } = {}) {
  return new Promise(resolve => {
    const box = el(`<div><h3>${esc(title)}</h3>
      ${hint ? `<p class="muted small">${esc(hint)}</p>` : ''}
      <textarea class="${mono ? 'mono' : ''}" rows="${rows}"></textarea>
      <div class="modal-actions">
        <button class="btn" data-x="no">Cancel</button>
        <button class="btn primary" data-x="yes">Save</button>
      </div></div>`);
    box.querySelector('textarea').value = initial || '';
    const close = openModal(box);
    box.querySelector('[data-x=no]').onclick = () => { close(); resolve(null); };
    box.querySelector('[data-x=yes]').onclick = () => {
      const v = box.querySelector('textarea').value;
      close(); resolve(v);
    };
  });
}

/* ── Job watcher — polls /api/jobs/<id>, shows live progress ───────────── */
function watchJob(jobId, title) {
  return new Promise(resolve => {
    let hidden = false;
    const box = el(`<div><h3>${esc(title)}</h3>
      <div class="prog"><div style="width:2%"></div></div>
      <div class="prog-msg">starting…</div>
      <div class="modal-actions"><button class="btn small" data-x="hide">Run in background</button></div>
    </div>`);
    const close = openModal(box);
    box.querySelector('[data-x=hide]').onclick = () => { hidden = true; close(); };
    const tick = async () => {
      let j;
      try { j = await api(`/jobs/${jobId}`); }
      catch (e) { if (!hidden) close(); toast(`Job lost: ${e.message}`, 'err'); return resolve(null); }
      if (!hidden) {
        box.querySelector('.prog > div').style.width = `${Math.max(3, j.progress * 100)}%`;
        box.querySelector('.prog-msg').textContent = j.message || '';
      }
      if (j.state === 'running') return setTimeout(tick, 1500);
      if (!hidden) close();
      if (j.state === 'done') toast(`${title} — done ✓`, 'ok');
      else toast(`${title} — failed: ${j.error || 'unknown'}`, 'err', 9000);
      resolve(j);
    };
    tick();
  });
}

/* ── State + router ────────────────────────────────────────────────────── */
const state = { view: 'overview', gateCount: 0, inrRate: 84 };

const VIEWS = [
  ['overview',  '◉',  'Overview',      vOverview],
  ['gate',      '📬', 'Gate',          vGate],
  ['stories',   '📰', 'Stories',       vStories],
  ['carousels', '🖼', 'Carousels',     vCarousels],
  ['reels',     '🎬', 'Reels',         vReels],
  ['digs',      '🗺', 'Digs',          vDigs],
  ['cos',       '🧭', 'Chief of staff', vCos],
  ['sources',   '📡', 'Sources',       vSources],
  ['ingest',    '📥', 'Ingest',        vIngest],
  ['system',    '⚙',  'System',        vSystem],
  ['costs',     '₹',  'Costs',         vCosts],
];

function nav() {
  const wrap = $('#nav-items');
  wrap.innerHTML = '';
  for (const [name, icon, label] of VIEWS) {
    const b = el(`<button class="nav-item ${state.view === name ? 'active' : ''}">
      <span>${icon}</span><span>${label}</span>
      ${name === 'gate' && state.gateCount ? `<span class="badge">${state.gateCount}</span>` : ''}
    </button>`);
    b.onclick = () => { location.hash = '#/' + name; };
    wrap.appendChild(b);
  }
}

async function route() {
  const name = (location.hash || '#/overview').replace('#/', '') || 'overview';
  const entry = VIEWS.find(v => v[0] === name) || VIEWS[0];
  state.view = entry[0];
  nav();
  const main = $('#main');
  main.innerHTML = '<div class="muted" style="padding:30px">Loading…</div>';
  try { await entry[3](main); }
  catch (e) {
    if (e.message !== 'unauthorized')
      main.innerHTML = `<div class="card danger">Failed to load: ${esc(e.message)}</div>`;
  }
}
window.addEventListener('hashchange', route);

/* ── Shared: status dots + gate badge ──────────────────────────────────── */
function paintStatus(breaker, voiceUp) {
  const b = $('#nav-breaker'), v = $('#nav-voice');
  if (breaker) {
    b.className = 'nav-dot ' + (breaker.open ? 'bad' : 'ok');
    b.title = breaker.open ? `Breaker OPEN: ${breaker.reason}` : 'APIs: breaker closed';
  }
  if (voiceUp !== undefined) {
    v.className = 'nav-dot ' + (voiceUp ? 'ok' : 'warn');
    v.title = voiceUp ? 'Voice server up (:3901)' : 'Voice server down';
  }
}

/* ══ OVERVIEW ═══════════════════════════════════════════════════════════ */
async function vOverview(main) {
  const d = await api('/overview');
  state.gateCount = (d.gate || []).length;
  state.breaker = d.breaker;
  paintStatus(d.breaker, d.voice_up); nav();
  const c = d.counts || {};
  main.innerHTML = '';
  main.appendChild(el(`<div><h1>Overview</h1>
    <div class="sub">The engine at a glance — ${new Date().toUTCString().slice(17, 25)} UTC</div></div>`));

  if (d.breaker.open)
    main.appendChild(el(`<div class="banner warn"><span class="big">⛔</span><div>
      <b>Quota breaker open</b> — ${esc(d.breaker.reason)}<br>
      <span class="muted small">Model stages are parked. Run attended (<code>./attend cycle</code>) or wait for credit.
      ${d.breaker.until ? 'Auto-retry ' + ago(d.breaker.until).replace(' ago', '') : ''}</span></div></div>`));

  // Gold, not red: hitting the cap is the governor working, not an outage.
  if (d.budget && d.budget.over)
    main.appendChild(el(`<div class="banner"><span class="big">💰</span><div>
      <b>Daily budget reached</b> — $${(d.budget.spent_today_usd).toFixed(2)} of $${Number(d.budget.cap_usd).toFixed(2)}<br>
      <span class="muted small">Model stages are parked until midnight UTC. Publishing and approvals still work.
      Change the cap in <a href="#/system">System</a>.</span></div></div>`));

  main.appendChild(el(d.gate.length
    ? `<div class="banner"><span class="big">📬</span><div><b>${d.gate.length}</b> draft${d.gate.length > 1 ? 's' : ''} waiting at your gate
       — <a href="#/gate">review now</a></div></div>`
    : `<div class="banner"><span class="big">✓</span><div class="muted">Gate clear — nothing waiting on you.</div></div>`));

  main.appendChild(el(`<div class="tiles">
    <div class="tile gold"><div class="v">${d.gate.length}</div><div class="l">at the gate</div></div>
    <div class="tile"><div class="v">${(d.held || []).length}</div><div class="l">held</div></div>
    <div class="tile"><div class="v">${(d.agents || []).length}</div><div class="l">live agents</div></div>
    <div class="tile"><div class="v">${(d.digs || []).length}</div><div class="l">active digs</div></div>
    <div class="tile"><div class="v">${d.published}</div><div class="l">published</div></div>
    <div class="tile"><div class="v">${inr(d.today_cost.usd)}</div><div class="l">cost today</div></div>
  </div>`));

  const g = el(`<div class="grid2"><div></div><div></div></div>`);
  const left = g.children[0], right = g.children[1];

  left.appendChild(el(`<div class="eyebrow">⚡ Live agents ${d.agents.length ? '— ' + d.agents.length + ' running' : '— idle'}</div>`));
  for (const a of d.agents) {
    const m = Math.floor(a.secs / 60);
    left.appendChild(el(`<div class="item"><span class="id">${esc(a.skill)}</span>
      <span class="muted small">· ${esc(a.model || '')} · ${m}m ${a.secs % 60}s</span>
      <div class="meta">${esc((a.topic || '').slice(0, 70))}</div></div>`));
  }
  left.appendChild(el(`<div class="eyebrow">Recent runs</div>`));
  for (const r of d.recent) {
    left.appendChild(el(`<div class="item clickable" onclick="location.hash='#/stories';setTimeout(()=>openRun(${r.id}),50)">
      <div class="row between"><div>
        <span class="id">#${r.id}</span> <span class="title">${esc((r.throughline || 'Untitled').slice(0, 80))}</span>
        <div class="meta">${fdate(r.created_at)} · ${esc(r.source || '')} · gate ${esc(r.trust_gate || '—')}</div>
      </div>${pill(r.status)}</div></div>`));
  }

  right.appendChild(el(`<div class="eyebrow">Quick submit</div>`));
  const qs = el(`<div class="card"><textarea placeholder="What's the story?"></textarea>
    <div class="actions"><button class="btn primary block">Submit topic →</button></div></div>`);
  qs.querySelector('button').onclick = async () => {
    const v = qs.querySelector('textarea').value.trim();
    if (!v) return;
    await api('/topics', { method: 'POST', body: { topic: v } });
    qs.querySelector('textarea').value = '';
    toast('Topic queued — picked up within ~2 min.', 'ok');
  };
  right.appendChild(qs);

  right.appendChild(el(`<div class="eyebrow">Digs in flight</div>`));
  if (!d.digs.length) right.appendChild(el(`<div class="muted small">No active digs — open one in Digs.</div>`));
  for (const dg of d.digs.slice(0, 6)) {
    right.appendChild(el(`<div class="item clickable" onclick="location.hash='#/digs'">
      <span class="id">#${dg.id}</span> ${esc((dg.title || '').slice(0, 46))}
      <div class="meta">updated ${ago(dg.updated_at)} ${pill(dg.status)}</div></div>`));
  }
  main.appendChild(g);
}

/* ══ RUN DETAIL (shared by Gate + Stories) ══════════════════════════════ */
window.openRun = async function (rid) {
  let d;
  try { d = await api(`/runs/${rid}`); }
  catch (e) { return toast(e.message, 'err'); }
  const run = d.run;
  const box = el(`<div>
    <div class="row between"><h3>#${run.id} ${pill(run.status)}</h3></div>
    <p><b>${esc(run.throughline || 'Untitled')}</b></p>
    <div class="muted small">${fdate(run.created_at)} · ${esc(run.source || '')} · trust gate: ${esc(run.trust_gate || '—')}
      ${d.article_url ? ` · <a href="${esc(d.article_url)}" target="_blank">article page ↗</a>` : ''}</div>
    <div class="actions" data-x="actions"></div>
    <details open><summary>Draft</summary><div><div class="reader">${md(run.draft_text)}</div></div></details>
    <details><summary>Verification report</summary><div><pre class="raw">${esc(run.verification_report || '—')}</pre></div></details>
    <details><summary>Review notes</summary><div><pre class="raw">${esc(run.review_text || '—')}</pre></div></details>
    ${d.suggestions ? `<details open><summary>AI suggestions (saved)</summary><div><div class="reader">${md(d.suggestions)}</div></div></details>` : ''}
    ${(d.carousels || []).length ? `<div class="eyebrow">Carousels</div>` + d.carousels.map(c =>
      `<div class="small">🖼 #${c.id} ${pill(c.status)} ${c.ig_permalink ? `<a href="${esc(c.ig_permalink)}" target="_blank">on IG ↗</a>` : ''}</div>`).join('') : ''}
    ${(d.reels || []).length ? `<div class="eyebrow">Reels</div>` + d.reels.map(r =>
      `<div class="small">🎬 #${r.id} ${pill(r.status)} ${r.ig_permalink ? `<a href="${esc(r.ig_permalink)}" target="_blank">on IG ↗</a>` : ''}</div>`).join('') : ''}
  </div>`);
  const close = openModal(box);
  const actions = box.querySelector('[data-x=actions]');
  const refresh = () => { close(); openRun(rid); };

  const gateish = ['pending_human', 'held', 'hold', 'needs_attention'].includes(run.status);
  if (gateish) {
    addBtn(actions, '✓ Approve & publish', 'primary', async () => {
      if (!await confirmModal('Publish this story?',
        `<b>#${run.id}</b> — ${esc(run.throughline || '')}<br><br>This is the gated action: it posts to the Telegram channel, creates the public article page, and adds the bio link. It cannot be unpublished quietly.`,
        { danger: false, label: 'Publish' })) return;
      const r = await api(`/runs/${rid}/approve`, { method: 'POST', body: {} });
      close();
      const j = await watchJob(r.job, `Publish run #${rid}`);
      if (j && j.state === 'done') route();
    });
    addBtn(actions, '📖 Edit draft', '', async () => {
      const v = await editModal(`Edit draft #${rid}`, run.draft_text, {
        hint: 'Your edit, saved verbatim — the human gate at work. No model touches this.' });
      if (v == null) return;
      await api(`/runs/${rid}`, { method: 'PATCH', body: { draft_text: v } });
      toast('Draft saved.', 'ok'); refresh();
    });
    addBtn(actions, '✨ AI suggestions', '', async () => {
      try {
        const r = await api(`/runs/${rid}/suggest`, { method: 'POST', body: {} });
        const j = await watchJob(r.job, `Suggestions for #${rid}`);
        if (j && j.state === 'done') refresh();
      } catch (e) {
        toast(e.data && e.data.hint ? e.data.hint : e.message, 'err', 9000);
      }
    });
    addBtn(actions, '🔄 Recheck…', '', async () => {
      const v = await editModal(`Recheck #${rid} — editorial direction (optional)`, '', {
        mono: false, rows: 5,
        hint: 'The engine re-develops the story. Add direction or paste source links; leave empty to just recheck.' });
      if (v == null) return;
      const r = await api(`/runs/${rid}/recheck`, { method: 'POST', body: { note: v.trim() } });
      toast(r.note, r.breaker && r.breaker.open ? '' : 'ok', 8000); refresh();
    });
    if (run.status === 'pending_human')
      addBtn(actions, '⏸ Hold', '', async () => {
        await api(`/runs/${rid}/action`, { method: 'POST', body: { action: 'hold' } });
        toast('Held.'); close(); route();
      });
    else
      addBtn(actions, '📬 Requeue to gate', '', async () => {
        await api(`/runs/${rid}/action`, { method: 'POST', body: { action: 'requeue' } });
        toast('Requeued to your gate.'); close(); route();
      });
    addBtn(actions, '✗ Kill', 'danger', async () => {
      if (!await confirmModal('Kill this story?', `#${run.id} will be marked killed.`, { danger: true, label: 'Kill' })) return;
      await api(`/runs/${rid}/action`, { method: 'POST', body: { action: 'kill' } });
      toast('Killed.'); close(); route();
    });
  }
  if (run.status === 'published') {
    addBtn(actions, '🖼 Make carousel', '', async () => {
      const r = await api('/carousels', { method: 'POST', body: { run_id: rid } });
      toast(r.note, 'ok', 9000);
    });
    addBtn(actions, '🎬 Make reel', '', async () => { close(); makeReelFlow(rid); });
  }
};

function addBtn(parent, label, cls, fn) {
  const b = el(`<button class="btn ${cls}">${label}</button>`);
  b.onclick = async () => {
    b.disabled = true;
    try { await fn(); } catch (e) { toast(e.message, 'err', 8000); }
    b.disabled = false;
  };
  parent.appendChild(b);
}

function runCard(r) {
  const c = el(`<div class="item clickable">
    <div class="row between"><div style="min-width:0">
      <span class="id">#${r.id}</span> <span class="title">${esc((r.throughline || 'Untitled').slice(0, 95))}</span>
      <div class="meta">${fdate(r.created_at)} · ${esc(r.source || '')} · gate ${esc(r.trust_gate || '—')}</div>
    </div>${pill(r.status)}</div></div>`);
  c.onclick = () => openRun(r.id);
  return c;
}

/* ══ GATE ═══════════════════════════════════════════════════════════════ */
async function vGate(main) {
  const [pending, held] = await Promise.all([
    api('/runs?status=pending_human&limit=50'),
    api('/runs?status=held&limit=30'),
  ]);
  state.gateCount = pending.runs.length; nav();
  main.innerHTML = '';
  main.appendChild(el(`<div><h1>The gate</h1>
    <div class="sub">${pending.runs.length} pending · ${held.runs.length} held — <b>approving is the only action that publishes.</b></div></div>`));
  if (!pending.runs.length && !held.runs.length)
    main.appendChild(el(`<div class="card">Nothing at the gate. The engine will bring drafts here.</div>`));
  for (const r of pending.runs) main.appendChild(runCard(r));
  if (held.runs.length) {
    main.appendChild(el(`<div class="eyebrow">⏸ Held / needs attention — read why, then requeue, recheck, publish, or kill</div>`));
    for (const r of held.runs) main.appendChild(runCard(r));
  }
}

/* ══ STORIES ════════════════════════════════════════════════════════════ */
async function vStories(main) {
  main.innerHTML = '';
  main.appendChild(el(`<div><h1>Stories</h1><div class="sub">Every pipeline run — click any to open the full dossier.</div></div>`));
  const bar = el(`<div class="row" style="margin-bottom:12px">
    <select style="width:auto">
      ${['all', 'pending_human', 'published', 'held', 'investigating', 'writing', 'recheck_requested', 'killed'].map(s => `<option>${s}</option>`).join('')}
    </select>
    <input placeholder="Search throughline…" style="flex:1;min-width:140px">
    <button class="btn">Search</button></div>`);
  main.appendChild(bar);
  const list = el(`<div></div>`);
  main.appendChild(list);
  async function load() {
    list.innerHTML = '<div class="muted">Loading…</div>';
    const st = bar.querySelector('select').value;
    const q = bar.querySelector('input').value.trim();
    const d = await api(`/runs?status=${st}&q=${encodeURIComponent(q)}&limit=60`);
    list.innerHTML = '';
    if (!d.runs.length) list.appendChild(el(`<div class="muted">No runs match.</div>`));
    for (const r of d.runs) list.appendChild(runCard(r));
  }
  bar.querySelector('button').onclick = load;
  bar.querySelector('select').onchange = load;
  bar.querySelector('input').onkeydown = e => { if (e.key === 'Enter') load(); };
  await load();
}

/* ══ CAROUSELS ══════════════════════════════════════════════════════════ */
async function vCarousels(main) {
  const d = await api('/carousels?limit=20');
  paintStatus(d.breaker);
  main.innerHTML = '';
  main.appendChild(el(`<div><h1>Carousels</h1>
    <div class="sub">The "receipts" deep-dive — optional per story, reels are the reach default.
    Click a slide to edit its headline.</div></div>`));

  const mk = el(`<div class="card"><div class="row">
    <input type="number" placeholder="published run #" style="width:150px">
    <button class="btn">➕ Make carousel</button></div></div>`);
  mk.querySelector('button').onclick = async () => {
    const rid = parseInt(mk.querySelector('input').value);
    if (!rid) return;
    try {
      const r = await api('/carousels', { method: 'POST', body: { run_id: rid } });
      toast(r.note, 'ok', 9000); route();
    } catch (e) { toast(e.message, 'err', 8000); }
  };
  main.appendChild(mk);

  const actionable = ['pending_review', 'queued', 'composing', 'approved_manual', 'failed'];
  for (const c of d.carousels) {
    const card = el(`<div class="item">
      <div class="row between"><div>
        <span class="id">🖼 #${c.id}</span> · run #${c.run_id} — ${esc((c.story || '').slice(0, 80))}
      </div>${pill(c.status)}</div>
      <div class="slides" data-x="slides"></div>
      <div data-x="warn"></div>
      <details><summary>Caption</summary><div><pre class="raw">${esc(c.caption || '(none)')}</pre></div></details>
      <div class="actions" data-x="actions"></div></div>`);
    const strip = card.querySelector('[data-x=slides]');
    for (const s of (c.slides || [])) {
      const sl = el(`<div class="slide">
        ${s.url ? `<img src="${esc(s.url)}?t=${Date.now() % 1e7}" loading="lazy">` : `<div class="card small">${esc(s.headline)}</div>`}
        <div class="pos">${s.position}</div></div>`);
      sl.onclick = async () => {
        const v = await editModal(`Slide ${s.position} — headline`, s.headline, { mono: false, rows: 4,
          hint: 'Saves to the DB and re-renders the hosted image (what Meta fetches at post time).' });
        if (v == null || !v.trim()) return;
        const r = await api(`/carousels/${c.id}/slides/${s.position}`, { method: 'PATCH', body: { headline: v.trim() } });
        toast(r.refreshed ? 'Slide updated + re-rendered.' : (r.note || 'Saved.'), r.refreshed ? 'ok' : '', 8000);
        route();
      };
      strip.appendChild(sl);
    }
    const acts = card.querySelector('[data-x=actions]');
    if (actionable.includes(c.status)) {
      const noSlides = !(c.slides || []).length;
      if (noSlides)
        card.querySelector('[data-x=warn]').appendChild(el(`<div class="muted small">⏳ Slides not composed yet${d.breaker.open ? ` — breaker open (${esc(d.breaker.reason)}). Attended: <code>./attend carousel ${c.id}</code>` : ' — composes on the next tick.'}</div>`));
      addBtn(acts, '📤 Post to Instagram', 'primary', async () => {
        if (noSlides) return toast('No slides composed yet.', 'err');
        if (!await confirmModal('Post carousel to Instagram?',
          `Carousel <b>#${c.id}</b> (${(c.slides || []).length} slides) goes live on @thelivu.reports.`,
          { label: 'Post' })) return;
        const r = await api(`/carousels/${c.id}/post`, { method: 'POST', body: {} });
        const j = await watchJob(r.job, `Post carousel #${c.id}`);
        if (j && j.state === 'done') route();
      });
      addBtn(acts, '✏️ Edit caption', '', async () => {
        const v = await editModal(`Caption — carousel #${c.id}`, c.caption, { mono: false, rows: 8 });
        if (v == null) return;
        await api(`/carousels/${c.id}`, { method: 'PATCH', body: { caption: v } });
        toast('Caption saved.', 'ok'); route();
      });
      addBtn(acts, '🔄 Rebuild slides', '', async () => {
        const r = await api(`/carousels/${c.id}/action`, { method: 'POST', body: { action: 'rebuild' } });
        toast(r.note, '', 9000);
      });
      addBtn(acts, '✗ Kill', 'danger', async () => {
        if (!await confirmModal('Kill this carousel?', `Carousel #${c.id} will be discarded.`, { danger: true, label: 'Kill' })) return;
        await api(`/carousels/${c.id}/action`, { method: 'POST', body: { action: 'kill' } });
        route();
      });
    } else if (c.status === 'posted' && c.ig_permalink) {
      acts.appendChild(el(`<a class="btn small" href="${esc(c.ig_permalink)}" target="_blank">View on Instagram ↗</a>`));
    }
    main.appendChild(card);
  }
  if (!d.carousels.length) main.appendChild(el(`<div class="card muted">No carousels yet.</div>`));
}

/* ══ REELS ══════════════════════════════════════════════════════════════ */
async function makeReelFlow(rid) {
  const box = el(`<div><h3>🎬 Make reel${rid ? ` — run #${rid}` : ''}</h3>
    <p class="muted small">Free Gemma 4 writes the script, your Chatterbox voice + ffmpeg render locally (a few minutes). You preview before anything posts.</p>
    ${rid ? '' : '<label class="f">Published run #</label><input type="number" data-x="rid">'}
    <label class="f">Theme</label>
    <select data-x="dark"><option value="1" selected>Ink-dark (brand default)</option><option value="0">Light kraft</option></select>
    <div class="modal-actions"><button class="btn" data-x="no">Cancel</button>
    <button class="btn primary" data-x="go">Build reel</button></div></div>`);
  const close = openModal(box);
  box.querySelector('[data-x=no]').onclick = close;
  box.querySelector('[data-x=go]').onclick = async () => {
    const runId = rid || parseInt((box.querySelector('[data-x=rid]') || {}).value);
    if (!runId) return toast('Run # required', 'err');
    const dark = box.querySelector('[data-x=dark]').value === '1';
    close();
    try {
      const r = await api('/reels', { method: 'POST', body: { run_id: runId, dark } });
      const j = await watchJob(r.job, `Build reel for run #${runId}`);
      if (j && j.state === 'done') { location.hash = '#/reels'; route(); }
      else if (j && j.result) {
        const res = j.result;
        if (res.voice_down) toast(`Voice server is down — start it in System, or: ${res.hint}`, 'err', 12000);
        else if (res.needs_terminal) toast(`Attended mode: run ${res.hint} in a terminal.`, '', 12000);
      }
    } catch (e) { toast(e.message, 'err', 9000); }
  };
}

async function vReels(main) {
  const d = await api('/reels?limit=30');
  paintStatus(undefined, d.voice_up);
  main.innerHTML = '';
  main.appendChild(el(`<div><h1>Reels</h1>
    <div class="sub">The reach surface — narrated in your cloned voice, rendered on this laptop.
    Voice server: ${d.voice_up ? '<span style="color:var(--good)">● up</span>' : '<span style="color:var(--brick)">● down</span> (start it in System)'}</div></div>`));

  const mkb = el(`<div class="actions" style="margin-bottom:14px"><button class="btn primary">🎬 Make a reel…</button></div>`);
  mkb.querySelector('button').onclick = () => makeReelFlow(null);
  main.appendChild(mkb);

  for (const r of d.reels) {
    const size = r.size_bytes ? `${Math.round(r.size_bytes / 1024)} KB` : '—';
    const card = el(`<div class="item">
      <div class="row between"><div>
        <span class="id">🎬 #${r.id}</span> · run #${r.run_id || '—'} — ${esc((r.story || '').slice(0, 75))}
        <div class="meta">${fdate(r.created_at)} · ${size}${r.posted_at ? ' · posted ' + fdate(r.posted_at) : ''}</div>
      </div>${pill(r.status)}</div>
      <details><summary>Preview</summary><div>
        <video class="reel" controls preload="none" src="/api/reels/${r.id}.mp4"></video>
      </div></details>
      <details><summary>Caption / narration</summary><div><pre class="raw">${esc(r.caption || '(none)')}</pre></div></details>
      <div class="actions" data-x="actions"></div></div>`);
    const acts = card.querySelector('[data-x=actions]');
    if (r.status !== 'posted' && r.status !== 'killed') {
      addBtn(acts, '📤 Post to Instagram', 'primary', async () => {
        if (!await confirmModal('Post reel to Instagram?',
          `Reel <b>#${r.id}</b> goes live on @thelivu.reports. Preview it first — you're the only gate.`,
          { label: 'Post' })) return;
        const rr = await api(`/reels/${r.id}/post`, { method: 'POST', body: {} });
        const j = await watchJob(rr.job, `Post reel #${r.id}`);
        if (j && j.state === 'done') route();
      });
      addBtn(acts, '✏️ Edit caption', '', async () => {
        const v = await editModal(`Caption — reel #${r.id}`, r.caption, { mono: false, rows: 10 });
        if (v == null) return;
        await api(`/reels/${r.id}/action`, { method: 'POST', body: { action: 'caption', caption: v } });
        toast('Caption saved.', 'ok'); route();
      });
      if (r.run_id) addBtn(acts, '🔁 Remake', '', async () => makeReelFlow(r.run_id));
      addBtn(acts, '✗ Kill', 'danger', async () => {
        if (!await confirmModal('Kill this reel?', `Reel #${r.id} will be discarded (the run keeps its story).`, { danger: true, label: 'Kill' })) return;
        await api(`/reels/${r.id}/action`, { method: 'POST', body: { action: 'kill' } });
        route();
      });
    } else if (r.ig_permalink) {
      acts.appendChild(el(`<a class="btn small" href="${esc(r.ig_permalink)}" target="_blank">View on Instagram ↗</a>`));
    }
    main.appendChild(card);
  }
  if (!d.reels.length) main.appendChild(el(`<div class="card muted">No reels yet — make one from a published story.</div>`));
}

/* ══ DIGS ═══════════════════════════════════════════════════════════════ */
async function vDigs(main) {
  const showClosed = state.digsClosed ? '1' : '0';
  const d = await api(`/digs?closed=${showClosed}`);
  main.innerHTML = '';
  main.appendChild(el(`<div><h1>Digs</h1>
    <div class="sub">Threads investigated over days: scope → records → disprove → promote. Promotion still ends at your gate.</div></div>`));

  const newd = el(`<details><summary>➕ Open a new dig</summary><div>
    <label class="f">Title</label><input data-x="t">
    <label class="f">Falsifiable question</label><textarea data-x="q" rows="2"></textarea>
    <label class="f">Kerala anchor (optional)</label><input data-x="a">
    <label class="f">Hypothesis (optional)</label><textarea data-x="h" rows="2"></textarea>
    <div class="actions"><button class="btn primary">Open dig + queue first step</button></div>
  </div></details>`);
  newd.querySelector('button').onclick = async () => {
    const t = newd.querySelector('[data-x=t]').value.trim();
    if (!t) return toast('Title required', 'err');
    await api('/digs', { method: 'POST', body: {
      title: t, question: newd.querySelector('[data-x=q]').value,
      kerala_anchor: newd.querySelector('[data-x=a]').value,
      hypothesis: newd.querySelector('[data-x=h]').value, advance: true } });
    toast('Dig opened + first step queued.', 'ok'); route();
  };
  main.appendChild(newd);

  if ((d.watchlist || []).length) {
    const wl = el(`<details><summary>📋 Watchlist (${d.watchlist.length}) — start any as a dig</summary><div></div></details>`);
    for (const th of d.watchlist) {
      const row = el(`<div class="item"><div class="row between"><div>
        <b>${esc(th.id || '?')}</b> — <span class="small">${esc((th.question || '').slice(0, 110))}</span>
        <div class="meta">anchor: ${esc(th.kerala_anchor || '—')}</div></div>
        <button class="btn small">Start</button></div></div>`);
      row.querySelector('button').onclick = async () => {
        await api('/digs', { method: 'POST', body: {
          title: (th.id || 'theme').replace(/-/g, ' '), question: th.question || '',
          kerala_anchor: th.kerala_anchor || '', watchlist_id: th.id, advance: true } });
        toast('Dig opened from watchlist.', 'ok'); route();
      };
      wl.querySelector('div').appendChild(row);
    }
    main.appendChild(wl);
  }

  const tog = el(`<div class="row" style="margin:12px 0"><label class="small muted"><input type="checkbox" style="width:auto" ${state.digsClosed ? 'checked' : ''}> show parked/killed</label></div>`);
  tog.querySelector('input').onchange = e => { state.digsClosed = e.target.checked; route(); };
  main.appendChild(tog);

  for (const dg of d.digs) {
    const card = el(`<div class="item">
      <div class="row between"><div><span class="id">#${dg.id}</span> <b>${esc(dg.title)}</b>
        <div class="meta">updated ${ago(dg.updated_at)} · priority ${dg.priority}</div></div>${pill(dg.status)}</div>
      ${dg.question ? `<div class="small" style="margin-top:6px"><b>Q:</b> ${esc(dg.question)}</div>` : ''}
      ${dg.hypothesis ? `<div class="small muted">Hyp: ${esc(dg.hypothesis)}</div>` : ''}
      <div class="actions" data-x="a"></div>
      <details><summary>Investigation log</summary><div data-x="log"><div class="muted small">Loading…</div></div></details>
    </div>`);
    const a = card.querySelector('[data-x=a]');
    const act = (action, okMsg) => async () => {
      const r = await api(`/digs/${dg.id}/action`, { method: 'POST', body: { action } });
      toast(r.note || okMsg, 'ok'); route();
    };
    addBtn(a, '⏭ Advance', '', act('advance', 'Queued.'));
    addBtn(a, '📝 Promote', '', act('promote', 'Promoting.'));
    addBtn(a, '🗒 Note…', '', async () => {
      const v = await editModal(`Owner note — dig #${dg.id}`, '', { mono: false, rows: 4 });
      if (!v || !v.trim()) return;
      await api(`/digs/${dg.id}/action`, { method: 'POST', body: { action: 'note', body: v.trim() } });
      toast('Note added.', 'ok');
    });
    addBtn(a, '🅿 Park', '', act('park', 'Parked.'));
    addBtn(a, '✗ Kill', 'danger', async () => {
      if (!await confirmModal('Kill this dig?', `Dig #${dg.id} — "${esc(dg.title)}"`, { danger: true, label: 'Kill' })) return;
      await act('kill', 'Killed.')();
    });
    card.querySelector('details').addEventListener('toggle', async function (e) {
      if (!this.open || this.dataset.loaded) return;
      this.dataset.loaded = '1';
      const det = await api(`/digs/${dg.id}`);
      const log = card.querySelector('[data-x=log]');
      log.innerHTML = '';
      if (!det.updates.length) log.innerHTML = '<div class="muted small">No steps yet.</div>';
      for (const u of det.updates)
        log.appendChild(el(`<div style="margin:8px 0;border-bottom:1px solid var(--line);padding-bottom:8px">
          <div class="small"><code>${String(u.created_at).slice(0, 16)}</code> · <b>${esc(u.kind)}</b></div>
          <div class="reader" style="max-height:300px">${md((u.body || '').slice(0, 4000))}</div></div>`));
    });
    main.appendChild(card);
  }
  if (!d.digs.length) main.appendChild(el(`<div class="card muted">No digs.</div>`));
}

/* ══ CHIEF OF STAFF ═════════════════════════════════════════════════════ */
async function vCos(main) {
  const d = await api('/cos');
  main.innerHTML = '';
  main.appendChild(el(`<div class="row between"><div><h1>Chief of staff</h1>
    <div class="sub">Works the neglected backlog autonomously — last sweep ${ago(d.last_at)}.</div></div>
    <button class="btn primary">▶ Run sweep now</button></div>`));
  main.querySelector('button').onclick = async () => {
    const r = await api('/cos/run', { method: 'POST', body: {} });
    toast(r.note, 'ok');
  };
  if (!d.brief && !d.acted.length) {
    main.appendChild(el(`<div class="card muted">No sweep has run yet.</div>`));
    return;
  }
  main.appendChild(el(`<div class="eyebrow">Acted autonomously</div>`));
  if (!d.acted.length) main.appendChild(el(`<div class="muted small">No backlog actions needed last sweep.</div>`));
  for (const a of d.acted) main.appendChild(el(`<div class="card accent small">${esc(a)}</div>`));
  if (d.recommendations.length) {
    const det = el(`<details><summary>Why — reasoning for ${d.recommendations.length} call(s)</summary><div></div></details>`);
    for (const rec of d.recommendations)
      det.querySelector('div').appendChild(el(`<div class="small" style="margin:6px 0"><b>${esc(rec.ref || '')}</b> → <code>${esc(rec.action || '')}</code> — ${esc(rec.why || '')}</div>`));
    main.appendChild(det);
  }
  if (d.new_digs.length) {
    main.appendChild(el(`<div class="eyebrow">New threads proposed (auto-opened as digs)</div>`));
    for (const nd of d.new_digs) main.appendChild(el(`<div class="card small"><b>${esc(nd.title || '')}</b> — ${esc(nd.question || '')}</div>`));
  }
  if (d.brief) main.appendChild(el(`<details><summary>Full sweep brief</summary><div><div class="reader">${md(d.brief)}</div></div></details>`));
}

/* ══ SOURCES ════════════════════════════════════════════════════════════ */
async function vSources(main) {
  const d = await api('/sources');
  main.innerHTML = '';
  main.appendChild(el(`<div><h1>Sources</h1><div class="sub">Judged on what they produce — leads → published, kill rate.</div></div>`));

  const rows = d.performance.map(p => {
    const kr = p.runs ? Math.round(p.killed / p.runs * 100) : 0;
    const pr = p.runs ? Math.round(p.published / p.runs * 100) : 0;
    return `<tr><td>${esc(p.source || '—')}</td><td>${p.runs}</td><td>${p.published} (${pr}%)</td>
      <td>${p.killed} (${kr}%)</td><td>${p.held}</td><td>${fdate(p.last_seen)}</td></tr>`;
  }).join('');
  main.appendChild(el(`<div class="tablewrap"><table>
    <tr><th>source</th><th>runs</th><th>published</th><th>killed</th><th>held</th><th>last seen</th></tr>${rows}</table></div>`));

  const g = el(`<div class="grid2" style="margin-top:16px"><div></div><div></div></div>`);
  const L = g.children[0], R = g.children[1];

  L.appendChild(el(`<div class="eyebrow">sources.yaml — active</div>`));
  for (const s of d.yaml_sources.filter(s => s.status === 'active')) {
    const sil = s.silent_cycles >= 10
      ? ` <span style="color:var(--brick)">⚠ silent ${s.silent_cycles} cycles</span>` : '';
    L.appendChild(el(`<div class="small">${s.platform === 'youtube' ? '🎬' : '📰'} <b>${esc(s.name)}</b> · T${s.tier} · ${esc((s.lean || '').slice(0, 50))}${sil}</div>`));
  }
  const cand = d.yaml_sources.filter(s => s.status === 'candidate');
  if (cand.length) {
    const det = el(`<details open><summary>Candidates (${cand.length}) — activate straight from here, live on the next cycle</summary><div></div></details>`);
    for (const s of cand) {
      const row = el(`<div class="row between small" style="margin:5px 0;gap:8px">
        <span style="min-width:0">${s.platform === 'youtube' ? '🎬' : s.has_feed ? '📰' : '🔖'}
          <b>${esc(s.name)}</b> · T${s.tier} · ${esc(s.role || '')}
          <span class="muted">— ${esc((s.lean || '').slice(0, 55))}</span>
          ${s.has_feed ? '' : '<span class="muted">(no feed — reference only)</span>'}</span>
        <span data-x="b" style="flex:none"></span></div>`);
      const slot = row.querySelector('[data-x=b]');
      if (s.activated) slot.innerHTML = '<span class="pill published">active</span>';
      else addBtn(slot, 'Activate', 'small', async () => {
        const r = await api('/sources/candidates/activate', { method: 'POST', body: { id: s.id } });
        toast(r.note, 'ok', 9000); route();
      });
      det.querySelector('div').appendChild(row);
    }
    L.appendChild(det);
  }
  L.appendChild(el(`<div class="eyebrow">Approved via bot / command center</div>`));
  for (const s of d.approved) {
    const row = el(`<div class="row between small" style="margin:3px 0"><span><b>${esc(s.name)}</b> · ${esc(s.platform)} · T${s.tier}</span>
      <button class="btn small">retire</button></div>`);
    row.querySelector('button').onclick = async () => {
      await api(`/sources/${s.id}/action`, { method: 'POST', body: { action: 'deactivate' } });
      toast(`${s.name} retired.`); route();
    };
    L.appendChild(row);
  }

  R.appendChild(el(`<div class="eyebrow">Pending proposals</div>`));
  if (!d.proposals.length) R.appendChild(el(`<div class="muted small">None.</div>`));
  for (const p of d.proposals) {
    const c = el(`<div class="item"><b>${esc(p.name)}</b> — ${esc(p.platform)} · T${p.tier}
      <div class="meta">${esc((p.lean || '').slice(0, 70))} ${esc((p.notes || '').slice(0, 60))}</div>
      <div class="actions"><button class="btn small primary">✓ Add</button><button class="btn small">✗ Skip</button></div></div>`);
    c.querySelectorAll('button')[0].onclick = async () => {
      await api(`/sources/${p.id}/action`, { method: 'POST', body: { action: 'approve' } }); route();
    };
    c.querySelectorAll('button')[1].onclick = async () => {
      await api(`/sources/${p.id}/action`, { method: 'POST', body: { action: 'skip' } }); route();
    };
    R.appendChild(c);
  }
  const form = el(`<details><summary>➕ Add RSS source</summary><div>
    <label class="f">Name</label><input data-x="n">
    <label class="f">Feed URL</label><input data-x="u">
    <label class="f">Platform</label><select data-x="p"><option>web</option><option>youtube</option></select>
    <label class="f">Lean / description</label><input data-x="l">
    <label class="f">Tier</label><select data-x="t"><option>1</option><option selected>2</option><option>3</option></select>
    <div class="actions"><button class="btn primary">Add</button></div></div></details>`);
  form.querySelector('button').onclick = async () => {
    const r = await api('/sources', { method: 'POST', body: {
      name: form.querySelector('[data-x=n]').value, feed_url: form.querySelector('[data-x=u]').value,
      platform: form.querySelector('[data-x=p]').value, lean: form.querySelector('[data-x=l]').value,
      tier: form.querySelector('[data-x=t]').value } });
    toast(r.note, 'ok'); route();
  };
  R.appendChild(form);
  main.appendChild(g);
}

/* ══ INGEST ═════════════════════════════════════════════════════════════ */
async function vIngest(main) {
  const d = await api('/ingest');
  main.innerHTML = '';
  main.appendChild(el(`<div><h1>Ingest</h1>
    <div class="sub">Paste article or YouTube links — the engine fetches, triages, verifies on the open web, and brings a draft to your gate. Nothing auto-publishes.</div></div>`));
  const form = el(`<div class="card">
    <label class="f">URL(s) — one per line</label>
    <textarea rows="4" placeholder="https://www.thehindu.com/…&#10;https://youtu.be/…"></textarea>
    <label class="f">Angle / note (optional)</label>
    <input placeholder="Why this, what to look for">
    <div class="actions"><button class="btn primary">Ingest →</button></div></div>`);
  form.querySelector('button').onclick = async () => {
    const urls = form.querySelector('textarea').value.split('\n').map(s => s.trim()).filter(s => s.startsWith('http'));
    if (!urls.length) return toast('No valid URLs.', 'err');
    const r = await api('/ingest', { method: 'POST', body: { urls, note: form.querySelector('input').value } });
    toast(`Queued ${r.queued} link(s). ${r.note}`, 'ok', 8000); route();
  };
  main.appendChild(form);
  main.appendChild(el(`<div class="eyebrow">Recent ingests</div>`));
  if (!d.ingests.length) main.appendChild(el(`<div class="muted small">No links ingested yet.</div>`));
  for (const i of d.ingests)
    main.appendChild(el(`<div class="item small"><div class="row between">
      <span>#${i.id} ${esc((i.topic || '').slice(0, 90))}</span>${pill(i.status)}</div>
      <div class="meta">${fdate(i.submitted_at)}</div></div>`));
}

/* ══ SYSTEM ═════════════════════════════════════════════════════════════ */
async function vSystem(main) {
  const d = await api('/system');
  paintStatus(d.breaker, d.voice_up);
  main.innerHTML = '';
  main.appendChild(el(`<div><h1>System</h1><div class="sub">The machinery — schedules, breaker, voice, jobs, bio page.</div></div>`));

  const bk = el(`<div class="card ${d.breaker.open ? 'danger' : ''}">
    <b>Quota breaker:</b> ${d.breaker.open ? `OPEN — ${esc(d.breaker.reason)}` : 'closed (APIs usable, credit permitting)'}
    ${d.breaker.until ? `<div class="muted small">auto-retry at ${String(d.breaker.until).slice(11, 16)} UTC</div>` : ''}
    <div class="actions" data-x="a"></div></div>`);
  if (d.breaker.open)
    addBtn(bk.querySelector('[data-x=a]'), 'Close breaker (after top-up)', '', async () => {
      if (!await confirmModal('Close the breaker?', 'Only do this after topping up credit — otherwise the next call just re-opens it.')) return;
      await api('/system/breaker/clear', { method: 'POST', body: {} });
      toast('Breaker closed.', 'ok'); route();
    });
  main.appendChild(bk);

  const bg = d.budget || {};
  const capTxt = bg.cap_usd == null ? 'disabled (no cap)' : `$${Number(bg.cap_usd).toFixed(2)}/day`;
  const bd = el(`<div class="card">
    <b>Daily budget:</b> ${capTxt}
    <span class="muted small">— spent today $${Number(bg.spent_today_usd || 0).toFixed(4)}${bg.over ? ' · <b>cap reached, model stages parked</b>' : ''}</span>
    <div class="muted small">Parks model stages at the cap and resumes at midnight UTC — the engine can't drain the balance mid-story. 0 disables it.</div>
    <div class="actions" data-x="a"><input data-x="usd" type="number" step="0.05" min="0" max="20"
      value="${bg.cap_usd == null ? 0 : bg.cap_usd}" style="width:90px"></div></div>`);
  addBtn(bd.querySelector('[data-x=a]'), 'Set cap', '', async () => {
    const v = bd.querySelector('[data-x=usd]').value;
    const r = await api('/system/budget', { method: 'POST', body: { usd: v } });
    toast(r.budget.cap_usd == null ? 'Budget governor disabled.' : `Cap set to $${r.budget.cap_usd}/day.`, 'ok');
    route();
  });
  main.appendChild(bd);

  // Tech steward — advisory only. Recommendations are shown with the exact
  // command to apply; nothing here changes a model on its own.
  const sw = d.steward || {};
  const recs = sw.recs || [];
  const st = el(`<div class="card">
    <b>Tech steward:</b> ${recs.length} open recommendation${recs.length === 1 ? '' : 's'}
    <span class="muted small">— last sweep ${ago(sw.last)}</span>
    <div class="muted small">Watches model catalogues, pricing and routing. Advisory — it never switches a model or spends.</div>
    <div class="actions" data-x="a"></div><div data-x="recs"></div></div>`);
  addBtn(st.querySelector('[data-x=a]'), 'Run sweep now', 'small', async () => {
    const r = await api('/system/signal', { method: 'POST', body: { key: 'force_tech_steward', value: '1' } });
    toast(r.note, 'ok');
  });
  const rbox = st.querySelector('[data-x=recs]');
  for (const r of recs) {
    const saves = (r.saves_usd_mo === null || r.saves_usd_mo === undefined || r.saves_usd_mo === '')
      ? '' : ` · ~$${Number(r.saves_usd_mo).toFixed(2)}/mo`;
    rbox.appendChild(el(`<div class="item">
      <div class="row between"><div><b>${esc(String(r.action || ''))}</b></div>
        <div class="muted small">${esc(String(r.area || ''))} · ${esc(String(r.risk || ''))} risk${saves}</div></div>
      <div class="muted small">${esc(String(r.why || ''))}</div>
      ${r.from || r.to ? `<div class="muted small">${esc(String(r.from || '?'))} → ${esc(String(r.to || '?'))}</div>` : ''}
    </div>`));
  }
  if (sw.brief)
    rbox.appendChild(el(`<details><summary class="muted small">Full brief</summary><pre class="small" style="white-space:pre-wrap">${esc(sw.brief)}</pre></details>`));
  main.appendChild(st);

  const vc = el(`<div class="card"><b>Voice server (:3901):</b> ${d.voice_up ? '<span style="color:var(--good)">up</span>' : '<span style="color:var(--brick)">down</span>'}
    <span class="muted small">— Chatterbox holds ~2 GB RAM; stop it when idle.</span>
    <div class="actions" data-x="a"></div></div>`);
  addBtn(vc.querySelector('[data-x=a]'), d.voice_up ? '⏹ Stop' : '▶ Start', '', async () => {
    const r = await api('/system/voice', { method: 'POST', body: { action: d.voice_up ? 'stop' : 'start' } });
    toast(r.up ? 'Voice server up.' : 'Voice server stopped.', 'ok'); route();
  });
  main.appendChild(vc);

  main.appendChild(el(`<div class="eyebrow">Scheduled jobs — triggers are signals the 2-min tick reads</div>`));
  for (const s of d.schedules) {
    const row = el(`<div class="item"><div class="row between">
      <div><b>${esc(s.label)}</b> <span class="muted small">· ${esc(s.cadence)} · last ${ago(s.last)}</span></div>
      <div data-x="b"></div></div></div>`);
    if (s.signal)
      addBtn(row.querySelector('[data-x=b]'), 'Run now', 'small', async () => {
        const r = await api('/system/signal', { method: 'POST', body: { key: s.signal, value: s.signal_value } });
        toast(r.note, 'ok');
      });
    else row.querySelector('[data-x=b]').innerHTML = '<span class="muted small">automatic</span>';
    main.appendChild(row);
  }

  if (d.queue.length) {
    main.appendChild(el(`<div class="eyebrow">Topic queue</div>`));
    for (const t of d.queue)
      main.appendChild(el(`<div class="item small"><span class="id">#${t.id}</span> [${esc(t.source)}] ${esc((t.topic || '').slice(0, 80))} ${pill(t.status)}${t.stale ? ' <span class="muted">(stale)</span>' : ''}</div>`));
  }

  main.appendChild(el(`<div class="eyebrow">Environment</div>`));
  const envRow = Object.entries(d.env).map(([k, ok]) =>
    `<div class="small">${ok ? '✅' : '❌'} <code>${esc(k)}</code></div>`).join('');
  main.appendChild(el(`<div class="card">${envRow}</div>`));

  /* bio links */
  main.appendChild(el(`<div class="eyebrow">Bio page links</div>`));
  const bioWrap = el(`<div class="card" data-x="bio"><div class="muted small">Loading…</div></div>`);
  main.appendChild(bioWrap);
  api('/bio').then(b => {
    bioWrap.innerHTML = '';
    for (const l of b.links) {
      const row = el(`<div class="row between small" style="margin:4px 0">
        <span>${l.pinned ? '📌 ' : ''}<b>${esc(l.title)}</b> <span class="muted">${esc(l.url)}</span></span>
        <span class="row"><button class="btn small">${l.pinned ? 'unpin' : 'pin'}</button><button class="btn small danger">✗</button></span></div>`);
      row.querySelectorAll('button')[0].onclick = async () => {
        await api(`/bio/${l.id}`, { method: 'PATCH', body: { pinned: !l.pinned } }); route();
      };
      row.querySelectorAll('button')[1].onclick = async () => {
        if (!await confirmModal('Remove bio link?', esc(l.title), { danger: true, label: 'Remove' })) return;
        await api(`/bio/${l.id}`, { method: 'DELETE' }); route();
      };
      bioWrap.appendChild(row);
    }
    const add = el(`<details><summary>➕ Add link</summary><div>
      <label class="f">Title</label><input data-x="t">
      <label class="f">URL (relative /a/… or absolute)</label><input data-x="u">
      <div class="actions"><button class="btn primary small">Add</button></div></div></details>`);
    add.querySelector('button').onclick = async () => {
      await api('/bio', { method: 'POST', body: { title: add.querySelector('[data-x=t]').value, url: add.querySelector('[data-x=u]').value } });
      toast('Link added.', 'ok'); route();
    };
    bioWrap.appendChild(add);
  }).catch(() => { bioWrap.innerHTML = '<div class="muted small">Could not load bio links.</div>'; });

  main.appendChild(el(`<div class="eyebrow">Background jobs (this session)</div>`));
  if (!d.jobs.length) main.appendChild(el(`<div class="muted small">None yet.</div>`));
  for (const j of d.jobs)
    main.appendChild(el(`<div class="item small"><div class="row between">
      <span>${esc(j.name)} <span class="muted">· ${esc(j.message || '')}</span></span>${pill(j.state)}</div></div>`));
}

/* ══ COSTS ══════════════════════════════════════════════════════════════ */
async function vCosts(main) {
  const d = await api('/costs');
  state.inrRate = d.inr_rate;
  main.innerHTML = '';
  main.appendChild(el(`<div><h1>Costs</h1><div class="sub">${d.runs_today} run(s) today.</div></div>`));
  main.appendChild(el(`<div class="tiles">
    <div class="tile gold"><div class="v">${inr(d.summary.today)}</div><div class="l">today</div></div>
    <div class="tile"><div class="v">${inr(d.summary.month)}</div><div class="l">this month</div></div>
    <div class="tile"><div class="v">${inr(d.summary.total)}</div><div class="l">all time</div></div>
  </div>`));

  /* daily bars (30d, aggregated across models) */
  const byDay = {};
  for (const r of d.daily) byDay[r.day] = (byDay[r.day] || 0) + r.usd;
  const days = Object.keys(byDay).sort();
  if (days.length) {
    const max = Math.max(...Object.values(byDay), 0.0001);
    const bars = days.map(day =>
      `<div class="bar" style="height:${Math.max(3, byDay[day] / max * 100)}%" title="${day}: ${inr(byDay[day])}"></div>`).join('');
    main.appendChild(el(`<div class="card"><div class="eyebrow" style="margin-top:0">Daily spend — last 30 days</div>
      <div class="bars">${bars}</div>
      <div class="row between muted small"><span>${days[0]}</span><span>${days[days.length - 1]}</span></div></div>`));
  }

  main.appendChild(el(`<div class="eyebrow">By model</div>`));
  main.appendChild(el(`<div class="tablewrap"><table>
    <tr><th>model</th><th>today</th><th>month</th><th>all time</th><th>tokens</th></tr>
    ${d.by_model.map(m => `<tr><td>${esc(m.model)}</td><td>${inr(m.today_usd)}</td>
      <td>${inr(m.month_usd)}</td><td>${inr(m.total_usd)}</td>
      <td>${(m.total_tokens / 1e6).toFixed(2)}M</td></tr>`).join('')}</table></div>`));

  main.appendChild(el(`<div class="eyebrow">By skill</div>`));
  main.appendChild(el(`<div class="tablewrap"><table>
    <tr><th>skill</th><th>model</th><th>calls</th><th>cost</th></tr>
    ${d.by_skill.map(s => `<tr><td>${esc(s.skill || '—')}</td><td>${esc(s.model || '')}</td>
      <td>${s.calls}</td><td>${inr(s.usd)}</td></tr>`).join('')}</table></div>`));

  main.appendChild(el(`<div class="eyebrow">Published (${d.publications.length})</div>`));
  for (const p of d.publications)
    main.appendChild(el(`<div class="item small clickable" onclick="openRun(${p.run_id})">
      <span class="id">#${p.run_id || '—'}</span> ${esc((p.throughline || '').slice(0, 90))}
      <div class="meta">${fdate(p.published_at)} · ${esc(p.source || '')} · ${esc(p.trust_gate || '')}</div></div>`));
}

/* ── Login + boot ──────────────────────────────────────────────────────── */
function showLogin() {
  $('#shell').classList.add('hidden');
  $('#login').classList.remove('hidden');
  $('#login-pw').focus();
}
async function tryLogin() {
  const pw = $('#login-pw').value;
  try {
    await api('/login', { method: 'POST', body: { password: pw } });
    $('#login').classList.add('hidden');
    $('#shell').classList.remove('hidden');
    route();
  } catch (e) {
    $('#login-err').textContent = e.status === 401 ? 'Wrong password.' : e.message;
  }
}
$('#login-btn').onclick = tryLogin;
$('#login-pw').addEventListener('keydown', e => { if (e.key === 'Enter') tryLogin(); });
$('#nav-refresh').onclick = () => route();

(async function boot() {
  try {
    await api('/overview');           // cookie still valid?
    $('#shell').classList.remove('hidden');
    route();
  } catch (e) { /* showLogin already triggered on 401 */ }
})();
