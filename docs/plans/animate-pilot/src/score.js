  // SCORE BODY — Nagaland MGNREGS, under the voice. A low pad, soft plucks on the write-ons, a tick per counter, SILENCE
  // before the red reveal (the pad stops 0.9s ahead), one low hit on it, a held chord to the sign-off, then a single quiet chime.
  const T = TIMELINE, cu = T.cues, c5 = ERA_LIST[5][0];
  to = 'm';
  pad(0.0, cu.red - 0.9, ['D3', 'A3', 'Fs4'], 0.028, { type: 'triangle', cut: 900, att: 0.4, rel: 0.4 });
  pad(cu.red, c5 + 0.4, ['D3', 'A3', 'D4', 'Fs4'], 0.04, { type: 'triangle', cut: 1100, att: 0.5, rel: 0.6, send: 0.5 });
  [['D4', 0.3], ['Fs4', 0.55], ['A4', 0.85]].forEach(([n, t], i) => pluck(cu.rule + t, nz(n), 0.12, -0.2 + i * 0.2, 0.5, 2600, 0.35));
  [cu.big, cu.late, cu.bill, cu.owed, cu.reply].forEach((t, i) => pluck(t, nz(['A4', 'B4', 'D5', 'E5', 'Fs4'][i]), 0.12, -0.2 + i * 0.1, 0.5, 3000, 0.35));
  chime(cu.pct1, [nz('D5'), nz('A5'), nz('Fs6')], 0.05);
  to = 's';
  for (let i = 0; i < 8; i++) blip(cu.count + 0.1 + i * 0.22, 1400 + i * 70, 1200, 0.02, 0.02);   // the counter ticking up
  blip(cu.longest + 1.8, 900, 1200, 0.03, 0.03);
  sub(cu.red, 0.9);
  noiseHit(cu.red, 0.5, 'lowpass', 400, 0.7, 0.35);
  chime(cu.red + 0.05, [nz('D4'), nz('A4')], 0.06);
  chime(c5 + 0.4, [nz('D5'), nz('Fs5'), nz('A5')], 0.04);
