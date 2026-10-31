import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createHash, webcrypto } from 'node:crypto';
import { validateImageBytes, validateMetadata, sha256Hex, verifyAsset } from '../web/validation.js';
const fixtures = JSON.parse(await readFile(new URL('./fixtures/image-containers.json', import.meta.url), 'utf8'));
const bytes = (name) => new Uint8Array(Buffer.from(fixtures[name], 'base64'));
const metadata = JSON.parse(await readFile(new URL('../artifacts/metadata.json', import.meta.url), 'utf8'));
for (const [name, format] of [['png', 'png'], ['pngAlpha', 'png'], ['jpeg', 'jpeg'], ['webp', 'webp']]) {
  test(`real ${name} container dimensions are bounded before native decoding`, () => assert.deepEqual(validateImageBytes(bytes(name)), { format, width: 64, height: 48 }));
}
test('animated PNG and WebP are rejected before bitmap allocation', () => { for (const name of ['pngAnimated', 'webpAnimated']) assert.throws(() => validateImageBytes(bytes(name)), /[Aa]nimat/); });
test('empty unsupported oversized and truncated containers are rejected', () => {
  for (const value of [new Uint8Array(), new Uint8Array([1, 2, 3]), new Uint8Array(12 * 1024 * 1024 + 1), bytes('png').subarray(0, 40), bytes('jpeg').subarray(0, 40), bytes('webp').subarray(0, 40)]) assert.throws(() => validateImageBytes(value));
});
test('PNG dimensions are checked before native decoder allocation', () => {
  for (const [width, height] of [[0, 48], [31, 48], [4097, 48], [4096, 4096]]) { const image = bytes('png'); const view = new DataView(image.buffer); view.setUint32(16, width); view.setUint32(20, height); assert.throws(() => validateImageBytes(image), /32|4096|megapixel/i); }
});
test('forged PNG lengths and appended trailing bytes are rejected', () => {
  const image = bytes('png'); new DataView(image.buffer).setUint32(8, 0xffffffff); assert.throws(() => validateImageBytes(image)); assert.throws(() => validateImageBytes(new Uint8Array([...bytes('png'), 0])));
});
test('forged WebP RIFF length is rejected', () => { const image = bytes('webp'); new DataView(image.buffer).setUint32(4, 0xffffffff, true); assert.throws(() => validateImageBytes(image)); });
test('metadata rejects changed scoring and tensor contracts', () => {
  assert.equal(validateMetadata(metadata), metadata);
  for (const mutation of [(v) => { v.threshold = NaN; }, (v) => { v.threshold = -1; }, (v) => { v.image_size = 64; }, (v) => { v.input_name = 'unexpected'; }, (v) => { v.input_shape = [1, 1, 256, 256]; }, (v) => { v.score_top_fraction = .5; }, (v) => { v.score.smoothing = 3; }, (v) => { v.export.model_sha256 = 'bad'; },
    (v) => { v.input.color = 'BGR'; }, (v) => { v.input.layout = 'NHWC'; }, (v) => { v.input.dtype = 'float64'; }, (v) => { v.input.range = [0, 255]; }, (v) => { v.input.alpha_compositing = 'ignore'; }, (v) => { v.input.max_pixels = 1e12; }, (v) => { v.calibration.strict_greater_than = false; }, (v) => { v.score.pixel_count = 0; }, (v) => { v.model_path = '../other.onnx'; }]) {
    const value = structuredClone(metadata); mutation(value); assert.throws(() => validateMetadata(value));
  }
});
for (const type of ['acTL', 'fcTL', 'fdAT', 'ANIM', 'ANMF']) {
  test(`singleton ${type} animation chunk is rejected before bitmap allocation`, () => {
    let image;
    if (['acTL', 'fcTL', 'fdAT'].includes(type)) {
      const source = bytes('png'); const payload = Buffer.alloc(type === 'acTL' ? 8 : type === 'fcTL' ? 26 : 4); const chunk = Buffer.alloc(payload.length + 12);
      chunk.writeUInt32BE(payload.length); chunk.write(type, 4, 'ascii'); payload.copy(chunk, 8); image = Buffer.concat([source.subarray(0, 33), chunk, source.subarray(33)]);
    } else {
      const chunk = Buffer.alloc(8); chunk.write(type, 0, 'ascii'); image = Buffer.concat([bytes('webp'), chunk]); image.writeUInt32LE(image.length - 8, 4);
    }
    assert.throws(() => validateImageBytes(image), /[Aa]nimat/);
  });
}
test('WebCrypto SHA256 passes the abc known-answer vector', async () => assert.equal(await sha256Hex(new TextEncoder().encode('abc'), { cryptoProvider: webcrypto }), 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'));
test('actual local noble fallback works without WebCrypto', async () => assert.equal(await sha256Hex(new TextEncoder().encode('abc'), { cryptoProvider: null, loadHash: () => import('@noble/hashes/sha2.js') }), 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'));
test('asset verification rejects altered bytes or missing/mismatched digests', async () => {
  const input = bytes('png'); const expected = createHash('sha256').update(input).digest('hex'); assert.deepEqual(await verifyAsset(input, expected), input);
  for (const bad of ['', '0'.repeat(64), expected.toUpperCase()]) await assert.rejects(() => verifyAsset(input, bad));
  const changed = input.slice(); changed[changed.length - 1] ^= 1; await assert.rejects(() => verifyAsset(changed, expected));
});
