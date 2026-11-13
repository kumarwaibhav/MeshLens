import test from 'node:test';
import assert from 'node:assert/strict';
import { Worker } from 'node:worker_threads';
import { createDetector, validateDetectorMetadata, validateDetectorEvaluation, assertInputQuality, InputQualityError } from '../web/detector.js';
import { detectorFixture, textureWorkerFactory } from './helpers/detector-fixture.mjs';
import { deferred } from './helpers/browser-harness.mjs';

test('detector metadata accepts nonprobability scores and rejects changed contracts', () => {
  const { metadata } = detectorFixture(); assert.equal(validateDetectorMetadata(metadata).threshold, 1.01);
  for (const change of [{ runtime: 'unknown' }, { preprocessing: 'canvas-high-quality' }, { threshold: NaN }, { decision: 'greater-or-equal' }, { image_size: 0 }, { score_is_probability: true }, { export: { ...metadata.export, model_file: '../secret.json' } }, { export: { ...metadata.export, model_bytes: 0 } }, { calibration: { ...metadata.calibration, count: 51 } }, { outputs: { ...metadata.outputs, map_size: 2048 } }, { input_quality: { min_side: 32, max_aspect_ratio: 1.5 } }]) assert.throws(() => validateDetectorMetadata({ ...metadata, ...change }), /contract/);
});
test('detector evaluation binds score limit, artifact, provenance and all test outcomes', () => {
  const { metadata, evaluation } = detectorFixture(); assert.equal(validateDetectorEvaluation(evaluation, metadata), evaluation);
  for (const change of [{ threshold: 9 }, { model_sha256: 'd'.repeat(64) }, { model_version: 'other' }, { test_count: 77 }, { coverage: { ...evaluation.coverage, scored: 77 } }, { model: { ...evaluation.model, false_negative: 0 } }, { protocol: { ...evaluation.protocol, selection_used_test: true } }]) assert.throws(() => validateDetectorEvaluation({ ...evaluation, ...change }, metadata), /evaluation/);
});
test('unsupported capture geometry is an explicit quality review', () => {
  const { metadata } = detectorFixture(); assert.doesNotThrow(() => assertInputQuality(640, 480, metadata)); for (const [width, height] of [[255, 256], [1024, 256]]) assert.throws(() => assertInputQuality(width, height, metadata), InputQualityError);
});
test('texture worker copies input, preserves unbounded score and releases resources', async () => {
  const { metadata, model } = detectorFixture(); const worker = textureWorkerFactory(); const detector = await createDetector(metadata, model, null, worker); const rgb = new Uint8Array(256 * 256 * 3).fill(73);
  const result = await detector.score(rgb); assert.equal(result.score, 1.2); assert.equal(result.map_size, 256); assert.equal(rgb.length, 256 * 256 * 3); assert.equal(rgb[0], 73); assert.equal(worker.workers[0].messages[1].rgb8[0], 73);
  await detector.release(); assert.equal(worker.workers[0].terminated, true); await assert.rejects(detector.score(rgb), /unavailable/);
});
test('worker start failure has no main-thread fallback', async () => {
  const { metadata, model } = detectorFixture(); await assert.rejects(createDetector(metadata, model, null, { createWorker() { throw new Error('CSP blocked'); } }), /worker could not start/);
});
test('texture artifact cutoff and preprocessing must match metadata before worker creation', async () => {
  const { metadata, model } = detectorFixture(); const artifact = JSON.parse(model);
  for (const change of [{ threshold: 0.01 }, { preprocessing: 'canvas-resize' }]) { const worker = textureWorkerFactory(); const bytes = Buffer.from(JSON.stringify({ ...artifact, ...change })); await assert.rejects(createDetector(metadata, bytes, null, worker), /numerical contract/); assert.equal(worker.workers.length, 0); }
});
test('quality rejection is recoverable while invalid worker result never becomes a score', async () => {
  const { metadata, model } = detectorFixture(); let calls = 0; const worker = textureWorkerFactory({ onScore() { calls += 1; if (calls === 1) throw Object.assign(new Error('No mesh repeat reference'), { code: 'mesh-pattern-unavailable' }); return { score: NaN, map_size: 256, anomaly_map: new Float32Array(256 * 256) }; } });
  const detector = await createDetector(metadata, model, null, worker); const rgb = new Uint8Array(256 * 256 * 3); await assert.rejects(detector.score(rgb), { code: 'mesh-pattern-unavailable' }); assert.equal(worker.workers[0].terminated, false); await assert.rejects(detector.score(rgb), /invalid result/); await detector.release();
});
test('releasing pending inference rejects it and rejects overlapping score requests', async () => {
  const { metadata, model } = detectorFixture(); const pending = deferred(); const started = deferred(); const worker = textureWorkerFactory({ onScore() { started.resolve(); return pending.promise; } }); const detector = await createDetector(metadata, model, null, worker); const rgb = new Uint8Array(256 * 256 * 3);
  const first = detector.score(rgb); await started.promise; await assert.rejects(detector.score(rgb), /already in progress/); const rejected = assert.rejects(first, /released/); await detector.release(); await rejected; pending.resolve();
});
test('a mismatched worker response terminates the detector', async () => {
  const { metadata, model } = detectorFixture(); const worker = textureWorkerFactory({ onScore(message, current) { current.onmessage({ data: { type: 'result', id: message.id + 1 } }); } }); const detector = await createDetector(metadata, model, null, worker);
  await assert.rejects(detector.score(new Uint8Array(256 * 256 * 3)), /unexpected response/); assert.equal(worker.workers[0].terminated, true);
});
test('worker initialization and stalled scoring have bounded, fatal timeouts', async () => {
  const { metadata, model } = detectorFixture(); const loading = textureWorkerFactory({ onInitialize() {} }); await assert.rejects(createDetector(metadata, model, null, { ...loading, workerTimeoutMs: 10 }), /timed out/); assert.equal(loading.workers[0].terminated, true);
  const scoring = textureWorkerFactory({ onScore() {} }); const detector = await createDetector(metadata, model, null, { ...scoring, workerTimeoutMs: 10 }); await assert.rejects(detector.score(new Uint8Array(256 * 256 * 3)), /timed out/); assert.equal(scoring.workers[0].terminated, true);
});
function onnxFixture({ poison } = {}) {
  const { metadata } = detectorFixture(); metadata.runtime = 'onnx'; metadata.image_size = 384; metadata.outputs.map_size = 48; metadata.export.model_file = 'detector.onnx'; metadata.input_quality.min_side = 384;
  const disposed = { inputs: 0, outputs: 0, sessions: 0 }; let lastInput;
  const session = {
    inputNames: ['image'], outputNames: ['score', 'anomaly_map'], inputMetadata: [{ name: 'image', type: 'float32', shape: [1, 3, 384, 384] }], outputMetadata: [{ name: 'score', type: 'float32', shape: [1] }, { name: 'anomaly_map', type: 'float32', shape: [1, 1, 48, 48] }],
    async run({ image }) {
      lastInput = image; const score = { type: 'float32', dims: [1], data: new Float32Array([1.2]), dispose() { disposed.outputs += 1; } }; const map = { type: 'float32', dims: [1, 1, 48, 48], data: new Float32Array(48 * 48), dispose() { disposed.outputs += 1; } };
      if (poison === 'type') score.type = 'float64'; if (poison === 'score') score.data[0] = NaN; if (poison === 'shape') map.dims = [1, 1, 24, 96]; if (poison === 'map') map.data[0] = -1; return { score, anomaly_map: map };
    }, async release() { disposed.sessions += 1; },
  };
  const ort = { Tensor: class { constructor(type, data, dims) { Object.assign(this, { type, data, dims }); } dispose() { disposed.inputs += 1; } }, InferenceSession: { create: async () => session } };
  return { metadata, ort, session, disposed, get lastInput() { return lastInput; } };
}
test('ONNX adapter uses canonical RGB channels and validates both independent outputs', async () => {
  const h = onnxFixture(); const detector = await createDetector(h.metadata, new Uint8Array([1]), h.ort); const rgb = new Uint8Array(384 * 384 * 3); rgb.set([255, 128, 64]); const result = await detector.score(rgb);
  assert.deepEqual(h.lastInput.dims, [1, 3, 384, 384]); assert.equal(h.lastInput.data[0], 1); assert.ok(Math.abs(h.lastInput.data[384 * 384] - 128 / 255) < 1e-7); assert.ok(result.score > 1); assert.equal(result.anomaly_map.length, 48 * 48); assert.deepEqual(h.disposed, { inputs: 1, outputs: 2, sessions: 0 }); await detector.release(); assert.equal(h.disposed.sessions, 1);
});
for (const poison of ['type', 'score', 'shape', 'map']) test(`ONNX invalid ${poison} cannot return a score and tensors are disposed`, async () => {
  const h = onnxFixture({ poison }); const detector = await createDetector(h.metadata, new Uint8Array([1]), h.ort); await assert.rejects(detector.score(new Uint8Array(384 * 384 * 3)), /invalid/); assert.deepEqual(h.disposed, { inputs: 1, outputs: 2, sessions: 0 }); await detector.release();
});
test('ONNX shape mismatch releases the created session before exposing an adapter', async () => {
  const h = onnxFixture(); h.session.inputMetadata[0].shape = [1, 3, 256, 256]; await assert.rejects(createDetector(h.metadata, new Uint8Array([1]), h.ort), /tensor contract/); assert.equal(h.disposed.sessions, 1);
});
test('actual module worker loads the texture runtime, transfers maps and reports unreadable patterns', async () => {
  const { metadata, model } = detectorFixture(); const entry = new URL('../web/texture_worker.js', import.meta.url).href;
  const code = `import { parentPort } from 'node:worker_threads'; globalThis.self = { postMessage: (...args) => parentPort.postMessage(...args) }; await import(${JSON.stringify(entry)}); parentPort.on('message', data => self.onmessage({ data }));`;
  let nativeWorker; const detector = await createDetector(metadata, model, null, { createWorker() { nativeWorker = new Worker(new URL(`data:text/javascript,${encodeURIComponent(code)}`)); const bridge = { postMessage: (...args) => nativeWorker.postMessage(...args), terminate: () => nativeWorker.terminate() }; nativeWorker.on('message', data => bridge.onmessage?.({ data })); nativeWorker.on('error', error => bridge.onerror?.(error)); return bridge; } });
  try {
    const rgb = new Uint8Array(256 * 256 * 3); for (let y = 0; y < 256; y += 1) for (let x = 0; x < 256; x += 1) { const value = Math.floor(128 + 42 * Math.sin(2 * Math.PI * (x + 0.4 * y) / 24) + 36 * Math.cos(2 * Math.PI * (0.2 * x - y) / 23) + 0.5); rgb.fill(value, (y * 256 + x) * 3, (y * 256 + x) * 3 + 3); }
    const result = await detector.score(rgb); assert.ok(Number.isFinite(result.score)); assert.ok(result.repeat_count >= 2); assert.equal(result.anomaly_map.length, 65536); assert.equal(result.map_size, 256); assert.equal(rgb.byteLength, 65536 * 3); await assert.rejects(detector.score(new Uint8Array(65536 * 3)), { code: 'mesh-pattern-unavailable' });
  } finally { await detector.release(); }
});
