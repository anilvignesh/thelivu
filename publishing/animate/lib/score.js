  // SCORE BODY — generic: a low pad under the voice, a soft pluck as each scene opens, counter ticks on a compare or figure, SILENCE
  // before the payoff (the pad stops 0.9s ahead), one low hit on it, a held chord to the source card, one quiet chime at the sign-off.
  const T = TIMELINE, hit = HIT, signoff = ERAS[ERAS.length - 1].t0, srcT = ERAS[ERAS.length - 2].t0;
  to = 'm';
  const quietEnd = hit > 0 ? hit - 0.9 : srcT + 0.4;
  pad(0.0, quietEnd, ['D3', 'A3', 'Fs4'], 0.028, { type: 'triangle', cut: 900, att: 0.4, rel: 0.4 });
  if (hit > 0) pad(hit, srcT + 0.4, ['D3', 'A3', 'D4', 'Fs4'], 0.04, { type: 'triangle', cut: 1100, att: 0.5, rel: 0.6, send: 0.5 });
  ERAS.slice(0, -2).forEach((er, i) => pluck(er.t0 + 0.3, nz(['A4', 'B4', 'D5', 'E5', 'Fs4', 'A4'][i % 6]), 0.12, -0.2 + (i % 5) * 0.1, 0.5, 3000, 0.35));
  to = 's';
  ERAS.forEach((er) => { if (er.type === 'compare' || er.type === 'figure' || er.type === 'share') for (let i = 0; i < 6; i++) blip(er.t0 + 2 + i * 0.22, 1400 + i * 70, 1200, 0.02, 0.02); });
  if (hit > 0) { sub(hit, 0.9); noiseHit(hit, 0.5, 'lowpass', 400, 0.7, 0.35); chime(hit + 0.05, [nz('D4'), nz('A4')], 0.06); }
  chime(signoff + 0.4, [nz('D5'), nz('Fs5'), nz('A5')], 0.04);
