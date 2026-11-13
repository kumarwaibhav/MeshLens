/** Verify actual browser scorer results against canonical Python fixtures. */
import {readFileSync} from 'node:fs';
import {performance} from 'node:perf_hooks';
import {createTextureDetector} from '../web/texture_detector.js';
const inputs = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const detector = createTextureDetector(inputs.model);
const samples = [];
const acceptance = {score_absolute_tolerance: 0, map_absolute_tolerance: 2e-5, periodicity_absolute_tolerance: 1e-10};
for (const sample of inputs.samples) {
  const bytes = Uint8Array.from(readFileSync(sample.input_file));
  const start = performance.now(); const actual = detector.score(bytes); const elapsed = performance.now() - start;
  const buffer = readFileSync(sample.map_file);
  if (buffer.length !== actual.anomaly_map.length * 4 || actual.map_size !== inputs.model.image_size) throw new Error(`Unexpected map dimensions for ${sample.id}`);
  let maxMapError = 0;
  for (let i = 0; i < actual.anomaly_map.length; i += 1) maxMapError = Math.max(maxMapError, Math.abs(actual.anomaly_map[i] - buffer.readFloatLE(i * 4)));
  samples.push({id: sample.id, scope: sample.scope, score: actual.score, expected_score: sample.expected_score,
    score_error: Math.abs(actual.score - sample.expected_score), periodicity_error: Math.abs(actual.periodicity - sample.expected_periodicity),
    map_max_error: maxMapError, repeat_count: actual.repeat_count, repeat_count_error: actual.repeat_count - sample.expected_repeat_count,
    decision_changed: (actual.score > inputs.model.threshold) !== (sample.expected_score > inputs.model.threshold), elapsed_ms: elapsed});
}
const durations = samples.map(r => r.elapsed_ms).sort((a, b) => a - b);
const report = {sample_count: samples.length, calibration_count: samples.filter(r => r.scope === 'calibration').length,
  development_count: samples.filter(r => r.scope === 'development').length,
  max_score_error: Math.max(...samples.map(r => r.score_error)), max_map_error: Math.max(...samples.map(r => r.map_max_error)),
  max_periodicity_error: Math.max(...samples.map(r => r.periodicity_error)), decision_changes: samples.filter(r => r.decision_changed).length,
  repeat_count_changes: samples.filter(r => r.repeat_count_error !== 0).length,
  median_runtime_ms: (durations[31] + durations[32]) / 2, mean_runtime_ms: durations.reduce((a, b) => a + b, 0) / durations.length,
  min_runtime_ms: durations[0], max_runtime_ms: durations.at(-1), node_version: process.version, acceptance, samples};
report.passed = report.max_score_error === 0 && report.max_map_error <= acceptance.map_absolute_tolerance
  && report.max_periodicity_error <= acceptance.periodicity_absolute_tolerance && report.decision_changes === 0 && report.repeat_count_changes === 0;
process.stdout.write(`${JSON.stringify(report)}\n`);
