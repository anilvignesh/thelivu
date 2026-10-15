// =====================================================================
//  ERAS, BRIDGES — math demo (read by kit/morph.js). No camera moves: a manim stage holds still.
// =====================================================================
const ERA_BG = ['#17140D', '#17140D', '#17140D', '#17140D', '#17140D', '#1B1710'];
const BRIDGES = [];   // hard cuts on the 8th grid: each cut is a next-step
// one slow, eased push-in over every scene: the stage holds still otherwise, and a held frame with no motion reads as a dead beat
function pieceCam(era, t) {
  const e = ERA_LIST[era], u = clamp((t - e[0]) / (e[1] - e[0]));
  return era === 5 ? camera(540, 960, 1) : camera(540 + 24 * (u - 0.5), 960 - 50 * u, 1 + 0.12 * u);   // a steady, linear push: the voice runs long, so the picture never rests
}
