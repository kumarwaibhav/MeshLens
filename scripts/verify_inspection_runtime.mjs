/** Actual portable input/scorer equivalence with full Python Float64 maps. */
import { readFileSync } from 'node:fs';
import { performance } from 'node:perf_hooks';
import { inspectionRgb8 } from '../web/inspection_input.js';
import { createTextureDetector } from '../web/texture_detector.js';
const input = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const detector = createTextureDetector(input.model);
const records = [];
for (const sample of input.samples) {
  const rgba = Uint8Array.from(readFileSync(sample.rgba_file));
  const rgb = inspectionRgb8(rgba, sample.width, sample.height, input.model.image_size);
  const expected = readFileSync(sample.rgb_file);
  if (rgb.length !== expected.length) throw Error('Canonical input lengths differ');
  let rgbError = 0;
  for (let i = 0; i < rgb.length; i++) rgbError += rgb[i] !== expected[i];
  const start = performance.now();
  let actual; let reason;
  try { actual = detector.score(rgb); } catch (error) { reason = error.code || 'runtime-error'; }
  const record = { id: sample.id, scope: sample.scope, rgb_channel_differences: rgbError,
    expected_score: sample.score, expected_reason: sample.reason, elapsed_ms: performance.now() - start };
  if (sample.reason) {
    Object.assign(record, { reason: reason || null, quality_matched: reason === sample.reason,
      decision_changed: Boolean(actual), score_error: null, map_max_error: null });
  } else {
    if (reason || !actual || !Number.isFinite(actual.score)) throw Error(`Scored case failed: ${sample.id}: ${reason}`);
    const map = readFileSync(sample.map_file);
    if (!(actual.anomaly_map instanceof Float32Array) || actual.map_size !== input.model.image_size
        || map.length !== actual.anomaly_map.length * 8) throw Error('Map dimensions differ');
    let maximum = 0;
    for (let i = 0; i < actual.anomaly_map.length; i++) {
      const value = actual.anomaly_map[i], expectedValue = map.readDoubleLE(i * 8);
      if (!Number.isFinite(value) || value < 0 || !Number.isFinite(expectedValue) || expectedValue < 0) throw Error('Invalid map');
      maximum = Math.max(maximum, Math.abs(value - expectedValue));
    }
    Object.assign(record, { score: actual.score, reason: null, quality_matched: true,
      score_error: Math.abs(actual.score - sample.score), map_max_error: maximum,
      decision_changed: (actual.score > input.threshold) !== (sample.score > input.threshold) });
  }
  records.push(record);
}
const max = list => Math.max(0, ...list);
const scored = records.filter(r => r.score_error !== null);
const times = records.map(r => r.elapsed_ms).sort((a, b) => a - b);
const report = { sample_count: records.length, original_cases: records.filter(r => r.scope === 'official').length,
  gallery_cases: records.filter(r => r.scope === 'gallery').length,
  max_rgb_channel_differences: max(records.map(r => r.rgb_channel_differences)),
  max_score_abs_error: max(scored.map(r => r.score_error)), max_map_abs_error: max(scored.map(r => r.map_max_error)),
  decision_changes: records.filter(r => r.decision_changed).length,
  quality_mismatches: records.filter(r => !r.quality_matched).length, node_version: process.version,
  median_runtime_ms: times.length % 2 ? times[(times.length - 1) / 2] : (times[times.length / 2 - 1] + times[times.length / 2]) / 2,
  acceptance: { rgb_channel_differences: 0, score_absolute_tolerance: 0, map_absolute_tolerance: 2e-5 }, records };
report.passed = report.max_rgb_channel_differences === 0 && report.max_score_abs_error === 0
  && report.max_map_abs_error <= 2e-5 && report.decision_changes === 0 && report.quality_mismatches === 0;
report.status = report.passed ? 'passed' : 'failed';
process.stdout.write(JSON.stringify(report) + '\n');
if (!report.passed) process.exitCode = 1;
