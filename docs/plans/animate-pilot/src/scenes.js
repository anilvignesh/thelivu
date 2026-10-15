// =====================================================================
//  SCENES — Nagaland MGNREGS, in Thelivu's frame. Ink ground; one colour per meaning, everywhere:
//  cream = the rule / neutral text, gold = money released, red = what is late or missing, dim = labels.
//  Frame furniture (BRAND.md): gold stamp top-left, THELIVU wordmark, serif caption, progress line, handle footer; the
//  sign-off card is the real logo (assets/logo.png) and the descriptor, held in silence after the voice.
//  Every figure is a grounded finding (CAG Nagaland, Audit Report for the year ended 31 March 2024, paras 3.2.8.5-3.2.8.6).
// =====================================================================
const INK = '#17140D', LOGO_INK = '#1B1710', CREAM = '#E9E0C8', GOLD = '#D2AA6D', DIM = '#B3A891', LATE = MC.red;
MC.bg = INK; STYLE.paper = INK;
const money = (v, d = 2) => { const s = v.toFixed(d), [a, b] = s.split('.'); return a.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (b ? '.' + b : ''); };
const MONOF = '"Courier New", "Liberation Mono", ui-monospace, monospace';
const line = (s, x, y, size, p, c = CREAM, o = {}) => writeText(s, x, y, size, p, { color: c, ...o });
const mono = (s, x, y, size, color, align = 'left', alpha = 1, sp = 3) => {
  ctx.save(); ctx.font = `${size}px ${MONOF}`; ctx.letterSpacing = sp + 'px'; ctx.textAlign = align; ctx.textBaseline = 'alphabetic';
  ctx.globalAlpha = alpha; ctx.fillStyle = color; ctx.fillText(s, x, y); ctx.restore();
};

// the spoken words, as captions: a short phrase at a time, each word lights up as the voice reaches it
const SERIF = 'Georgia, "Noto Serif", "Times New Roman", serif';
const PHRASES = (() => {
  const out = [];
  VOICE.lines.forEach((L) => {
    let cur = [];
    L.words.forEach((w, i) => {
      cur.push(w);
      const last = i === L.words.length - 1;
      if (last || /[.,]$/.test(w.w) || cur.length >= 6) { out.push({ words: cur, t0: cur[0].t0, t1: last ? L.t1 + 0.25 : L.words[i + 1].t0 }); cur = []; }
    });
  });
  return out;
})();
function captions() {
  const P = PHRASES.find((p) => TT >= p.t0 - 0.05 && TT < p.t1);
  if (!P) return;
  ctx.save(); ctx.font = `bold 44px ${SERIF}`; ctx.textBaseline = 'alphabetic'; ctx.textAlign = 'left';
  const w44 = ctx.measureText(P.words.map((w) => w.w).join(' ')).width, fs = Math.min(44, Math.floor(44 * 780 / w44));
  ctx.font = `bold ${fs}px ${SERIF}`;
  const sp = ctx.measureText(' ').width, ws = P.words.map((w) => ctx.measureText(w.w).width);
  const total = ws.reduce((a, b) => a + b, 0) + sp * (ws.length - 1);
  let x = CX - total / 2;
  P.words.forEach((w, i) => {
    const on = TT >= w.t0, now = on && TT < (P.words[i + 1] ? P.words[i + 1].t0 : P.t1 - 0.25);
    ctx.fillStyle = now ? GOLD : CREAM; ctx.globalAlpha = on ? 1 : 0.32; ctx.fillText(w.w, x, 1425); x += ws[i] + sp;
  });
  ctx.restore();
}

// the frame, the same on every story scene: stamp, wordmark, progress line, handle
function furniture(tag) {
  ctx.save(); ctx.translate(70, 300); ctx.rotate(-0.052);
  ctx.font = `30px ${MONOF}`; ctx.letterSpacing = '4px';
  const w = ctx.measureText(tag).width;
  ctx.strokeStyle = GOLD; ctx.lineWidth = 2.5; ctx.strokeRect(-14, -34, w + 24, 52);
  ctx.fillStyle = GOLD; ctx.textBaseline = 'alphabetic'; ctx.fillText(tag, -2, 2); ctx.restore();
  mono('THELIVU', 940, 304, 34, GOLD, 'right', 1, 8);
  ctx.save(); ctx.globalAlpha = 0.9; ctx.fillStyle = 'rgba(179,168,145,0.3)'; ctx.fillRect(70, 1528, 870, 4);
  ctx.fillStyle = GOLD; ctx.fillRect(70, 1528, 870 * clamp(TT / DURATION), 4); ctx.restore();
  mono('thelivu.reports · sources in bio', 70, 1496, 26, DIM, 'left', 0.75, 2);
  captions();
}

// 1. THE RULE ---------------------------------------------------------------------------------------------------------
function sceneRule() {
  const cu = TIMELINE.cues;
  fillAll(INK);
  line('Central money must be', CX, 560, 60, runS(cu.rule, 0.9));
  line('passed on within', CX, 640, 60, runS(cu.rule + 0.45, 0.9));
  line('3 days', CX, 930, 170, runS(cu.days3 - 0.2, 0.9), CREAM, { bold: true });
  // a day axis, 0 to 15: the deadline marks day 3
  const x0 = 130, ux = 50, y = 1180, X = (d) => x0 + d * ux, ap = runS(cu.axis, 1.0);
  segLine(X(0), y, X(15), y, DIM, 4, ap);
  for (let d = 0; d <= 15; d += 3) { segLine(X(d), y - 10, X(d), y + 10, DIM, 3, ap); mText(String(d), X(d), y + 52, 32, { color: DIM, alpha: ap }); }
  mText('days from receipt', X(7.5), y + 100, 32, { color: DIM, alpha: ap });
  const dp = runS(cu.days3 + 0.3, 0.5);
  segLine(X(3), y - 120, X(3), y, CREAM, 6, dp);
  line('deadline', X(3), y - 140, 40, dp, CREAM);
  mText('15 days from 2022-23', X(15), y - 40, 32, { color: DIM, alpha: runS(cu.days3 + 0.9, 0.5), align: 'right' });
  furniture('CAG AUDIT · NAGALAND');
}

// 2. THE DELAY --------------------------------------------------------------------------------------------------------
function sceneDelay() {
  const cu = TIMELINE.cues;
  fillAll(INK);
  line('₹1,710.34 crore', CX, 500, 104, runS(cu.big, 1.0), GOLD, { bold: true });
  line([{ s: 'was released ', c: CREAM }, { s: 'late', c: LATE }], CX, 590, 62, runS(cu.late, 0.8));
  // bars, 3 px per day from x = 130; rows: shortest and longest delay
  const x0 = 130, ppd = 3, ay = 1230, ap = runS(cu.bars - 0.3, 0.8);
  segLine(x0, ay, x0 + 240 * ppd, ay, DIM, 4, ap);
  for (let d = 0; d <= 240; d += 60) { segLine(x0 + d * ppd, ay - 10, x0 + d * ppd, ay + 10, DIM, 3, ap); mText(String(d), x0 + d * ppd, ay + 52, 32, { color: DIM, alpha: ap }); }
  mText('days late', x0 + 120 * ppd, ay + 100, 32, { color: DIM, alpha: ap });
  const rows = [[4, 'shortest delay', 800, cu.bars, 0.4], [238, 'longest delay', 1010, cu.longest, 1.8]];
  rows.forEach(([d, lab, y, t0, dur]) => {
    const p = runS(t0, dur), v = d * p;
    mText(lab, x0, y - 92, 40, { color: DIM, align: 'left', alpha: runS(t0 - 0.2, 0.4) });
    if (p > 0.001) { ctx.save(); ctx.fillStyle = rgbaM(LATE, 0.28); ctx.strokeStyle = LATE; ctx.lineWidth = 4; ctx.fillRect(x0, y - 70, Math.max(2, v * ppd), 140); ctx.strokeRect(x0, y - 70, Math.max(2, v * ppd), 140); ctx.restore(); }
    mText(Math.round(v) + ' days', Math.min(x0 + v * ppd + 20, 930 - textW('238 days', 52)), y + (v * ppd > 640 ? -96 : 18), 52, { color: LATE, align: 'left', alpha: runS(t0, 0.3) });
  });
  line('238 days = 34 weeks', CX, 1160, 90, runS(Math.min(cu.longest + 1.9, ERA_LIST[1][1] - 2.4), 0.8), LATE, { bold: true });
  furniture('CAG AUDIT · NAGALAND');
}

// 3. THE BILL ---------------------------------------------------------------------------------------------------------
function sceneBill() {
  const cu = TIMELINE.cues;
  fillAll(INK);
  line('Late release carries interest', CX, 520, 60, runS(E0 + 0.2, 1.0));
  line('interest at 12% on late releases', CX, 600, 44, runS(cu.bill, 0.8), DIM);
  line('Audit: the reasons for the delays', CX, 1180, 40, runS(cu.why, 0.8), DIM);
  line('were neither on record nor given', CX, 1235, 40, runS(cu.why + 0.3, 0.8), DIM);
  const v = keysM([[cu.count, 0], [cu.count + 1.8, 22.37]]), full = '₹22.37 crore', fw = textW(full, 130, { bold: true });
  mText('₹' + money(v) + ' crore', CX - fw / 2, 1000, 130, { color: LATE, align: 'left', bold: true, alpha: runS(cu.count - 0.1, 0.3) });
  line('interest liability the State ran up', CX, 1090, 46, runS(cu.count + 1.6, 0.8), CREAM);
  line('2019-20 and 2020-21', CX, 1310, 84, runS(cu.count + 1.8, 0.8), CREAM, { bold: true });
  furniture('CAG AUDIT · NAGALAND');
}

// 4. THE GAP ----------------------------------------------------------------------------------------------------------
function sceneShare() {
  const cu = TIMELINE.cues;
  fillAll(INK);
  line([{ s: 'The State owed ', c: CREAM }, { s: '₹338.09 crore', c: CREAM }], CX, 500, 64, runS(cu.owed, 1.0));
  line('as its own share, 2019-24', CX, 575, 44, runS(cu.owed + 0.4, 0.8), DIM);
  const x0 = 120, bw = 800, by = 760, bh = 240, rel = 233.70 / 338.09;
  const op = runS(cu.outline, 0.8);
  showCreation([[x0, by], [x0 + bw, by], [x0 + bw, by + bh], [x0, by + bh]], op, { c: CREAM, w: 4, closed: true, fill: 0 });
  const fp = runS(cu.fill, 1.4);
  if (fp > 0.001) { ctx.save(); ctx.fillStyle = rgbaM(GOLD, 0.85); ctx.fillRect(x0 + 2, by + 2, bw * rel * fp - 4, bh - 4); ctx.restore(); }
  const rp = runS(cu.red, 0.5);
  if (rp > 0.001) {
    const rx = x0 + bw * rel, rw = bw * (1 - rel) * rp;
    ctx.save(); ctx.fillStyle = rgbaM(LATE, 0.30); ctx.fillRect(rx, by + 2, rw - 2, bh - 4);
    ctx.beginPath(); ctx.rect(rx, by + 2, rw - 2, bh - 4); ctx.clip(); ctx.strokeStyle = rgbaM(LATE, 0.9); ctx.lineWidth = 3;
    for (let k = -bh; k < rw + bh; k += 22) { ctx.beginPath(); ctx.moveTo(rx + k, by + bh); ctx.lineTo(rx + k + bh, by); ctx.stroke(); }
    ctx.restore();
  }
  const gc = x0 + bw * rel / 2, rc = x0 + bw * rel + bw * (1 - rel) / 2;
  mText('released', gc, by - 24, 40, { color: DIM, alpha: runS(cu.fill + 0.8, 0.5) });
  mText('short', rc, by - 24, 40, { color: DIM, alpha: runS(cu.red + 0.2, 0.5) });
  const pg = runS(cu.pct1, 0.8), pr = runS(cu.pct2, 0.8);
  line('69%', gc, 1130, 124, pg, GOLD, { bold: true });
  line('₹233.70 crore', gc, 1210, 46, runS(cu.pct1 + 0.3, 0.7), GOLD);
  line('31%', rc, 1130, 124, pr, LATE, { bold: true });
  line('₹104.39 crore', rc, 1210, 46, runS(cu.pct2 + 0.3, 0.7), LATE);
  furniture('CAG AUDIT · NAGALAND');
}

// 5. THE REPLY --------------------------------------------------------------------------------------------------------
function sceneReply() {
  const cu = TIMELINE.cues;
  fillAll(INK);
  line('The State government’s reply', CX, 480, 56, runS(cu.reply, 0.9), GOLD);
  line('(December 2024)', CX, 545, 40, runS(cu.reply + 0.3, 0.7), DIM);
  [['It noted the audit and said releases', 680], ['would be pursued for timely release.', 745], ['Its 2023-24 matching share, it said,', 850], ['had been released in full.', 915]].forEach(([s, y], i) => line(s, CX, y, 46, runS(cu.reply + 0.8 + i * 0.55, 0.9), CREAM));
  segLine(160, 1090, 840, 1090, DIM, 2.5, runS(cu.source - 0.4, 0.8));
  const sp = runS(cu.source, 0.9);
  line('Source: CAG, Audit Report for the year', CX, 1160, 36, sp, DIM);
  line('ended 31 March 2024, Nagaland', CX, 1210, 36, runS(cu.source + 0.25, 0.9), DIM);
  line('paras 3.2.8.5 and 3.2.8.6 (MGNREGS)', CX, 1260, 36, runS(cu.source + 0.5, 0.9), DIM);
  segLine(160, 1310, 840, 1310, GOLD, 4, runS(cu.rule2, 1.6));
  furniture('CAG AUDIT · NAGALAND');
}

// 6. THE SIGN-OFF — silent: the logo and the descriptor ----------------------------------------------------------------
function sceneSignoff() {
  const cu = TIMELINE.cues, u = clamp((TT - E0) / (DURATION - E0));
  fillAll(LOGO_INK);
  const lp = runS(E0 - 0.3, 0.4), size = 560 * (1 + 0.05 * u);
  ctx.save(); ctx.globalAlpha = lp; ctx.drawImage(ASSETS['logo.png'], CX - size / 2, 790 - size / 2, size, size); ctx.restore();
  line('Fact-checked stories.', CX, 1190, 44, runS(E0 + 0.7, 0.8), CREAM);
  line('Every claim verified, every piece', CX, 1250, 44, runS(E0 + 0.9, 0.8), CREAM);
  line('human-reviewed.', CX, 1310, 44, runS(E0 + 1.1, 0.8), CREAM);
  mono('thelivu.reports', CX, 1400, 30, GOLD, 'center', runS(E0 + 1.5, 0.8), 6);
}
