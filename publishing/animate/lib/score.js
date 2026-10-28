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
  const allEras = ERAS.slice(0, -2), WIDE = STORY.format === 'wide';
  let eras = allEras, quietEnd = hit > 0 ? hit - 0.9 : srcT + 0.4;
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
  if (!WIDE) {
    TEX[mood]();
    if (hit > 0) pad(hit, srcT + 0.4, P.held, 0.04, { type: 'triangle', cut: 1100, att: 0.5, rel: 0.6, send: 0.5 });   // the signature: the same payoff hit and held chord in every mood
  } else {
    // LONG FORM: a documentary underscore with a beat, not a drone. One tempo per mood, a fixed grid, a chord every two bars, and layers that
    // enter and leave with the story's level:
    //   pads      soft chords under everything (cross-faded every two bars)
    //   bass      a rhythmic root pattern on the grid
    //   arp       an eighth-note arpeggio of the chord, accented on the beat
    //   hats      eighth-note hats, sixteenths at the peak
    //   kick/snare  a kick on 1 and 3 (a syncopated ghost at the peak), a soft snare on 2 and 4 once the story is driving
    //   melody    a four-bar hook that plays every other phrase (call and response), the thing a listener hums
    //   fills     a snare roll into every eighth bar, a cymbal wash on its downbeat
    // The level follows the story: build to the chapter holding the payoff, ebb, a second crest, resolve. A snare roll climbs into the payoff,
    // then 0.9 s of silence, one low hit and the held chord; the groove returns half a beat later at about half weight, without the kick.
    const chs = allEras.filter((er) => er.type === 'chapter').map((er) => er.t0), n = chs.length, end = hit > 0 ? srcT : srcT + 0.4;
    const C = hit > 0 ? Math.max(0, chs.filter((t) => t <= hit).length - 1) : Math.max(0, n - 2);
    const rk = allEras.filter((er) => er.type === 'chapter').findIndex((er) => er.beat && er.beat.data && er.beat.data.recap), m = rk >= 0 ? n - 1 : n;   // the recap chapter, when there is one, closes at a high level; the chapter before it resolves
    const lev0 = (k) => k === rk ? 0.85 : k < C ? 0.5 + 0.35 * (C ? k / C : 1) : k === C ? 1 : k === m - 1 ? 0.4 : 0.55 + 0.25 * ((k - C - 1) / Math.max(1, m - C - 2));
    const centres = chs.map((c0, k) => [(c0 + (k + 1 < n ? chs[k + 1] : end)) / 2, lev0(k)]);
    const lev = (t) => {                                                   // smooth between chapter centres
      if (!centres.length) return 0.7;
      if (t <= centres[0][0]) return centres[0][1];
      for (let i = 1; i < centres.length; i++) if (t <= centres[i][0]) { const [ta, la] = centres[i - 1], [tb, lb] = centres[i]; return la + (lb - la) * (t - ta) / (tb - ta); }
      return centres[centres.length - 1][1];
    };
    const GAP = hit > 0 ? [hit - 0.9, hit + 2.4] : [1e9, 1e9];             // the payoff's silence
    const inGap = (t) => t > GAP[0] - 0.12 && t < GAP[1];
    const fadeOut = (t) => t > end - 5 ? Math.max(0, (end + 0.4 - t) / 5.4) : 1;   // the last seconds ease away under the source card
    const post = (t) => t >= GAP[1] ? 0.6 : 1;                             // after the payoff everything is quieter
    const BPM = { grave: 72, tense: 100, neutral: 96, hopeful: 104, urgent: 116, reflective: 78, investigative: 94, cold: 88 }[mood];
    const beat = 60 / BPM, e8 = beat / 2, bar = beat * 4, seq = [0, 1, 2, 1];
    const chordB = (t) => P.chords[(seq[Math.floor(t / (2 * bar)) % 4] + start) % P.chords.length];
    const cut = (sp) => { const r = []; sp.forEach(([a, b2]) => { if (b2 <= GAP[0] || a >= GAP[1]) r.push([a, b2]); else { if (a < GAP[0] - 0.4) r.push([a, GAP[0] - 0.4]); if (b2 > GAP[1]) r.push([GAP[1], b2]); } }); return r; };
    // 1. pads: one chord per two bars, overlapped so they never break
    for (let t0 = 0; t0 < end; t0 += 2 * bar) {
      const c = chordB(t0 + 0.01), L = lev(t0 + bar);
      cut([[t0 - 0.6, Math.min(end, t0 + 2 * bar + 0.6)]]).forEach(([a, b2]) => {
        a = Math.max(0, a); if (b2 - a < 1.2) return;
        const g = fadeOut(t0 + bar) * post(a), ar = Math.min(1.2, (b2 - a) / 3);
        pad(a, b2, c, 0.016 * (0.5 + 0.5 * L) * g, { type: 'sawtooth', cut: 600 + 1600 * L, att: ar, rel: ar, send: 0.55 });
        pad(a, b2, [c[1], c[2] || c[0]], 0.01 * g, { type: 'triangle', cut: 1600, att: ar, rel: ar, send: 0.6, pan: 0.1 });
      });
    }
    // 2. the grid, one step per eighth note
    const bassPat = [1, 0, 1, 0, 1, 1, 0, 1], arpPat = [0, 1, 2, 3, 2, 1, 2, 1];
    const motif = { 0: 4, 3: 3, 5: 2, 8: 3, 11: 1, 12: 0 };                // step in a 16-step phrase -> scale degree
    for (let i = 0; ; i++) {
      const t = i * e8; if (t >= end - 2) break;
      if (inGap(t)) continue;
      const L = lev(t), g = fadeOut(t) * post(t), bt = i % 8, barN = Math.floor(i / 8), c = chordB(t), post1 = t >= GAP[1];
      const root = nz(c[0]) / 2, odd = bt % 2, pan = ((i % 4) - 1.5) * 0.2;
      if (barN >= 1 && bassPat[bt]) bass(t, bt === 7 ? nz(c[1]) / 2 : bt === 5 ? root * 2 : root, 0.05 * (0.6 + 0.4 * L) * g);
      if (!post1 && barN >= 3 && L > 0.55 && (bt === 0 || bt === 4)) sub(t, 0.07 * L * g);
      if (!post1 && barN >= 3 && L > 0.85 && bt === 3) sub(t, 0.035 * g);
      if (barN >= 4 && L > 0.7 && (bt === 2 || bt === 6)) noiseHit(t, 0.16, 'bandpass', 1900, 0.9, 0.026 * L * g, 0.05, 0.12);
      if (barN >= 2 && L > 0.5) {
        noiseHit(t + (odd ? 0.015 : 0), 0.04, 'highpass', 7500, 1, (odd ? 0.011 : 0.016) * L * g, pan);
        if (L > 0.9) noiseHit(t + e8 / 2, 0.03, 'highpass', 8000, 1, 0.007 * g, -pan);
      }
      const an = nz(c[arpPat[bt] % c.length]) * (L > 0.9 && barN % 4 >= 2 ? 2 : 1);
      pluck(t, an, (0.02 + 0.028 * L) * (bt % 4 === 0 ? 1.3 : 1) * g, pan, beat * 1.5, P.bright * (0.5 + 0.5 * L), 0.4);
      if (L > 0.55 && Math.floor(barN / 4) % 2 === 1 && motif[i % 16] !== undefined) pluck(t, nz(pick(motif[i % 16])), 0.06 * L * g, 0.2, beat * 3, P.bright, 0.6);
      if (barN % 8 === 7 && bt >= 4 && L > 0.5) noiseHit(t, 0.1, 'bandpass', 2200, 0.8, (0.012 + 0.008 * (bt - 4)) * g, -0.1, 0.1);
      if (barN % 8 === 0 && barN > 0 && bt === 0 && L > 0.6) noiseHit(t, 0.9, 'highpass', 5000, 0.7, 0.022 * L * g, 0, 0.4);
    }
    // 3. the run-up: a snare roll that quickens into the payoff's silence
    if (hit > 0) for (let t = GAP[0] - 4, d = beat / 2; t < GAP[0] - 0.2; t += d, d = Math.max(0.07, d * 0.9)) noiseHit(t, 0.08, 'bandpass', 2000, 0.9, 0.012 + 0.03 * (t - (GAP[0] - 4)) / 3.8, 0, 0.1);
    // 4. each chapter card: a low whoosh into it
    chs.forEach((c0, k) => { if (k > 0) { to = 's'; sweep(c0 - 1.8, c0, 0.03, 160, 1600); sub(c0, 0.045); to = 'm'; } });   // a low whoosh and a soft thud, no saw riser (it squeaks)
    // 5. the payoff: the held chord rings out over the return
    if (hit > 0) pad(hit, hit + 9, P.held, 0.035, { type: 'triangle', cut: 1100, att: 0.5, rel: 3, send: 0.5 });
  }
  // scene cues (reels only: in a long video single tones on every scene are what makes it sound quirky)
  if (!WIDE) eras.forEach((er, i) => {
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
  if (!WIDE) ERAS.forEach((er) => { if (er.type === 'compare' || er.type === 'figure' || er.type === 'share') for (let i = 0; i < 6; i++) blip(er.t0 + 2 + i * 0.22, 1400 + i * 70, 1200, 0.02, 0.02); });
  if (hit > 0) { sub(hit, 0.9); noiseHit(hit, 0.5, 'lowpass', 400, 0.7, 0.35); chime(hit + 0.05, [nz(P.held[1]), nz(P.held[2])], 0.06); }
  chime(signoff + 0.4, [nz('D5'), nz('Fs5'), nz('A5')], 0.04);
