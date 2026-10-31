import test from 'node:test';
import assert from 'node:assert/strict';
import { browserHarness, cameraStream, deferred } from './helpers/browser-harness.mjs';
const tick = () => new Promise((resolve) => setImmediate(resolve));
test('corrupt or non-array local history cannot prevent startup', async () => {
  for (const history of ['{bad JSON', '{}', 'null', '42']) { const h = await browserHarness({ history }); assert.equal(h.app.state.history.length, 0); assert.equal(h.byId('history-count').textContent, '0'); }
});
test('history filters malformed records and treats hostile filenames as text', async () => {
  const valid = { filename: '<img src=x onerror=alert(1)>', timestamp: new Date().toISOString(), score: .01, threshold: .02, inference_ms: 1, is_anomaly: false, source: 'upload', model_version: 'frozen-test-version' };
  const h = await browserHarness({ history: JSON.stringify([valid, null, { ...valid, score: null }, { ...valid, filename: null }]) });
  assert.equal(h.app.state.history.length, 1); assert.match(h.byId('history-body').textContent, /<img src=x/); assert.equal(h.byId('history-body').querySelectorAll('img').length, 0);
});
test('storage quota failure retains the completed result and export', async () => {
  const h = await browserHarness({ setItem() { throw new Error('QuotaExceededError'); } }); h.ready(); h.app.setInput(h.makeBitmap(), 'local.png'); await h.app.inspect();
  assert.equal(h.app.state.history.length, 1); assert.equal(h.app.state.result.filename, 'local.png'); assert.equal(h.byId('export-csv').disabled, false); assert.match(h.byId('notice').textContent, /storage|export/i);
});
test('pending inference is single-flight and disposes every tensor', async () => {
  const run = deferred(); let calls = 0;
  const h = await browserHarness({ run: async (feeds) => { calls += 1; await run.promise; return { reconstruction: { data: feeds.image.data, type: 'float32', dims: feeds.image.dims, dispose() { h.disposals.output += 1; } } }; } });
  h.ready(); h.app.setInput(h.makeBitmap(), 'one.png'); const pending = h.app.inspect(); await tick(); await h.app.inspect(); assert.equal(calls, 1); assert.equal(h.app.state.busy, true);
  run.resolve(); await pending; assert.equal(h.disposals.input, 1); assert.equal(h.disposals.output, 1); assert.equal(h.app.state.busy, false); assert.equal(h.app.state.history.length, 1);
});
test('failed inference releases input and records no decision', async () => {
  const h = await browserHarness({ run: async () => { throw new Error('backend failure'); } }); h.ready(); h.app.setInput(h.makeBitmap(), 'failure.png'); await h.app.inspect();
  assert.equal(h.disposals.input, 1); assert.equal(h.app.state.history.length, 0); assert.equal(h.app.state.result, null); assert.equal(h.app.state.busy, false); assert.match(h.byId('decision-title').textContent, /did not complete/i);
});
test('newer input invalidates an older in-flight result', async () => {
  const run = deferred(); const h = await browserHarness({ run: async (feeds) => { await run.promise; return { reconstruction: { data: feeds.image.data, type: 'float32', dims: feeds.image.dims, dispose() {} } }; } });
  h.ready(); h.app.setInput(h.makeBitmap(), 'old.png'); const pending = h.app.inspect(); await tick(); h.app.setInput(h.makeBitmap({ color: [255, 255, 255, 255] }), 'new.png'); run.resolve(); await pending;
  assert.equal(h.app.state.source.filename, 'new.png'); assert.equal(h.app.state.result, null); assert.equal(h.app.state.history.length, 0);
});
test('asynchronous file decodes retain the newest input and close stale bitmaps', async () => {
  const first = deferred(); const second = deferred(); let calls = 0; const h = await browserHarness({ createImageBitmap: async () => (++calls === 1 ? first.promise : second.promise) }); h.ready();
  const a = h.app.loadFile(await h.sampleFile('first.png')); await tick(); const b = h.app.loadFile(await h.sampleFile('second.png')); await tick();
  const newer = h.makeBitmap(); second.resolve(newer); await b; const older = h.makeBitmap(); first.resolve(older); await a;
  assert.equal(h.app.state.source.filename, 'second.png'); assert.equal(h.app.state.history.length, 1); assert.equal(h.app.state.history[0].filename, 'second.png'); assert.equal(older.closed, true); assert.equal(newer.closed, true);
});
test('stopping replay before fetch resolves prevents stale inspection', async () => {
  const fetch = deferred(); const h = await browserHarness({ fetch: async () => fetch.promise }); h.ready(); const pending = h.app.toggleReplay(); await tick(); h.app.stopReplay(); fetch.resolve(await h.defaultFetch(h.app.state.samples[0].url)); await pending;
  assert.equal(h.app.state.replayActive, false); assert.equal(h.app.state.source, null); assert.equal(h.app.state.history.length, 0); assert.equal(h.timers.size, 0);
});
test('failed replay fetch stops replay without a timer or decision', async () => {
  const h = await browserHarness({ fetch: async (_url, _options, { response }) => response('offline', 503) }); h.ready(); await h.app.toggleReplay();
  assert.equal(h.app.state.replayActive, false); assert.equal(h.timers.size, 0); assert.equal(h.app.state.history.length, 0); assert.match(h.byId('notice').textContent, /sample|load|fetch/i);
});
test('replay visits every sample once and finishes without a recurring timer', async () => {
  const h = await browserHarness(); h.ready(); h.app.state.samples = h.app.state.samples.slice(0, 2); await h.app.toggleReplay(); assert.equal(h.app.state.history.length, 1); await h.fireTimer();
  assert.equal(h.app.state.history.length, 2); assert.equal(h.app.state.replayActive, false); assert.equal(h.timers.size, 0); assert.match(h.byId('source-status').textContent, /complete/i);
});
test('camera denial restores controls and records no result', async () => {
  const h = await browserHarness({ getUserMedia: async () => { throw new Error('NotAllowedError'); } }); h.ready(); await h.app.toggleCamera();
  assert.equal(h.app.state.cameraActive, false); assert.equal(h.app.state.stream, null); assert.equal(h.byId('camera-button').disabled, false); assert.equal(h.app.state.history.length, 0); assert.match(h.byId('notice').textContent, /camera|allow/i);
});
test('missing camera API offers upload fallback', async () => { const h = await browserHarness(); h.ready(); delete h.context.navigator.mediaDevices; await h.app.toggleCamera(); assert.equal(h.app.state.cameraActive, false); assert.match(h.byId('notice').textContent, /upload/i); });
test('permission grant after cancellation stops every stale track', async () => {
  const permission = deferred(); const stream = cameraStream(); const h = await browserHarness({ getUserMedia: async () => permission.promise }); h.ready(); const pending = h.app.toggleCamera(); h.app.stopCamera(); permission.resolve(stream); await pending;
  assert.equal(stream.track.stops, 1); assert.equal(h.app.state.cameraActive, false); assert.equal(h.byId('camera-video').srcObject, null); assert.equal(h.timers.size, 0);
});
test('video playback failure releases stream and restores controls', async () => {
  const stream = cameraStream(); const h = await browserHarness({ getUserMedia: async () => stream, play: async () => { throw new Error('play failed'); } }); h.ready(); await h.app.toggleCamera();
  assert.equal(stream.track.stops, 1); assert.equal(h.app.state.cameraActive, false); assert.equal(h.byId('camera-button').disabled, false); assert.equal(h.app.state.history.length, 0);
});
test('stop during pending video.play cannot reactivate camera controls', async () => {
  const play = deferred(); const stream = cameraStream(); const h = await browserHarness({ getUserMedia: async () => stream, play: async () => play.promise }); h.ready(); const pending = h.app.toggleCamera(); await tick(); h.app.stopCamera(); play.resolve(); await pending;
  assert.equal(h.app.state.cameraActive, false); assert.equal(h.timers.size, 0); assert.equal(h.byId('camera-button').getAttribute('aria-pressed'), 'false'); assert.equal(h.byId('camera-button').classList.contains('running'), false);
});
test('stale permission denial cannot stop a newer stream', async () => {
  const old = deferred(); const stream = cameraStream(); let requests = 0; const h = await browserHarness({ getUserMedia: async () => (++requests === 1 ? old.promise : stream) }); h.ready(); h.byId('camera-video').readyState = 0;
  const pending = h.app.toggleCamera(); h.app.stopCamera(); await h.app.toggleCamera(); old.reject(new Error('stale denial')); await pending;
  assert.equal(h.app.state.cameraActive, true); assert.equal(h.app.state.stream, stream); assert.equal(stream.track.stops, 0); h.app.stopCamera();
});
test('empty media stream cannot be sampled', async () => {
  const h = await browserHarness({ getUserMedia: async () => ({ getTracks: () => [], getVideoTracks: () => [] }) }); h.ready(); await h.app.toggleCamera();
  assert.equal(h.app.state.cameraActive, false); assert.equal(h.timers.size, 0); assert.equal(h.app.state.history.length, 0); assert.match(h.byId('notice').textContent, /camera|video|stream/i);
});
test('ended video track stops sampling and clears recurring work', async () => {
  const stream = cameraStream(); const h = await browserHarness({ getUserMedia: async () => stream }); h.ready(); h.byId('camera-video').readyState = 0; await h.app.toggleCamera(); stream.track.readyState = 'ended'; await stream.track.dispatch('ended');
  assert.equal(h.app.state.cameraActive, false); assert.equal(h.timers.size, 0); assert.equal(h.byId('camera-video').srcObject, null);
});
test('page hiding releases tracks and cancels timers', async () => {
  const stream = cameraStream(); const h = await browserHarness({ getUserMedia: async () => stream }); h.ready(); h.byId('camera-video').readyState = 0; await h.app.toggleCamera(); h.document.hidden = true; await h.dispatchDocument('visibilitychange');
  assert.equal(stream.track.stops, 1); assert.equal(h.app.state.cameraActive, false); assert.equal(h.timers.size, 0);
});
test('model fetch failure remains retryable without a usable session', async () => {
  let failed = true; const h = await browserHarness({ fetch: async (url, _options, { defaultFetch, response }) => failed && String(url).includes('metadata') ? response('offline', 503) : defaultFetch(url) });
  await h.app.initialize(); assert.equal(h.app.state.ready, false); assert.equal(h.app.state.initializing, false); assert.match(h.byId('notice').textContent, /try again|load|connection/i); failed = false; await h.app.initialize(); assert.equal(h.app.state.ready, true);
});
test('tampered model bytes are rejected before runtime creation', async () => {
  let created = 0; const h = await browserHarness({ fetch: async (url, _options, { defaultFetch, response }) => String(url).endsWith('/model.onnx') ? response(new Uint8Array([1, 2, 3])) : defaultFetch(url), createSession: async (_args, factory) => { created += 1; return factory(); } });
  await h.app.initialize(); assert.equal(h.app.state.ready, false); assert.equal(created, 0);
});
test('session tensor-name mismatch is rejected before inference', async () => {
  const h = await browserHarness({ createSession: async (_args, factory) => { const session = factory(); session.inputNames = ['unexpected']; return session; } }); await h.app.initialize(); assert.equal(h.app.state.ready, false); assert.equal(h.app.state.history.length, 0);
});
test('tampered sample bytes cannot produce an inspection', async () => {
  const h = await browserHarness({ fetch: async (_url, _options, { response }) => response(new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10])) }); h.ready(); await h.app.loadSample(0); assert.equal(h.app.state.history.length, 0); assert.equal(h.app.state.source, null);
});
test('measured misses and low-recall limitation stay visible', async () => {
  const h = await browserHarness(); h.ready(); h.app.renderMetadata(); for (const id of ['measured-limitation', 'decision-limitation', 'results-limitation']) assert.equal(h.byId(id).hidden, false);
  assert.match(h.byId('measured-limitation-text').textContent, /46 of 57 defects were missed/); assert.equal(h.byId('metric-recall').textContent, '19.3%'); h.app.setInput(h.makeBitmap(), 'sample.png'); await h.app.inspect(); assert.match(h.byId('decision-description').textContent, /not a defect-free guarantee/i);
});
test('history rejects negative scores invalid dates giant filenames and contradictory decisions', async () => {
  const valid = { filename: 'mesh.png', timestamp: new Date().toISOString(), score: .01, threshold: .02, inference_ms: 1, is_anomaly: false, source: 'upload', model_version: 'test' };
  const invalid = [{ ...valid, score: -1 }, { ...valid, threshold: 2 }, { ...valid, inference_ms: -1 }, { ...valid, timestamp: 'not a date' }, { ...valid, filename: 'x'.repeat(513) }, { ...valid, model_version: 'x'.repeat(129) }, { ...valid, source: 'unknown' }, { ...valid, is_anomaly: true }];
  const h = await browserHarness({ history: JSON.stringify([valid, ...invalid]) }); assert.equal(h.app.state.history.length, 1); assert.equal(h.app.state.history[0].filename, 'mesh.png');
});
for (const poison of ['type', 'shape', 'length', 'nan', 'range']) {
  test(`invalid runtime output ${poison} records no decision and disposes tensors`, async () => {
    const h = await browserHarness({ run: async (feeds) => {
      const output = { type: 'float32', dims: [...feeds.image.dims], data: feeds.image.data.slice(), dispose() { h.disposals.output += 1; } };
      if (poison === 'type') output.type = 'float64';
      if (poison === 'shape') output.dims = [1, 3, 1, 1];
      if (poison === 'length') output.data = new Float32Array(1);
      if (poison === 'nan') output.data[0] = NaN;
      if (poison === 'range') output.data[0] = 2;
      return { reconstruction: output };
    } });
    h.ready(); h.app.setInput(h.makeBitmap(), 'malformed.png'); await h.app.inspect();
    assert.equal(h.app.state.result, null); assert.equal(h.app.state.history.length, 0); assert.equal(h.app.state.busy, false);
    assert.equal(h.disposals.input, 1); assert.equal(h.disposals.output, 1);
  });
}
test('file byte limits and dimensions reject before native image decode', async () => {
  let decoded = 0; const h = await browserHarness({ createImageBitmap: async () => { decoded += 1; return h.makeBitmap(); } }); h.ready();
  const source = await h.sampleFile(); const oversizedDimensions = new Uint8Array(await source.arrayBuffer()); new DataView(oversizedDimensions.buffer).setUint32(16, 4097);
  for (const file of [new h.context.File([new Uint8Array(12 * 1024 * 1024 + 1)], 'large.png'), new h.context.File([oversizedDimensions], 'dimensions.png'), new h.context.File(['not an image'], 'fake.png')]) await h.app.loadFile(file);
  assert.equal(decoded, 0); assert.equal(h.app.state.history.length, 0); assert.equal(h.app.state.source, null);
});
test('native decode failure is recoverable and records no result', async () => {
  const h = await browserHarness({ createImageBitmap: async () => { throw new Error('native decoder rejected corrupt pixels'); } }); h.ready(); await h.app.loadFile(await h.sampleFile());
  assert.equal(h.app.state.result, null); assert.equal(h.app.state.history.length, 0); assert.equal(h.app.state.busy, false); assert.equal(h.byId('notice').hidden, false);
});
test('stale decode rejection cannot cover a newer successful result with an error', async () => {
  const first = deferred(); let calls = 0; const h = await browserHarness({ createImageBitmap: async () => ++calls === 1 ? first.promise : h.makeBitmap() }); h.ready();
  const pending = h.app.loadFile(await h.sampleFile('old.png')); await tick(); await h.app.loadFile(await h.sampleFile('new.png')); first.reject(new Error('stale decode error')); await pending;
  assert.equal(h.app.state.result.filename, 'new.png'); assert.equal(h.byId('notice').hidden, true); assert.equal(h.app.state.history.length, 1);
});
test('replacing the session during inference discards stale results', async () => {
  const run = deferred(); const h = await browserHarness({ run: async (feeds) => { await run.promise; return { reconstruction: { type: 'float32', dims: feeds.image.dims, data: feeds.image.data, dispose() { h.disposals.output += 1; } } }; } });
  h.ready(); h.app.setInput(h.makeBitmap(), 'old-session.png'); const pending = h.app.inspect(); await tick(); h.app.state.session = {}; run.resolve(); await pending;
  assert.equal(h.app.state.result, null); assert.equal(h.app.state.history.length, 0); assert.equal(h.disposals.output, 1);
});
test('camera inference failure stops tracks and cancels recurring work', async () => {
  const stream = cameraStream(); const h = await browserHarness({ getUserMedia: async () => stream, run: async () => { throw new Error('backend failed'); } }); h.ready(); await h.app.toggleCamera();
  assert.equal(h.app.state.cameraActive, false); assert.equal(stream.track.stops, 1); assert.equal(h.timers.size, 0); assert.equal(h.app.state.history.length, 0);
});
test('camera sampling never queues frames and applies the selected post-inference delay', async () => {
  const run = deferred(); const stream = cameraStream(); let calls = 0;
  const h = await browserHarness({ getUserMedia: async () => stream, run: async (feeds) => { calls += 1; await run.promise; return { reconstruction: { type: 'float32', dims: feeds.image.dims, data: feeds.image.data, dispose() {} } }; } });
  h.ready(); h.byId('camera-cadence').value = '250'; const pending = h.app.toggleCamera(); await tick(); assert.equal(calls, 1); assert.equal(h.timers.size, 0); await h.app.inspect(); assert.equal(calls, 1);
  run.resolve(); await pending; assert.equal(h.timers.size, 1); assert.equal([...h.timers.values()][0].delay, 250);
  assert.ok(Number.isFinite(Date.parse(h.app.state.result.source_timestamp))); assert.ok(h.app.state.result.processing_ms >= 0);
  h.app.stopCamera(); assert.equal(h.timers.size, 0);
});
test('benchmark labels stay hidden until inference and never enter model feeds', async () => {
  const run = deferred(); let inputNames;
  const h = await browserHarness({ run: async (feeds) => { inputNames = Object.keys(feeds); await run.promise; return { reconstruction: { type: 'float32', dims: feeds.image.dims, data: feeds.image.data, dispose() {} } }; } });
  h.ready(); const sample = { label: 1, defect_type: 'broken' }; h.app.setInput(h.makeBitmap(), 'labeled.png', { kind: 'sample', sample }); const pending = h.app.inspect(); await tick(); assert.equal(h.byId('ground-truth').hidden, true);
  run.resolve(); await pending; assert.deepEqual(inputNames, ['image']); assert.equal(h.app.state.result.is_anomaly, false); assert.equal(h.byId('ground-truth').hidden, false);
});
test('pending reinspection clears old decision and cancelled work preserves only completed history', async () => {
  const second = deferred(); let calls = 0;
  const h = await browserHarness({ run: async (feeds) => {
    calls += 1; if (calls === 2) await second.promise;
    return { reconstruction: { type: 'float32', dims: feeds.image.dims, data: feeds.image.data, dispose() {} } };
  } });
  h.ready(); h.app.setInput(h.makeBitmap(), 'repeat.png'); await h.app.inspect();
  assert.equal(h.app.state.history.length, 1); assert.equal(h.byId('decision-title').textContent, 'Within learned range');
  const pending = h.app.inspect(); await tick();
  assert.equal(h.app.state.result, null); assert.equal(h.byId('anomaly-score').textContent, '—');
  assert.doesNotMatch(h.byId('decision-title').textContent, /Within learned range|Review recommended/);
  assert.equal(h.byId('download-record').disabled, true);
  h.app.stopReplay(); second.resolve(); await pending;
  assert.equal(h.app.state.result, null); assert.equal(h.app.state.history.length, 1); assert.equal(h.app.state.busy, false);
  assert.equal(h.byId('anomaly-score').textContent, '—'); assert.doesNotMatch(h.byId('decision-title').textContent, /Within learned range|Review recommended/);
});
