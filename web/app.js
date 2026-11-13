import { preprocessRGBA, computeResidual, scoreResidual, classify, reconstructionRGBA, csvEscape } from './inference.js';
import { validateImageBytes, validateMetadata, verifyAsset, IMAGE_LIMITS } from './validation.js';
import { inspectionRgb8 } from './inspection_input.js';
import { validateDetectorMetadata, validateDetectorEvaluation, assertInputQuality, createDetector, DETECTOR_MODEL_MAX_BYTES, InputQualityError } from './detector.js';

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
const RELEASE_MANIFEST_BYTES = 256 * 1024;
const RELEASE_ASSET_BYTES = 25 * 1024 * 1024;
const ASSET_LOAD_TIMEOUT_MS = 30_000;
const state = {
  metadata: null, evaluation: null, samples: [], session: null, ort: null, imageSize: 256,
  threshold: null, topFraction: 0.01, ready: false, initializing: false, busy: false,
  pixels: null, reconstruction: null, residual: null, source: null, result: null, view: 'input',
  imageEpoch: 0, mediaEpoch: 0, cameraActive: false, stream: null, cameraTimer: null,
  replayActive: false, replayTimer: null, replayEpoch: 0, history: readHistory(),
  inputAbort: null, cameraPending: false, trackListeners: [], release: null,
  detectorMetadata: null, detector: null, detectorPixels: null, detectorMap: null, detectorEvaluation: null, inputQuality: null,
};

function readHistory() {
  try {
    const stored = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
    if (!Array.isArray(stored)) return [];
    return stored.filter((record) => record && typeof record.filename === 'string' && record.filename.length <= 512
      && typeof record.timestamp === 'string' && Number.isFinite(Date.parse(record.timestamp))
      && Number.isFinite(record.score) && record.score >= 0 && (record.detector_version !== undefined || record.score <= 1)
      && Number.isFinite(record.threshold) && record.threshold >= 0 && (record.detector_version !== undefined || record.threshold <= 1)
      && (record.detector_version === undefined || (typeof record.detector_version === 'string' && record.detector_version.length > 0
        && record.detector_version === record.model_version && record.detector_version.length <= 128))
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

function showNotice(message, type = 'info', actionLabel, action, target = elements.notice) {
  target.classList.toggle('error', type === 'error');
  target.setAttribute('role', type === 'error' ? 'alert' : 'status');
  target.replaceChildren(document.createTextNode(message));
  if (actionLabel && action) {
    const button = document.createElement('button'); button.className = 'text-button notice-action';
    button.textContent = actionLabel; button.addEventListener('click', action, { once: true });
    target.append(' ', button);
  }
  target.hidden = false;
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
  for (const button of elements['quick-samples'].querySelectorAll('button')) {
    button.disabled = unavailable || state.replayActive;
    const selected = state.source?.sample?.index === Number(button.dataset.sampleIndex);
    button.setAttribute('aria-pressed', String(selected)); button.classList.toggle('selected', selected);
  }
  byId('jump-to-result').hidden = !state.result;
  byId('upload-own-image').disabled = state.busy || state.initializing;
  byId('visualization-panel').setAttribute('aria-busy', String(state.busy));
  for (const tab of document.querySelectorAll('.view-tab')) {
    tab.hidden = tab.dataset.view === 'detector' && !state.detectorMetadata;
    tab.disabled = tab.dataset.view === 'detector' ? !state.detectorMap : tab.dataset.view !== 'input' && !state.reconstruction;
  }
  elements.dropzone.setAttribute('aria-disabled', String(state.busy || state.initializing));
  elements.dropzone.disabled = state.busy || state.initializing;
  elements['file-input'].disabled = state.busy || state.initializing;
  elements['camera-cadence'].disabled = state.cameraPending;
  elements['camera-button'].disabled = !state.ready || state.initializing || (state.busy && !state.cameraActive && !state.cameraPending);
  elements['processing-overlay'].hidden = !state.busy;
  elements['download-record'].disabled = !state.result;
  elements['download-metadata'].disabled = !state.metadata;
}
async function fetchBytes(path, { signal, maxBytes = RELEASE_MANIFEST_BYTES } = {}) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) abort();
  signal?.addEventListener('abort', abort, { once: true });
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    abort();
  }, ASSET_LOAD_TIMEOUT_MS);
  let reader;
  try {
    const response = await fetch(path, { credentials: 'same-origin', mode: 'same-origin', redirect: 'error', cache: 'no-cache', signal: controller.signal });
    if (!response.ok) throw new Error(`Could not load ${path} (${response.status}).`);
    const declaredSize = Number(response.headers.get('content-length'));
    if (!response.headers.get('content-encoding') && declaredSize > maxBytes) throw new Error('An application asset exceeds its permitted size.');
    if (!response.body) throw new Error('This browser could not stream an application asset.');
    reader = response.body.getReader();
    const chunks = [];
    let size = 0;
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maxBytes) throw new Error('An application asset exceeds its permitted size.');
      chunks.push(value);
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) {
      bytes.set(chunk, offset);
      offset += chunk.byteLength;
    }
    return bytes;
  } catch (error) {
    if (reader) void reader.cancel().catch(() => {});
    abort();
    if (timedOut) throw new Error('The application asset load timed out. Check your connection and retry.');
    throw error;
  } finally {
    reader?.releaseLock();
    clearTimeout(timer);
    signal?.removeEventListener('abort', abort);
  }
}
function assetSize(entry, limit) {
  if (!entry || !Number.isSafeInteger(entry.bytes) || entry.bytes < 1 || entry.bytes > limit || !/^[a-f0-9]{64}$/.test(entry.sha256 ?? '')) {
    throw new Error('An application asset is missing or has invalid release metadata.');
  }
  return entry.bytes;
}
async function releaseAsset(name, maxBytes = RELEASE_ASSET_BYTES) {
  if (!/^[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(name) || name.includes('..')) throw new Error('An application asset name is invalid.');
  const entry = state.release?.assets?.[name];
  const expectedSize = assetSize(entry, maxBytes);
  const bytes = await fetchBytes(`/assets/${name}`, { maxBytes: expectedSize });
  if (expectedSize !== bytes.length) throw new Error('Application asset size does not match this release.');
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
  const missed = state.samples.find((sample) => sample.label === 1 && sample.expected_anomaly === false);
  const examples = [...new Set([normal, defect, missed, ...state.samples].filter(Boolean))].slice(0, 3);
  for (const [position, sample] of examples.entries()) {
    const button = document.createElement('button'); button.className = 'quick-sample'; button.type = 'button'; button.disabled = !state.ready;
    button.dataset.sampleIndex = String(sample.index);
    const image = document.createElement('img'); image.src = sample.url; image.alt = ''; image.width = 52; image.height = 52; image.loading = 'eager';
    const label = document.createElement('span'); label.textContent = `Example ${sample.index + 1} `;
    const hint = document.createElement('small'); hint.textContent = ['Start here', 'Compare another', 'Look a little closer'][position]; label.append(hint);
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
function renderStressTests(report, upgraded) {
  const section = byId('stress-results'); const body = byId('stress-body'); body.replaceChildren(); section.hidden = !upgraded;
  if (!upgraded) return;
  const conditions = [ ['original', 'Original images'], ['brightness_070', 'Brightness ×0.70'], ['brightness_130', 'Brightness ×1.30'], ['shift_8x4_ref256', 'Shift 8 px / 4 px'], ['blur_sigma_0p8_ref256', 'Blur σ0.8'], ['jpeg_quality_75', 'JPEG quality 75'] ];
  const supported = (entry) => entry && ['defect_alerts', 'defective', 'clean_alerts', 'clean', 'defective_unusable', 'clean_unusable'].every((key) => Number.isInteger(entry[key]) && entry[key] >= 0)
    && entry.defective === 57 && entry.clean === 21 && entry.defect_alerts + entry.defective_unusable <= entry.defective && entry.clean_alerts + entry.clean_unusable <= entry.clean;
  for (const [key, label] of conditions) {
    const entry = report.stress_tests?.[key]; const row = document.createElement('tr'); const heading = document.createElement('th'); heading.scope = 'row'; heading.textContent = label; row.append(heading);
    const values = supported(entry) ? [`${entry.defect_alerts} / ${entry.defective}`, `${entry.clean_alerts} / ${entry.clean} (${(entry.clean_alerts / entry.clean * 100).toFixed(1)}%)`, `${entry.defective_unusable} defective · ${entry.clean_unusable} normal`] : ['Unavailable', 'Unavailable', 'Unavailable'];
    if (key === 'shift_8x4_ref256') row.className = 'stress-shift';
    for (const value of values) { const cell = document.createElement('td'); cell.textContent = value; row.append(cell); } body.append(row);
  }
  const shift = report.stress_tests?.shift_8x4_ref256;
  byId('stress-shift-note').textContent = supported(shift)
    ? `Shift sensitivity: ${shift.clean_alerts} of ${shift.clean} normal images triggered false alarms (${(shift.clean_alerts / shift.clean * 100).toFixed(1)}%) after an 8 px / 4 px simulated shift at the 256 px reference scale, using reflected borders. The detector is not qualified for translation changes or production acceptance. Validate physical camera alignment and representative new parts.`
    : 'Verified shift-test counts are unavailable. The detector is not qualified for translation changes or production acceptance. Validate physical camera alignment and representative new parts.';
}
function renderMetadata() {
  const metadata = state.detectorMetadata || state.metadata; const upgraded = Boolean(state.detectorMetadata);
  elements['threshold-value'].textContent = formatScore(state.threshold);
  elements['model-input'].textContent = `${metadata.image_size} × ${metadata.image_size} · RGB · ${upgraded ? 'area-rgb8-v1' : '[0, 1]'}`;
  elements['model-scoring'].textContent = upgraded ? metadata.runtime === 'texture-js' ? 'Normal lattice consistency · calibrated score' : 'Distance to normal patch memory' : `Mean top ${(state.topFraction * 100).toLocaleString()}% pixel residuals`;
  elements['model-version'].textContent = String(metadata.model_version || metadata.version || 'Frozen checkpoint');
  const architecture = metadata.architecture;
  if (typeof architecture === 'string') elements['model-architecture'].textContent = architecture;
  else if (architecture?.name || architecture?.type) elements['model-architecture'].textContent = architecture.name || architecture.type;
  else if (upgraded) elements['model-architecture'].textContent = metadata.runtime === 'texture-js' ? 'Normal lattice texture detector' : 'Normal patch memory detector';
  byId('model-bottleneck').textContent = upgraded ? metadata.runtime === 'texture-js' ? 'Repeated mesh references within each image' : 'Multiscale patch features' : Number.isInteger(architecture?.latent_channels) ? `${architecture.latent_channels} latent channels` : 'See model metadata';
  byId('model-fitting').textContent = upgraded ? '160 normal images · separate selection and calibration' : 'Normal images only · 25,339 parameters';
  byId('model-runtime').textContent = upgraded && metadata.runtime === 'texture-js' ? 'JavaScript detector worker · ONNX autoencoder illustration' : 'ONNX · browser WebAssembly';
  byId('capture-resolution').textContent = upgraded
    ? `Use an original photo at least ${metadata.input_quality?.min_side ?? metadata.image_size} px on each side. Keep the long side within ${metadata.input_quality?.max_aspect_ratio ?? 1.5}× the short side. The full image is area-resized to ${metadata.image_size} × ${metadata.image_size}; no silent crop is applied.`
    : 'Square framing works best. The whole image is resized to 256 × 256; small details can be lost.';
  if (upgraded) {
    byId('method-learning').textContent = metadata.runtime === 'texture-js'
      ? 'Fit normal mesh statistics on 160 clean images. Each inspection also compares repeated structures within the input. Select with a separate development group, then calibrate the limit on 52 untouched normal images.'
      : 'Fit a memory of normal feature patches using 160 clean images. Select with a separate development group, then calibrate the limit on 52 untouched normal images.';
    byId('method-inference').textContent = `Decode a native image, composite transparency on white, and use the deterministic area resize to ${metadata.image_size} × ${metadata.image_size}. Run the detector here, then rebuild a separate 256 × 256 view with the original autoencoder. Uploads do not retrain either model.`;
    byId('method-decision').textContent = `Recommend review only when the active detector score is strictly greater than ${formatScore(metadata.threshold)}. The detector map supports inspection; the autoencoder error map is separate evidence. Unreadable inputs produce no defect decision.`;
    byId('score-formula').textContent = metadata.runtime === 'texture-js'
      ? `Compare local mesh with repeated structures, combine texture and intensity differences, and average the strongest responses with the frozen fitted scale. Round scores consistently before strict score > ${metadata.threshold}. A missing repeat reference requires manual review. Neither map is a defect probability.`
      : `Measure feature patches against the fitted normal memory and aggregate the strongest response. Use strict score > ${metadata.threshold} for review. The relative map is not a probability; the separate autoencoder residual does not set this score.`;
  } else {
    byId('method-decision').textContent = `The baseline averages the largest 1% of pixel reconstruction errors and recommends review only when score > ${metadata.threshold}.`;
    byId('score-formula').textContent = `Average squared RGB errors per pixel, then average the largest 656 of 65,536 pixel errors. Use strict score > ${metadata.threshold}. Relative map colors do not change this score.`;
  }
  const calibrationCount = metadata.calibration?.count ?? metadata.dataset?.calibration;
  byId('model-calibration').textContent = Number.isInteger(calibrationCount) ? `${calibrationCount} separate normal images` : 'Separate normal images';
  const report = state.detectorEvaluation || state.evaluation || metadata.evaluation || metadata.metrics || {}; renderStressTests(report, upgraded);
  const metrics = report.model || report.autoencoder || report.image_metrics || report.metrics?.autoencoder || report.metrics?.image || report.metrics || report.image || report;
  for (const [element, keys, percentage] of [ ['metric-auroc', ['auroc', 'roc_auc', 'image_auroc', 'auc_roc'], false], ['metric-precision', ['precision'], true], ['metric-recall', ['recall', 'defect_recall'], true], ['metric-f1', ['f1', 'f1_score'], true] ]) {
    const value = numericMetric(metrics, keys); elements[element].textContent = value === null ? '—' : percentage ? `${(value * 100).toFixed(1)}%` : value.toFixed(3);
  }
  const confusion = metrics.confusion_matrix || metrics.confusion || report.confusion_matrix || report.confusion;
  let counts = confusion || { tn: numericMetric(metrics, ['true_negative', 'true_negatives', 'tn']), fp: numericMetric(metrics, ['false_positive', 'false_positives', 'fp']), fn: numericMetric(metrics, ['false_negative', 'false_negatives', 'fn']), tp: numericMetric(metrics, ['true_positive', 'true_positives', 'tp']) };
  if (Array.isArray(confusion) && Array.isArray(confusion[0])) counts = { tn: confusion[0][0], fp: confusion[0][1], fn: confusion[1][0], tp: confusion[1][1] };
  if (counts) {
    for (const key of ['tn', 'fp', 'fn', 'tp']) elements[`confusion-${key}`].textContent = Number.isFinite(counts[key]) ? String(counts[key]) : '—';
    const total = ['tn', 'fp', 'fn', 'tp'].reduce((sum, key) => sum + (counts[key] || 0), 0); if (total) elements['test-count'].textContent = `${total} real test images`;
    const defects = (counts.tp || 0) + (counts.fn || 0);
    if (Number.isFinite(counts.fn) && defects > 0) {
      const inconclusive = report.coverage?.inconclusive ?? 0; const clean = report.test_normal ?? counts.tn + counts.fp + (report.coverage?.clean_inconclusive ?? 0);
      const falseAlarms = clean > 0 ? `${counts.fp} of ${clean} normal images triggered false alarms (${(counts.fp / clean * 100).toFixed(1)}%). ` : '';
      const limitation = `At the measured threshold, ${counts.fn} of ${defects} defects were missed${inconclusive ? ` (including ${report.coverage.defective_inconclusive} inconclusive defect inputs)` : ''}. ${falseAlarms}${inconclusive} of ${report.test_count ?? 78} test inputs were inconclusive. This benchmark does not qualify an automated production acceptance system.`;
      byId('scope-summary').textContent = `An experiment you can inspect. On the official Grid test, the active ${upgraded ? 'detector' : 'autoencoder baseline'} flagged ${counts.tp} of ${defects} defects and missed ${counts.fn}. ${falseAlarms}${inconclusive} inputs were inconclusive. A low score does not establish defect-free material.`;
      byId('defect-strip').setAttribute('aria-label', `${counts.tp} of ${defects} defects flagged; ${counts.fn} missed, including any inconclusive defect inputs.`);
      byId('defect-fill').style.width = `${counts.tp / defects * 100}%`; byId('defect-flagged').textContent = `${counts.tp} flagged`; byId('defect-missed').textContent = `${counts.fn} missed`;
      for (const id of ['measured-limitation-text', 'decision-limitation', 'results-limitation']) { byId(id).textContent = limitation; byId(id).hidden = false; } byId('measured-limitation').hidden = false;
      if (upgraded) byId('results-limitation').textContent += ` Normal test inputs requiring review: ${counts.fp + report.coverage.clean_inconclusive} of 21 (${counts.fp} false alarms + ${report.coverage.clean_inconclusive} inconclusive).`;
    }
  }
  const testCount = numericMetric(metrics, ['n_test', 'test_count', 'n_images', 'n_samples', 'samples']) || numericMetric(report, ['n_test', 'test_count', 'n_images', 'n_samples']); if (testCount) elements['test-count'].textContent = `${testCount} real test images`;
  const brightStress = report.stress_tests?.bright_130_percent; const activeBrightStress = report.stress_tests?.brightness_130;
  if (upgraded && Number.isInteger(activeBrightStress?.clean_alerts) && Number.isInteger(activeBrightStress?.clean)) byId('lighting-limitation').textContent = `Brightness stress test: at 1.3× brightness, ${activeBrightStress.clean_alerts} of ${activeBrightStress.clean} normal test images triggered false alarms; ${activeBrightStress.clean_unusable ?? 0} normal and ${activeBrightStress.defective_unusable ?? 0} defective inputs were inconclusive. This simulated benchmark test is not evidence of field qualification. Validate the actual camera, lighting and inspection line.`;
  else if (!upgraded && Number.isFinite(brightStress?.false_alarms) && Number.isFinite(brightStress?.normal_samples)) byId('lighting-limitation').textContent = `Lighting stress test: at 1.3× brightness, ${brightStress.false_alarms} of ${brightStress.normal_samples} normal test images triggered false alarms. Stable lighting and local validation are essential.`;
  else byId('lighting-limitation').textContent = 'Lighting and viewpoint changes require validation on the target inspection line. Benchmark results are not evidence of field qualification.';
  elements['evaluation-note'].textContent = upgraded
    ? `Official test images were excluded from the new detector’s fitting, selection and calibration. The benchmark has previously been evaluated. Coverage: ${report.coverage.scored}/${report.coverage.total} scored; ${report.coverage.inconclusive} inconclusive. AUROC ranks scored inputs only; recall counts inconclusive defects as missed.`
    : 'The official test split was excluded from autoencoder training, architecture selection, and threshold calibration.';
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
  state.initializing = true; state.ready = false; state.result = null; state.reconstruction = null; state.residual = null; state.detectorMap = null;
  clearNotice(); engineStatus('Loading inspection model', 'loading'); updateControls();
  let session; let detector;
  try {
    const old = state.session; const oldDetector = state.detector; const oldDetectorHash = state.detectorMetadata?.export.model_sha256;
    state.session = null; state.detector = null; state.detectorMetadata = null; state.detectorEvaluation = null;
    await old?.release?.(); await oldDetector?.release?.();
    const release = JSON.parse(new TextDecoder().decode(await fetchBytes('/assets/release.json')));
    if (![1, 2].includes(release.schema_version) || typeof release.model_version !== 'string' || !release.assets || !release.samples
        || (release.schema_version === 2 && (typeof release.detector_version !== 'string' || !release.detector_version))) throw new Error('The release manifest is invalid.');
    state.release = release;
    const metadata = validateMetadata(JSON.parse(new TextDecoder().decode(await releaseAsset('metadata.json'))));
    if (metadata.model_version !== release.model_version) throw new Error('The release and metadata model versions differ.');
    const model = await releaseAsset('model.onnx'); await verifyAsset(model, metadata.export.model_sha256);
    state.metadata = metadata; state.imageSize = metadata.image_size; state.threshold = metadata.threshold; state.topFraction = metadata.score.top_fraction;
    if (release.schema_version === 2) {
      const detectorMetadata = validateDetectorMetadata(JSON.parse(new TextDecoder().decode(await releaseAsset('detector.json'))));
      if (detectorMetadata.model_version !== release.detector_version) throw new Error('The release and detector versions differ.');
      state.detectorMetadata = detectorMetadata; state.threshold = detectorMetadata.threshold;
    }
    if (oldDetectorHash !== state.detectorMetadata?.export.model_sha256) {
      state.pixels = null; state.detectorPixels = null; state.source = null; state.inputQuality = null;
    }
    const optional = await Promise.allSettled([releaseAsset('samples.json'), releaseAsset('evaluation.json')]); const warnings = [];
    try {
      if (optional[0].status === 'rejected') throw optional[0].reason;
      state.samples = normalizeSamples(JSON.parse(new TextDecoder().decode(optional[0].value)));
    } catch { state.samples = []; warnings.push('The sample gallery is unavailable; you can upload a local image.'); }
    try {
      if (optional[1].status === 'rejected') throw optional[1].reason;
      const evaluation = JSON.parse(new TextDecoder().decode(optional[1].value));
      for (const [key, value] of Object.entries(metadata.metrics)) if (evaluation.model?.[key] !== value) throw new Error('Evaluation metrics differ.');
      state.evaluation = evaluation;
    } catch { state.evaluation = null; warnings.push('The baseline evaluation report is unavailable.'); }
    const imported = await import('/vendor/ort.wasm.min.mjs'); state.ort = imported.default || imported;
    state.ort.env.wasm.numThreads = 1; state.ort.env.wasm.wasmPaths = '/vendor/'; state.ort.env.wasm.proxy = false; state.ort.env.logLevel = 'warning';
    session = await state.ort.InferenceSession.create(model, { executionProviders: ['wasm'], graphOptimizationLevel: 'all' }); validateSession(session); state.session = session;
    if (state.detectorMetadata) {
      const artifact = state.detectorMetadata.export; const detectorBytes = await releaseAsset(artifact.model_file, DETECTOR_MODEL_MAX_BYTES);
      if (detectorBytes.length !== artifact.model_bytes) throw new Error('The detector artifact size differs from its metadata.');
      await verifyAsset(detectorBytes, artifact.model_sha256);
      state.detectorEvaluation = validateDetectorEvaluation(JSON.parse(new TextDecoder().decode(await releaseAsset('detector-evaluation.json'))), state.detectorMetadata);
      detector = await createDetector(state.detectorMetadata, detectorBytes, state.ort); state.detector = detector;
    }
    renderMetadata(); renderSamples(); state.ready = true; engineStatus(state.detector ? 'Detector ready · runs locally' : 'Model ready · runs locally'); updateControls();
    if (state.samples.length && !state.pixels) await loadSample(0); else if (state.pixels) await inspect();
    if (warnings.length) showNotice(warnings.join(' '));
  } catch (error) {
    state.ready = false; state.session = null; state.detector = null;
    try { await session?.release?.(); } catch { /* Preserve initialization failure. */ }
    try { await detector?.release?.(); } catch { /* Preserve initialization failure. */ }
    console.error('MeshLens initialization failed:', error); engineStatus('Model unavailable', 'error');
    showNotice('The inspection model could not load or failed its integrity checks. Check your connection and retry.', 'error', 'Retry model load', initialize);
    elements['decision-panel'].className = 'decision-panel pending'; elements['decision-icon'].textContent = '—';
    elements['decision-title'].textContent = 'Model unavailable'; elements['decision-description'].textContent = 'A verified model must load before any new decision can be recorded.';
    elements['anomaly-score'].textContent = '—'; elements['inference-time'].textContent = '—'; elements['ground-truth'].hidden = true; switchView('input');
    elements['source-status'].textContent = 'A loaded model is required for inspection.';
  } finally { state.initializing = false; updateControls(); }
}
function setInput(source, filename, details = {}) {
  const width = source.videoWidth || source.width; const height = source.videoHeight || source.height;
  if (!Number.isInteger(width) || !Number.isInteger(height) || width < IMAGE_LIMITS.minSide || height < IMAGE_LIMITS.minSide
      || width > IMAGE_LIMITS.maxSide || height > IMAGE_LIMITS.maxSide || width * height > IMAGE_LIMITS.maxPixels) throw new Error('Choose a still image with sides from 32 to 4096 pixels and at most 16 megapixels.');
  let detectorPixels = null; let inputQuality = null;
  if (state.detectorMetadata) {
    try { assertInputQuality(width, height, state.detectorMetadata); }
    catch (error) { if (!(error instanceof InputQualityError)) throw error; inputQuality = error; }
    if (!inputQuality) {
      const native = document.createElement('canvas'); native.width = width; native.height = height;
      const nativeContext = native.getContext('2d', { willReadFrequently: true });
      if (!nativeContext) throw new Error('This browser could not create the native image canvas.');
      nativeContext.fillStyle = '#fff'; nativeContext.fillRect(0, 0, width, height); nativeContext.drawImage(source, 0, 0, width, height);
      const nativePixels = nativeContext.getImageData(0, 0, width, height); detectorPixels = inspectionRgb8(nativePixels.data, width, height, state.detectorMetadata.image_size);
      native.width = 0; native.height = 0;
    }
  }
  const canvas = document.createElement('canvas'); canvas.width = state.imageSize; canvas.height = state.imageSize;
  const context = canvas.getContext('2d', { willReadFrequently: true });
  if (!context) throw new Error('This browser could not create an image canvas.');
  context.fillStyle = '#fff'; context.fillRect(0, 0, canvas.width, canvas.height);
  context.imageSmoothingEnabled = true; context.imageSmoothingQuality = 'high'; context.drawImage(source, 0, 0, canvas.width, canvas.height);
  const pixels = context.getImageData(0, 0, canvas.width, canvas.height); cancelInput();
  state.pixels = pixels; state.detectorPixels = detectorPixels; state.inputQuality = inputQuality; state.source = { filename: String(filename).slice(0, 512), width, height, kind: 'upload', ...details, source_timestamp: new Date().toISOString() };
  state.reconstruction = null; state.residual = null; state.result = null; state.detectorMap = null;
  elements['image-dimensions'].textContent = state.detectorMetadata ? `${width} × ${height} → ${state.detectorMetadata.image_size}² detector · ${state.imageSize}² reconstruction` : `${width} × ${height} → ${state.imageSize} × ${state.imageSize}`;
  elements['canvas-empty'].hidden = true; elements['canvas-corner'].hidden = false; elements['inspection-canvas'].parentElement.classList.add('has-image');
  elements['decision-panel'].className = 'decision-panel pending'; elements['decision-icon'].textContent = '—'; elements['decision-title'].textContent = 'Image selected';
  elements['decision-description'].textContent = 'Run an inspection to compare it with the learned normal pattern.';
  elements['anomaly-score'].textContent = '—'; elements['inference-time'].textContent = '—'; elements['ground-truth'].hidden = true;
  switchView('input'); updateControls();
}
async function loadFile(file, focusResult = false) {
  if (!file || state.busy || state.initializing) return false;
  stopReplay(); stopCamera(); let epoch = cancelInput(); clearNotice();
  let bitmap;
  let loaded = false;
  try {
    if (file.size > IMAGE_LIMITS.maxBytes) throw new Error('Choose a PNG, JPEG, or WebP still image up to 12 MiB.');
    const bytes = new Uint8Array(await file.arrayBuffer()); const header = validateImageBytes(bytes);
    if (epoch !== state.imageEpoch) return false;
    bitmap = await createImageBitmap(new Blob([bytes])); if (epoch !== state.imageEpoch) return false;
    if (!((bitmap.width === header.width && bitmap.height === header.height) || (bitmap.width === header.height && bitmap.height === header.width))) throw new Error('Decoded image dimensions differ from its header.');
    setInput(bitmap, file.name, { kind: 'upload' }); elements['source-status'].textContent = `${state.source.filename} · ${(file.size / 1024).toFixed(0)} KiB · local file`;
    epoch = state.imageEpoch;
    loaded = state.ready ? await inspect() : true;
    return loaded;
  } catch (error) {
    if (epoch === state.imageEpoch) { console.error('Image load failed:', error); showNotice(error.message || 'The image could not be decoded. Try a different image.', 'error'); }
    return false;
  } finally {
    bitmap?.close();
    if (focusResult && epoch === state.imageEpoch) {
      const target = loaded ? byId('evidence-title') : elements.notice;
      if (!target.hidden) { target.focus(); target.scrollIntoView?.({ block: 'start', behavior: 'auto' }); }
    }
  }
}
async function loadSample(index) {
  if (state.busy || !Number.isInteger(index) || !state.samples[index]) return false;
  const epoch = cancelInput(); const sample = state.samples[index]; const abort = new AbortController(); state.inputAbort = abort; let bitmap;
  try {
    const maxBytes = state.release ? assetSize(state.release.samples?.[sample.filename], IMAGE_LIMITS.maxBytes) : IMAGE_LIMITS.maxBytes;
    const bytes = await fetchBytes(sample.url, { signal: abort.signal, maxBytes });
    if (state.release && maxBytes !== bytes.length) throw new Error('The sample size differs from this release.');
    await verifyAsset(bytes, sample.sha256); const header = validateImageBytes(bytes);
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
  const detector = state.detector; const detectorMetadata = state.detectorMetadata; const detectorPixels = state.detectorPixels;
  const size = state.imageSize; const threshold = state.threshold; const topFraction = state.topFraction; const processingStarted = performance.now();
  state.busy = true; state.result = null; state.reconstruction = null; state.residual = null; state.detectorMap = null; clearNotice(); updateControls();
  elements['decision-panel'].className = 'decision-panel pending'; elements['decision-icon'].textContent = '—';
  elements['decision-title'].textContent = 'Inspection in progress'; elements['decision-description'].textContent = 'A decision will appear when this inspection completes.';
  elements['anomaly-score'].textContent = '—'; elements['inference-time'].textContent = '—'; elements['ground-truth'].hidden = true; switchView('input');
  let tensor; let outputs;
  try {
    await new Promise((resolve) => requestAnimationFrame(resolve)); if (epoch !== state.imageEpoch) return false;
    if (state.release?.schema_version === 2 && (!detector || !detectorMetadata)) throw new Error('A verified detector is required for this release.');
    if (state.inputQuality) throw state.inputQuality;
    let detection; let detectorElapsed = 0;
    if (detector) {
      const detectorStarted = performance.now(); detection = await detector.score(detectorPixels); detectorElapsed = performance.now() - detectorStarted;
      if (epoch !== state.imageEpoch || detector !== state.detector) return false;
    }
    const input = preprocessRGBA(pixels.data, size, size);
    tensor = new state.ort.Tensor('float32', input, [1, 3, size, size]);
    const start = performance.now(); outputs = await session.run({ image: tensor }); const elapsed = performance.now() - start;
    if (epoch !== state.imageEpoch || session !== state.session || detector !== state.detector) return false;
    const output = outputs.reconstruction;
    if (!output || output.type !== 'float32' || JSON.stringify(output.dims) !== JSON.stringify([1, 3, size, size]) || output.data?.length !== 3 * size * size) throw new Error('The model returned an invalid tensor.');
    const reconstruction = Float32Array.from(output.data);
    for (const value of reconstruction) if (!Number.isFinite(value) || value < 0 || value > 1) throw new Error('The model returned invalid pixel values.');
    const residual = computeResidual(input, reconstruction, { width: size, height: size });
    const reconstructionScore = scoreResidual(residual, topFraction);
    const score = detection ? detection.score : reconstructionScore; const isAnomaly = classify(score, threshold);
    const result = {
      id: globalThis.crypto?.randomUUID ? globalThis.crypto.randomUUID() : `mesh-${Date.now()}-${state.history.length}`,
      timestamp: new Date().toISOString(), source_timestamp: source.source_timestamp, filename: source.filename, source: source.kind,
      score, threshold, is_anomaly: isAnomaly, inference_ms: elapsed + detectorElapsed, processing_ms: performance.now() - processingStarted,
      model_version: String(detectorMetadata?.model_version ?? state.metadata.model_version), input_width: source.width, input_height: source.height,
      model_image_size: detectorMetadata?.image_size ?? size, score_is_probability: false,
      ...(detectorMetadata ? { detector_version: detectorMetadata.model_version, detector_runtime: detectorMetadata.runtime,
        preprocessing: detectorMetadata.preprocessing, detector_inference_ms: detectorElapsed,
        reconstruction_model_version: state.metadata.model_version, reconstruction_score: reconstructionScore,
        reconstruction_threshold: state.metadata.threshold, input_quality: 'supported-dimensions' } : {}),
    };
    state.reconstruction = reconstruction; state.residual = residual; state.detectorMap = detection ? { values: detection.anomaly_map, size: detection.map_size } : null; state.result = result;
    state.history.unshift({ ...result }); state.history = state.history.slice(0, 100); persistHistory(); renderHistory();
    elements['decision-panel'].className = `decision-panel ${isAnomaly ? 'review' : 'accepted'}`;
    elements['decision-icon'].textContent = isAnomaly ? '!' : '✓'; elements['decision-title'].textContent = isAnomaly ? 'Review recommended' : 'Within learned range';
    elements['decision-description'].textContent = detectorMetadata
      ? isAnomaly ? 'The detector score exceeds its frozen normal-reference limit. Inspect the highlighted regions and material yourself.' : 'The detector score stays within its calibrated range. This is not a defect-free guarantee; the reconstruction is separate visual evidence.'
      : isAnomaly ? 'Reconstruction error exceeds the frozen threshold. Take a closer look at the surface.' : 'Reconstruction error stays within the calibrated range. This is not a defect-free guarantee.';
    const totalElapsed = elapsed + detectorElapsed;
    elements['anomaly-score'].textContent = formatScore(score); elements['inference-time'].textContent = totalElapsed < 1000 ? `${Math.round(totalElapsed)} ms` : `${(totalElapsed / 1000).toFixed(2)} s`;
    if (source.sample && source.sample.label !== undefined) {
      const defect = source.sample.label === 0 || source.sample.label === 'normal' || source.sample.label === 'good' ? 'normal mesh' : `defective mesh${source.sample.defect_type ? ` · ${String(source.sample.defect_type).replaceAll('_', ' ')}` : ''}`;
      const knownDefect = source.sample.label === 1 || source.sample.label === 'anomaly' || source.sample.label === 'defective';
      const comparison = knownDefect ? (isAnomaly ? 'The model flagged this known defect.' : 'Missed defect: the model kept this defective image within range.') : (isAnomaly ? 'False alarm: the model flagged this normal image.' : 'The model kept this normal image within range.');
      elements['ground-truth'].textContent = `Benchmark ground truth: ${defect}. ${comparison} The known label is revealed after inference and is not passed to the model.`; elements['ground-truth'].hidden = false;
    }
    if (!state.cameraActive && !state.replayActive) switchView(detectorMetadata ? 'detector' : 'heatmap'); else drawView();
    return true;
  } catch (error) {
    if (epoch === state.imageEpoch) {
      console.error('Inspection failed:', error); state.result = null; state.reconstruction = null; state.residual = null; state.detectorMap = null;
      const qualityReview = error instanceof InputQualityError || error.code === 'mesh-pattern-unavailable'; const runtimeFailed = error.code === 'detector-runtime-unavailable';
      if (runtimeFailed) { state.ready = false; engineStatus('Detector unavailable', 'error'); }
      showNotice(qualityReview ? (error.message || 'The mesh repeat pattern could not be measured. Use a focused close-up similar to the examples.') : runtimeFailed ? error.message : 'The image could not be inspected. Try again or select another mesh image.', qualityReview ? 'info' : 'error', runtimeFailed ? 'Reload detector' : undefined, runtimeFailed ? initialize : undefined);
      elements['decision-panel'].className = `decision-panel ${qualityReview ? 'review' : 'pending'}`; elements['decision-icon'].textContent = qualityReview ? '!' : '—';
      elements['decision-title'].textContent = qualityReview ? 'Input needs review' : 'Inspection did not complete';
      elements['decision-description'].textContent = qualityReview ? 'The input is outside the supported capture conditions or its mesh pattern is unreadable. No defect decision or acceptance record was produced.' : 'No decision has been recorded for this attempt.';
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
  reconstruction: 'The autoencoder’s reconstruction at 256 × 256. This is separate visual evidence, not the upgraded detector’s decision.',
  heatmap: 'Autoencoder residuals compare original and reconstructed pixels. This relative map does not set the upgraded detector’s score or show defect probabilities.',
  detector: 'Warmer colors locate stronger detector responses. The color scale is relative to this image, not a defect probability or a validated segmentation mask.',
};
function switchView(view) {
  state.view = view; byId('visualization-panel').setAttribute('aria-labelledby', `view-tab-${view}`);
  for (const tab of document.querySelectorAll('.view-tab')) {
    const active = tab.dataset.view === view; tab.classList.toggle('active', active); tab.setAttribute('aria-selected', String(active)); tab.tabIndex = active ? 0 : -1;
  }
  elements['view-label'].textContent = { input: 'INPUT IMAGE', reconstruction: 'AUTOENCODER RECONSTRUCTION', heatmap: 'AUTOENCODER RESIDUAL', detector: 'DETECTOR RESPONSE' }[view];
  elements['view-description'].textContent = view === 'input' && state.detectorMetadata
    ? `The detector sees this ${state.detectorMetadata.image_size} × ${state.detectorMetadata.image_size} RGB image after the verified area resize. The autoencoder uses a separate 256 × 256 view.`
    : !state.detectorMetadata && view === 'heatmap' ? 'Warmer colors show larger residuals. The scale is relative to this image, not a defect probability.'
      : !state.detectorMetadata && view === 'reconstruction' ? 'The autoencoder’s reconstruction. Differences can indicate an unfamiliar pattern.' : descriptions[view];
  elements['overlay-control'].hidden = !['heatmap', 'detector'].includes(view); drawView();
}
function heatColor(value) {
  const stops = [[24, 63, 65], [48, 115, 116], [94, 164, 130], [210, 190, 109], [239, 128, 69], [229, 64, 45]];
  const position = Math.max(0, Math.min(1, value)) * (stops.length - 1); const low = Math.min(stops.length - 2, Math.floor(position)); const blend = position - low;
  return stops[low].map((channel, index) => channel * (1 - blend) + stops[low + 1][index] * blend);
}
function drawView() {
  if (!state.pixels) return;
  const detectorView = state.detectorMetadata && state.detectorPixels && ['input', 'detector'].includes(state.view);
  const size = detectorView ? state.detectorMetadata.image_size : state.imageSize; let pixels = state.pixels;
  if (detectorView) {
    const rgba = new Uint8ClampedArray(size * size * 4);
    for (let pixel = 0; pixel < size * size; pixel += 1) {
      for (let channel = 0; channel < 3; channel += 1) rgba[pixel * 4 + channel] = state.detectorPixels[pixel * 3 + channel];
      rgba[pixel * 4 + 3] = 255;
    }
    pixels = new ImageData(rgba, size, size);
  }
  const canvas = elements['inspection-canvas']; canvas.width = size; canvas.height = size; const context = canvas.getContext('2d');
  canvas.setAttribute('aria-label', `${state.source?.filename || 'Mesh image'} — ${state.view === 'input' ? 'original' : state.view === 'heatmap' ? 'relative reconstruction error map' : state.view === 'detector' ? 'relative detector response map' : 'model reconstruction'}`);
  if (state.view === 'input' || !state.reconstruction || (state.view === 'detector' && !state.detectorMap)) { context.putImageData(pixels, 0, 0); return; }
  if (state.view === 'reconstruction') { context.putImageData(new ImageData(reconstructionRGBA(state.reconstruction, state.imageSize, state.imageSize), state.imageSize, state.imageSize), 0, 0); return; }
  const map = state.view === 'detector' ? state.detectorMap.values : state.residual;
  const mapSize = state.view === 'detector' ? state.detectorMap.size : state.imageSize;
  const ordered = Float32Array.from(map).sort(); const scale = Math.max(ordered[Math.min(ordered.length - 1, Math.floor(ordered.length * 0.995))], 1e-7);
  const rgba = new Uint8ClampedArray(pixels.data.length); const overlay = elements['overlay-toggle'].checked;
  for (let index = 0; index < size * size; index += 1) {
    const y = Math.floor(index / size); const x = index % size;
    const value = map[Math.floor(y * mapSize / size) * mapSize + Math.floor(x * mapSize / size)];
    const normalized = Math.min(1, value / scale); const color = heatColor(normalized); const mix = overlay ? 0.12 + normalized * 0.68 : 1;
    for (let channel = 0; channel < 3; channel += 1) rgba[index * 4 + channel] = color[channel] * mix + pixels.data[index * 4 + channel] * (1 - mix);
    rgba[index * 4 + 3] = 255;
  }
  context.putImageData(new ImageData(rgba, size, size), 0, 0);
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
    const decision = document.createElement('td'); const tag = document.createElement('span'); tag.className = `history-pill ${record.is_anomaly ? 'review' : ''}`; tag.textContent = record.is_anomaly ? 'Review' : 'Within range'; decision.append(tag);
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
          if (!succeeded) { stopCamera(); return; }
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

function chooseFile() { if (!state.busy && !state.initializing) elements['file-input'].click(); }
// Native buttons provide Enter/Space activation without a duplicate key handler.
elements.dropzone.addEventListener('click', chooseFile);
byId('upload-own-image').addEventListener('click', chooseFile);
for (const eventName of ['dragenter', 'dragover']) elements.dropzone.addEventListener(eventName, (event) => { event.preventDefault(); elements.dropzone.classList.add('dragover'); });
for (const eventName of ['dragleave', 'drop']) elements.dropzone.addEventListener(eventName, (event) => { event.preventDefault(); elements.dropzone.classList.remove('dragover'); });
elements.dropzone.addEventListener('drop', (event) => loadFile(event.dataTransfer.files[0]));
elements['file-input'].addEventListener('change', async (event) => {
  const file = event.target.files[0]; event.target.value = ''; if (!file) return;
  await loadFile(file, true);
});
elements['load-sample'].addEventListener('click', () => manualSample(Number(elements['sample-select'].value)));
elements['sample-select'].addEventListener('change', () => manualSample(Number(elements['sample-select'].value)));
elements['inspect-button'].addEventListener('click', inspect); elements['replay-button'].addEventListener('click', toggleReplay); elements['camera-button'].addEventListener('click', toggleCamera); elements['overlay-toggle'].addEventListener('change', drawView);
for (const tab of document.querySelectorAll('.view-tab')) {
  tab.addEventListener('click', () => switchView(tab.dataset.view));
  tab.addEventListener('keydown', (event) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return; event.preventDefault();
    const tabs = [...document.querySelectorAll('.view-tab')].filter((item) => !item.disabled && !item.hidden); const index = tabs.indexOf(tab);
    if (!tabs.length) return;
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    switchView(tabs[next].dataset.view); tabs[next].focus();
  });
}
elements['clear-history'].addEventListener('click', () => {
  const cleared = state.history; state.history = []; persistHistory(); renderHistory();
  showNotice('Inspection history cleared. The current result is still available.', 'info', 'Undo clear', () => {
    const current = new Set(state.history.map((record) => record.id || `${record.timestamp}:${record.filename}`));
    state.history = [...state.history, ...cleared.filter((record) => !current.has(record.id || `${record.timestamp}:${record.filename}`))].slice(0, 100);
    persistHistory(); renderHistory(); showNotice('Inspection history restored.', 'info', undefined, undefined, byId('history-feedback'));
  }, byId('history-feedback'));
});
elements['export-csv'].addEventListener('click', () => {
  const fields = ['timestamp', 'source_timestamp', 'filename', 'source', 'score', 'threshold', 'is_anomaly', 'inference_ms', 'processing_ms', 'model_version', 'detector_version', 'preprocessing', 'reconstruction_model_version', 'reconstruction_score'];
  const lines = [fields.map(csvEscape).join(','), ...state.history.map((record) => fields.map((field) => csvEscape(record[field])).join(','))];
  download(`\uFEFF${lines.join('\r\n')}\r\n`, `MeshLens-inspections-${new Date().toISOString().slice(0, 10)}.csv`, 'text/csv;charset=utf-8');
});
elements['download-record'].addEventListener('click', () => { if (state.result) download(`${JSON.stringify(state.result, null, 2)}\n`, `MeshLens-inspection-${state.result.id}.json`, 'application/json'); });
elements['download-metadata'].addEventListener('click', () => { if (state.metadata) download(`${JSON.stringify(state.detectorMetadata || state.metadata, null, 2)}\n`, 'MeshLens-model-metadata.json', 'application/json'); });
window.addEventListener('pagehide', () => { stopReplay(); stopCamera(); });
document.addEventListener('visibilitychange', () => { if (document.hidden) { stopReplay(); stopCamera(); } });
if ('IntersectionObserver' in window) {
  const observer = new IntersectionObserver((entries) => { for (const entry of entries) if (entry.isIntersecting) for (const link of document.querySelectorAll('.nav-link')) link.classList.toggle('active', link.hash === `#${entry.target.id}`); }, { rootMargin: '-5% 0px -65% 0px', threshold: 0 });
  for (const id of ['inspect', 'dataset', 'results', 'method']) observer.observe(byId(id));
}
renderHistory(); updateControls(); initialize();
