  // SCORE BODY — a score that belongs to THIS story. The mood (STORY.mood, else drawn from the story name) picks the key and the colour,
  // the story name seeds the variation, and each scene type has its own cue:
  //   picture beat  a riser and a chime lead into it        timeline  a rising pluck on each event line
  //   excerpt       a paper rustle as the quote appears     list      a low thud as each item lands (the bad news, one by one)
  //   compare       a low note, then a high one             figure / share  counter ticks
  // The pad opens as the story builds, goes SILENT before the payoff, one low hit lands it, a held chord carries to the source card.
  const T = TIMELINE, hit = HIT, signoff = ERAS[ERAS.length - 1].t0, srcT = ERAS[ERAS.length - 2].t0;
  const PAL = {
    grave:   { chords: [['D3', 'A3', 'F4'], ['Bb2', 'F3', 'D4'], ['G2', 'D3', 'Bb3']], held: ['D3', 'A3', 'D4', 'F4'], scale: ['D4', 'F4', 'G4', 'A4', 'C5', 'D5'], cut: 650, rise: 500, type: 'triangle', pluck: 0.1, bright: 2200 },
    tense:   { chords: [['A2', 'E3', 'A3', 'C4'], ['F2', 'C3', 'F3', 'A3'], ['E2', 'B2', 'E3', 'G3']], held: ['A2', 'E3', 'A3', 'C4', 'E4'], scale: ['A3', 'C4', 'E4', 'G4', 'A4', 'B4'], cut: 700, rise: 900, type: 'sawtooth', pluck: 0.1, bright: 2600, pulse: true },
    neutral: { chords: [['D3', 'A3', 'Fs4'], ['E3', 'B3', 'Fs4'], ['G3', 'D4', 'B4']], held: ['D3', 'A3', 'D4', 'Fs4'], scale: ['A4', 'B4', 'D5', 'E5', 'Fs4', 'A4'], cut: 900, rise: 400, type: 'triangle', pluck: 0.12, bright: 3000 },
    hopeful: { chords: [['F3', 'C4', 'E4', 'A4'], ['G3', 'D4', 'G4', 'B4'], ['C3', 'G3', 'E4', 'G4']], held: ['F3', 'C4', 'F4', 'A4', 'C5'], scale: ['C5', 'D5', 'E5', 'G5', 'A5', 'C5'], cut: 1100, rise: 700, type: 'triangle', pluck: 0.13, bright: 3600 },
  };
  const MOODS = Object.keys(PAL), R = RNG('score', STORY.name || STORY.title || '');
  const mood = PAL[STORY.mood] ? STORY.mood : MOODS[Math.floor(R.f() * MOODS.length)], P = PAL[mood];
  const start = Math.floor(R.f() * P.chords.length);     // which chord the story opens on: two stories in one mood still differ
  const pick = (k) => P.scale[(k + start) % P.scale.length];
  const eras = ERAS.slice(0, -2), quietEnd = hit > 0 ? hit - 0.9 : srcT + 0.4;
  to = 'm';
  // the pad: one chord per scene run, brighter as the story builds, stopping 0.9 s before the payoff
  eras.forEach((er, i) => {
    const t0 = er.t0, t1 = Math.min(quietEnd, er.t1 + 0.5); if (t1 - t0 < 0.8) return;
    const chord = P.chords[(i + start) % P.chords.length], prog = i / Math.max(1, eras.length - 1);
    pad(t0, t1, chord, 0.026, { type: P.type, cut: P.cut + P.rise * prog, att: 0.5, rel: 0.5 });
  });
  if (hit > 0) pad(hit, srcT + 0.4, P.held, 0.04, { type: 'triangle', cut: 1100, att: 0.5, rel: 0.6, send: 0.5 });
  if (P.pulse) for (let t = 1.2, gap = 1.1; t < quietEnd; t += gap, gap = Math.max(0.55, gap * 0.985)) bass(t, nz('A2'), 0.05);   // a heartbeat that quickens
  // scene cues
  eras.forEach((er, i) => {
    const b = er.beat, lines = b.say.map((s) => VL(s.id)), t0 = er.t0;
    if (er.type === 'illustration') {
      if (t0 > 0.5) { riser(Math.max(0, t0 - 1.1), t0, 0.05); chime(t0 + 0.02, [nz(pick(i)), nz(pick(i + 2))], 0.05); }
      else chime(t0 + 0.3, [nz(pick(0)), nz(pick(2)), nz(pick(4))], 0.05);
    } else if (er.type === 'timeline') {
      lines.forEach((L, k) => pluck(L.t0 + 0.05, nz(pick(k * 2)), P.pluck, -0.3 + k * 0.2, 0.5, P.bright, 0.4));
    } else if (er.type === 'excerpt') {
      to = 's'; noiseHit(t0 + 0.25, 0.22, 'highpass', 3500, 0.7, 0.05, 0.1, 0.15); to = 'm';
      pluck(t0 + 0.3, nz(pick(i)), P.pluck, 0, 0.5, P.bright, 0.4);
    } else if (er.type === 'list') {
      lines.forEach((L, k) => { bass(L.t0 + 0.05, nz(['D2', 'A2'][k % 2]), 0.09); pluck(L.t0 + 0.08, nz(pick(k + 1)), P.pluck * 0.7, 0.2 - k * 0.1, 0.35, P.bright, 0.3); });
    } else if (er.type === 'compare') {
      lines.forEach((L, k) => pluck(L.t0 + 0.05, nz(k === 0 ? pick(0) : pick(4)), P.pluck * 1.1, k ? 0.3 : -0.3, 0.6, P.bright, 0.4));
    } else {
      pluck(t0 + 0.3, nz(pick(i)), P.pluck, -0.2 + (i % 5) * 0.1, 0.5, P.bright, 0.35);
    }
  });
  to = 's';
  ERAS.forEach((er) => { if (er.type === 'compare' || er.type === 'figure' || er.type === 'share') for (let i = 0; i < 6; i++) blip(er.t0 + 2 + i * 0.22, 1400 + i * 70, 1200, 0.02, 0.02); });
  if (hit > 0) { sub(hit, 0.9); noiseHit(hit, 0.5, 'lowpass', 400, 0.7, 0.35); chime(hit + 0.05, [nz(P.held[1]), nz(P.held[2])], 0.06); }
  chime(signoff + 0.4, [nz('D5'), nz('Fs5'), nz('A5')], 0.04);
