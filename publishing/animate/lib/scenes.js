// =====================================================================
//  SCENES — the Thelivu scene library, "dossier" layout. Same brand palette (engine/BRAND.md): ink ground; one colour per meaning, everywhere:
//  cream = neutral text, gold = what is real or released, red = what is missing, late or lost, dim = labels.
//  Our voice is set in Archivo; the source's own words in Charter, on a kraft sheet, so the viewer can tell who is speaking.
//  Figures sit on a gold block (real) or a red block (missing/late); no tilted stamp, no mono kicker.
//  Frame furniture: document header (wordmark left, topic right, hairline), progress line, handle footer; a silent source card and
//  the real logo (assets/logo.png) close every piece. No captions: the voice and the picture carry the story.
//  Scene types: illustration, timeline, excerpt, compare, figure, share, list, source, signoff. Each is drawn from the beat's
//  declared data (STORY.beats[i].data); nothing is read off the narration.
// =====================================================================
const INK = '#17140D', LOGO_INK = '#1B1710', CREAM = '#E9E0C8', GOLD = '#D2AA6D', DIM = '#B3A891', LATE = MC.red;
MC.bg = INK; STYLE.paper = INK;
const SERIF = 'Archivo, "Liberation Sans", Arial, sans-serif';            // our voice (name kept: every scene reads it)
const DOCF = '"Bitstream Charter", Charter, "Liberation Serif", Georgia, serif';   // the source's words
const KRAFT = '#E6DCC3', KRAFT_INK = '#1B1710';
// width of a string exactly as writeText lays it out (per-glyph advance)
const eo = (u) => 1 - Math.pow(1 - clamp(u), 3);                          // ease-out cubic: entrances decelerate into place
// the header's right-hand label: the real citation (who published it, which report, where); our own stories keep their topic stamp
function citation() {
  const S = STORY.source || {};
  if (/Comptroller/i.test(S.publisher || '')) return ['CAG', S.report, S.place].filter(Boolean).join(' · ');
  if (S.publisher && S.publisher !== 'Thelivu') return [S.publisher, S.report].filter(Boolean).join(' · ');
  return STORY.stamp;
}
const gw = (str, size) => { ctx.save(); ctx.font = `700 ${size}px ${SERIF}`; let w = 0; for (const ch of str) w += ctx.measureText(ch).width; ctx.restore(); return w * 1.04; };
// a figure or phrase on its block: gold = what the record shows, red = what is missing, late or lost. Type inside is ink.
function onBlock(s, cx, base, size, kind, p, left = false) {
  if (p <= 0.001) return;
  while (gw(s, size) > 800 && size > 60) size -= 6;                      // a long figure shrinks to fit the frame
  const w = gw(s, size), pad = size * 0.16, x = left ? 70 + pad : cx - w / 2;
  const k = 1 + 0.04 * (1 - eo(p)), ox = left ? x - pad : cx, oy = base - size * 0.3;          // lands with a short settle, ease-out
  ctx.save(); ctx.translate(ox, oy); ctx.scale(k, k); ctx.translate(-ox, -oy);
  ctx.fillStyle = kind === 'late' ? LATE : GOLD; ctx.fillRect(x - pad, base - size * 0.88, (w + pad * 2) * eo(p * 1.6), size * 1.12);
  if (p > 0.25) mText(s, x, base, size, { color: INK, align: 'left', bold: true, font: SERIF });
  ctx.restore();
}
const line = (s, x, y, size, p, c = CREAM, o = {}) => writeText(s, x, y, size, p, { color: c, font: SERIF, ...o });
const mono = (s, x, y, size, color, align = 'left', alpha = 1, sp = 3) => {
  ctx.save(); ctx.font = `500 ${size}px ${SERIF}`; ctx.letterSpacing = sp + 'px'; ctx.textAlign = align; ctx.textBaseline = 'alphabetic';
  ctx.globalAlpha = alpha; ctx.fillStyle = color; ctx.fillText(s, x, y); ctx.restore();
};
// Indian digit grouping, as the audit prints it: 4,67,682
const inr = (n) => { const s = String(Math.round(n)); if (s.length <= 3) return s; const h = s.slice(-3); let r = s.slice(0, -3), o = ''; while (r.length > 2) { o = ',' + r.slice(-2) + o; r = r.slice(0, -2); } return r + o + ',' + h; };
// word-wrapped lines of `str` within maxW at `size`
function wrapLines(str, maxW, size, bold = false, font = SERIF) {
  ctx.save(); ctx.font = `${bold ? '700 ' : ''}${size}px ${font}`;
  const words = str.split(/\s+/), out = []; let cur = '';
  words.forEach((w) => { const t = cur ? cur + ' ' + w : w; if (ctx.measureText(t).width > maxW && cur) { out.push(cur); cur = w; } else cur = t; });
  if (cur) out.push(cur); ctx.restore(); return out;
}
// text that fades up into place (left or centre aligned), p = 0..1
function fade(s, x, y, size, p, color = CREAM, o = {}) {
  if (p <= 0.001) return;
  ctx.save(); ctx.font = `${o.bold ? '700 ' : ''}${size}px ${o.font || SERIF}`; ctx.textAlign = o.align || 'left'; ctx.textBaseline = 'alphabetic';
  ctx.globalAlpha = clamp(p) * (o.alpha ?? 1); ctx.fillStyle = color; ctx.fillText(s, x, y + (1 - clamp(p)) * 14); ctx.restore();
}

// the frame, the same on every story scene: stamp, wordmark, progress line, handle
function furniture() {
  const tag = citation();
  mono('THELIVU', 70, 304, 34, GOLD, 'left', 1, 7);
  ctx.save(); let size = 26; ctx.font = `500 ${size}px ${SERIF}`; ctx.letterSpacing = '1px'; let w = ctx.measureText(tag).width;
  for (; w > 520 && size > 16; size -= 2) { ctx.font = `500 ${size}px ${SERIF}`; w = ctx.measureText(tag).width; }   // never reach the wordmark
  ctx.textAlign = 'right'; ctx.fillStyle = DIM; ctx.fillText(tag, 940, 304); ctx.restore();
  ctx.save(); ctx.fillStyle = 'rgba(233,224,200,0.55)'; ctx.fillRect(70, 326, 870, 3); ctx.restore();
  ctx.save(); ctx.globalAlpha = 0.9; ctx.fillStyle = 'rgba(179,168,145,0.3)'; ctx.fillRect(70, 1528, 870, 3);
  ctx.fillStyle = GOLD; ctx.fillRect(70, 1528, 870 * clamp(TT / DURATION), 3); ctx.restore();
  mono('thelivu.reports · sources in bio', 70, 1496, 26, DIM, 'left', 0.75, 1);
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
// picture motion, chosen per beat by what the beat is about (data.motion); every move is slow and continuous
const MOTION = {
  push: (u) => [1.08 + 0.22 * u, 50 - 100 * u, -60 * u],            // closing in on the subject
  pull: (u) => [1.3 - 0.22 * u, -50 + 100 * u, 60 * u - 60],        // opening out to show the scale of it
  pan_l: (u) => [1.22, 160 - 320 * u, 0],
  pan_r: (u) => [1.22, -160 + 320 * u, 0],
  rise: (u) => [1.2, 0, 130 - 260 * u],                              // a slow tilt up
  sway: (u) => [1.18, 90 * Math.sin(u * 6.283), 45 * Math.cos(u * 6.283)],
};
function pic(img, alpha, u, motion) {
  const [k, dx, dy] = (MOTION[motion] || MOTION.push)(u), s = Math.max(W / img.width, H / img.height) * k, iw = img.width * s, ih = img.height * s;
  ctx.globalAlpha = alpha; ctx.drawImage(img, (W - iw) / 2 + dx, (H - ih) / 2 + dy, iw, ih);
}
function backdrop(e) {
  const d = e.beat.data || {}, img = ASSETS[d.bg];
  if (!img) return;
  // the picture is the scene's ground, not a watermark: near full strength, moving, with a second picture crossfading in
  // mid-beat when there is one (data.bg2), and just enough shade behind the text band and the footer to keep figures readable
  const u = clamp((TT - e.t0) / (e.t1 - e.t0)), a = 0.95 * runS(e.t0, 0.5);
  ctx.save();
  const img2 = d.bg2 && ASSETS[d.bg2], x = img2 ? clamp((u - 0.42) / 0.16) : 0;
  pic(img, a * (1 - x * 0.0), u, d.motion);
  if (img2) pic(img2, a * x, u, d.motion2 || d.motion);
  ctx.globalAlpha = 1; ctx.fillStyle = 'rgba(23,20,13,0.2)'; ctx.fillRect(0, 0, W, H);
  const hv = ctx.createLinearGradient(0, 0, 0, 600); hv.addColorStop(0, 'rgba(23,20,13,1)'); hv.addColorStop(0.8, 'rgba(23,20,13,1)'); hv.addColorStop(1, 'rgba(23,20,13,0)');
  ctx.fillStyle = hv; ctx.fillRect(0, 0, W, 600);
  const band = ctx.createLinearGradient(0, 380, 0, 1300);
  band.addColorStop(0, 'rgba(23,20,13,0)'); band.addColorStop(0.35, 'rgba(23,20,13,0.5)'); band.addColorStop(0.7, 'rgba(23,20,13,0.5)'); band.addColorStop(1, 'rgba(23,20,13,0)');
  ctx.fillStyle = band; ctx.fillRect(0, 380, W, 920);
  const g = ctx.createLinearGradient(0, 1250, 0, 1920); g.addColorStop(0, 'rgba(23,20,13,0)'); g.addColorStop(1, 'rgba(23,20,13,0.85)');
  ctx.fillStyle = g; ctx.fillRect(0, 1250, W, 670); ctx.restore();
}

function heads(e, y0 = 470, size = 66) {
  backdrop(e);
  const H_ = e.beat.head || [];
  H_.forEach((s, i) => line(s, 70, y0 + i * (size + 20), i === 0 ? size : size - 14, runS(e.t0 + 0.25 + i * 0.4, 0.9), i === 0 ? CREAM : DIM, { bold: i === 0, align: 'left' }));
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
  const d = e.beat.data, y = 1040, x0 = 130, x1 = 930, num = (v) => { if (typeof v !== 'string') return v; const m = v.match(/^(\d{4})(?:-(\d{1,2}))?/); return m ? +m[1] + ((+m[2] || 1) - 1) / 12 : parseFloat(v); };
  const lo = num(d.from), hi = Math.max(num(d.to), lo + 1), X = (v) => x0 + (num(v) - lo) / (hi - lo) * (x1 - x0);
  // events dated too close together (a month, a day) would print on top of each other: spread them evenly in order
  const slot = (d.events.length > 1 && d.events.some((ev, k) => k && Math.abs(X(ev.at) - X(d.events[k - 1].at)) < 300)) ? (k) => 230 + k * (480 / (d.events.length - 1)) : null;
  fillAll(INK); heads(e);
  const ap = runS(e.t0 + 0.5, 1.0);
  segLine(x0, y, x1, y, DIM, 4, ap);
  const step = (hi - lo) > 14 ? 5 : (hi - lo) > 7 ? 2 : 1;
  for (let yr = Math.ceil(lo / step) * step; yr <= Math.floor(hi); yr += step) { segLine(X(yr), y - 10, X(yr), y + 10, DIM, 3, ap); mText(String(yr), X(yr), y + 52, 32, { color: DIM, alpha: ap, font: SERIF }); }
  d.events.forEach((ev, k) => {
    const t = itemT(e, ev.cue, k, d.events.length), p = runS(t, 0.7), col = ev.kind === 'late' ? LATE : GOLD, h = k % 2 ? 300 : 170;
    const ex = slot ? slot(k) : X(ev.at);
    segLine(ex, y, ex, y - h, col, 5, p);
    const lines = wrapLines(ev.label, 300, 38), cx = Math.min(Math.max(ex, 290), 780);
    lines.forEach((s, i) => { const by = y - h - 14 - (lines.length - 1 - i) * 46, w = textW(s, 38, { font: SERIF }), lp = runS(t + 0.2, 0.7);
      if (lp > 0.001) { ctx.save(); ctx.fillStyle = col; ctx.globalAlpha = clamp(lp); ctx.fillRect(cx - w / 2 - 8, by - 34, w + 16, 46); ctx.restore(); }
      fade(s, cx, by, 38, lp, INK, { align: 'center' }); });
  });
  (d.spans || []).forEach((sp, k) => {
    const t = itemT(e, sp.cue, d.events.length + k, d.events.length + (d.spans || []).length), p = runS(t, 1.4), col = sp.kind === 'late' ? LATE : GOLD;
    const a = X(sp.from), b = a + (X(sp.to) - a) * p;
    ctx.save(); ctx.fillStyle = rgbaM(col, 0.28); ctx.strokeStyle = col; ctx.lineWidth = 4; ctx.fillRect(a, y + 100, b - a, 70); ctx.strokeRect(a, y + 100, b - a, 70); ctx.restore();
    onBlock(sp.label, (X(sp.from) + X(sp.to)) / 2, y + 262, 64, sp.kind === 'late' ? 'late' : 'real', runS(t + 1.0, 0.8));
    if (sp.note) fade(sp.note, (X(sp.from) + X(sp.to)) / 2, y + 325, 34, runS(t + 1.3, 0.8), DIM, { align: 'center' });
  });
  furniture();
};

// EXCERPT: the report's own sentence, verbatim, with the key phrase marked. The page is the evidence.
SCENE.excerpt = (e) => {
  const d = e.beat.data, size = d.size || 44, maxW = 770, x0 = 112;
  fillAll(INK); heads(e, 470, 66);
  const words = d.text.split(/\s+/), marks = (d.mark || []).map((m) => { const i = d.text.indexOf(m); return [i, i + m.length]; });
  ctx.save(); ctx.font = `${size}px ${DOCF}`;
  let pos = 0; const items = [];
  words.forEach((w) => { const i = d.text.indexOf(w, pos); pos = i + w.length; const hot = marks.some(([a, b]) => i >= a && i < b); ctx.font = `${hot ? '700 ' : ''}${size}px ${DOCF}`; items.push({ w, hot, width: ctx.measureText(w).width }); });
  ctx.font = `${size}px ${DOCF}`;
  const sp = ctx.measureText(' ').width; ctx.restore();
  const rows = []; let cur = [], cw = 0;
  items.forEach((it) => { if (cw + it.width > maxW && cur.length) { rows.push(cur); cur = []; cw = 0; } cur.push(it); cw += it.width + sp; });
  if (cur.length) rows.push(cur);
  const lh = size * 1.5, top = 740, hgt = rows.length * lh + 80, cp = runS(e.t0 + 0.9, 0.8);
  ctx.save(); ctx.globalAlpha = eo(cp); ctx.translate(0, 20 * (1 - eo(cp))); ctx.shadowColor = 'transparent'; ctx.fillStyle = 'rgba(30,26,18,0.75)'; ctx.fillRect(70, top - 50, 870, hgt);
  ctx.shadowColor = 'transparent'; ctx.strokeStyle = 'rgba(210,170,109,0.5)'; ctx.lineWidth = 2; ctx.strokeRect(71, top - 49, 868, hgt - 2);
  ctx.fillStyle = GOLD; ctx.fillRect(70, top - 50, 8, hgt); ctx.restore();
  const hot = itemT(e, d.cue, 0, 1), hp = runS(hot, 0.9);
  rows.forEach((row, r) => {
    let x = x0; const rp = runS(e.t0 + 1.2 + r * 0.22, 0.7);
    row.forEach((it, ii) => {
      const hh = it.hot ? hp : 0, joinNext = it.hot && row[ii + 1] && row[ii + 1].hot;
      if (hh > 0.001) { ctx.save(); ctx.fillStyle = GOLD; ctx.fillRect(x - 4, top + r * lh - size * 0.95, (it.width + 8 + (joinNext ? sp : 0)) * hh, size * 1.25); ctx.restore(); }
      fade(it.w, x, top + r * lh, size, rp, it.hot && hh > 0.5 ? INK : CREAM, { bold: it.hot && hh > 0.5, font: DOCF });
      x += it.width + sp;
    });
  });
  fade(d.where, 70, top - 50 + hgt + 56, 28, runS(e.t0 + 1.8, 0.8), DIM);
  furniture();
};

// COMPARE: two declared values as bars, then the declared change. The change is arithmetic on the two, and says so.
SCENE.compare = (e) => {
  const d = e.beat.data, x0 = 70, bw = 790, ay = 800, by = 1020, hh = 130;
  fillAll(INK); heads(e);
  const mx = Math.max(d.a.value, d.b.value);
  [[d.a, ay, GOLD, 0], [d.b, by, LATE, 1]].forEach(([it, y, col, k]) => {
    const t = itemT(e, it.cue, k, 2), p = runS(t, 1.4), v = it.value * p;
    fade(it.label, x0, y - hh / 2 - 22, 38, runS(t - 0.2, 0.5), DIM);
    ctx.save(); ctx.fillStyle = rgbaM(col, 0.34); ctx.strokeStyle = col; ctx.lineWidth = 4;
    const w = Math.max(2, bw * v / mx); ctx.fillRect(x0, y - hh / 2, w, hh); ctx.strokeRect(x0, y - hh / 2, w, hh); ctx.restore();
    if (p > 0.01) mText((d.fmt === 'inr' ? inr(v) : Math.round(v)) + (d.unit || ''), Math.min(x0 + Math.max(2, bw * v / mx) + 20, 900 - 330), y + 22, 66, { color: col, align: 'left', bold: true, font: SERIF, alpha: runS(t, 0.3) });
  });
  if (d.derived) {                           // the change between the bars, drawn only when the story labels it as derived
    const dp = runS(HIT, 0.6), pc = Math.round(Math.abs(1 - d.b.value / d.a.value) * 100), down = d.b.value < d.a.value;
    onBlock((down ? '−' : '+') + pc + '%', CX, 1330, 150, 'late', dp, true);
    fade(d.derived, 70, 1410, 34, runS(HIT + 0.4, 0.8), DIM);
  }
  furniture();
};

// SHARE: a declared percentage as 100 dots, counted up; the red dots are the share that went wrong
SCENE.share = (e) => {
  const d = e.beat.data, t = itemT(e, d.cue, 0, 1), sp = 54, x0 = 70 + 22, y0 = 850, col = d.color === 'gold' ? GOLD : LATE;
  fillAll(INK); heads(e);
  const v = keysM([[t, 0], [t + 1.8, d.value]]);
  onBlock(v.toFixed(d.decimals ?? 0) + '%', CX, 770, 130, d.color === 'gold' ? 'real' : 'late', runS(t - 0.1, 0.4), true);
  for (let i = 0; i < 100; i++) {
    const on = clamp(v - i), cx = x0 + (i % 10) * sp, cy = y0 + Math.floor(i / 10) * sp;
    ctx.save(); ctx.beginPath(); ctx.arc(cx, cy, 22, 0, Math.PI * 2);
    ctx.globalAlpha = 0.9; ctx.fillStyle = on > 0 ? rgbaM(col, 0.25 + 0.75 * on) : rgbaM(DIM, 0.16); ctx.fill(); ctx.restore();
  }
  wrapLines(d.label, 880, 42).forEach((r, i) => fade(r, 70, 1400 + i * 50, 42, runS(t + 1.6, 0.8), CREAM, { align: 'left' }));
  furniture();
};

// FIGURE: one declared number, counted up
SCENE.figure = (e) => {
  const d = e.beat.data, t = itemT(e, d.cue, 0, 1);
  fillAll(INK); heads(e);
  const v = keysM([[t, 0], [t + 1.8, d.value]]), s = (d.prefix || '') + v.toFixed(d.decimals ?? 0).replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (d.suffix || '');
  onBlock(s, CX, 1000, 130, d.color === 'gold' ? 'real' : 'late', runS(t - 0.1, 0.4), true);
  wrapLines(d.label, 820, 46).forEach((r, i) => fade(r, 70, 1100 + i * 60, 46, runS(t + 1.6, 0.8), CREAM, { align: 'left' }));
  furniture();
};

// LIST: things the audit found missing or stopped, one at a time
SCENE.list = (e) => {
  const d = e.beat.data, size = 46, maxW = 700, x0 = 165;
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
  mono('SOURCE', 70, 640, 34, GOLD, 'left', runS(e.t0 + 0.2, 0.6), 10);
  segLine(70, 670, 330, 670, GOLD, 3, runS(e.t0 + 0.3, 0.8));
  let y = 760;
  [[S.publisher, 40, DIM], ...wrapLines(S.title, 860, 50, true).map((s) => [s, 50, CREAM]), [S.report, 38, GOLD], [S.place, 38, DIM]].forEach(([s, size, c], i) => {
    line(s, 70, y, size, runS(e.t0 + 0.5 + i * 0.3, 0.8), c, { bold: size === 50, align: 'left' }); y += size + 30;
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
