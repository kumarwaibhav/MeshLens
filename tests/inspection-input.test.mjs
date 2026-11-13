import test from 'node:test';
import assert from 'node:assert/strict';
import { inspectionRgb8, INSPECTION_PREPROCESSING } from '../web/inspection_input.js';
function pixels(w, h, value) {
  const data = new Uint8Array(w * h * 4);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) data.set(typeof value === 'function' ? value(x, y) : value, (y * w + x) * 4);
  return data;
}
test('canonical input declares area-rgb8-v1', () => assert.equal(INSPECTION_PREPROCESSING, 'area-rgb8-v1'));
test('constant colors survive fractional and extreme-aspect area resizing', () => {
  for (const [w, h, s] of [[1024, 1024, 384], [57, 103, 31], [4096, 32, 17], [32, 4096, 17], [32, 33, 384]]) {
    const actual = inspectionRgb8(pixels(w, h, [17, 128, 255, 255]), w, h, s);
    for (let i = 0; i < actual.length; i += 3) assert.deepEqual([...actual.subarray(i, i + 3)], [17, 128, 255]);
  }
});
test('independent two by two block oracle rounds half upwards', () => {
  const actual = inspectionRgb8(pixels(64, 64, (x, y) => [x + 2 * y, x % 2, y % 2, 255]), 64, 64, 32);
  for (let y = 0; y < 32; y++) for (let x = 0; x < 32; x++) assert.deepEqual([...actual.subarray((y * 32 + x) * 3, (y * 32 + x) * 3 + 3)], [Math.floor((8 * x + 16 * y + 8) / 4), 1, 1]);
});
test('identity alpha composites white without modifying source pixels', () => {
  const data = pixels(32, 32, (x, y) => [17, 128, 249, (x * 7 + y * 11) % 256]);
  const copy = data.slice(); const actual = inspectionRgb8(data, 32, 32, 32);
  for (let i = 0; i < 1024; i++) for (let c = 0; c < 3; c++) assert.equal(actual[i * 3 + c], Math.round(data[i * 4 + c] * data[i * 4 + 3] / 255 + 255 - data[i * 4 + 3]));
  assert.deepEqual(data, copy);
});
test('integer enlargement repeats source pixels exactly', () => {
  const actual = inspectionRgb8(pixels(32, 32, (x, y) => [x, y, x + y, 255]), 32, 32, 64);
  for (let y = 0; y < 64; y++) for (let x = 0; x < 64; x++) assert.deepEqual([...actual.subarray((y * 64 + x) * 3, (y * 64 + x) * 3 + 3)], [Math.floor(x / 2), Math.floor(y / 2), Math.floor(x / 2) + Math.floor(y / 2)]);
});
test('incomplete buffers and unsupported bounds fail before resizing', () => {
  const data = pixels(32, 32, [0, 0, 0, 255]);
  for (const s of [0, 7, 1025, 8.5, NaN, Infinity, true]) assert.throws(() => inspectionRgb8(data, 32, 32, s));
  for (const [w, h] of [[31, 32], [32, 31], [4097, 32], [4096, 4096], [32.5, 32]]) assert.throws(() => inspectionRgb8(data, w, h, 32));
  assert.throws(() => inspectionRgb8(data.subarray(1), 32, 32, 32));
  assert.throws(() => inspectionRgb8([...data], 32, 32, 32));
});
