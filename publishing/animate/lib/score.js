  // SCORE BODY — a score that belongs to THIS story. The mood (STORY.mood, else drawn from the story name) picks the key and the colour,
  // the story name seeds the variation, and each scene type has its own cue:
  //   picture beat  a riser and a chime lead into it        timeline  a rising pluck on each event line
  //   excerpt       a paper rustle as the quote appears     list      a low thud as each item lands (the bad news, one by one)
  //   compare       a low note, then a high one             figure / share  counter ticks
  // The pad opens as the story builds, goes SILENT before the payoff, one low hit lands it, a held chord carries to the source card.
  const T = TIMELINE, hit = HIT, signoff = ERAS[ERAS.length - 1].t0, srcT = ERAS[ERAS.length - 2].t0;
  // Eight moods. Each has its own chords AND its own texture (what plays under the voice), so they differ in sound, not only in pitch.
  const PAL = {
    grave:         { chords: [['D3', 'A3', 'F4'], ['Bb2', 'F3', 'D4'], ['G2', 'D3', 'Bb3']], held: ['D3', 'A3', 'D4', 'F4'], scale: ['D4', 'F4', 'G4', 'A4', 'C5', 'D5'], pluck: 0.1, bright: 2000 },
    tense:         { chords: [['A2', 'E3', 'A3', 'C4'], ['F2', 'C3', 'F3', 'A3'], ['E2', 'B2', 'E3', 'G3']], held: ['A2', 'E3', 'A3', 'C4', 'E4'], scale: ['A3', 'C4', 'E4', 'G4', 'A4', 'B4'], pluck: 0.1, bright: 2600 },
    neutral:       { chords: [['D3', 'A3', 'Fs4'], ['E3', 'B3', 'Fs4'], ['G3', 'D4', 'B4']], held: ['D3', 'A3', 'D4', 'Fs4'], scale: ['A4', 'B4', 'D5', 'E5', 'Fs4', 'A4'], pluck: 0.12, bright: 3000 },
    hopeful:       { chords: [['F3', 'C4', 'E4', 'A4'], ['G3', 'D4', 'G4', 'B4'], ['C3', 'G3', 'E4', 'G4']], held: ['F3', 'C4', 'F4', 'A4', 'C5'], scale: ['C5', 'D5', 'E5', 'G5', 'A5', 'C5'], pluck: 0.13, bright: 3600 },
    urgent:        { chords: [['E3', 'B3', 'E4', 'G4'], ['C3', 'G3', 'C4', 'E4'], ['D3', 'A3', 'D4', 'Fs4']], held: ['E3', 'B3', 'E4', 'G4', 'B4'], scale: ['E4', 'G4', 'A4', 'B4', 'D5', 'E5'], pluck: 0.1, bright: 3400 },
    reflective:    { chords: [['C3', 'G3', 'E4'], ['A2', 'E3', 'C4'], ['F2', 'C3', 'A3']], held: ['C3', 'G3', 'C4', 'E4'], scale: ['E4', 'G4', 'A4', 'C5', 'D5', 'E5'], pluck: 0.12, bright: 1800 },
    investigative: { chords: [['G2', 'D3', 'G3', 'Bb3'], ['Eb3', 'Bb3', 'D4'], ['F3', 'C4', 'Eb4']], held: ['G2', 'D3', 'G3', 'Bb3', 'D4'], scale: ['G3', 'Bb3', 'C4', 'D4', 'F4', 'G4'], pluck: 0.11, bright: 1500 },
    cold:          { chords: [['B2', 'Fs3', 'B3'], ['G2', 'D3', 'G3'], ['E3', 'B3', 'E4']], held: ['B2', 'Fs3', 'B3', 'Ds4'], scale: ['B4', 'Cs5', 'Ds5', 'Fs5', 'Gs5', 'B5'], pluck: 0.09, bright: 4200 },
  };
  const MOODS = Object.keys(PAL), R = RNG('score', STORY.name || STORY.title || '');
  const mood = PAL[STORY.mood] ? STORY.mood : MOODS[Math.floor(R.f() * MOODS.length)], P = PAL[mood];
  const start = Math.floor(R.f() * P.chords.length);      // which chord the story opens on
  const pace = 0.9 + R.f() * 0.2, rhythm = Math.floor(R.f() * 3);   // tempo factor and one of three rhythm patterns per mood
  const pick = (k) => P.scale[(k + start) % P.scale.length];
  const eras = ERAS.slice(0, -2), quietEnd = hit > 0 ? hit - 0.9 : srcT + 0.4;
  const chordAt = (t) => { const k = Math.max(0, eras.findIndex((er) => t < er.t1)); return P.chords[(k + start) % P.chords.length]; };
  const prog = (t) => Math.min(1, t / Math.max(1, quietEnd));
  // a note of the current chord, stepping through it: n = 0, 1, 2 ... (octave up past the top)
  const chordNote = (t, n) => { const c = chordAt(t); return nz(c[n % c.length]) * (n >= c.length ? 2 : 1); };
  to = 'm';
  const TEX = {
    // slow low drone that moves with the chords, one long soft note every few seconds. No pad, no rhythm: weight.
    grave() {
      eras.forEach((er, i) => { const c = P.chords[(i + start) % P.chords.length], t1 = Math.min(quietEnd, er.t1 + 0.6); if (t1 - er.t0 > 0.8) drone(er.t0, t1, nz(c[0]) / 2, 0.05, { att: 0.9, rel: 0.7 }); });
      for (let t = 1.5 + rhythm; t < quietEnd; t += 4.2 * pace) pluck(t, chordNote(t, 1) / 2, 0.08, 0, 1.6, 900, 0.7);
    },
    // a clock: dry ticks that quicken, a heartbeat under them, one detuned saw drone that opens up. No pad chords.
    tense() {
      for (let t = 0.8, gap = 0.5 * pace; t < quietEnd; t += gap, gap = Math.max(0.2, gap * 0.992)) { to = 's'; noiseHit(t, 0.03, 'highpass', 6500, 1, 0.035, ((t * 3) % 1) - 0.5); to = 'm'; }
      for (let t = 1.2, gap = 1.2 * pace; t < quietEnd; t += gap, gap = Math.max(0.6, gap * 0.985)) { bass(t, nz('A2'), 0.06); bass(t + 0.2, nz('A2'), 0.035); }
      eras.forEach((er, i) => { const t1 = Math.min(quietEnd, er.t1 + 0.4); if (t1 - er.t0 > 0.8) pad(er.t0, t1, [P.chords[(i + start) % P.chords.length][0]], 0.016, { type: 'sawtooth', cut: 500 + 900 * prog(er.t0), att: 0.6, rel: 0.5 }); });
    },
    // a steady piano-like figure walking through the chord, quiet. No pad.
    neutral() {
      const step = 0.5 * pace, pat = [[0, 1, 2, 1], [0, 2, 1, 2], [0, 1, 2, 3]][rhythm];
      for (let t = 0.6, n = 0; t < quietEnd; t += step, n++) pluck(t, chordNote(t, pat[n % 4]), 0.07, -0.2 + (n % 4) * 0.13, 0.55, 2600, 0.3);
    },
    // bells and a lifting bass: a bell on each chord change, a rising line, a soft warm pad.
    hopeful() {
      eras.forEach((er, i) => { const c = P.chords[(i + start) % P.chords.length], t1 = Math.min(quietEnd, er.t1 + 0.5);
        if (t1 - er.t0 > 0.8) pad(er.t0, t1, c, 0.016, { type: 'sine', cut: 1400, att: 0.8, rel: 0.6, send: 0.6 });
        chime(er.t0 + 0.1, [nz(c[1]) * 2, nz(c[2]) * 2], 0.035, -0.2 + (i % 3) * 0.2); });
      for (let t = 1, n = 0; t < quietEnd; t += 2.4 * pace, n++) pluck(t, nz(pick(n)) * 2, 0.06, 0.25, 0.9, 4200, 0.6);
    },
    // fast 16th arpeggio in a saw pulse feel with a driving bass: things are moving.
    urgent() {
      const step = 0.23 * pace;
      for (let t = 0.4, n = 0; t < quietEnd; t += step, n++) { pluck(t, chordNote(t, [0, 1, 2, 3, 2, 1][n % 6]), 0.06, ((n % 5) - 2) * 0.15, 0.2, 3800, 0.15); if (n % 2 === 0) bass(t, chordNote(t, 0) / 2, 0.05); }
    },
    // very sparse: a few long notes ringing into a wide reverb, a very low pad. Space between the facts.
    reflective() {
      eras.forEach((er, i) => { const c = P.chords[(i + start) % P.chords.length], t1 = Math.min(quietEnd, er.t1 + 0.6); if (t1 - er.t0 > 0.8) pad(er.t0, t1, [c[0], c[1]], 0.014, { type: 'sine', cut: 700, att: 1.0, rel: 0.8, send: 0.7 }); });
      for (let t = 1.2, n = 0; t < quietEnd; t += 3.1 * pace, n++) pluck(t, nz(pick(n * 2)), 0.09, ((n % 3) - 1) * 0.3, 1.8, 1700, 0.9);
    },
    // a muted marimba-like syncopated pattern over a low pedal: something is being dug into.
    investigative() {
      const step = 0.375 * pace, pat = [[1, 0, 1, 0, 0, 1, 0, 1], [1, 0, 0, 1, 0, 1, 0, 0], [1, 1, 0, 1, 0, 0, 1, 0]][rhythm];
      for (let t = 0.5, n = 0; t < quietEnd; t += step, n++) if (pat[n % 8]) pluck(t, chordNote(t, (n >> 1) % 3 + 1), 0.07, ((n % 4) - 1.5) * 0.2, 0.14, 1300, 0.12);
      eras.forEach((er, i) => { const t1 = Math.min(quietEnd, er.t1 + 0.4); if (t1 - er.t0 > 0.8) drone(er.t0, t1, nz(P.chords[(i + start) % P.chords.length][0]), 0.04, { att: 0.5, rel: 0.5 }); });
    },
    // glassy: high sine tones on a slow grid with a clock tick between them, almost no low end. Distance, process, records.
    cold() {
      for (let t = 0.7, n = 0; t < quietEnd; t += 1.6 * pace, n++) { chime(t, [nz(pick(n * 2))], 0.03, ((n % 4) - 1.5) * 0.25); to = 's'; noiseHit(t + 0.8 * pace, 0.02, 'highpass', 7000, 1, 0.03); to = 'm'; }
      eras.forEach((er, i) => { const t1 = Math.min(quietEnd, er.t1 + 0.5); if (t1 - er.t0 > 0.8) drone(er.t0, t1, nz(P.chords[(i + start) % P.chords.length][0]), 0.03, { att: 1.0, rel: 0.7 }); });
    },
  };
  TEX[mood]();
  if (hit > 0) pad(hit, srcT + 0.4, P.held, 0.04, { type: 'triangle', cut: 1100, att: 0.5, rel: 0.6, send: 0.5 });   // the signature: the same payoff hit and held chord in every mood
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
