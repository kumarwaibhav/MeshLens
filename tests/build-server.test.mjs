import test from 'node:test';
import assert from 'node:assert/strict';
import { cp, mkdir, mkdtemp, readFile, readdir, rm, symlink, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildWeb } from '../scripts/build_web.mjs';
import { startServer } from '../scripts/serve_web.mjs';
const source = fileURLToPath(new URL('../', import.meta.url));
const hash = (bytes) => createHash('sha256').update(bytes).digest('hex');

async function fixture(t) {
  const root = await mkdtemp(path.join(os.tmpdir(), 'meshlens-build-test-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  for (const directory of ['web', 'artifacts', 'data', 'reports']) await mkdir(path.join(root, directory), { recursive: true });
  await cp(path.join(source, 'web'), path.join(root, 'web'), { recursive: true });
  await cp(path.join(source, 'artifacts/inspection'), path.join(root, 'artifacts/inspection'), { recursive: true });
  await cp(path.join(source, 'reports/inspection'), path.join(root, 'reports/inspection'), { recursive: true });
  await cp(path.join(source, 'src'), path.join(root, 'src'), { recursive: true });
  await cp(path.join(source, 'artifacts/samples'), path.join(root, 'artifacts/samples'), { recursive: true });
  await cp(path.join(source, 'third_party'), path.join(root, 'third_party'), { recursive: true });
  for (const name of ['artifacts/model.onnx', 'artifacts/checkpoint.pt', 'artifacts/metadata.json', 'artifacts/samples.json', 'data/manifest.csv', 'data/provenance.json', 'reports/metrics.json', 'reports/frozen_configuration.json', 'reports/calibration_scores.csv', 'reports/selection.json', 'reports/technical_report.pdf', 'LICENSE', 'THIRD_PARTY_NOTICES.md']) await cp(path.join(source, name), path.join(root, name));
  const runtime = path.join(root, 'node_modules/onnxruntime-web'); await mkdir(path.join(runtime, 'dist'), { recursive: true });
  await writeFile(path.join(runtime, 'package.json'), JSON.stringify({ version: '1.23.2' }));
  for (const name of ['ort.wasm.min.mjs', 'ort-wasm-simd-threaded.mjs']) await writeFile(path.join(runtime, 'dist', name), '// isolated runtime fixture\n');
  await writeFile(path.join(runtime, 'dist/ort-wasm-simd-threaded.wasm'), new Uint8Array([0, 97, 115, 109, 1, 0, 0, 0]));
  for (const name of ['LICENSE', 'ThirdPartyNotices.txt']) await writeFile(path.join(runtime, name), 'Isolated fixture notice\n');
  await mkdir(path.join(root, 'node_modules/@noble'), { recursive: true });
  await cp(path.join(source, 'node_modules/@noble/hashes'), path.join(root, 'node_modules/@noble/hashes'), { recursive: true });
  return root;
}
async function edit(root, filename, action) { const p = path.join(root, filename); const data = JSON.parse(await readFile(p, 'utf8')); action(data); await writeFile(p, JSON.stringify(data)); }
async function marker(root) { await mkdir(path.join(root, 'dist'), { recursive: true }); await writeFile(path.join(root, 'dist/previous.txt'), 'previous working release'); }
async function preserved(root) { assert.equal(await readFile(path.join(root, 'dist/previous.txt'), 'utf8'), 'previous working release'); assert.deepEqual(await readdir(path.join(root, 'dist')), ['previous.txt']); assert.equal((await readdir(root)).some((name) => name.startsWith('.build-stage-')), false); }

test('build creates an internally consistent release manifest and all 18 sample digests', async (t) => {
  const root = await fixture(t); const result = await buildWeb({ root }); assert.equal(result.samples, 18);
  const release = JSON.parse(await readFile(path.join(root, 'dist/assets/release.json'), 'utf8')); assert.equal(release.schema_version, 2); assert.match(release.detector_version, /^meshlens-inspect-/); for (const required of ['detector.json','detector-model.json','detector-evaluation.json']) assert.ok(release.assets[required]);
  for (const [name, expected] of Object.entries(release.assets)) { const content = await readFile(path.join(root, 'dist/assets', name)); assert.equal(hash(content), expected.sha256); assert.equal(content.length, expected.bytes); }
  assert.equal(Object.keys(release.samples).length, 18);
  for (const [name, expected] of Object.entries(release.samples)) { const content = await readFile(path.join(root, 'dist/assets/samples', name)); assert.equal(hash(content), expected.sha256); assert.equal(content.length, expected.bytes); }
});
test('successful replacement removes stale assets without changing source inputs', async (t) => {
  const root = await fixture(t); const before = await readFile(path.join(root, 'data/manifest.csv')); await buildWeb({ root }); await writeFile(path.join(root, 'dist/assets/stale.png'), 'stale'); await buildWeb({ root });
  await assert.rejects(() => readFile(path.join(root, 'dist/assets/stale.png')), { code: 'ENOENT' }); assert.deepEqual(await readFile(path.join(root, 'data/manifest.csv')), before);
});
for (const input of ['artifacts/model.onnx', 'artifacts/checkpoint.pt', 'reports/calibration_scores.csv', 'data/manifest.csv', 'artifacts/samples/good-000.png']) {
  test(`tampered ${input} cannot replace the previous build`, async (t) => { const root = await fixture(t); await marker(root); await writeFile(path.join(root, input), 'tampered bytes'); await assert.rejects(() => buildWeb({ root }), /SHA|integrity/i); await preserved(root); });
}
test('mismatched evaluation metrics or frozen thresholds cannot be packaged', async (t) => {
  for (const kind of ['metrics', 'threshold']) {
    const root = await fixture(t); await marker(root);
    if (kind === 'metrics') await edit(root, 'reports/metrics.json', (data) => { data.model.recall = 1; }); else await edit(root, 'artifacts/metadata.json', (data) => { data.threshold = .5; });
    await assert.rejects(() => buildWeb({ root }), /mismatch|configuration/i); await preserved(root);
  }
});
test('sample traversal and duplicate gallery entries fail before publication', async (t) => {
  for (const name of ['../outside.png', 'good-000.png']) { const root = await fixture(t); await marker(root); await edit(root, 'artifacts/samples.json', (data) => { data.samples[1].filename = name; }); await assert.rejects(() => buildWeb({ root }), /filename|duplicate/i); await preserved(root); }
});
test('late runtime-copy failure cleans staging and retains the previous build', async (t) => {
  const root = await fixture(t); await marker(root); await rm(path.join(root, 'node_modules/onnxruntime-web/dist/ort-wasm-simd-threaded.wasm')); await assert.rejects(() => buildWeb({ root })); await preserved(root);
});
test('build refuses source directories and paths outside the project', async (t) => {
  const root = await fixture(t); const before = await readFile(path.join(root, 'web/app.js'));
  for (const destination of [root, ...['web', 'artifacts', 'reports', 'docs', 'third_party', 'notebooks', 'arbitrary-output'].map((name) => path.join(root, name)), path.join(root, '../outside')]) await assert.rejects(() => buildWeb({ root, destination }), /destination|source|directory|dist/i);
  assert.deepEqual(await readFile(path.join(root, 'web/app.js')), before);
});
test('symlinked public input cannot leak a private file into a release', async (t) => {
  const root = await fixture(t); await marker(root); await writeFile(path.join(root, 'private.txt'), 'private secret'); await symlink(path.join(root, 'private.txt'), path.join(root, 'web/leak.txt')); await assert.rejects(() => buildWeb({ root }), /[Ss]ymlink/); await preserved(root);
});

// Rebind digests to test semantic validation rather than only stale checksums.
async function rebindInspection(root) {
  const filename = (name) => path.join(root,name);
  const metadata = JSON.parse(await readFile(filename('artifacts/inspection/detector.json')));
  const model = await readFile(filename('artifacts/inspection/detector-model.json'));
  metadata.export.model_sha256=hash(model); metadata.export.model_bytes=model.length;
  metadata.calibration.scores_sha256=hash(await readFile(filename('artifacts/inspection/calibration.json')));
  await writeFile(filename('artifacts/inspection/detector.json'),JSON.stringify(metadata));
  const freeze=JSON.parse(await readFile(filename('reports/inspection/frozen_configuration.json')));
  freeze.calibration=metadata.calibration; freeze.model_sha256=metadata.export.model_sha256;
  for (const name of Object.keys(freeze.files)) { const bytes=await readFile(filename(name)); freeze.files[name]={sha256:hash(bytes),bytes:bytes.length}; }
  await writeFile(filename('reports/inspection/frozen_configuration.json'),JSON.stringify(freeze));
  const freezeHash=hash(await readFile(filename('reports/inspection/frozen_configuration.json')));
  const raw=JSON.parse(await readFile(filename('reports/inspection/independent_evaluation.json')));
  raw.freeze_sha256=freezeHash;
  await writeFile(filename('reports/inspection/independent_evaluation.json'),JSON.stringify(raw));
  const rawHash=hash(await readFile(filename('reports/inspection/independent_evaluation.json')));
  await edit(root,'reports/inspection/evaluation.json',(report) => { report.freeze_sha256=freezeHash; report.raw_report_sha256=rawHash; report.protocol.freeze_sha256=freezeHash; report.protocol.raw_report_sha256=rawHash; });
}
for (const input of ['artifacts/inspection/detector-model.json','artifacts/inspection/calibration.json','reports/inspection/independent_evaluation.json','src/meshlens/texture_detector.py','web/inspection_input.js','artifacts/inspection/samples/glue-008.png','web/downloads/MeshLens-18-Benchmark-Examples.zip']) {
  test(`active detector tampering in ${input} preserves the previous release`, async (t) => {
    const root=await fixture(t); await marker(root); await writeFile(path.join(root,input),'tampered');
    await assert.rejects(() => buildWeb({root})); await preserved(root);
  });
}
test('schema2 never falls back to the historical autoencoder when an inspection artifact is missing', async (t) => {
  const root=await fixture(t); await marker(root); await rm(path.join(root,'artifacts/inspection/detector-model.json'));
  await assert.rejects(() => buildWeb({root}), /ENOENT/); await preserved(root);
});
test('reserved normal calibration membership and rank51 remain enforced after all digests are rebound', async (t) => {
  for (const kind of ['membership','rank']) {
    const root=await fixture(t); await marker(root);
    await edit(root,'artifacts/inspection/calibration.json',(rows) => { if (kind==='membership') rows[0].path=rows[1].path; else { const index=rows.findIndex((row) => row.score===1.01049636); assert.ok(index>=0); rows[index].score=.1; } });
    await rebindInspection(root); await assert.rejects(() => buildWeb({root}), /calibration|rank51/i); await preserved(root);
  }
});
test('raw strict-threshold decisions,78x6coverage and pre-evaluation freeze are independently checked', async (t) => {
  for (const kind of ['equality','duplicate','timestamp']) {
    const root=await fixture(t); await marker(root);
    await edit(root,'reports/inspection/independent_evaluation.json',(raw) => {
      if (kind==='equality') { raw.evaluation.records[0].score=1.01049636; raw.evaluation.records[0].decision='review'; }
      else if (kind==='duplicate') raw.evaluation.records[1]={...raw.evaluation.records[0]};
      else raw.evaluated_at='2000-01-01T00:00:00Z';
    });
    await rebindInspection(root); await assert.rejects(() => buildWeb({root}), /decision|coverage|freeze/i); await preserved(root);
  }
});
test('all six public summaries, Wilson intervals and qualification claims must agree with raw records', async (t) => {
  for (const kind of ['condition','interval','qualification']) {
    const root=await fixture(t); await marker(root);
    await edit(root,'reports/inspection/evaluation.json',(report) => {
      if (kind==='condition') report.conditions.shift_8x4_ref256.model.false_positive=0;
      else if (kind==='interval') report.binomial_wilson_intervals_95.recall.lower=1;
      else report.qualification.automated_line_inspection_qualified=true;
    });
    await assert.rejects(() => buildWeb({root}), /metric|interval|qualification|protocol/i); await preserved(root);
  }
});
test('raw cached aggregate metrics are ignored in favor of recomputation from per-image records', async (t) => {
  const root=await fixture(t);
  await edit(root,'reports/inspection/independent_evaluation.json',(raw) => { raw.evaluation.metrics={invented:{defect_alerts:0}}; });
  await rebindInspection(root); await buildWeb({root});
  const report=JSON.parse(await readFile(path.join(root,'dist/assets/detector-evaluation.json')));
  assert.equal(report.model.true_positive,56); assert.equal(report.model.false_positive,4);
});

function request(server, pathname, method = 'GET') {
  return new Promise((resolve, reject) => { const req = http.request({ hostname: '127.0.0.1', port: server.address().port, path: pathname, method, agent: false }, (response) => { const chunks = []; response.on('data', (chunk) => chunks.push(chunk)); response.on('end', () => resolve({ status: response.statusCode, headers: response.headers, body: Buffer.concat(chunks) })); }); req.on('error', reject); req.end(); });
}
async function served(t) {
  const root = await mkdtemp(path.join(os.tmpdir(), 'meshlens-serve-test-')); const site = path.join(root, 'site'); await mkdir(path.join(site, 'assets'), { recursive: true });
  await writeFile(path.join(site, 'index.html'), '<h1>MeshLens fixture</h1>'); await writeFile(path.join(site, 'app.js'), '// module'); await writeFile(path.join(site, 'assets/data.json'), '{"value":1}'); await writeFile(path.join(site, 'assets/runtime.wasm'), new Uint8Array([0, 97, 115, 109]));
  await writeFile(path.join(root, 'private.txt'), 'private sentinel'); const server = await startServer({ root: site, port: 0, host: '127.0.0.1' });
  t.after(async () => { server.closeAllConnections?.(); await new Promise((resolve) => server.close(resolve)); await rm(root, { recursive: true, force: true }); });
  return { root, site, server };
}
test('server serves GET and HEAD with exact bytes MIME and no-sniff headers', async (t) => {
  const { server } = await served(t);
  for (const [name, type] of [['/', 'text/html'], ['/app.js', 'text/javascript'], ['/assets/data.json', 'application/json'], ['/assets/runtime.wasm', 'application/wasm']]) { const get = await request(server, name); assert.equal(get.status, 200); assert.match(get.headers['content-type'], new RegExp(type)); assert.equal(get.headers['x-content-type-options'], 'nosniff'); const head = await request(server, name, 'HEAD'); assert.equal(head.status, 200); assert.equal(head.body.length, 0); assert.equal(Number(head.headers['content-length']), get.body.length); }
});
test('server returns real 404 and refuses non-read-only methods', async (t) => {
  const { server } = await served(t); assert.equal((await request(server, '/missing.png')).status, 404); const post = await request(server, '/', 'POST'); assert.equal(post.status, 405); assert.equal(post.headers.allow, 'GET, HEAD');
});
test('server blocks encoded traversal dotfiles backslashes NUL and malformed escapes', async (t) => {
  const { server } = await served(t);
  for (const pathname of ['/../private.txt', '/%2e%2e/private.txt', '/%2e%2e%2fprivate.txt', '/..%5cprivate.txt', '/.secret', '/%00', '/%ZZ']) { const response = await request(server, pathname); assert.ok([400, 403].includes(response.status), `${pathname}: ${response.status}`); assert.doesNotMatch(response.body.toString(), /private sentinel/); }
});
test('server rejects symlinks outside the served root and ignores query strings', async (t) => {
  const { root, site, server } = await served(t); await symlink(path.join(root, 'private.txt'), path.join(site, 'leak.txt')); assert.equal((await request(server, '/leak.txt')).status, 403); assert.equal((await request(server, '/assets/data.json?query=ok')).status, 200);
});
test('server startup reports missing roots and occupied ports', async (t) => {
  const { site, server } = await served(t); await assert.rejects(() => startServer({ root: path.join(site, 'missing'), port: 0 })); await assert.rejects(() => startServer({ root: site, port: server.address().port }), { code: 'EADDRINUSE' });
});
