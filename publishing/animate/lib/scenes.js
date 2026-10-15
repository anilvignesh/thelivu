// =====================================================================
//  SCENES — the Thelivu scene library. Ink ground; one colour per meaning, everywhere:
//  cream = neutral text, gold = what is real or released, red = what is missing, late or lost, dim = labels.
//  Frame furniture (BRAND.md): gold stamp, THELIVU wordmark, progress line, handle footer; a silent source card and
//  the real logo (assets/logo.png) close every piece. No captions: the voice and the picture carry the story.
//  Scene types: illustration, timeline, excerpt, compare, figure, share, list, source, signoff. Each is drawn from the beat's
//  declared data (STORY.beats[i].data); nothing is read off the narration.
// =====================================================================
const INK = '#17140D', LOGO_INK = '#1B1710', CREAM = '#E9E0C8', GOLD = '#D2AA6D', DIM = '#B3A891', LATE = MC.red;
MC.bg = INK; STYLE.paper = INK;
const SERIF = 'Georgia, "Noto Serif", "Times New Roman", serif';
const MONOF = '"Courier New", "Liberation Mono", ui-monospace, monospace';
const line = (s, x, y, size, p, c = CREAM, o = {}) => writeText(s, x, y, size, p, { color: c, ...o });
const mono = (s, x, y, size, color, align = 'left', alpha = 1, sp = 3) => {
  ctx.save(); ctx.font = `${size}px ${MONOF}`; ctx.letterSpacing = sp + 'px'; ctx.textAlign = align; ctx.textBaseline = 'alphabetic';
  ctx.globalAlpha = alpha; ctx.fillStyle = color; ctx.fillText(s, x, y); ctx.restore();
};
// Indian digit grouping, as the audit prints it: 4,67,682
const inr = (n) => { const s = String(Math.round(n)); if (s.length <= 3) return s; const h = s.slice(-3); let r = s.slice(0, -3), o = ''; while (r.length > 2) { o = ',' + r.slice(-2) + o; r = r.slice(0, -2); } return r + o + ',' + h; };
// word-wrapped lines of `str` within maxW at `size`
function wrapLines(str, maxW, size, bold = false, font = SERIF) {
  ctx.save(); ctx.font = `${bold ? 'bold ' : ''}${size}px ${font}`;
  const words = str.split(/\s+/), out = []; let cur = '';
  words.forEach((w) => { const t = cur ? cur + ' ' + w : w; if (ctx.measureText(t).width > maxW && cur) { out.push(cur); cur = w; } else cur = t; });
  if (cur) out.push(cur); ctx.restore(); return out;
}
// text that fades up into place (left or centre aligned), p = 0..1
function fade(s, x, y, size, p, color = CREAM, o = {}) {
  if (p <= 0.001) return;
  ctx.save(); ctx.font = `${o.bold ? 'bold ' : ''}${size}px ${o.font || SERIF}`; ctx.textAlign = o.align || 'left'; ctx.textBaseline = 'alphabetic';
  ctx.globalAlpha = clamp(p) * (o.alpha ?? 1); ctx.fillStyle = color; ctx.fillText(s, x, y + (1 - clamp(p)) * 14); ctx.restore();
}

// the frame, the same on every story scene: stamp, wordmark, progress line, handle
function furniture() {
  const tag = STORY.stamp;
  ctx.save(); ctx.translate(70, 300); ctx.rotate(-0.052);
  ctx.font = `30px ${MONOF}`; ctx.letterSpacing = '4px';
  const w = ctx.measureText(tag).width;
  ctx.strokeStyle = GOLD; ctx.lineWidth = 2.5; ctx.strokeRect(-14, -34, w + 24, 52);
  ctx.fillStyle = GOLD; ctx.textBaseline = 'alphabetic'; ctx.fillText(tag, -2, 2); ctx.restore();
  mono('THELIVU', 940, 304, 34, GOLD, 'right', 1, 8);
  ctx.save(); ctx.globalAlpha = 0.9; ctx.fillStyle = 'rgba(179,168,145,0.3)'; ctx.fillRect(70, 1528, 870, 4);
  ctx.fillStyle = GOLD; ctx.fillRect(70, 1528, 870 * clamp(TT / DURATION), 4); ctx.restore();
  mono('thelivu.reports · sources in bio', 70, 1496, 26, DIM, 'left', 0.75, 2);
}

// when item k of n appears: on the word it names (cue: ['thirteen','13'], optionally {line, n}), else spread across the beat's speech
function itemT(e, cue, k, n) {
  const b = e.beat, L = beatLines(b), t0 = L[0].t0, t1 = L[L.length - 1].t1;
  if (cue) { const c = Array.isArray(cue) ? { w: cue } : cue; return WD(c.line || b.say[0].id, c.w, c.n || 1, (k + 0.5) / n) - (c.lead ?? 0.15); }
  return t0 + 0.2 + k * (t1 - t0 - 0.6) / n;
}
// the headline lines at the top of a scene
// a faint generated picture behind a data scene (data.bg): slow push and drift, so the frame is never still and never bare.
// It is atmosphere only. Every number, date and word is drawn on top of it, never in it.
function backdrop(e) {
  const img = e.beat.data && ASSETS[e.beat.data.bg];
  if (!img) return;
  const u = clamp((TT - e.t0) / (e.t1 - e.t0)), s = Math.max(W / img.width, H / img.height) * (1.06 + 0.12 * u), iw = img.width * s, ih = img.height * s;
  ctx.save(); ctx.globalAlpha = 0.5 * runS(e.t0, 0.6);
  ctx.drawImage(img, (W - iw) / 2 + (30 - 60 * u), (H - ih) / 2 - 40 * u, iw, ih);
  ctx.globalAlpha = 1; ctx.fillStyle = 'rgba(23,20,13,0.38)'; ctx.fillRect(0, 0, W, H);
  const g = ctx.createLinearGradient(0, 1250, 0, 1920); g.addColorStop(0, 'rgba(23,20,13,0)'); g.addColorStop(1, 'rgba(23,20,13,0.85)');
  ctx.fillStyle = g; ctx.fillRect(0, 1250, W, 670); ctx.restore();
}

function heads(e, y0 = 470, size = 58) {
  backdrop(e);
  const H_ = e.beat.head || [];
  H_.forEach((s, i) => line(s, CX, y0 + i * (size + 20), i === 0 ? size : size - 12, runS(e.t0 + 0.25 + i * 0.4, 0.9), i === 0 ? CREAM : DIM));
}

const SCENE = {};

// ILLUSTRATION: a generated picture of objects and space, full bleed, slow push; drawn type over it, never lettering in it
SCENE.illustration = (e) => {
  const d = e.beat.data, img = ASSETS[d.image], u = clamp((TT - e.t0) / (e.t1 - e.t0));
  fillAll(INK);
  const s = Math.max(W / img.width, H / img.height) * (1 + 0.12 * u), iw = img.width * s, ih = img.height * s;
  ctx.save(); ctx.globalAlpha = runS(e.t0, 0.5); ctx.drawImage(img, (W - iw) / 2 - 20 * u, (H - ih) / 2 - 30 * u, iw, ih);
  const g = ctx.createLinearGradient(0, 760, 0, 1500); g.addColorStop(0, 'rgba(23,20,13,0)'); g.addColorStop(1, 'rgba(23,20,13,0.92)');
  ctx.fillStyle = g; ctx.fillRect(0, 760, W, 800); ctx.restore();
  (e.beat.head || []).forEach((s_, i) => line(s_, CX, 1180 + i * 74, i === 0 ? 64 : 46, runS(e.t0 + 0.7 + i * 0.5, 0.9), i === 0 ? CREAM : GOLD, { bold: i === 0 }));
  furniture();
};

// TIMELINE: dated events on an axis, spans between them. Dates are decimal years (2011.46 = June 2011); every label is declared.
SCENE.timeline = (e) => {
  const d = e.beat.data, y = 1040, x0 = 130, x1 = 930, X = (v) => x0 + (v - d.from) / (d.to - d.from) * (x1 - x0);
  fillAll(INK); heads(e);
  const ap = runS(e.t0 + 0.5, 1.0);
  segLine(x0, y, x1, y, DIM, 4, ap);
  const step = (d.to - d.from) > 14 ? 5 : (d.to - d.from) > 7 ? 2 : 1;
  for (let yr = Math.ceil(d.from / step) * step; yr <= d.to; yr += step) { segLine(X(yr), y - 10, X(yr), y + 10, DIM, 3, ap); mText(String(yr), X(yr), y + 52, 32, { color: DIM, alpha: ap }); }
  d.events.forEach((ev, k) => {
    const t = itemT(e, ev.cue, k, d.events.length), p = runS(t, 0.7), col = ev.kind === 'late' ? LATE : GOLD, h = k % 2 ? 300 : 170;
    segLine(X(ev.at), y, X(ev.at), y - h, col, 5, p);
    const lines = wrapLines(ev.label, 300, 38), cx = Math.min(Math.max(X(ev.at), 290), 780);
    lines.forEach((s, i) => fade(s, cx, y - h - 14 - (lines.length - 1 - i) * 46, 38, runS(t + 0.2, 0.7), col === GOLD ? CREAM : LATE, { align: 'center' }));
  });
  (d.spans || []).forEach((sp, k) => {
    const t = itemT(e, sp.cue, d.events.length + k, d.events.length + (d.spans || []).length), p = runS(t, 1.4), col = sp.kind === 'late' ? LATE : GOLD;
    const a = X(sp.from), b = a + (X(sp.to) - a) * p;
    ctx.save(); ctx.fillStyle = rgbaM(col, 0.28); ctx.strokeStyle = col; ctx.lineWidth = 4; ctx.fillRect(a, y + 100, b - a, 70); ctx.strokeRect(a, y + 100, b - a, 70); ctx.restore();
    line(sp.label, (X(sp.from) + X(sp.to)) / 2, y + 250, 64, runS(t + 1.0, 0.8), col, { bold: true });
    if (sp.note) fade(sp.note, (X(sp.from) + X(sp.to)) / 2, y + 305, 34, runS(t + 1.3, 0.8), DIM, { align: 'center' });
  });
  furniture();
};

// EXCERPT: the report's own sentence, verbatim, with the key phrase marked. The page is the evidence.
SCENE.excerpt = (e) => {
  const d = e.beat.data, size = d.size || 40, maxW = 740, x0 = 150;
  fillAll(INK); heads(e, 470, 54);
  const words = d.text.split(/\s+/), marks = (d.mark || []).map((m) => { const i = d.text.indexOf(m); return [i, i + m.length]; });
  ctx.save(); ctx.font = `${size}px ${SERIF}`;
  let pos = 0; const items = [];
  words.forEach((w) => { const i = d.text.indexOf(w, pos); pos = i + w.length; const hot = marks.some(([a, b]) => i >= a && i < b); ctx.font = `${hot ? 'bold ' : ''}${size}px ${SERIF}`; items.push({ w, hot, width: ctx.measureText(w).width }); });
  ctx.font = `${size}px ${SERIF}`;
  const sp = ctx.measureText(' ').width; ctx.restore();
  const rows = []; let cur = [], cw = 0;
  items.forEach((it) => { if (cw + it.width > maxW && cur.length) { rows.push(cur); cur = []; cw = 0; } cur.push(it); cw += it.width + sp; });
  if (cur.length) rows.push(cur);
  const lh = size * 1.5, top = 760, hgt = rows.length * lh + 80, cp = runS(e.t0 + 0.9, 0.8);
  ctx.save(); ctx.globalAlpha = cp; ctx.fillStyle = 'rgba(233,224,200,0.06)'; ctx.fillRect(100, top - 50, 840, hgt); ctx.fillStyle = GOLD; ctx.fillRect(100, top - 50, 8, hgt); ctx.restore();
  const hot = itemT(e, d.cue, 0, 1), hp = runS(hot, 0.9);
  rows.forEach((row, r) => {
    let x = x0; const rp = runS(e.t0 + 1.2 + r * 0.22, 0.7);
    row.forEach((it) => {
      const hh = it.hot ? hp : 0;
      if (hh > 0.001) { ctx.save(); ctx.fillStyle = rgbaM(GOLD, 0.22); ctx.fillRect(x - 4, top + r * lh - size * 0.95, (it.width + 8) * hh, size * 1.25); ctx.restore(); }
      fade(it.w, x, top + r * lh, size, rp, it.hot && hh > 0.5 ? GOLD : CREAM, { bold: it.hot && hh > 0.5 });
      x += it.width + sp;
    });
  });
  mono(d.where, 100, top - 50 + hgt + 56, 26, DIM, 'left', runS(e.t0 + 1.8, 0.8), 2);
  furniture();
};

// COMPARE: two declared values as bars, then the declared change. The change is arithmetic on the two, and says so.
SCENE.compare = (e) => {
  const d = e.beat.data, x0 = 120, bw = 760, ay = 800, by = 1020, hh = 130;
  fillAll(INK); heads(e);
  const mx = Math.max(d.a.value, d.b.value);
  [[d.a, ay, GOLD, 0], [d.b, by, LATE, 1]].forEach(([it, y, col, k]) => {
    const t = itemT(e, it.cue, k, 2), p = runS(t, 1.4), v = it.value * p;
    fade(it.label, x0, y - hh / 2 - 22, 38, runS(t - 0.2, 0.5), DIM);
    ctx.save(); ctx.fillStyle = rgbaM(col, 0.34); ctx.strokeStyle = col; ctx.lineWidth = 4;
    const w = Math.max(2, bw * v / mx); ctx.fillRect(x0, y - hh / 2, w, hh); ctx.strokeRect(x0, y - hh / 2, w, hh); ctx.restore();
    if (p > 0.01) mText((d.fmt === 'inr' ? inr(v) : Math.round(v)) + (d.unit || ''), Math.min(x0 + Math.max(2, bw * v / mx) + 20, 900 - 330), y + 22, 66, { color: col, align: 'left', bold: true, alpha: runS(t, 0.3) });
  });
  const dp = runS(HIT, 0.6), pc = Math.round((1 - d.b.value / d.a.value) * 100);
  line('−' + pc + '%', CX, 1330, 150, dp, LATE, { bold: true });
  fade(d.derived, CX, 1400, 34, runS(HIT + 0.4, 0.8), DIM, { align: 'center' });
  furniture();
};

// SHARE: a declared percentage as 100 dots, counted up; the red dots are the share that went wrong
SCENE.share = (e) => {
  const d = e.beat.data, t = itemT(e, d.cue, 0, 1), sp = 66, x0 = CX - 4.5 * sp, y0 = 760, col = d.color === 'gold' ? GOLD : LATE;
  fillAll(INK); heads(e);
  const v = keysM([[t, 0], [t + 1.8, d.value]]);
  const fw = textW(d.value.toFixed(d.decimals ?? 0) + '%', 130, { bold: true });
  mText(v.toFixed(d.decimals ?? 0) + '%', CX - fw / 2, 700, 130, { color: col, align: 'left', bold: true, alpha: runS(t - 0.1, 0.3) });
  for (let i = 0; i < 100; i++) {
    const on = clamp(v - i), cx = x0 + (i % 10) * sp, cy = y0 + Math.floor(i / 10) * sp;
    ctx.save(); ctx.beginPath(); ctx.arc(cx, cy, 22, 0, Math.PI * 2);
    ctx.globalAlpha = 0.9; ctx.fillStyle = on > 0 ? rgbaM(col, 0.25 + 0.75 * on) : rgbaM(DIM, 0.16); ctx.fill(); ctx.restore();
  }
  wrapLines(d.label, 820, 42).forEach((r, i) => fade(r, CX, 1440 + i * 54, 42, runS(t + 1.6, 0.8), CREAM, { align: 'center' }));
  furniture();
};

// FIGURE: one declared number, counted up
SCENE.figure = (e) => {
  const d = e.beat.data, t = itemT(e, d.cue, 0, 1);
  fillAll(INK); heads(e);
  const v = keysM([[t, 0], [t + 1.8, d.value]]), s = (d.prefix || '') + v.toFixed(d.decimals ?? 0).replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (d.suffix || '');
  const fw = textW((d.prefix || '') + d.value.toFixed(d.decimals ?? 0) + (d.suffix || ''), 130, { bold: true });
  mText(s, CX - fw / 2, 1000, 130, { color: d.color === 'gold' ? GOLD : LATE, align: 'left', bold: true, alpha: runS(t - 0.1, 0.3) });
  wrapLines(d.label, 820, 46).forEach((r, i) => fade(r, CX, 1090 + i * 60, 46, runS(t + 1.6, 0.8), CREAM, { align: 'center' }));
  furniture();
};

// LIST: things the audit found missing or stopped, one at a time
SCENE.list = (e) => {
  const d = e.beat.data, size = 46, maxW = 640, x0 = 210;
  fillAll(INK); heads(e);
  let y = 780;
  d.items.forEach((it, k) => {
    const t = itemT(e, it.cue, k, d.items.length), p = runS(t, 0.8), rows = wrapLines(it.text, maxW, size);
    const cy = y - size * 0.35;
    segLine(x0 - 88, cy - 18, x0 - 52, cy + 18, LATE, 6, runS(t, 0.4)); segLine(x0 - 52, cy - 18, x0 - 88, cy + 18, LATE, 6, runS(t + 0.15, 0.4));
    rows.forEach((s, i) => fade(s, x0, y + i * (size * 1.3), size, p, CREAM));
    y += rows.length * size * 1.3 + 70;
  });
  furniture();
};

// SOURCE: the report, named; silent
SCENE.source = (e) => {
  const S = STORY.source;
  fillAll(INK);
  mono('SOURCE', CX, 640, 34, GOLD, 'center', runS(e.t0 + 0.2, 0.6), 10);
  segLine(240, 670, 760, 670, GOLD, 3, runS(e.t0 + 0.3, 0.8));
  let y = 760;
  [[S.publisher, 40, DIM], ...wrapLines(S.title, 760, 46, true).map((s) => [s, 46, CREAM]), [S.report, 38, GOLD], [S.place, 38, DIM]].forEach(([s, size, c], i) => {
    line(s, CX, y, size, runS(e.t0 + 0.5 + i * 0.3, 0.8), c, { bold: size === 46 }); y += size + 30;
  });
  furniture();
};

// SIGN-OFF: silent; the logo and the descriptor
SCENE.signoff = (e) => {
  const u = clamp((TT - e.t0) / (e.t1 - e.t0));
  fillAll(LOGO_INK);
  const lp = runS(e.t0 - 0.3, 0.4), size = 560 * (1 + 0.05 * u);
  ctx.save(); ctx.globalAlpha = lp; ctx.drawImage(ASSETS['logo.png'], CX - size / 2, 790 - size / 2, size, size); ctx.restore();
  line('Fact-checked stories.', CX, 1190, 44, runS(e.t0 + 0.7, 0.8), CREAM);
  line('Every claim verified, every piece', CX, 1250, 44, runS(e.t0 + 0.9, 0.8), CREAM);
  line('human-reviewed.', CX, 1310, 44, runS(e.t0 + 1.1, 0.8), CREAM);
  mono('thelivu.reports', CX, 1400, 30, GOLD, 'center', runS(e.t0 + 1.5, 0.8), 6);
};
