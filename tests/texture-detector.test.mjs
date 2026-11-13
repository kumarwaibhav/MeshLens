import assert from 'node:assert/strict';
import test from 'node:test';
import {createTextureDetector, TextureQualityError} from '../web/texture_detector.js';

const MODEL = {kind: 'normal-lattice-v1', image_size: 256, variant: 'joint', tail_fraction: 0.005, fit_scale: 1, score_decimals: 8};
function periodicMesh() {
  const pixels = new Uint8Array(256 * 256 * 3);
  for (let y = 0; y < 256; y += 1) for (let x = 0; x < 256; x += 1) {
    const gray = Math.floor(128 + 42 * Math.sin(2 * Math.PI * (x + 0.4 * y) / 24) + 36 * Math.cos(2 * Math.PI * (0.2 * x - y) / 23) + 0.5);
    pixels.fill(gray, (y * 256 + x) * 3, (y * 256 + x) * 3 + 3);
  }
  return pixels;
}

test('flat frames require an identifiable quality review', () => {
  for (const level of [0, 128, 255]) assert.throws(() => createTextureDetector(MODEL).score(new Uint8Array(256 * 256 * 3).fill(level)), error => error instanceof TextureQualityError && error.code === 'mesh-pattern-unavailable');
});

test('invalid artifacts and buffers fail before producing a score', () => {
  for (const changes of [{kind: 'other'}, {variant: 'unknown'}, {score_decimals: 4}, ...[0, -1, true, Infinity, NaN].map(fit_scale => ({fit_scale})), ...[0, 2, true, NaN].map(tail_fraction => ({tail_fraction}))]) assert.throws(() => createTextureDetector({...MODEL, ...changes}));
  for (const pixels of [[], new Float32Array(256 * 256 * 3), new Uint8Array(1)]) assert.throws(() => createTextureDetector(MODEL).score(pixels));
});

test('local texture damage increases and localizes the anomaly signal', () => {
  const clean = periodicMesh(); const before = clean.slice(); const damaged = clean.slice();
  for (let y = 112; y < 144; y += 1) for (let x = 112; x < 144; x += 1) damaged.fill(230, (y * 256 + x) * 3, (y * 256 + x) * 3 + 3);
  const detector = createTextureDetector(MODEL); const cleanResult = detector.score(clean); const result = detector.score(damaged);
  assert.ok(result.score > cleanResult.score * 2); assert.equal(result.map_size, 256); assert.equal(result.anomaly_map.length, 65536);
  let maxIndex = 0; for (let i = 0; i < result.anomaly_map.length; i += 1) { assert.ok(Number.isFinite(result.anomaly_map[i]) && result.anomaly_map[i] >= 0); if (result.anomaly_map[i] > result.anomaly_map[maxIndex]) maxIndex = i; }
  assert.ok(Math.floor(maxIndex / 256) >= 96 && Math.floor(maxIndex / 256) < 160 && maxIndex % 256 >= 96 && maxIndex % 256 < 160);
  assert.ok(result.periodicity >= 0 && result.periodicity <= 1 && result.repeat_count >= 2); assert.deepEqual(clean, before);
});
