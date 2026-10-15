// =====================================================================
//  ERAS, BRIDGES — hard cuts, a steady push-in on every scene except the full-bleed illustration and the sign-off
// =====================================================================
const ERA_BG = ERAS.map((e) => (e.type === 'signoff' ? '#1B1710' : '#17140D'));
const BRIDGES = [];
function pieceCam(era, t) {
  const e = ERA_LIST[era], u = clamp((t - e[0]) / (e[1] - e[0])), type = ERAS[era].type;
  return type === 'signoff' || type === 'illustration' ? camera(540, 960, 1) : camera(540 + 24 * (u - 0.5), 960 - 50 * u, 1 + 0.12 * u);
}
