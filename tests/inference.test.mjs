import test from 'node:test';
import assert from 'node:assert/strict';
import {
  preprocessRGBA, computeResidual, scoreResidual, classify,
  reconstructionRGBA, boxSmooth, csvEscape,
} from '../web/inference.js';

const close = (actual, expected, tolerance = 1e-7) => {
  assert.ok(Math.abs(actual - expected) <= tolerance, `${actual} is not within ${tolerance} of ${expected}`);
};

test('RGBA decoding produces RGB channel-major float32 values and ignores alpha', () => {
  const bytes = new Uint8ClampedArray([255, 0, 128, 0, 17, 255, 0, 255]);
  const copy = bytes.slice();
  const values = preprocessRGBA(bytes, 2, 1);
  assert.ok(values instanceof Float32Array);
  assert.equal(values.length, 6);
  [1, 17 / 255, 0, 1, 128 / 255, 0].forEach((value, i) => close(values[i], value));
  assert.deepEqual(bytes, copy);
});

test('invalid image dimensions and incomplete pixel buffers are rejected', () => {
  assert.throws(() => preprocessRGBA(new Uint8Array(4), 0, 1), RangeError);
  assert.throws(() => preprocessRGBA(new Uint8Array(4), 1.5, 1), RangeError);
  assert.throws(() => preprocessRGBA(new Uint8Array(3), 1, 1), RangeError);
  for (const value of [NaN, Infinity, -1, 256]) {
    assert.throws(() => preprocessRGBA([value, 0, 0, 255], 1, 1), RangeError);
  }
});

test('RGB residual means square error across channels, then averages the largest ceiling tail', () => {
  const input = new Float32Array(12);
  const reconstruction = Float32Array.from([0, .5, 1, .25, 0, .5, 1, .25, 0, .5, 1, .25]);
  const copy = reconstruction.slice();
  const residual = computeResidual(input, reconstruction, { width: 2, height: 2 });
  assert.deepEqual(Array.from(residual), [0, .25, 1, .0625]);
  close(scoreResidual(residual, .5), .625);
  close(scoreResidual(residual, 1), .328125);
  close(scoreResidual(residual, .01), 1);
  assert.deepEqual(reconstruction, copy);
});

test('RGB channels are averaged rather than summed', () => {
  const input = new Float32Array(3);
  const output = Float32Array.from([1, 0, 0]);
  close(computeResidual(input, output, { width: 1, height: 1 })[0], 1 / 3);
});

test('score calculation preserves the input heatmap and uses numeric ordering', () => {
  const map = Float32Array.from([.02, .9, .1, .7, .5]);
  const copy = map.slice();
  close(scoreResidual(map, .21), .8);
  assert.deepEqual(map, copy);
});

test('nonfinite tensors and mismatched model output shapes fail explicitly', () => {
  const valid = new Float32Array(3);
  for (const bad of [NaN, Infinity, -Infinity]) {
    assert.throws(() => computeResidual(valid, Float32Array.from([bad, 0, 0]), { width: 1, height: 1 }), RangeError);
  }
  assert.throws(() => computeResidual(valid, new Float32Array(6), { width: 1, height: 1 }), RangeError);
});

test('invalid score tails and heatmap values cannot produce a decision', () => {
  for (const fraction of [0, -.1, 1.1, NaN, Infinity]) {
    assert.throws(() => scoreResidual(Float32Array.from([.1]), fraction), RangeError);
  }
  for (const map of [[], [NaN], [Infinity], [-.1]]) {
    assert.throws(() => scoreResidual(map), RangeError);
  }
});

test('the frozen threshold uses strict greater-than, including exact ties', () => {
  assert.equal(classify(.25, .25), false);
  assert.equal(classify(.251, .25), true);
  assert.equal(classify(.249, .25), false);
  assert.equal(classify(0, 0), false);
  for (const bad of [NaN, Infinity, -1]) {
    assert.throws(() => classify(bad, .25), RangeError);
    assert.throws(() => classify(.25, bad), RangeError);
  }
});

test('reconstruction display clamps pixel bytes without changing floating point model output', () => {
  const values = Float32Array.from([0, .5, 1]);
  const before = values.slice();
  assert.deepEqual(Array.from(reconstructionRGBA(values, 1, 1)), [0, 128, 255, 255]);
  assert.deepEqual(values, before);
  assert.throws(() => reconstructionRGBA(Float32Array.from([NaN, 0, 0]), 1, 1), RangeError);
});

test('display smoothing has replicated boundaries and leaves a no-op map unaliased', () => {
  const map = Float32Array.from([1, 0, 0]);
  const identity = boxSmooth(map, 3, 1, 1);
  assert.notEqual(identity, map);
  assert.deepEqual(identity, map);
  const smoothed = boxSmooth(map, 3, 1, 3);
  [2 / 3, 1 / 3, 0].forEach((value, i) => close(smoothed[i], value));
  assert.throws(() => boxSmooth(map, 3, 1, 2), RangeError);
});

test('CSV cell escaping preserves delimiters, quotes and line breaks', () => {
  assert.equal(csvEscape('sample,"one"\nnext'), '"sample,""one""\nnext"');
  assert.equal(csvEscape(null), '""');
});

test('CSV exports neutralize spreadsheet formulas in untrusted filenames', () => {
  for (const value of ['=1+1', '+SUM(A1:A2)', '-1+1', '@SUM(A1)', '  =HYPERLINK("x")']) {
    assert.ok(csvEscape(value).startsWith('"\''), value);
  }
});
