/** Verify the shipped WebAssembly backend and the actual browser score functions. */
import { readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import * as ort from '../node_modules/onnxruntime-web/dist/ort.wasm.min.mjs';
import { computeResidual, scoreResidual, classify } from '../web/inference.js';

const [manifestPath, outputPath] = process.argv.slice(2);
if (!manifestPath || !outputPath) throw new Error('Usage: node scripts/verify_wasm.mjs MANIFEST.json OUTPUT.json');
const manifest = JSON.parse(await readFile(manifestPath, 'utf8'));
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const runtimePackage = JSON.parse(await readFile(path.join(root, 'node_modules/onnxruntime-web/package.json'), 'utf8'));
ort.env.wasm.numThreads = 1;
ort.env.wasm.proxy = false;
ort.env.wasm.wasmPaths = `${pathToFileURL(path.join(root, 'node_modules/onnxruntime-web/dist')).href}/`;
ort.env.logLevel = 'warning';
const session = await ort.InferenceSession.create(new Uint8Array(await readFile(manifest.model)), {
  executionProviders: ['wasm'], graphOptimizationLevel: 'all',
});
const readFloat32 = async (filename) => {
  const buffer = await readFile(filename);
  return new Float32Array(buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength));
};
const records = [];
for (const sample of manifest.samples) {
  const input = await readFloat32(sample.input_file);
  const expectedOutput = await readFloat32(sample.expected_output_file);
  const tensor = new ort.Tensor('float32', input, manifest.shape);
  const started = performance.now();
  const outputs = await session.run({ [session.inputNames[0]]: tensor });
  tensor.dispose?.();
  const output = outputs[session.outputNames[0]];
  const elapsed = performance.now() - started;
  if (output.data.length !== expectedOutput.length) throw new Error('WASM output tensor shape differs from Python ORT.');
  let maxError = 0;
  for (let index = 0; index < output.data.length; index += 1) {
    const error = Math.abs(output.data[index] - expectedOutput[index]);
    if (!Number.isFinite(error)) throw new Error('WASM reconstruction contains nonfinite values.');
    maxError = Math.max(maxError, error);
  }
  const residual = computeResidual(input, output.data, {
    width: manifest.image_size, height: manifest.image_size, channels: 3,
  });
  const score = scoreResidual(residual, manifest.top_fraction);
  records.push({
    id: sample.id, max_reconstruction_abs_error: maxError,
    python_ort_score: sample.expected_score, wasm_score: score,
    score_abs_error: Math.abs(score - sample.expected_score),
    expected_anomaly: classify(sample.expected_score, manifest.threshold),
    wasm_anomaly: classify(score, manifest.threshold), inference_ms: elapsed,
  });
  for (const value of Object.values(outputs)) value.dispose?.();
}
await session.release();
const maxReconstructionError = Math.max(...records.map((item) => item.max_reconstruction_abs_error));
const maxScoreError = Math.max(...records.map((item) => item.score_abs_error));
const changedDecisions = records.filter((item) => item.expected_anomaly !== item.wasm_anomaly).length;
const result = {
  status: maxReconstructionError <= manifest.reconstruction_tolerance && maxScoreError <= manifest.score_tolerance && changedDecisions === 0 ? 'passed' : 'failed',
  backend: 'onnxruntime-web WebAssembly (single thread)', samples: records.length,
  onnxruntime_web_version: runtimePackage.version,
  reconstruction_tolerance: manifest.reconstruction_tolerance, score_tolerance: manifest.score_tolerance,
  max_reconstruction_abs_error: maxReconstructionError, max_score_abs_error: maxScoreError,
  changed_decisions: changedDecisions, records,
};
await writeFile(outputPath, `${JSON.stringify(result, null, 2)}\n`);
console.log(`WASM parity: ${result.status}; ${result.samples} samples; max score difference ${maxScoreError}; changed decisions ${changedDecisions}.`);
if (result.status !== 'passed') process.exitCode = 1;
