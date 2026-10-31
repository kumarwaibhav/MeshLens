/** Build a verified, fresh static release without Python dependencies. */
import { cp, mkdir, readFile, writeFile, lstat, readdir, mkdtemp, rename, rm } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { validateMetadata, validateImageBytes } from '../web/validation.js';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const hash = (value) => createHash('sha256').update(value).digest('hex');
const inside = (parent, child) => child !== parent && !path.relative(parent, child).startsWith(`..${path.sep}`) && path.relative(parent, child) !== '..' && !path.isAbsolute(path.relative(parent, child));
async function regular(filename) {
  const info = await lstat(filename);
  if (!info.isFile() || info.isSymbolicLink()) throw new Error(`Expected a regular file: ${path.basename(filename)}`);
  return readFile(filename);
}
async function safeCopyTree(source, destination) {
  const info = await lstat(source);
  if (info.isSymbolicLink()) throw new Error('Symlinks are not permitted in public build inputs.');
  if (info.isDirectory()) {
    await mkdir(destination, { recursive: true });
    for (const name of await readdir(source)) await safeCopyTree(path.join(source, name), path.join(destination, name));
  } else if (info.isFile()) await cp(source, destination);
  else throw new Error('Only regular public assets can be packaged.');
}
function assertDigest(bytes, expected, name) {
  if (!/^[a-f0-9]{64}$/.test(expected ?? '') || hash(bytes) !== expected) throw new Error(`${name} SHA-256 integrity check failed.`);
}
export async function buildWeb({ root = ROOT, destination = path.join(root, 'dist') } = {}) {
  root = path.resolve(root); destination = path.resolve(destination);
  const relative = path.relative(root, destination);
  if (!inside(root, destination) || !/^dist(?:-[A-Za-z0-9_-]+)?$/.test(relative)) throw new Error('The build destination must be a dist or dist-* directory directly inside the project; source directories cannot be replaced.');
  const read = (name) => regular(path.join(root, name));
  const [model, metadataBytes, samplesBytes, evaluationBytes, frozenBytes, calibration, checkpoint, manifest, provenanceBytes, selectionBytes, pdf] = await Promise.all([
    read('artifacts/model.onnx'), read('artifacts/metadata.json'), read('artifacts/samples.json'), read('reports/metrics.json'), read('reports/frozen_configuration.json'), read('reports/calibration_scores.csv'), read('artifacts/checkpoint.pt'), read('data/manifest.csv'), read('data/provenance.json'), read('reports/selection.json'), read('reports/technical_report.pdf'),
  ]);
  const metadata = validateMetadata(JSON.parse(metadataBytes)); const frozen = JSON.parse(frozenBytes);
  const samples = JSON.parse(samplesBytes).samples; const evaluation = JSON.parse(evaluationBytes);
  const provenance = JSON.parse(provenanceBytes); const selection = JSON.parse(selectionBytes);
  assertDigest(model, metadata.export.model_sha256, 'ONNX model'); assertDigest(checkpoint, frozen.checkpoint_sha256, 'Checkpoint');
  assertDigest(calibration, frozen.calibration_score_sha256, 'Calibration scores'); assertDigest(manifest, provenance.manifest_sha256, 'Dataset manifest'); assertDigest(manifest, selection.manifest_sha256, 'Selection manifest');
  if (metadata.threshold !== frozen.threshold || metadata.top_fraction !== frozen.top_fraction || metadata.calibration.count !== frozen.calibration_count
      || metadata.calibration.order_statistic_rank !== frozen.calibration_order_rank || metadata.calibration.alpha !== frozen.calibration_alpha
      || metadata.model_version !== `meshlens-ae-${frozen.checkpoint_sha256.slice(0, 12)}` || metadata.export.model_bytes !== model.length
      || ['latent_channels', 'epochs', 'best_epoch', 'noise_std'].some((key) => metadata.architecture[key] !== frozen.candidate[key])) throw new Error('Metadata differs from the frozen model configuration.');
  for (const [key, value] of Object.entries(metadata.metrics)) if (evaluation.model?.[key] !== value) throw new Error(`Evaluation metric mismatch: ${key}`);
  if (!Array.isArray(samples) || !samples.length) throw new Error('The sample gallery is empty or invalid.');
  const sampleAssets = new Map();
  for (const sample of samples) {
    if (typeof sample.filename !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9_.-]*\.(png|jpe?g|webp)$/i.test(sample.filename) || sample.filename.includes('..') || sampleAssets.has(sample.filename)) throw new Error('Invalid or duplicate sample filename.');
    const bytes = await read(`artifacts/samples/${sample.filename}`); assertDigest(bytes, sample.sha256, `Sample ${sample.filename}`);
    const size = validateImageBytes(bytes);
    if (size.width !== 256 || size.height !== 256) throw new Error('Benchmark samples must use the frozen 256px preprocessing.');
    sampleAssets.set(sample.filename, bytes);
  }
  const runtime = JSON.parse(await read('node_modules/onnxruntime-web/package.json')); const noble = JSON.parse(await read('node_modules/@noble/hashes/package.json'));
  if (runtime.version !== '1.23.2' || noble.version !== '2.4.0') throw new Error('Installed browser dependencies differ from the pinned release. Run npm ci.');
  const stage = await mkdtemp(path.join(root, '.build-stage-')); let backup;
  try {
    await safeCopyTree(path.join(root, 'web'), stage); await mkdir(path.join(stage, 'assets/samples'), { recursive: true });
    const assets = { 'model.onnx': model, 'metadata.json': metadataBytes, 'samples.json': samplesBytes, 'evaluation.json': evaluationBytes };
    const release = { schema_version: 1, model_version: metadata.model_version, assets: {}, samples: {} };
    for (const [name, bytes] of Object.entries(assets)) { await writeFile(path.join(stage, 'assets', name), bytes); release.assets[name] = { sha256: hash(bytes), bytes: bytes.length }; }
    await writeFile(path.join(stage, 'assets/metrics.json'), evaluationBytes); await writeFile(path.join(stage, 'assets/technical_report.pdf'), pdf);
    for (const [name, bytes] of sampleAssets) { await writeFile(path.join(stage, 'assets/samples', name), bytes); release.samples[name] = { sha256: hash(bytes), bytes: bytes.length }; }
    await writeFile(path.join(stage, 'assets/release.json'), `${JSON.stringify(release, null, 2)}\n`);
    await mkdir(path.join(stage, 'vendor/noble'), { recursive: true });
    for (const name of ['ort.wasm.min.mjs', 'ort-wasm-simd-threaded.mjs', 'ort-wasm-simd-threaded.wasm']) await writeFile(path.join(stage, 'vendor', name), await read(`node_modules/onnxruntime-web/dist/${name}`));
    // The npm web package omits license files; retain the unmodified upstream tag's notices.
    for (const name of ['LICENSE', 'ThirdPartyNotices.txt']) await writeFile(path.join(stage, 'vendor', name), await read(`third_party/onnxruntime/${name}`));
    for (const name of await readdir(path.join(root, 'node_modules/@noble/hashes'))) if (name.endsWith('.js') || name === 'LICENSE') await writeFile(path.join(stage, 'vendor/noble', name), await read(`node_modules/@noble/hashes/${name}`));
    for (const name of ['LICENSE', 'THIRD_PARTY_NOTICES.md']) await writeFile(path.join(stage, name), await read(name));
    await writeFile(path.join(stage, 'build-info.json'), `${JSON.stringify({ model_version: metadata.model_version, model_sha256: metadata.export.model_sha256 }, null, 2)}\n`);
    try {
      const existing = await lstat(destination);
      if (!existing.isDirectory() || existing.isSymbolicLink()) throw new Error('Existing build destination is not a real directory.');
      backup = `${stage}-previous`; await rename(destination, backup);
    } catch (error) { if (error.code !== 'ENOENT') throw error; }
    try { await rename(stage, destination); }
    catch (error) { if (backup) { await rename(backup, destination); backup = null; } throw error; }
    if (backup) await rm(backup, { recursive: true, force: true });
    return { destination, model_version: metadata.model_version, samples: sampleAssets.size };
  } finally { await rm(stage, { recursive: true, force: true }); }
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { const result = await buildWeb(); console.log(`Built verified MeshLens static release: ${result.samples} samples in dist/`); }
  catch (error) { console.error(`Build failed: ${error.message}`); process.exitCode = 1; }
}
