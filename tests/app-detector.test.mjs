import test from 'node:test';
import assert from 'node:assert/strict';
import { browserHarness, cameraStream, deferred } from './helpers/browser-harness.mjs';
import { detectorFixture, textureWorkerFactory } from './helpers/detector-fixture.mjs';

test('v2 decision, evidence and stored record use the detector while AE stays separate', async () => {
  const inspection = detectorFixture(); const worker = textureWorkerFactory({ score: 1.2 }); const h = await browserHarness({ inspection, ...worker }); await h.app.initialize();
  assert.equal(h.app.state.ready, true); const record = h.app.state.result;
  assert.equal(record.score, 1.2); assert.equal(record.threshold, 1.01); assert.equal(record.is_anomaly, true); assert.equal(record.model_version, inspection.metadata.model_version); assert.equal(record.detector_version, record.model_version);
  assert.equal(record.reconstruction_model_version, h.metadata.model_version); assert.equal(record.reconstruction_score, 0); assert.equal(record.score_is_probability, false); assert.equal(h.app.state.view, 'detector');
  assert.equal(h.byId('view-tab-detector').hidden, false); assert.match(h.byId('view-description').textContent, /not a defect probability/);
  const message = worker.workers[0].messages.find((item) => item.type === 'score'); assert.deepEqual(Object.keys(message).sort(), ['id', 'rgb8', 'type']); assert.equal(message.rgb8.length, 256 * 256 * 3);
  assert.match(h.byId('model-version').textContent, /test-detector/); assert.match(h.byId('evaluation-note').textContent, /78\/78 scored/); await h.app.state.detector.release();
});
test('raw detector distances survive history reload and exact cutoff ties stay within range', async () => {
  const inspection = detectorFixture(); const worker = textureWorkerFactory({ score: inspection.metadata.threshold }); const h = await browserHarness({ inspection, ...worker }); await h.app.initialize();
  const record = h.app.state.result; assert.equal(record.is_anomaly, false); assert.ok(record.score > 1);
  const reloaded = await browserHarness({ history: JSON.stringify([record]) }); assert.equal(reloaded.app.state.history.length, 1); assert.equal(reloaded.app.state.history[0].threshold, inspection.metadata.threshold); await h.app.state.detector.release();
});
for (const missing of ['detector.json', 'detector-model.json', 'detector-evaluation.json']) test(`v2 missing ${missing} fails closed without falling back to the AE`, async () => {
  const inspection = detectorFixture(); const worker = textureWorkerFactory(); const h = await browserHarness({ inspection, ...worker, fetch: async (url, _options, { defaultFetch, response }) => String(url).endsWith(`/${missing}`) ? response('missing', 404) : defaultFetch(url) });
  await h.app.initialize(); assert.equal(h.app.state.ready, false); assert.equal(h.app.state.detector, null); assert.equal(h.app.state.result, null); assert.equal(h.app.state.history.length, 0); assert.equal(worker.workers.length, 0);
  assert.match(h.byId('decision-title').textContent, /Model unavailable/); assert.equal(h.byId('inspect-button').disabled, true);
});
test('detector tampering or a mismatched evaluation cannot start the worker', async () => {
  for (const poison of ['model', 'evaluation']) {
    const inspection = detectorFixture(); if (poison === 'evaluation') inspection.evaluation.model_version = 'other'; const worker = textureWorkerFactory();
    const h = await browserHarness({ inspection, ...worker, fetch: async (url, _options, { defaultFetch, response }) => poison === 'model' && String(url).endsWith('/detector-model.json') ? response('tampered') : defaultFetch(url) });
    await h.app.initialize(); assert.equal(h.app.state.ready, false); assert.equal(h.app.state.history.length, 0); assert.equal(worker.workers.length, 0);
  }
});
test('unsupported input geometry clears the prior result and produces no acceptance record', async () => {
  const worker = textureWorkerFactory(); const h = await browserHarness({ inspection: detectorFixture(), ...worker }); await h.app.initialize(); const count = h.app.state.history.length; const calls = worker.workers[0].messages.length;
  for (const dimensions of [{ width: 128, height: 128 }, { width: 1024, height: 256 }]) {
    h.app.setInput(h.makeBitmap(dimensions), 'unsupported.png'); assert.equal(await h.app.inspect(), false); assert.equal(h.app.state.result, null); assert.equal(h.app.state.history.length, count); assert.equal(worker.workers[0].messages.length, calls);
    assert.equal(h.byId('decision-title').textContent, 'Input needs review'); assert.match(h.byId('decision-description').textContent, /No defect decision/); assert.equal(h.byId('download-record').disabled, true);
  } await h.app.state.detector.release();
});
test('an unreadable mesh pattern is inconclusive and a later supported image recovers', async () => {
  let calls = 0; const worker = textureWorkerFactory({ onScore() { calls += 1; if (calls === 1) throw Object.assign(new Error('No repeat reference; use a focused mesh close-up.'), { code: 'mesh-pattern-unavailable' }); return { score: 0.8, anomaly_map: new Float32Array(256 * 256), map_size: 256 }; } });
  const h = await browserHarness({ inspection: detectorFixture(), ...worker }); await h.app.initialize(); assert.equal(h.app.state.ready, true); assert.equal(h.app.state.history.length, 0); assert.equal(h.byId('decision-title').textContent, 'Input needs review');
  h.app.setInput(h.makeBitmap(), 'new-mesh.png'); assert.equal(await h.app.inspect(), true); assert.equal(h.app.state.history.length, 1); assert.equal(h.app.state.result.filename, 'new-mesh.png'); assert.equal(h.byId('notice').hidden, true); await h.app.state.detector.release();
});
test('a pending worker result cannot replace a newer image', async () => {
  const pending = deferred(); const started = deferred(); let calls = 0; const worker = textureWorkerFactory({ onScore() { calls += 1; if (calls === 2) { started.resolve(); return pending.promise; } return { score: 0.8, anomaly_map: new Float32Array(256 * 256), map_size: 256 }; } });
  const h = await browserHarness({ inspection: detectorFixture(), ...worker }); await h.app.initialize(); const count = h.app.state.history.length;
  h.app.setInput(h.makeBitmap(), 'old.png'); const running = h.app.inspect(); await started.promise; h.app.setInput(h.makeBitmap(), 'new.png'); pending.resolve({ score: 9, anomaly_map: new Float32Array(256 * 256), map_size: 256 });
  assert.equal(await running, false); assert.equal(h.app.state.result, null); assert.equal(h.app.state.source.filename, 'new.png'); assert.equal(h.app.state.history.length, count); assert.equal(h.app.state.detectorMap, null); await h.app.state.detector.release();
});
test('camera quality failure stops sampling and preserves capture instructions', async () => {
  const stream = cameraStream(); const worker = textureWorkerFactory(); const h = await browserHarness({ inspection: detectorFixture(), ...worker, getUserMedia: async () => stream }); await h.app.initialize(); const count = h.app.state.history.length; await h.app.toggleCamera();
  assert.equal(h.app.state.cameraActive, false); assert.equal(stream.track.stops, 1); assert.equal(h.timers.size, 0); assert.equal(h.app.state.history.length, count); assert.equal(h.byId('decision-title').textContent, 'Input needs review'); assert.match(h.byId('notice').textContent, /at least 256/); await h.app.state.detector.release();
});
test('a worker failure disables new inspections and a fresh model load recovers', async () => {
  const started = deferred(); let calls = 0; const worker = textureWorkerFactory({ onScore(_message, current) { calls += 1; if (calls === 2) { started.resolve(); current.onerror(); return; } return { score: 0.8, anomaly_map: new Float32Array(256 * 256), map_size: 256 }; } });
  const h = await browserHarness({ inspection: detectorFixture(), ...worker }); await h.app.initialize(); const count = h.app.state.history.length; h.app.setInput(h.makeBitmap(), 'new.png'); assert.equal(await h.app.inspect(), false); await started.promise;
  assert.equal(h.app.state.ready, false); assert.equal(h.app.state.result, null); assert.equal(h.app.state.history.length, count); assert.equal(h.byId('inspect-button').disabled, true); assert.equal(worker.workers[0].terminated, true);
  const reload = h.byId('notice').querySelectorAll('button')[0]; assert.equal(reload.textContent, 'Reload detector'); await reload.dispatch('click'); assert.equal(h.app.state.ready, true); assert.equal(h.app.state.result.filename, 'new.png'); assert.equal(worker.workers.length, 2); await h.app.state.detector.release();
});
test('all capture stresses expose false alarms and inconclusive inputs beside the main result', async () => {
  const inspection = detectorFixture(); const conditions = ['original', 'brightness_070', 'brightness_130', 'shift_8x4_ref256', 'blur_sigma_0p8_ref256', 'jpeg_quality_75'];
  inspection.evaluation.stress_tests = Object.fromEntries(conditions.map((key) => [key, { defect_alerts: key === 'shift_8x4_ref256' ? 57 : 40, defective: 57, clean_alerts: key === 'shift_8x4_ref256' ? 21 : 3, clean: 21, defective_unusable: key === 'jpeg_quality_75' ? 2 : 0, clean_unusable: key === 'jpeg_quality_75' ? 1 : 0 }]));
  const worker = textureWorkerFactory(); const h = await browserHarness({ inspection, ...worker }); await h.app.initialize(); assert.equal(h.byId('stress-results').hidden, false); const rows = h.byId('stress-body').children;
  assert.equal(rows.length, 6); assert.equal(rows[0].children[0].textContent, 'Original images'); assert.equal(rows[3].children[0].scope, 'row'); assert.equal(rows[3].children[1].textContent, '57 / 57'); assert.equal(rows[3].children[2].textContent, '21 / 21 (100.0%)'); assert.equal(rows[5].children[3].textContent, '2 defective · 1 normal');
  assert.match(h.byId('stress-shift-note').textContent, /21 of 21 normal images.*100\.0%/); assert.match(h.byId('stress-shift-note').textContent, /256 px reference.*reflected borders/); assert.match(h.byId('stress-shift-note').textContent, /not qualified for translation changes or production acceptance/);
  for (const id of ['measured-limitation-text', 'decision-limitation', 'results-limitation']) { assert.match(h.byId(id).textContent, /3 of 21 normal images.*14\.3%/); assert.match(h.byId(id).textContent, /does not qualify/); } await h.app.state.detector.release();
});
test('missing or invalid stress counts stay unavailable instead of becoming zero', async () => {
  const inspection = detectorFixture(); inspection.evaluation.stress_tests = { shift_8x4_ref256: { defect_alerts: 57, defective: 57, clean_alerts: 22, clean: 21, defective_unusable: 0, clean_unusable: 0 } };
  const worker = textureWorkerFactory(); const h = await browserHarness({ inspection, ...worker }); await h.app.initialize(); const rows = h.byId('stress-body').children; assert.equal(rows.length, 6);
  for (const row of rows) assert.deepEqual(row.children.slice(1).map((cell) => cell.textContent), ['Unavailable', 'Unavailable', 'Unavailable']); assert.match(h.byId('stress-shift-note').textContent, /counts are unavailable/); await h.app.state.detector.release();
});
