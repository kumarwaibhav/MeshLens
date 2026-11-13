/** Recompute the active release's claims from frozen provenance and raw outcomes. */
import { createHash } from 'node:crypto';
import { validateDetectorMetadata, validateDetectorEvaluation } from '../web/detector.js';
import { validateImageBytes } from '../web/validation.js';

export const INSPECTION_CONDITIONS = ['original', 'brightness_070', 'brightness_130', 'shift_8x4_ref256', 'blur_sigma_0p8_ref256', 'jpeg_quality_75'];
const NUMERIC_SOURCES = ['src/meshlens/texture_detector.py', 'src/meshlens/inspection_input.py', 'web/texture_detector.js', 'web/inspection_input.js'];
const BOUND_FILES = ['artifacts/inspection/detector-model.json', 'artifacts/inspection/detector.json', 'artifacts/inspection/calibration.json', 'reports/inspection/selection.json', 'reports/inspection/protocol.json', 'data/manifest.csv'];
const sha = (bytes) => createHash('sha256').update(bytes).digest('hex');
const fail = (message) => { throw new Error(`Inspection release: ${message}`); };
const digest = (bytes, expected, name) => { if (!/^[a-f0-9]{64}$/.test(expected ?? '') || sha(bytes) !== expected) fail(`${name} SHA-256 integrity mismatch.`); };
function same(actual, expected, name) {
  if (typeof expected === 'number') { if (!Number.isFinite(actual) || Math.abs(actual - expected) > 1e-12) fail(`${name} metric/count/interval mismatch.`); return; }
  if (expected === null || typeof expected !== 'object') { if (actual !== expected) fail(`${name} mismatch.`); return; }
  if (!actual || typeof actual !== 'object' || JSON.stringify(Object.keys(actual).sort()) !== JSON.stringify(Object.keys(expected).sort())) fail(`${name} fields mismatch.`);
  for (const key of Object.keys(expected)) same(actual[key], expected[key], `${name}.${key}`);
}
function csvRows(bytes) {
  const lines = bytes.toString('utf8').trim().split(/\r?\n/); const columns = lines.shift().split(',');
  if (columns.join(',') !== 'path,split,label,defect_type,sha256,mask_path') fail('Unexpected source manifest columns.');
  return lines.map((line) => { const values = line.split(','); if (values.length !== columns.length) fail('Malformed source manifest row.'); return Object.fromEntries(columns.map((column, index) => [column, values[index]])); });
}
export function wilson(successes, total) {
  if (!total) return { lower: 0, upper: 1 };
  const z = 1.959963984540054; const p = successes / total; const denominator = 1 + z*z/total;
  const center = (p + z*z/(2*total))/denominator;
  const half = z*Math.sqrt(p*(1-p)/total + z*z/(4*total*total))/denominator;
  return { lower: Math.max(0, center-half), upper: Math.min(1, center+half) };
}
export function summarizeInspection(rows, threshold) {
  const positive = rows.filter((row) => row.label === 1); const negative = rows.filter((row) => row.label === 0);
  const tp = positive.filter((row) => row.decision === 'review').length; const fp = negative.filter((row) => row.decision === 'review').length;
  const tn = negative.filter((row) => row.decision === 'within_range').length;
  const pi = positive.filter((row) => row.decision === 'unusable').length; const ni = negative.filter((row) => row.decision === 'unusable').length;
  const pScores = positive.filter((row) => row.decision !== 'unusable').map((row) => row.score);
  const nScores = negative.filter((row) => row.decision !== 'unusable').map((row) => row.score);
  let wins = 0; for (const p of pScores) for (const n of nScores) wins += p > n ? 1 : p === n ? .5 : 0;
  const fn = positive.length - tp;
  return {
    model: { auroc: pScores.length && nScores.length ? wins/(pScores.length*nScores.length) : null,
      precision: tp+fp ? tp/(tp+fp) : 0, recall: positive.length ? tp/positive.length : 0,
      f1: 2*tp+fp+fn ? 2*tp/(2*tp+fp+fn) : 0, accuracy: rows.length ? (tp+tn)/rows.length : 0,
      true_positive: tp, false_negative: fn, true_negative: tn, false_positive: fp, threshold, samples: rows.length },
    coverage: { total: rows.length, scored: rows.length-pi-ni, inconclusive: pi+ni, defective_inconclusive: pi, clean_inconclusive: ni },
    binomial_wilson_intervals_95: { recall: wilson(tp,positive.length), precision: wilson(tp,tp+fp), false_alarm_rate: wilson(fp,negative.length), clean_review_or_inconclusive_rate: wilson(fp+ni,negative.length), accuracy: wilson(tp+tn,rows.length) },
    normal_samples: negative.length, false_alarms: fp, false_alarm_rate: negative.length ? fp/negative.length : 0,
    clean_review_or_inconclusive_rate: negative.length ? (fp+ni)/negative.length : 0,
    mean_score: nScores.length ? nScores.reduce((sum,value) => sum+value,0)/nScores.length : null,
  };
}

/** No fallback: schema2 always requires the fully verified active detector inputs. */
export async function verifyInspectionRelease({ read, manifest }) {
  const [modelBytes, metadataBytes, calibrationBytes, samplesBytes, publicBytes, freezeBytes, protocolBytes, selectionBytes, rawBytes] = await Promise.all([
    read('artifacts/inspection/detector-model.json'), read('artifacts/inspection/detector.json'), read('artifacts/inspection/calibration.json'), read('artifacts/inspection/samples.json'), read('reports/inspection/evaluation.json'), read('reports/inspection/frozen_configuration.json'), read('reports/inspection/protocol.json'), read('reports/inspection/selection.json'), read('reports/inspection/independent_evaluation.json'),
  ]);
  const model = JSON.parse(modelBytes); const metadata = validateDetectorMetadata(JSON.parse(metadataBytes)); const calibration = JSON.parse(calibrationBytes);
  const gallery = JSON.parse(samplesBytes); const report = validateDetectorEvaluation(JSON.parse(publicBytes), metadata);
  const freeze = JSON.parse(freezeBytes); const protocol = JSON.parse(protocolBytes); const selection = JSON.parse(selectionBytes); const raw = JSON.parse(rawBytes);
  const expectedFiles = [...BOUND_FILES, ...NUMERIC_SOURCES];
  if (freeze.schema_version !== 1 || JSON.stringify(Object.keys(freeze.files ?? {}).sort()) !== JSON.stringify(expectedFiles.sort())) fail('Freeze does not bind all four numerical sources and required artifacts.');
  const contents = new Map([['artifacts/inspection/detector-model.json', modelBytes], ['artifacts/inspection/detector.json', metadataBytes], ['artifacts/inspection/calibration.json', calibrationBytes], ['reports/inspection/protocol.json', protocolBytes], ['reports/inspection/selection.json', selectionBytes], ['data/manifest.csv', manifest]]);
  for (const name of NUMERIC_SOURCES) contents.set(name, await read(name));
  for (const [name, bytes] of contents) { digest(bytes, freeze.files[name]?.sha256, name); if (freeze.files[name]?.bytes !== bytes.length) fail(`Frozen byte length differs: ${name}`); }
  digest(modelBytes, metadata.export.model_sha256, 'Detector model'); digest(calibrationBytes, metadata.calibration.scores_sha256, 'Normal calibration');
  digest(manifest, metadata.dataset.manifest_sha256, 'Detector dataset manifest'); digest(manifest, selection.data_manifest_sha256, 'Selection dataset');
  digest(selectionBytes, model.frozen_candidate_sha256, 'Selected candidate');
  digest(contents.get(NUMERIC_SOURCES[0]), model.implementation_sha256, 'Python scorer'); digest(contents.get(NUMERIC_SOURCES[1]), model.preprocessing_sha256, 'Python preprocessing');
  if (metadata.runtime !== 'texture-js' || model.kind !== 'normal-lattice-v1' || model.image_size !== 256 || model.variant !== 'joint' || model.tail_fraction !== .005 || model.score_decimals !== 8 || model.threshold !== 1.01049636 || model.threshold !== metadata.threshold || model.preprocessing !== metadata.preprocessing || metadata.export.model_file !== 'detector-model.json' || metadata.export.model_bytes !== modelBytes.length || metadata.score_decimals !== 8 || !Number.isFinite(model.fit_scale) || model.fit_scale <= 0) fail('The frozen A256joint model numerical contract differs.');
  same(model.calibration, { count: 52, alpha: .05, strict_greater_than: true }, 'Model calibration');
  if (metadata.calibration.strict_greater_than !== true || selection.fit_count !== 160 || selection.tune_clean_count !== 52 || selection.development_manifest_sha256 !== metadata.dataset.development_manifest_sha256 || selection.development_manifest_sha256 !== model.development_manifest_sha256) fail('Development selection/calibration boundary mismatch.');
  if (freeze.model_version !== metadata.model_version || freeze.model_sha256 !== metadata.export.model_sha256 || freeze.threshold !== metadata.threshold || freeze.decision_rule !== 'score > threshold' || freeze.score_decimals !== 8 || freeze.selection_used_test !== false) fail('Freeze identity differs from detector metadata.');
  same(freeze.calibration, metadata.calibration, 'Frozen calibration');
  if (protocol.schema_version !== 1 || protocol.test_images !== 78 || protocol.test_normal !== 21 || protocol.test_defect !== 57 || protocol.records_expected !== 468 || protocol.selection_used_test !== false || protocol.calibration_used_test !== false || protocol.decision_rule !== 'score > threshold' || protocol.score_decimals !== 8 || JSON.stringify(protocol.conditions) !== JSON.stringify(INSPECTION_CONDITIONS) || protocol.benchmark_reuse !== true || protocol.prior_evaluation_known !== true || protocol.new_blind_validation !== false || protocol.algorithm_changed_after_prior_test !== false) fail('Evaluation protocol or recovery disclosure differs.');
  const rows = csvRows(manifest); const partition = (name) => rows.filter((row) => row.split === name);
  if (rows.length !== 342 || new Set(rows.map((row) => row.path)).size !== 342 || new Set(rows.map((row) => row.sha256)).size !== 342 || partition('fit').length !== 160 || partition('tune').length !== 52 || partition('calibration').length !== 52 || partition('test').length !== 78 || rows.some((row) => row.split !== 'test' && row.label !== '0')) fail('The dataset split differs from160/52/52/78 normal-only development.');
  const cal = new Map(partition('calibration').map((row) => [row.path,row])); const seenCal = new Set();
  if (!Array.isArray(calibration) || calibration.length !== 52) fail('Calibration requires all reserved52 normals.');
  for (const row of calibration) {
    const expected = cal.get(row.path);
    if (!expected || seenCal.has(row.path) || row.sha256 !== expected.sha256 || (row.label ?? 0) !== 0 || !Number.isFinite(row.score) || row.score < 0 || Number(row.score.toFixed(8)) !== row.score) fail('Reserved normal calibration path/hash/score mismatch.');
    seenCal.add(row.path);
  }
  if (calibration.map((row) => row.score).sort((a,b) => a-b)[50] !== metadata.threshold) fail('Threshold differs from normal calibration rank51.');
  const freezeHash = sha(freezeBytes); const rawHash = sha(rawBytes);
  if (raw.schema_version !== 1 || raw.threshold_was_tuned !== false || raw.source_manifest_sha256 !== metadata.dataset.manifest_sha256 || raw.protocol_sha256 !== sha(protocolBytes) || raw.freeze_sha256 !== freezeHash || raw.model_sha256 !== metadata.export.model_sha256 || raw.model_version !== metadata.model_version || raw.evaluation?.cutoff !== metadata.threshold || !Number.isFinite(Date.parse(raw.evaluated_at)) || !Number.isFinite(Date.parse(freeze.frozen_at)) || Date.parse(raw.evaluated_at) < Date.parse(freeze.frozen_at)) fail('Raw evaluation is not bound to this pre-existing freeze.');
  if (report.freeze_sha256 !== freezeHash || report.raw_report_sha256 !== rawHash || report.protocol.freeze_sha256 !== freezeHash || report.protocol.raw_report_sha256 !== rawHash) fail('Public raw-report/freeze SHA-256 binding differs.');
  const original = new Map(partition('test').map((row) => [row.path,row])); const seen = new Set(); const records = raw.evaluation.records;
  if (!Array.isArray(records) || records.length !== 468 || [...original.values()].filter((row) => row.label === '1').length !== 57) fail('Expected all78test images under all6conditions.');
  for (const record of records) {
    const source = original.get(record.path); const key = `${record.path}:${record.variant}`;
    if (!source || !INSPECTION_CONDITIONS.includes(record.variant) || seen.has(key) || record.sha256 !== source.sha256 || !Number.isInteger(record.label) || record.label !== Number(source.label) || record.defect_type !== source.defect_type) fail('Raw test provenance or78x6 coverage mismatch.');
    seen.add(key); const score = record.score;
    if (score !== null && (!Number.isFinite(score) || score < 0 || Number(score.toFixed(8)) !== score)) fail('Raw score differs from frozen8decimal contract.');
    if (record.decision === 'unusable') { if (typeof record.unusable_reason !== 'string' || !record.unusable_reason.trim()) fail('Inconclusive result lacks its reason.'); }
    else if (score === null || record.unusable_reason !== null || record.decision !== (score > metadata.threshold ? 'review' : 'within_range')) fail('Raw decision differs from strict score > threshold.');
    if (!Number.isFinite(record.wall_ms) || record.wall_ms < 0) fail('Invalid raw evaluation timing.');
  }
  const conditions = Object.fromEntries(INSPECTION_CONDITIONS.map((condition) => [condition,summarizeInspection(records.filter((row) => row.variant === condition),metadata.threshold)]));
  const base = conditions.original; const originalRecords = records.filter((row) => row.variant === 'original');
  same(report.model,base.model,'Public benchmark'); same(report.coverage,base.coverage,'Public coverage');
  same(report.binomial_wilson_intervals_95,base.binomial_wilson_intervals_95,'Public Wilson95%'); same(report.conditions,conditions,'All6conditions');
  const groups = [...new Set(originalRecords.map((row) => row.defect_type))].sort();
  same(report.per_defect,Object.fromEntries(groups.map((group) => [group,summarizeInspection(originalRecords.filter((row) => row.defect_type === group),metadata.threshold)])),'Per-defect results');
  const stresses = Object.fromEntries(Object.entries(conditions).map(([name,summary]) => [name,{
    ...summary, defective: summary.model.true_positive+summary.model.false_negative,
    defect_alerts: summary.model.true_positive, clean: summary.normal_samples,
    clean_alerts: summary.model.false_positive, defective_unusable: summary.coverage.defective_inconclusive,
    clean_unusable: summary.coverage.clean_inconclusive, defect_recall: summary.model.recall,
    clean_false_alarm_rate: summary.false_alarm_rate,
  }]));
  same(report.stress_tests,stresses,'Stress summaries');
  for (const [key,value] of Object.entries(protocol)) same(report.protocol[key],value,`Public protocol.${key}`);
  if (report.protocol.source_manifest_sha256 !== metadata.dataset.manifest_sha256 || report.protocol.development_manifest_sha256 !== selection.development_manifest_sha256 || report.score_is_probability !== false || metadata.qualification?.status !== 'benchmark_only' || metadata.qualification.automated_line_inspection_qualified !== false || report.qualification.independent_target_line_qualified !== false || report.qualification.physical_camera_validation_completed !== false) fail('Qualification/benchmark-only disclosure mismatch.');
  if (gallery.schema_version !== 1 || gallery.model_version !== metadata.model_version || gallery.model_sha256 !== metadata.export.model_sha256 || gallery.threshold !== metadata.threshold || gallery.count !== 18 || gallery.preprocessing !== 'area-rgb8-v1' || !Array.isArray(gallery.samples) || gallery.samples.length !== 18 || gallery.license !== 'CC-BY-NC-SA-4.0') fail('Active gallery does not match the detector.');
  const sampleAssets = new Map(); const sourceRecords = new Map(originalRecords.map((row) => [row.path,row])); const samplePaths = new Set(); const groupCounts = new Map();
  for (const sample of gallery.samples) {
    const source = sourceRecords.get(sample.source_path);
    if (!source || samplePaths.has(sample.source_path) || !/^[A-Za-z0-9][A-Za-z0-9_-]*\.png$/.test(sample.filename ?? '') || sampleAssets.has(sample.filename) || sample.id !== sample.filename.slice(0,-4) || sample.source_sha256 !== source.sha256 || sample.label !== source.label || sample.defect_type !== source.defect_type || sample.model_version !== metadata.model_version || sample.preprocessing !== metadata.preprocessing || sample.expected_score !== source.score || sample.expected_anomaly !== (source.decision === 'review') || sample.expected_decision !== source.decision) fail('Gallery source label/score/decision mismatch.');
    const bytes = await read(`artifacts/inspection/samples/${sample.filename}`); digest(bytes,sample.sha256,`Active sample ${sample.filename}`);
    const size = validateImageBytes(bytes); if (size.width !== 256 || size.height !== 256 || bytes[24] !== 8 || bytes[25] !== 2) fail('Active samples must be canonical256px8bitRGB PNGs.');
    sampleAssets.set(sample.filename,bytes); samplePaths.add(sample.source_path); groupCounts.set(sample.defect_type,(groupCounts.get(sample.defect_type) ?? 0)+1);
  }
  if (groupCounts.size !== 6 || [...groupCounts.values()].some((count) => count !== 3) || !samplePaths.has('data/raw/grid/test/glue/008.png') || samplePaths.has('data/raw/grid/test/glue/002.png') || sourceRecords.get('data/raw/grid/test/glue/008.png')?.decision !== 'within_range') fail('Gallery must include the actual missed glue008 and all6groups.');
  if (gallery.download?.filename !== 'MeshLens-18-Benchmark-Examples.zip') fail('Active sample kit filename differs.');
  const kit = await read(`web/downloads/${gallery.download.filename}`); digest(kit,gallery.download.sha256,'Reproducible sample kit'); if (kit.length !== gallery.download.bytes) fail('Sample kit byte length differs.');
  return { metadata, report, gallery, sampleAssets, modelBytes, metadataBytes, samplesBytes, evaluationBytes: publicBytes, freezeHash, rawHash };
}
