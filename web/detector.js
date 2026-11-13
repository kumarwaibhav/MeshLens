/** Decision detector, independent of the reconstruction illustration. */
const SHA256 = /^[a-f0-9]{64}$/;
export const DETECTOR_MODEL_MAX_BYTES = 128 * 1024 * 1024;
export class InputQualityError extends Error {
  constructor(message, code = 'input-quality-review') { super(message); this.name = 'InputQualityError'; this.code = code; }
}
export function validateDetectorMetadata(metadata) {
  const artifact = metadata?.export; const quality = metadata?.input_quality;
  const counts = metadata?.dataset; const calibration = metadata?.calibration;
  if (!metadata || metadata.schema_version !== 1 || typeof metadata.model_version !== 'string'
      || !metadata.model_version || metadata.model_version.length > 128 || !['onnx', 'texture-js'].includes(metadata.runtime)
      || !Number.isInteger(metadata.image_size) || metadata.image_size < 32 || metadata.image_size > 1024
      || metadata.preprocessing !== 'area-rgb8-v1' || metadata.decision !== 'strict-greater-than' || metadata.score_is_probability !== false
      || !Number.isFinite(metadata.threshold) || metadata.threshold < 0
      || !artifact || !/^[A-Za-z0-9][A-Za-z0-9_-]*\.(onnx|json)$/.test(artifact.model_file ?? '')
      || (metadata.runtime === 'onnx') !== artifact.model_file.endsWith('.onnx')
      || !SHA256.test(artifact.model_sha256 ?? '') || !Number.isSafeInteger(artifact.model_bytes)
      || artifact.model_bytes < 1 || artifact.model_bytes > DETECTOR_MODEL_MAX_BYTES
      || metadata.outputs?.score_name !== 'score' || metadata.outputs?.map_name !== 'anomaly_map'
      || !Number.isInteger(metadata.outputs?.map_size) || metadata.outputs.map_size < 1 || metadata.outputs.map_size > metadata.image_size
      || calibration?.count !== 52 || calibration.alpha !== 0.05 || calibration.order_statistic_rank !== 51
      || !SHA256.test(calibration.scores_sha256 ?? '') || !SHA256.test(counts?.manifest_sha256 ?? '')
      || counts.fit !== 160 || counts.tune !== 52 || counts.calibration !== 52 || counts.test !== 78
      || (quality && (!Number.isInteger(quality.min_side) || quality.min_side < metadata.image_size || quality.min_side > 4096
        || !Number.isFinite(quality.max_aspect_ratio) || quality.max_aspect_ratio < 1 || quality.max_aspect_ratio > 2))) throw new Error('The detector metadata does not match the supported inspection contract.');
  return metadata;
}
export function assertInputQuality(width, height, metadata) {
  const minimum = metadata.input_quality?.min_side ?? metadata.image_size;
  const aspect = metadata.input_quality?.max_aspect_ratio ?? 1.5;
  if (Math.min(width, height) < minimum) throw new InputQualityError(`Use an original mesh photo at least ${minimum} pixels on each side. Enlarging a small image cannot restore defect detail.`);
  if (Math.max(width, height) / Math.min(width, height) > aspect) throw new InputQualityError(`Use nearly square framing (long side no more than ${aspect}× the short side). The current shape would distort the mesh pattern.`);
}
export function validateDetectorEvaluation(report, metadata) {
  const counts = ['true_positive', 'false_negative', 'true_negative', 'false_positive'];
  if (!report || report.schema_version !== 1 || report.model_version !== metadata.model_version
      || report.model_sha256 !== metadata.export.model_sha256 || report.threshold !== metadata.threshold
      || report.test_count !== 78 || report.test_normal !== 21 || report.test_defect !== 57
      || counts.some((key) => !Number.isInteger(report.model?.[key]) || report.model[key] < 0 || report.model[key] > 78)
      || ['recall', 'precision', 'f1', 'accuracy'].some((key) => !Number.isFinite(report.model?.[key]) || report.model[key] < 0 || report.model[key] > 1)
      || !(report.model?.auroc === null || (Number.isFinite(report.model?.auroc) && report.model.auroc >= 0 && report.model.auroc <= 1))
      || report.protocol?.selection_used_test !== false || report.protocol.source_manifest_sha256 !== metadata.dataset.manifest_sha256
      || !SHA256.test(report.protocol.development_manifest_sha256 ?? '')
      || report.qualification?.status !== 'benchmark_only' || report.qualification.automated_line_inspection_qualified !== false
      || report.coverage?.total !== 78 || !Number.isInteger(report.coverage.scored) || !Number.isInteger(report.coverage.inconclusive)
      || report.coverage.scored < 0 || report.coverage.inconclusive < 0 || report.coverage.scored + report.coverage.inconclusive !== 78) throw new Error('The detector evaluation does not match its frozen model and test protocol.');
  if (!Number.isInteger(report.coverage.defective_inconclusive) || !Number.isInteger(report.coverage.clean_inconclusive)
      || report.coverage.defective_inconclusive < 0 || report.coverage.clean_inconclusive < 0
      || report.coverage.defective_inconclusive + report.coverage.clean_inconclusive !== report.coverage.inconclusive
      || report.model.true_positive + report.model.false_negative !== 57
      || report.model.true_negative + report.model.false_positive + report.coverage.clean_inconclusive !== 21
      || report.model.samples !== 78 || report.model.threshold !== metadata.threshold) throw new Error('The detector evaluation omits test outcomes.');
  return report;
}
function validateTensor(item, name, shape) {
  if (!item || item.name !== name || item.isTensor === false || item.type !== 'float32'
      || JSON.stringify(item.shape ?? item.dimensions) !== JSON.stringify(shape)) throw new Error('The detector returned an unsupported tensor contract.');
}
function validateResult(result, metadata) {
  const size = metadata.outputs.map_size;
  if (!result || !Number.isFinite(result.score) || result.score < 0 || result.map_size !== size
      || !(result.anomaly_map instanceof Float32Array) || result.anomaly_map.length !== size * size) throw new Error('The detector returned an invalid result.');
  for (const value of result.anomaly_map) if (!Number.isFinite(value) || value < 0) throw new Error('The detector returned an invalid map.');
  return result;
}
function textureWorker(model, createWorker, timeoutMs) {
  let worker;
  try { worker = createWorker(); } catch { throw new Error('The detector worker could not start. Check browser worker support and reload the model.'); }
  let pending = null; let nextId = 0; let closed = false;
  const unavailable = (message) => Object.assign(new Error(message), { code: 'detector-runtime-unavailable' });
  const fail = (error) => { closed = true; worker.terminate(); if (pending) { clearTimeout(pending.timer); const current = pending; pending = null; current.reject(error); } };
  worker.onerror = () => fail(unavailable('The detector worker stopped. Reload the model before trying another image.'));
  worker.onmessageerror = () => fail(unavailable('The detector worker returned unreadable data. Reload the model.'));
  worker.onmessage = ({ data }) => {
    if (closed) return;
    if (!pending || !data || data.id !== pending.id || !['ready', 'result', 'error'].includes(data.type)
        || (pending.kind === 'initialize' && !['ready', 'error'].includes(data.type))
        || (pending.kind === 'score' && !['result', 'error'].includes(data.type))) { fail(unavailable('The detector worker returned an unexpected response. Reload the model.')); return; }
    const current = pending; pending = null; clearTimeout(current.timer);
    if (data.type === 'error') {
      if (data.code === 'mesh-pattern-unavailable') current.reject(new InputQualityError(String(data.message || 'The mesh repeat pattern could not be measured.'), data.code));
      else { const error = unavailable('The detector worker could not complete this inspection. Reload the model.'); closed = true; worker.terminate(); current.reject(error); }
    } else current.resolve(data);
  };
  const request = (kind, payload, transfer = []) => new Promise((resolve, reject) => {
    if (closed) { reject(unavailable('The detector worker is unavailable. Reload the model.')); return; }
    if (pending) { reject(new Error('A detector inspection is already in progress.')); return; }
    const id = ++nextId; const timer = setTimeout(() => fail(unavailable('The detector worker timed out. Reload the model or use a faster device.')), timeoutMs);
    pending = { id, kind, resolve, reject, timer };
    try { worker.postMessage({ type: kind, id, ...payload }, transfer); } catch { fail(unavailable('The detector input could not reach its worker. Reload the model.')); }
  });
  return { ready: request('initialize', { model }), score(rgb8) { const copy = rgb8.slice(); return request('score', { rgb8: copy }, [copy.buffer]); }, release() { fail(unavailable('The detector worker was released.')); } };
}
/** Create from bytes already checked against both manifest and metadata. */
export async function createDetector(metadata, bytes, ort, { createWorker = () => new Worker(new URL('./texture_worker.js', import.meta.url), { type: 'module', name: 'meshlens-detector' }), workerTimeoutMs = 30_000 } = {}) {
  validateDetectorMetadata(metadata);
  if (!Number.isFinite(workerTimeoutMs) || workerTimeoutMs <= 0 || workerTimeoutMs > 30_000) throw new Error('Invalid detector worker timeout.');
  const size = metadata.image_size; let session; let texture;
  try {
    if (metadata.runtime === 'texture-js') {
      const model = JSON.parse(new TextDecoder().decode(bytes));
      if (model.image_size !== size || model.threshold !== metadata.threshold || model.preprocessing !== metadata.preprocessing) throw new Error('The texture model numerical contract differs from its metadata.');
      texture = textureWorker(model, createWorker, workerTimeoutMs); await texture.ready;
    } else {
      session = await ort.InferenceSession.create(bytes, { executionProviders: ['wasm'], graphOptimizationLevel: 'all' });
      if (JSON.stringify(session.inputNames) !== '["image"]' || JSON.stringify(session.outputNames) !== '["score","anomaly_map"]'
          || session.inputMetadata?.length !== 1 || session.outputMetadata?.length !== 2) throw new Error('Unexpected detector inputs or outputs.');
      validateTensor(session.inputMetadata[0], 'image', [1, 3, size, size]);
      validateTensor(session.outputMetadata.find((item) => item.name === 'score'), 'score', [1]);
      validateTensor(session.outputMetadata.find((item) => item.name === 'anomaly_map'), 'anomaly_map', [1, 1, metadata.outputs.map_size, metadata.outputs.map_size]);
    }
  } catch (error) { await session?.release?.(); await texture?.release?.(); throw error; }
  return {
    async score(rgb8) {
      if (!(rgb8 instanceof Uint8Array) || rgb8.length !== size * size * 3) throw new Error('The detector needs its canonical RGB input.');
      if (texture) { const result = await texture.score(rgb8); try { return validateResult(result, metadata); } catch (error) { texture.release(); error.code = 'detector-runtime-unavailable'; throw error; } }
      let tensor; let outputs;
      try {
        const plane = size * size; const input = new Float32Array(plane * 3);
        for (let pixel = 0; pixel < plane; pixel += 1) for (let channel = 0; channel < 3; channel += 1) input[channel * plane + pixel] = rgb8[pixel * 3 + channel] / 255;
        tensor = new ort.Tensor('float32', input, [1, 3, size, size]); outputs = await session.run({ image: tensor });
        const score = outputs.score; const map = outputs.anomaly_map;
        if (score?.type !== 'float32' || JSON.stringify(score.dims) !== '[1]' || score.data?.length !== 1
            || map?.type !== 'float32' || JSON.stringify(map.dims) !== JSON.stringify([1, 1, metadata.outputs.map_size, metadata.outputs.map_size])) throw new Error('The detector returned invalid output tensors.');
        return validateResult({ score: score.data[0], anomaly_map: Float32Array.from(map.data), map_size: metadata.outputs.map_size }, metadata);
      } finally { tensor?.dispose?.(); if (outputs) for (const value of new Set(Object.values(outputs))) value?.dispose?.(); }
    }, async release() { await session?.release?.(); await texture?.release?.(); },
  };
}
