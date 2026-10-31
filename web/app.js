import { preprocessRGBA, computeResidual, scoreResidual, classify, reconstructionRGBA, csvEscape } from './inference.js';
import { validateImageBytes, validateMetadata, verifyAsset, IMAGE_LIMITS } from './validation.js';

const byId = (id) => document.getElementById(id);
const elements = Object.fromEntries([
  'engine-status', 'engine-status-text', 'notice', 'dropzone', 'file-input', 'quick-samples',
  'sample-select', 'load-sample', 'replay-button', 'camera-button', 'camera-cadence', 'camera-area', 'camera-video',
  'source-status', 'inspect-button', 'inspect-button-text', 'image-dimensions', 'view-label',
  'inspection-canvas', 'canvas-empty', 'processing-overlay', 'canvas-corner', 'view-description',
  'overlay-control', 'overlay-toggle', 'decision-panel', 'decision-icon', 'decision-title',
  'decision-description', 'download-record', 'anomaly-score', 'threshold-value', 'inference-time',
  'ground-truth', 'history-count', 'history-body', 'export-csv', 'clear-history', 'metric-auroc',
  'metric-precision', 'metric-recall', 'metric-f1', 'test-count', 'confusion-tp', 'confusion-fn',
  'confusion-tn', 'confusion-fp', 'evaluation-note', 'model-architecture', 'model-input',
  'model-scoring', 'model-version', 'download-metadata',
].map((id) => [id, byId(id)]));

const HISTORY_KEY = 'meshlens.inspections.v1';
const state = {
  metadata: null, evaluation: null, samples: [], session: null, ort: null, imageSize: 256,
  threshold: null, topFraction: 0.01, ready: false, initializing: false, busy: false,
  pixels: null, reconstruction: null, residual: null, source: null, result: null, view: 'input',
  imageEpoch: 0, mediaEpoch: 0, cameraActive: false, stream: null, cameraTimer: null,
  replayActive: false, replayTimer: null, replayEpoch: 0, history: readHistory(),
  inputAbort: null, cameraPending: false, trackListeners: [], release: null,
};

function readHistory() {
  try {
    const stored = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
    if (!Array.isArray(stored)) return [];
    return stored.filter((record) => record && typeof record.filename === 'string' && record.filename.length <= 512
      && typeof record.timestamp === 'string' && Number.isFinite(Date.parse(record.timestamp))
      && Number.isFinite(record.score) && record.score >= 0 && record.score <= 1
      && Number.isFinite(record.threshold) && record.threshold >= 0 && record.threshold <= 1
      && Number.isFinite(record.inference_ms) && record.inference_ms >= 0
      && typeof record.is_anomaly === 'boolean' && record.is_anomaly === (record.score > record.threshold)
      && typeof record.model_version === 'string' && record.model_version.length <= 128
      && ['sample', 'upload', 'camera'].includes(record.source)).slice(0, 100);
  } catch { return []; }
}

function persistHistory() {
  try { localStorage.setItem(HISTORY_KEY, JSON.stringify(state.history)); }
  catch { showNotice('Browser storage is unavailable. This session still works; export records before closing the page.'); }
}

function showNotice(message, type = 'info', actionLabel, action) {
  elements.notice.classList.toggle('error', type === 'error');
  elements.notice.replaceChildren(document.createTextNode(message));
  if (actionLabel && action) {
    const button = document.createElement('button'); button.className = 'text-button notice-action';
    button.textContent = actionLabel; button.addEventListener('click', action, { once: true });
    elements.notice.append(' ', button);
  }
  elements.notice.hidden = false;
}
function clearNotice() { elements.notice.hidden = true; }
function engineStatus(message, status = 'ready') {
  elements['engine-status-text'].textContent = message;
  elements['engine-status'].className = `engine-status ${status}`;
}
function formatScore(value) {
  if (!Number.isFinite(value)) return '—';
  return value >= 0.001 ? value.toFixed(5) : value.toExponential(2);
}
function updateControls() {
  const unavailable = !state.ready || state.busy || state.initializing;
  elements['inspect-button'].disabled = unavailable || !state.pixels || state.cameraActive || state.replayActive;
  elements['inspect-button-text'].textContent = state.busy ? 'Inspecting…' : 'Inspect image';
  elements['sample-select'].disabled = unavailable || state.samples.length === 0 || state.replayActive;
  elements['load-sample'].disabled = unavailable || state.samples.length === 0 || state.replayActive;
  elements['replay-button'].disabled = !state.replayActive && (unavailable || state.samples.length === 0);
  for (const button of elements['quick-samples'].querySelectorAll('button')) button.disabled = unavailable || state.replayActive;
  for (const tab of document.querySelectorAll('.view-tab')) tab.disabled = tab.dataset.view !== 'input' && !state.reconstruction;
  elements.dropzone.setAttribute('aria-disabled', String(state.busy || state.initializing));
  elements.dropzone.disabled = state.busy || state.initializing;
  elements['file-input'].disabled = state.busy || state.initializing;
  elements['camera-cadence'].disabled = state.cameraPending;
  elements['camera-button'].disabled = !state.ready || state.initializing || (state.busy && !state.cameraActive && !state.cameraPending);
  elements['processing-overlay'].hidden = !state.busy;
  elements['download-record'].disabled = !state.result;
  elements['download-metadata'].disabled = !state.metadata;
}
async function fetchBytes(path, options = {}) {
  const response = await fetch(path, { credentials: 'same-origin', cache: 'no-cache', ...options });
  if (!response.ok) throw new Error(`Could not load ${path} (${response.status}).`);
  return new Uint8Array(await response.arrayBuffer());
}
async function releaseAsset(name) {
  const entry = state.release?.assets?.[name];
  const bytes = await fetchBytes(`/assets/${name}`);
  if (!entry || !Number.isSafeInteger(entry.bytes) || entry.bytes !== bytes.length) throw new Error('Application asset size does not match this release.');
  await verifyAsset(bytes, entry.sha256); return bytes;
}
function cancelInput() {
  state.imageEpoch += 1; state.inputAbort?.abort(); state.inputAbort = null;
  return state.imageEpoch;
}
function normalizeSamples(data) {
  const samples = Array.isArray(data) ? data : data?.samples;
  if (!Array.isArray(samples) || samples.length > 1000) throw new Error('The sample gallery is invalid.');
  const seen = new Set();
  return samples.map((sample, index) => {
    const filename = sample.filename;
    if (typeof filename !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9_.-]*\.(png|jpe?g|webp)$/i.test(filename) || filename.includes('..')
        || seen.has(filename) || !/^[a-f0-9]{64}$/.test(sample.sha256 ?? '')) throw new Error('Invalid sample filename or checksum.');
    seen.add(filename);
    const expected = `/assets/samples/${encodeURIComponent(filename)}`;
    const candidate = sample.url || sample.image_url || expected;
    const url = new URL(candidate, location.origin);
    if (url.origin !== location.origin || url.pathname !== expected || url.search || url.hash) throw new Error('Sample assets must be hosted in this application’s sample directory.');
    const entry = state.release?.samples?.[filename];
    if (state.release && (!entry || entry.sha256 !== sample.sha256)) throw new Error('Sample checksums differ from this release.');
    return { ...sample, filename, url: url.pathname, index };
  });
}
function renderSamples() {
  elements['quick-samples'].replaceChildren(); elements['sample-select'].replaceChildren();
  if (!state.samples.length) {
    const option = document.createElement('option'); option.textContent = 'No bundled samples';
    elements['sample-select'].append(option); elements['source-status'].textContent = 'Upload a mesh image to begin.'; return;
  }
  state.samples.forEach((sample, index) => {
    const option = document.createElement('option'); option.value = String(index);
    option.textContent = `Mesh sample ${String(index + 1).padStart(2, '0')}`;
    elements['sample-select'].append(option);
  });
  const normal = state.samples.find((sample) => sample.label === 0 || sample.label === 'normal' || sample.label === 'good');
  const defect = state.samples.find((sample) => sample.label === 1 || sample.label === 'anomaly' || sample.label === 'defective');
  const examples = [...new Set([normal, defect, ...state.samples].filter(Boolean))].slice(0, 2);
  for (const sample of examples) {
    const button = document.createElement('button'); button.className = 'quick-sample'; button.type = 'button'; button.disabled = !state.ready;
    button.setAttribute('aria-label', `Inspect mesh sample ${sample.index + 1}`);
    const image = document.createElement('img'); image.src = sample.url; image.alt = `Industrial mesh sample ${sample.index + 1}`; image.loading = 'eager';
    const label = document.createElement('span'); label.textContent = `SAMPLE ${String(sample.index + 1).padStart(2, '0')} ↗`;
    button.append(image, label); button.addEventListener('click', () => manualSample(sample.index));
    elements['quick-samples'].append(button);
  }
  elements['source-status'].textContent = `${state.samples.length} real mesh examples · labels revealed after inspection`;
}
function numericMetric(object, names) {
  if (!object) return null;
  for (const name of names) if (Number.isFinite(object[name])) return object[name];
  return null;
}
function renderMetadata() {
  const metadata = state.metadata;
  elements['threshold-value'].textContent = formatScore(state.threshold);
  elements['model-input'].textContent = `${state.imageSize} × ${state.imageSize} · RGB · [0, 1]`;
  elements['model-scoring'].textContent = `Mean top ${(state.topFraction * 100).toLocaleString()}% pixel residuals`;
  elements['model-version'].textContent = String(metadata.model_version || metadata.version || 'Frozen checkpoint');
  const architecture = metadata.architecture;
  if (typeof architecture === 'string') elements['model-architecture'].textContent = architecture;
  else if (architecture?.name || architecture?.type) elements['model-architecture'].textContent = architecture.name || architecture.type;
  byId('model-bottleneck').textContent = Number.isInteger(architecture?.latent_channels) ? `${architecture.latent_channels} latent channels` : 'See model metadata';
  const calibrationCount = metadata.calibration?.count ?? metadata.dataset?.calibration;
  byId('model-calibration').textContent = Number.isInteger(calibrationCount) ? `${calibrationCount} separate normal images` : 'Separate normal images';
  const report = state.evaluation || metadata.evaluation || metadata.metrics || {};
  const metrics = report.model || report.autoencoder || report.image_metrics || report.metrics?.autoencoder || report.metrics?.image || report.metrics || report.image || report;
  for (const [element, keys, percentage] of [
    ['metric-auroc', ['auroc', 'roc_auc', 'image_auroc', 'auc_roc'], false],
    ['metric-precision', ['precision'], true], ['metric-recall', ['recall', 'defect_recall'], true],
    ['metric-f1', ['f1', 'f1_score'], true],
  ]) {
    const value = numericMetric(metrics, keys);
    elements[element].textContent = value === null ? '—' : percentage ? `${(value * 100).toFixed(1)}%` : value.toFixed(3);
  }
  const confusion = metrics.confusion_matrix || metrics.confusion || report.confusion_matrix || report.confusion;
  let counts = confusion || {
    tn: numericMetric(metrics, ['true_negative', 'true_negatives', 'tn']), fp: numericMetric(metrics, ['false_positive', 'false_positives', 'fp']),
    fn: numericMetric(metrics, ['false_negative', 'false_negatives', 'fn']), tp: numericMetric(metrics, ['true_positive', 'true_positives', 'tp']),
  };
  if (Array.isArray(confusion) && Array.isArray(confusion[0])) counts = { tn: confusion[0][0], fp: confusion[0][1], fn: confusion[1][0], tp: confusion[1][1] };
  if (counts) {
    for (const key of ['tn', 'fp', 'fn', 'tp']) elements[`confusion-${key}`].textContent = Number.isFinite(counts[key]) ? String(counts[key]) : '—';
    const total = ['tn', 'fp', 'fn', 'tp'].reduce((sum, key) => sum + (counts[key] || 0), 0);
    if (total) elements['test-count'].textContent = `${total} real test images`;
    const defects = (counts.tp || 0) + (counts.fn || 0);
    if (Number.isFinite(counts.fn) && defects > 0) {
      const limitation = `At the measured threshold, ${counts.fn} of ${defects} defects were missed. Use this as a research and human-review aid.`;
      byId('measured-limitation-text').textContent = limitation; byId('measured-limitation').hidden = false;
      byId('decision-limitation').textContent = limitation; byId('decision-limitation').hidden = false;
      byId('results-limitation').textContent = limitation; byId('results-limitation').hidden = false;
    }
  }
  const testCount = numericMetric(metrics, ['n_test', 'test_count', 'n_images', 'n_samples', 'samples']) || numericMetric(report, ['n_test', 'test_count', 'n_images', 'n_samples']);
  if (testCount) elements['test-count'].textContent = `${testCount} real test images`;
  const brightStress = report.stress_tests?.bright_130_percent;
  if (Number.isFinite(brightStress?.false_alarms) && Number.isFinite(brightStress?.normal_samples)) byId('lighting-limitation').textContent = `Lighting stress test: at 1.3× brightness, ${brightStress.false_alarms} of ${brightStress.normal_samples} normal test images triggered false alarms. Stable lighting and local validation are essential.`;
  elements['evaluation-note'].textContent = 'The official test split is held out from training, architecture selection, and threshold calibration.';
}
function validateSession(session) {
  if (JSON.stringify(session.inputNames) !== '["image"]' || JSON.stringify(session.outputNames) !== '["reconstruction"]') throw new Error('Unexpected model input or output name.');
  for (const [items, name] of [[session.inputMetadata, 'image'], [session.outputMetadata, 'reconstruction']]) {
    const item = items?.[0];
    if (items?.length !== 1 || item.name !== name || item.isTensor === false || item.type !== 'float32'
        || JSON.stringify(item.shape ?? item.dimensions) !== '[1,3,256,256]') throw new Error('Unexpected model tensor shape or data type.');
  }
}
async function initialize() {
  if (state.initializing) return;
  if (state.busy) { showNotice('Wait for the current inspection to finish before reloading the model.'); return; }
  stopReplay(); stopCamera();
  state.initializing = true; state.ready = false; state.result = null; state.reconstruction = null; state.residual = null;
  clearNotice(); engineStatus('Loading inspection model', 'loading'); updateControls();
  let session;
  try {
    const old = state.session; state.session = null; await old?.release?.();
    const release = JSON.parse(new TextDecoder().decode(await fetchBytes('/assets/release.json')));
    if (release.schema_version !== 1 || typeof release.model_version !== 'string' || !release.assets || !release.samples) throw new Error('The release manifest is invalid.');
    state.release = release;
    const metadata = validateMetadata(JSON.parse(new TextDecoder().decode(await releaseAsset('metadata.json'))));
    if (metadata.model_version !== release.model_version) throw new Error('The release and metadata model versions differ.');
    const model = await releaseAsset('model.onnx'); await verifyAsset(model, metadata.export.model_sha256);
    state.metadata = metadata; state.imageSize = metadata.image_size; state.threshold = metadata.threshold; state.topFraction = metadata.score.top_fraction;
    const optional = await Promise.allSettled([releaseAsset('samples.json'), releaseAsset('evaluation.json')]);
    const warnings = [];
    try {
      if (optional[0].status === 'rejected') throw optional[0].reason;
      state.samples = normalizeSamples(JSON.parse(new TextDecoder().decode(optional[0].value)));
    } catch { state.samples = []; warnings.push('The sample gallery is unavailable; you can upload a local image.'); }
    try {
      if (optional[1].status === 'rejected') throw optional[1].reason;
      const evaluation = JSON.parse(new TextDecoder().decode(optional[1].value));
      for (const [key, value] of Object.entries(metadata.metrics)) if (evaluation.model?.[key] !== value) throw new Error('Evaluation metrics differ.');
      state.evaluation = evaluation;
    } catch { state.evaluation = null; warnings.push('The full evaluation report is unavailable; displayed metrics come from the frozen metadata.'); }
    renderMetadata(); renderSamples();
    const imported = await import('/vendor/ort.wasm.min.mjs'); state.ort = imported.default || imported;
    state.ort.env.wasm.numThreads = 1; state.ort.env.wasm.wasmPaths = '/vendor/'; state.ort.env.wasm.proxy = false; state.ort.env.logLevel = 'warning';
    session = await state.ort.InferenceSession.create(model, { executionProviders: ['wasm'], graphOptimizationLevel: 'all' });
    validateSession(session); state.session = session; state.ready = true;
    engineStatus('Model ready · runs locally'); updateControls();
    if (state.samples.length && !state.pixels) await loadSample(0); else if (state.pixels) await inspect();
    if (warnings.length) showNotice(warnings.join(' '));
  } catch (error) {
    state.ready = false; state.session = null; try { await session?.release?.(); } catch { /* Preserve the original initialization failure. */ }
    console.error('MeshLens initialization failed:', error); engineStatus('Model unavailable', 'error');
    showNotice('The inspection model could not load or failed its integrity checks. Check your connection and retry.', 'error', 'Retry model load', initialize);
    elements['source-status'].textContent = 'A loaded model is required for inspection.';
  } finally { state.initializing = false; updateControls(); }
}
function setInput(source, filename, details = {}) {
  const width = source.videoWidth || source.width; const height = source.videoHeight || source.height;
  if (!Number.isInteger(width) || !Number.isInteger(height) || width < IMAGE_LIMITS.minSide || height < IMAGE_LIMITS.minSide
      || width > IMAGE_LIMITS.maxSide || height > IMAGE_LIMITS.maxSide || width * height > IMAGE_LIMITS.maxPixels) throw new Error('Choose a still image with sides from 32 to 4096 pixels and at most 16 megapixels.');
  const canvas = document.createElement('canvas'); canvas.width = state.imageSize; canvas.height = state.imageSize;
  const context = canvas.getContext('2d', { willReadFrequently: true });
  if (!context) throw new Error('This browser could not create an image canvas.');
  context.fillStyle = '#fff'; context.fillRect(0, 0, canvas.width, canvas.height);
  context.imageSmoothingEnabled = true; context.imageSmoothingQuality = 'high'; context.drawImage(source, 0, 0, canvas.width, canvas.height);
  const pixels = context.getImageData(0, 0, canvas.width, canvas.height); cancelInput();
  state.pixels = pixels; state.source = { filename: String(filename).slice(0, 512), width, height, kind: 'upload', ...details, source_timestamp: new Date().toISOString() };
  state.reconstruction = null; state.residual = null; state.result = null;
  elements['image-dimensions'].textContent = `${width} × ${height} → ${state.imageSize} × ${state.imageSize}`;
  elements['canvas-empty'].hidden = true; elements['canvas-corner'].hidden = false; elements['inspection-canvas'].parentElement.classList.add('has-image');
  elements['decision-panel'].className = 'decision-panel pending'; elements['decision-icon'].textContent = '—'; elements['decision-title'].textContent = 'Image selected';
  elements['decision-description'].textContent = 'Run an inspection to compare it with the learned normal pattern.';
  elements['anomaly-score'].textContent = '—'; elements['inference-time'].textContent = '—'; elements['ground-truth'].hidden = true;
  switchView('input'); updateControls();
}
async function loadFile(file) {
  if (!file || state.busy || state.initializing) return false;
  stopReplay(); stopCamera(); const epoch = cancelInput(); clearNotice(); let bitmap;
  try {
    if (file.size > IMAGE_LIMITS.maxBytes) throw new Error('Choose a PNG, JPEG, or WebP still image up to 12 MiB.');
    const bytes = new Uint8Array(await file.arrayBuffer()); const header = validateImageBytes(bytes);
    if (epoch !== state.imageEpoch) return false;
    bitmap = await createImageBitmap(new Blob([bytes])); if (epoch !== state.imageEpoch) return false;
    if (!((bitmap.width === header.width && bitmap.height === header.height) || (bitmap.width === header.height && bitmap.height === header.width))) throw new Error('Decoded image dimensions differ from its header.');
    setInput(bitmap, file.name, { kind: 'upload' }); elements['source-status'].textContent = `${state.source.filename} · ${(file.size / 1024).toFixed(0)} KiB · local file`;
    return state.ready ? await inspect() : true;
  } catch (error) {
    if (epoch === state.imageEpoch) { console.error('Image load failed:', error); showNotice(error.message || 'The image could not be decoded. Try a different image.', 'error'); }
    return false;
  } finally { bitmap?.close(); }
}
async function loadSample(index) {
  if (state.busy || !Number.isInteger(index) || !state.samples[index]) return false;
  const epoch = cancelInput(); const sample = state.samples[index]; const abort = new AbortController(); state.inputAbort = abort; let bitmap;
  try {
    const bytes = await fetchBytes(sample.url, { signal: abort.signal });
    await verifyAsset(bytes, sample.sha256); const header = validateImageBytes(bytes);
    const entry = state.release?.samples?.[sample.filename];
    if (entry && entry.bytes !== bytes.length) throw new Error('The sample size differs from this release.');
    if (epoch !== state.imageEpoch) return false;
    bitmap = await createImageBitmap(new Blob([bytes])); if (epoch !== state.imageEpoch) return false;
    if (bitmap.width !== header.width || bitmap.height !== header.height) throw new Error('The sample image dimensions are inconsistent.');
    setInput(bitmap, `Mesh sample ${String(index + 1).padStart(2, '0')}`, { kind: 'sample', sample }); elements['sample-select'].value = String(index);
    elements['source-status'].textContent = `Real mesh sample ${index + 1} of ${state.samples.length} · label hidden until inspection`;
    return state.ready ? await inspect() : true;
  } catch (error) {
    if (epoch === state.imageEpoch && error.name !== 'AbortError') showNotice(error.message || 'The selected sample could not load.', 'error');
    return false;
  } finally { bitmap?.close(); if (state.inputAbort === abort) state.inputAbort = null; }
}
async function manualSample(index) {
  if (state.busy || state.initializing) return; stopReplay(); stopCamera(); clearNotice(); await loadSample(index);
}
async function inspect() {
  if (!state.ready || !state.session || !state.pixels || state.busy) return false;
  const epoch = state.imageEpoch; const pixels = state.pixels; const source = { ...state.source }; const session = state.session;
  const size = state.imageSize; const threshold = state.threshold; const topFraction = state.topFraction; const processingStarted = performance.now();
  state.busy = true; state.result = null; state.reconstruction = null; state.residual = null; clearNotice(); updateControls();
  elements['decision-panel'].className = 'decision-panel pending'; elements['decision-icon'].textContent = '—';
  elements['decision-title'].textContent = 'Inspection in progress'; elements['decision-description'].textContent = 'A decision will appear when this inspection completes.';
  elements['anomaly-score'].textContent = '—'; elements['inference-time'].textContent = '—'; elements['ground-truth'].hidden = true; switchView('input');
  let tensor; let outputs;
  try {
    await new Promise((resolve) => requestAnimationFrame(resolve)); if (epoch !== state.imageEpoch) return false;
    const input = preprocessRGBA(pixels.data, size, size);
    tensor = new state.ort.Tensor('float32', input, [1, 3, size, size]);
    const start = performance.now(); outputs = await session.run({ image: tensor }); const elapsed = performance.now() - start;
    if (epoch !== state.imageEpoch || session !== state.session) return false;
    const output = outputs.reconstruction;
    if (!output || output.type !== 'float32' || JSON.stringify(output.dims) !== JSON.stringify([1, 3, size, size]) || output.data?.length !== 3 * size * size) throw new Error('The model returned an invalid tensor.');
    const reconstruction = Float32Array.from(output.data);
    for (const value of reconstruction) if (!Number.isFinite(value) || value < 0 || value > 1) throw new Error('The model returned invalid pixel values.');
    const residual = computeResidual(input, reconstruction, { width: size, height: size });
    const score = scoreResidual(residual, topFraction); const isAnomaly = classify(score, threshold);
    const result = {
      id: globalThis.crypto?.randomUUID ? globalThis.crypto.randomUUID() : `mesh-${Date.now()}-${state.history.length}`,
      timestamp: new Date().toISOString(), source_timestamp: source.source_timestamp, filename: source.filename, source: source.kind,
      score, threshold, is_anomaly: isAnomaly, inference_ms: elapsed, processing_ms: performance.now() - processingStarted,
      model_version: String(state.metadata.model_version), input_width: source.width, input_height: source.height,
      model_image_size: size, score_is_probability: false,
    };
    state.reconstruction = reconstruction; state.residual = residual; state.result = result;
    state.history.unshift({ ...result }); state.history = state.history.slice(0, 100); persistHistory(); renderHistory();
    elements['decision-panel'].className = `decision-panel ${isAnomaly ? 'review' : 'accepted'}`;
    elements['decision-icon'].textContent = isAnomaly ? '!' : '✓'; elements['decision-title'].textContent = isAnomaly ? 'Review recommended' : 'Within learned range';
    elements['decision-description'].textContent = isAnomaly ? 'Reconstruction error exceeds the frozen threshold. Take a closer look at the surface.' : 'Reconstruction error stays within the calibrated range. This is not a defect-free guarantee.';
    elements['anomaly-score'].textContent = formatScore(score); elements['inference-time'].textContent = elapsed < 1000 ? `${Math.round(elapsed)} ms` : `${(elapsed / 1000).toFixed(2)} s`;
    if (source.sample && source.sample.label !== undefined) {
      const defect = source.sample.label === 0 || source.sample.label === 'normal' || source.sample.label === 'good' ? 'normal mesh' : `defective mesh${source.sample.defect_type ? ` · ${String(source.sample.defect_type).replaceAll('_', ' ')}` : ''}`;
      elements['ground-truth'].textContent = `Benchmark ground truth: ${defect}. This label is revealed after inference and is not passed to the model.`; elements['ground-truth'].hidden = false;
    }
    if (!state.cameraActive && !state.replayActive) switchView('heatmap'); else drawView();
    return true;
  } catch (error) {
    if (epoch === state.imageEpoch) {
      console.error('Inspection failed:', error); state.result = null; state.reconstruction = null; state.residual = null;
      showNotice('The image could not be inspected. Try again or select another mesh image.', 'error');
      elements['decision-panel'].className = 'decision-panel pending'; elements['decision-icon'].textContent = '—';
      elements['decision-title'].textContent = 'Inspection did not complete'; elements['decision-description'].textContent = 'No decision has been recorded for this attempt.';
      elements['anomaly-score'].textContent = '—'; elements['inference-time'].textContent = '—'; elements['ground-truth'].hidden = true; switchView('input');
    }
    return false;
  } finally {
    tensor?.dispose?.(); if (outputs) for (const value of new Set(Object.values(outputs))) value?.dispose?.();
    if (!state.result && state.pixels === pixels && (epoch !== state.imageEpoch || session !== state.session)) {
      elements['decision-title'].textContent = 'Inspection cancelled'; elements['decision-description'].textContent = 'No decision has been recorded for this attempt.';
    }
    state.busy = false; updateControls();
  }
}
const descriptions = {
  input: 'The image the model sees, resized to its trained input resolution.',
  reconstruction: 'The autoencoder’s reconstruction. Differences can indicate an unfamiliar pattern.',
  heatmap: 'Warmer colors show larger residuals. The color scale is relative to this image, not a defect probability.',
};
function switchView(view) {
  state.view = view; byId('visualization-panel').setAttribute('aria-labelledby', `view-tab-${view}`);
  for (const tab of document.querySelectorAll('.view-tab')) {
    const active = tab.dataset.view === view; tab.classList.toggle('active', active); tab.setAttribute('aria-selected', String(active)); tab.tabIndex = active ? 0 : -1;
  }
  elements['view-label'].textContent = { input: 'INPUT IMAGE', reconstruction: 'MODEL RECONSTRUCTION', heatmap: 'RELATIVE RESIDUAL' }[view];
  elements['view-description'].textContent = descriptions[view]; elements['overlay-control'].hidden = view !== 'heatmap'; drawView();
}
function heatColor(value) {
  const stops = [[24, 63, 65], [48, 115, 116], [94, 164, 130], [210, 190, 109], [239, 128, 69], [229, 64, 45]];
  const position = Math.max(0, Math.min(1, value)) * (stops.length - 1); const low = Math.min(stops.length - 2, Math.floor(position)); const blend = position - low;
  return stops[low].map((channel, index) => channel * (1 - blend) + stops[low + 1][index] * blend);
}
function drawView() {
  if (!state.pixels) return;
  const canvas = elements['inspection-canvas']; canvas.width = state.imageSize; canvas.height = state.imageSize; const context = canvas.getContext('2d');
  canvas.setAttribute('aria-label', `${state.source?.filename || 'Mesh image'} — ${state.view === 'input' ? 'original' : state.view === 'heatmap' ? 'relative reconstruction error map' : 'model reconstruction'}`);
  if (state.view === 'input' || !state.reconstruction) { context.putImageData(state.pixels, 0, 0); return; }
  if (state.view === 'reconstruction') { context.putImageData(new ImageData(reconstructionRGBA(state.reconstruction, state.imageSize, state.imageSize), state.imageSize, state.imageSize), 0, 0); return; }
  const ordered = Float32Array.from(state.residual).sort(); const scale = Math.max(ordered[Math.min(ordered.length - 1, Math.floor(ordered.length * 0.995))], 1e-7);
  const rgba = new Uint8ClampedArray(state.pixels.data.length); const overlay = elements['overlay-toggle'].checked;
  for (let index = 0; index < state.residual.length; index += 1) {
    const normalized = Math.min(1, state.residual[index] / scale); const color = heatColor(normalized); const mix = overlay ? 0.12 + normalized * 0.68 : 1;
    for (let channel = 0; channel < 3; channel += 1) rgba[index * 4 + channel] = color[channel] * mix + state.pixels.data[index * 4 + channel] * (1 - mix);
    rgba[index * 4 + 3] = 255;
  }
  context.putImageData(new ImageData(rgba, state.imageSize, state.imageSize), 0, 0);
}
function renderHistory() {
  const body = elements['history-body']; body.replaceChildren(); elements['history-count'].textContent = String(state.history.length);
  elements['export-csv'].disabled = state.history.length === 0; elements['clear-history'].disabled = state.history.length === 0;
  if (!state.history.length) {
    const row = document.createElement('tr'); row.className = 'history-empty'; const cell = document.createElement('td'); cell.colSpan = 5;
    cell.textContent = 'Your inspection records will appear here.'; row.append(cell); body.append(row); return;
  }
  for (const record of state.history.slice(0, 5)) {
    const row = document.createElement('tr'); const image = document.createElement('td'); image.className = 'image-cell'; image.textContent = record.filename;
    const source = document.createElement('small'); source.textContent = record.source === 'sample' ? 'Dataset sample' : record.source === 'camera' ? 'Camera frame' : 'Local image'; image.append(source);
    const time = document.createElement('td'); const timestamp = new Date(record.timestamp);
    time.textContent = Number.isNaN(timestamp.getTime()) ? '—' : timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); time.title = Number.isNaN(timestamp.getTime()) ? '' : timestamp.toLocaleString();
    const score = document.createElement('td'); score.textContent = formatScore(record.score);
    const decision = document.createElement('td'); const tag = document.createElement('span'); tag.className = `decision-tag ${record.is_anomaly ? 'review' : ''}`; tag.textContent = record.is_anomaly ? 'Review' : 'Within range'; decision.append(tag);
    const runtime = document.createElement('td'); runtime.textContent = `${Math.round(record.inference_ms)} ms`; row.append(image, time, score, decision, runtime); body.append(row);
  }
}
function download(content, filename, type) {
  const url = URL.createObjectURL(new Blob([content], { type })); const link = document.createElement('a'); link.href = url; link.download = filename;
  document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function stopReplay() {
  const wasActive = state.replayActive;
  state.replayActive = false; state.replayEpoch += 1; cancelInput(); clearTimeout(state.replayTimer); state.replayTimer = null;
  if (wasActive) elements['source-status'].textContent = 'Replay stopped · completed inspection records are retained';
  elements['replay-button'].textContent = '▷ Start replay'; elements['replay-button'].setAttribute('aria-pressed', 'false'); elements['replay-button'].classList.remove('running'); updateControls();
}
async function toggleReplay() {
  if (state.replayActive) { stopReplay(); return; }
  if (!state.ready || state.busy || state.initializing || !state.samples.length) return;
  stopCamera(); clearNotice(); state.replayActive = true; const epoch = ++state.replayEpoch;
  let index = Number(elements['sample-select'].value) || 0; let inspected = 0;
  elements['replay-button'].textContent = '■ Stop replay'; elements['replay-button'].setAttribute('aria-pressed', 'true'); elements['replay-button'].classList.add('running'); updateControls();
  async function next() {
    if (!state.replayActive || epoch !== state.replayEpoch) return;
    const succeeded = await loadSample(index); if (!state.replayActive || epoch !== state.replayEpoch) return;
    if (!succeeded) { stopReplay(); return; }
    inspected += 1; elements['source-status'].textContent = `Replay · ${inspected} of ${state.samples.length} samples inspected`;
    if (inspected >= state.samples.length) { stopReplay(); elements['source-status'].textContent = `Replay complete · ${inspected} samples inspected`; return; }
    index = (index + 1) % state.samples.length; state.replayTimer = setTimeout(next, 1800);
  }
  await next();
}
function stopTracks(stream) {
  for (const track of stream?.getTracks?.() || []) if (track.readyState !== 'ended') track.stop();
}
function stopCamera() {
  state.mediaEpoch += 1; cancelInput(); state.cameraActive = false; state.cameraPending = false; clearTimeout(state.cameraTimer); state.cameraTimer = null;
  for (const [track, callback] of state.trackListeners) track.removeEventListener?.('ended', callback); state.trackListeners = [];
  stopTracks(state.stream); state.stream = null; elements['camera-video'].pause(); elements['camera-video'].srcObject = null; elements['camera-area'].hidden = true;
  elements['camera-button'].textContent = '⊙ Camera'; elements['camera-button'].setAttribute('aria-pressed', 'false'); elements['camera-button'].classList.remove('running'); updateControls();
}
function cameraCadence() {
  const value = Number(elements['camera-cadence'].value); return [250, 1000, 2500].includes(value) ? value : 1000;
}
async function toggleCamera() {
  if (state.cameraActive || state.cameraPending) { stopCamera(); return; }
  if (state.busy || state.initializing) return;
  if (!state.ready) { showNotice('Wait for the inspection model to finish loading before starting the camera.'); return; }
  if (!navigator.mediaDevices?.getUserMedia) { showNotice('Camera access is unavailable in this browser. Upload an image instead.'); return; }
  stopReplay(); stopCamera(); const epoch = ++state.mediaEpoch; let stream;
  state.cameraPending = true; elements['camera-button'].textContent = '■ Cancel camera'; elements['camera-button'].setAttribute('aria-pressed', 'true'); updateControls();
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' }, width: { ideal: 640 }, height: { ideal: 480 } }, audio: false });
    if (epoch !== state.mediaEpoch) { stopTracks(stream); return; }
    const tracks = stream?.getVideoTracks?.() || [];
    if (!tracks.length || !tracks.some((track) => track.readyState === 'live' && track.enabled !== false)) { stopTracks(stream); throw new Error('The camera returned no live video track.'); }
    state.stream = stream; state.cameraActive = true;
    for (const track of tracks) {
      const ended = () => { if (epoch === state.mediaEpoch && state.stream === stream) { stopCamera(); showNotice('The camera disconnected. Restart it or upload a mesh image.', 'error'); } };
      track.addEventListener?.('ended', ended); state.trackListeners.push([track, ended]);
    }
    elements['camera-video'].srcObject = stream; elements['camera-area'].hidden = false; await elements['camera-video'].play();
    if (epoch !== state.mediaEpoch || state.stream !== stream) { stopTracks(stream); return; }
    state.cameraPending = false; elements['camera-button'].textContent = '■ Stop camera'; elements['camera-button'].setAttribute('aria-pressed', 'true'); elements['camera-button'].classList.add('running'); clearNotice(); updateControls();
    async function frame() {
      if (!state.cameraActive || epoch !== state.mediaEpoch) return;
      try {
        if (!tracks.some((track) => track.readyState === 'live' && track.enabled !== false)) throw new Error('The video track ended.');
        if (!state.busy && elements['camera-video'].readyState >= 2 && tracks.some((track) => !track.muted)) {
          setInput(elements['camera-video'], 'Camera frame', { kind: 'camera' }); const succeeded = await inspect();
          if (!state.cameraActive || epoch !== state.mediaEpoch) return;
          if (!succeeded) throw new Error('The frame inspection failed.');
          elements['source-status'].textContent = `Camera sampling · ${cameraCadence()} ms delay after each inspection · no queued frames`;
        }
        if (state.cameraActive && epoch === state.mediaEpoch) state.cameraTimer = setTimeout(frame, cameraCadence());
      } catch (error) {
        if (epoch === state.mediaEpoch) { console.error('Camera sampling stopped:', error); stopCamera(); showNotice('Camera sampling stopped. Upload a mesh image or restart the camera.', 'error'); }
      }
    }
    await frame();
  } catch (error) {
    if (epoch !== state.mediaEpoch) { if (stream !== state.stream) stopTracks(stream); return; }
    console.error('Camera unavailable:', error); stopCamera(); showNotice('The camera could not start. Allow camera access in your browser, or upload a mesh image instead.', 'error');
  }
}

elements.dropzone.addEventListener('click', () => { if (!state.busy) elements['file-input'].click(); });
elements.dropzone.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); if (!state.busy) elements['file-input'].click(); } });
for (const eventName of ['dragenter', 'dragover']) elements.dropzone.addEventListener(eventName, (event) => { event.preventDefault(); elements.dropzone.classList.add('dragover'); });
for (const eventName of ['dragleave', 'drop']) elements.dropzone.addEventListener(eventName, (event) => { event.preventDefault(); elements.dropzone.classList.remove('dragover'); });
elements.dropzone.addEventListener('drop', (event) => loadFile(event.dataTransfer.files[0]));
elements['file-input'].addEventListener('change', (event) => { loadFile(event.target.files[0]); event.target.value = ''; });
elements['load-sample'].addEventListener('click', () => manualSample(Number(elements['sample-select'].value)));
elements['sample-select'].addEventListener('change', () => manualSample(Number(elements['sample-select'].value)));
elements['inspect-button'].addEventListener('click', inspect); elements['replay-button'].addEventListener('click', toggleReplay); elements['camera-button'].addEventListener('click', toggleCamera); elements['overlay-toggle'].addEventListener('change', drawView);
for (const tab of document.querySelectorAll('.view-tab')) {
  tab.addEventListener('click', () => switchView(tab.dataset.view));
  tab.addEventListener('keydown', (event) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return; event.preventDefault();
    const tabs = [...document.querySelectorAll('.view-tab')].filter((item) => !item.disabled); const index = tabs.indexOf(tab);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    switchView(tabs[next].dataset.view); tabs[next].focus();
  });
}
elements['clear-history'].addEventListener('click', () => { state.history = []; persistHistory(); renderHistory(); });
elements['export-csv'].addEventListener('click', () => {
  const fields = ['timestamp', 'source_timestamp', 'filename', 'source', 'score', 'threshold', 'is_anomaly', 'inference_ms', 'processing_ms', 'model_version'];
  const lines = [fields.map(csvEscape).join(','), ...state.history.map((record) => fields.map((field) => csvEscape(record[field])).join(','))];
  download(`\uFEFF${lines.join('\r\n')}\r\n`, `MeshLens-inspections-${new Date().toISOString().slice(0, 10)}.csv`, 'text/csv;charset=utf-8');
});
elements['download-record'].addEventListener('click', () => { if (state.result) download(`${JSON.stringify(state.result, null, 2)}\n`, `MeshLens-inspection-${state.result.id}.json`, 'application/json'); });
elements['download-metadata'].addEventListener('click', () => { if (state.metadata) download(`${JSON.stringify(state.metadata, null, 2)}\n`, 'MeshLens-model-metadata.json', 'application/json'); });
window.addEventListener('pagehide', () => { stopReplay(); stopCamera(); });
document.addEventListener('visibilitychange', () => { if (document.hidden) { stopReplay(); stopCamera(); } });
if ('IntersectionObserver' in window) {
  const observer = new IntersectionObserver((entries) => { for (const entry of entries) if (entry.isIntersecting) for (const link of document.querySelectorAll('.nav-link')) link.classList.toggle('active', link.hash === `#${entry.target.id}`); }, { rootMargin: '-5% 0px -65% 0px', threshold: 0 });
  for (const id of ['inspect', 'results', 'method']) observer.observe(byId(id));
}
renderHistory(); updateControls(); initialize();
