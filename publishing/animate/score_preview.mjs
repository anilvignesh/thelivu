#!/usr/bin/env node
// Hear a reel's score on the laptop in seconds, without a render on the VM.
//   node publishing/animate/score_preview.mjs <piece dir> [--out file.mp3] [--mood grave|tense|neutral|hopeful]
// Needs ~/animate (the renderer kit; rsync it from the VM, minus pieces/) and a piece folder (pieces/<name>) with its voice.json.
// Copies lib/score.js into the piece, rebuilds index.html, renders the score alone (music + sfx, no frames, no voice) and writes an mp3.
// The piece folder is the same one build_piece.py makes, so what you hear is what the reel gets.
import { createRequire } from 'node:module';
import { execSync, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const argv = process.argv.slice(2);
const piece = path.resolve(argv[0] || '');
const opt = (n) => { const i = argv.indexOf('--' + n); return i > -1 ? argv[i + 1] : null; };
if (!argv[0] || !fs.existsSync(path.join(piece, 'piece.json'))) { console.error('usage: score_preview.mjs <piece dir> [--out f.mp3] [--mood m]'); process.exit(2); }
const KIT = path.resolve(opt('kit') || path.join(os.homedir(), 'animate'));
const require = createRequire(import.meta.url);
const { chromium } = (() => { try { return require('playwright'); } catch { return require(path.join(execSync('npm root -g').toString().trim(), 'playwright')); } })();

fs.copyFileSync(path.join(HERE, 'lib', 'score.js'), path.join(piece, 'src', 'score.js'));
if (opt('mood')) {                                         // try a mood without touching the story: patch the page's copy
  const p = path.join(piece, 'src', 'head.html'); const h = fs.readFileSync(p, 'utf8');
  fs.writeFileSync(p, h.replace(/const STORY = (\{.*\});/, (m, j) => `const STORY = ${JSON.stringify({ ...JSON.parse(j), mood: opt('mood') })};`));
}
const b = spawnSync('node', [path.join(KIT, 'tools', 'build.mjs'), piece], { stdio: 'inherit' });
if (b.status !== 0) process.exit(b.status);

const browser = await chromium.launch();
const page = await browser.newPage();
page.on('pageerror', (e) => { console.error('page error:', e.message); });
await page.goto(pathToFileURL(path.join(piece, 'index.html')).href + '?export=1');
await page.waitForFunction(() => typeof window.renderAudioWav === 'function');
const t0 = Date.now();
const b64 = await page.evaluate(async () => await window.renderAudioWav());
await browser.close();
const wav = path.join(os.tmpdir(), 'score-preview.wav'), out = path.resolve(opt('out') || path.join(piece, 'score-preview.mp3'));
fs.writeFileSync(wav, Buffer.from(b64, 'base64'));
spawnSync('ffmpeg', ['-y', '-v', 'error', '-i', wav, '-b:a', '160k', out], { stdio: 'inherit' });
console.log(`score ${((Date.now() - t0) / 1000).toFixed(1)}s -> ${out}`);
