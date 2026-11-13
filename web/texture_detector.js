/** Browser implementation of the frozen normal-lattice-v1 inspection rule. */
const SIZE = 256;
const PIXELS = SIZE * SIZE;
const RADII = [3, 9];
const VARIANTS = new Set(['local', 'cell', 'relative', 'mixed', 'joint']);
const SCORE_DECIMALS = 8;
const SCORE_QUANTIZER = 10 ** SCORE_DECIMALS;

export class TextureQualityError extends Error {
  constructor(message) {
    super(message);
    this.name = 'TextureQualityError';
    this.code = 'mesh-pattern-unavailable';
  }
}

function integral(image) {
  const stride = SIZE + 1;
  const sums = new Float64Array(stride * stride);
  for (let y = 0; y < SIZE; y += 1) {
    let row = 0;
    for (let x = 0; x < SIZE; x += 1) {
      row += image[y * SIZE + x];
      sums[(y + 1) * stride + x + 1] = sums[y * stride + x + 1] + row;
    }
  }
  return sums;
}

function rectangleSum(sums, y0, y1, x0, x1) {
  const stride = SIZE + 1;
  return sums[y1 * stride + x1] - sums[y0 * stride + x1]
    - sums[y1 * stride + x0] + sums[y0 * stride + x0];
}

function boxMean(image, radius) {
  const sums = integral(image);
  const output = new Float64Array(PIXELS);
  for (let y = 0; y < SIZE; y += 1) {
    const y0 = Math.max(y - radius, 0);
    const y1 = Math.min(y + radius + 1, SIZE);
    for (let x = 0; x < SIZE; x += 1) {
      const x0 = Math.max(x - radius, 0);
      const x1 = Math.min(x + radius + 1, SIZE);
      output[y * SIZE + x] = rectangleSum(sums, y0, y1, x0, x1) / ((y1 - y0) * (x1 - x0));
    }
  }
  return output;
}

function fftLine(real, imaginary, offset, stride, inverse) {
  for (let i = 1, reversed = 0; i < SIZE; i += 1) {
    let bit = SIZE >> 1;
    for (; reversed & bit; bit >>= 1) reversed ^= bit;
    reversed ^= bit;
    if (i < reversed) {
      const a = offset + i * stride;
      const b = offset + reversed * stride;
      [real[a], real[b]] = [real[b], real[a]];
      [imaginary[a], imaginary[b]] = [imaginary[b], imaginary[a]];
    }
  }
  for (let length = 2; length <= SIZE; length *= 2) {
    const half = length / 2;
    const angle = (inverse ? 2 : -2) * Math.PI / length;
    for (let position = 0; position < half; position += 1) {
      const cosine = Math.cos(angle * position);
      const sine = Math.sin(angle * position);
      for (let block = 0; block < SIZE; block += length) {
        const left = offset + (block + position) * stride;
        const right = offset + (block + position + half) * stride;
        const r = real[right] * cosine - imaginary[right] * sine;
        const i = real[right] * sine + imaginary[right] * cosine;
        real[right] = real[left] - r;
        imaginary[right] = imaginary[left] - i;
        real[left] += r;
        imaginary[left] += i;
      }
    }
  }
}

function fft2(real, imaginary, inverse) {
  for (let y = 0; y < SIZE; y += 1) fftLine(real, imaginary, y * SIZE, 1, inverse);
  for (let x = 0; x < SIZE; x += 1) fftLine(real, imaginary, x, SIZE, inverse);
}

function lattice(structure) {
  const correlation = Float64Array.from(structure);
  const imaginary = new Float64Array(PIXELS);
  fft2(correlation, imaginary, false);
  for (let i = 0; i < PIXELS; i += 1) {
    correlation[i] = correlation[i] ** 2 + imaginary[i] ** 2;
    imaginary[i] = 0;
  }
  fft2(correlation, imaginary, true);
  const origin = correlation[0];
  if (origin / PIXELS < 1e-9) return { shifts: [], periodicity: 0 };
  for (let i = 0; i < PIXELS; i += 1) correlation[i] /= origin;
  const at = (y, x) => correlation[((y + SIZE) % SIZE) * SIZE + ((x + SIZE) % SIZE)];
  const radius = Math.round(0.19 * SIZE);
  const minimum = 0.055 * SIZE;
  const neighbors = [[-1, 0], [1, 0], [0, -1], [0, 1], [-1, -1], [-1, 1], [1, -1], [1, 1]];
  const candidates = [];
  for (let y = -radius; y <= radius; y += 1) {
    for (let x = 0; x <= radius; x += 1) {
      const length = Math.hypot(y, x);
      if (length < minimum || length > radius || (x === 0 && y <= 0)) continue;
      const value = at(y, x);
      if (neighbors.some(([dy, dx]) => value < at(y + dy, x + dx))) continue;
      candidates.push({ strength: value, y, x, rank: value - 0.003 * length });
    }
  }
  candidates.sort((a, b) => b.rank - a.rank || a.y - b.y || a.x - b.x);
  if (!candidates.length) return { shifts: [], periodicity: 0 };
  const periodicity = Math.max(0, Math.min(1, Math.max(...candidates.map(p => p.strength))));
  const selected = [];
  for (const candidate of candidates) {
    const { strength, y, x } = candidate;
    if (strength < Math.max(0.1, periodicity * 0.55)) continue;
    if (selected.some(p => Math.abs(y * p.x - x * p.y) < 0.24 * Math.hypot(y, x) * Math.hypot(p.y, p.x))) continue;
    selected.push(candidate);
    if (selected.length === 3) break;
  }
  const interpolate = (before, center, after) => {
    const curvature = before - 2 * center + after;
    return curvature >= -1e-12 ? 0 : Math.max(-0.5, Math.min(0.5, 0.5 * (before - after) / curvature));
  };
  const shifts = [];
  for (const { y, x } of selected) {
    const center = at(y, x);
    const offsetY = interpolate(at(y - 1, x), center, at(y + 1, x));
    const offsetX = interpolate(at(y, x - 1), center, at(y, x + 1));
    shifts.push([y + offsetY, x + offsetX], [-y - offsetY, -x - offsetX]);
  }
  return { shifts, periodicity };
}

function shiftedErrors(structure, detail, shiftY, shiftX) {
  const dy = Math.floor(shiftY);
  const dx = Math.floor(shiftX);
  const ay = shiftY - dy;
  const ax = shiftX - dx;
  const y0 = Math.max(0, -dy);
  const y1 = Math.min(SIZE, SIZE - dy - 1);
  const x0 = Math.max(0, -dx);
  const x1 = Math.min(SIZE, SIZE - dx - 1);
  const errors = new Float64Array(PIXELS);
  const shifted = (image, index) => {
    const top = image[index] * (1 - ax) + image[index + 1] * ax;
    const bottom = image[index + SIZE] * (1 - ax) + image[index + SIZE + 1] * ax;
    return top * (1 - ay) + bottom * ay;
  };
  for (let y = y0; y < y1; y += 1) {
    for (let x = x0; x < x1; x += 1) {
      const index = y * SIZE + x;
      const source = (y + dy) * SIZE + x + dx;
      const ds = structure[index] - shifted(structure, source);
      const dd = detail[index] - shifted(detail, source);
      errors[index] = ds * ds + 0.5 * dd * dd;
    }
  }
  return { sums: integral(errors), y0, y1, x0, x1 };
}

function analyze(rgb8) {
  const gray = new Float64Array(PIXELS);
  for (let i = 0; i < PIXELS; i += 1) {
    gray[i] = (Math.fround(rgb8[3 * i] / 255) + Math.fround(rgb8[3 * i + 1] / 255) + Math.fround(rgb8[3 * i + 2] / 255)) / 3;
  }
  const smooth = boxMean(gray, 1);
  const background = boxMean(smooth, 15);
  const structure = new Float64Array(PIXELS);
  const square = new Float64Array(PIXELS);
  for (let i = 0; i < PIXELS; i += 1) {
    structure[i] = smooth[i] - background[i];
    square[i] = structure[i] ** 2;
  }
  const energy = boxMean(square, 15);
  const detail = new Float64Array(PIXELS);
  for (let i = 0; i < PIXELS; i += 1) {
    const scale = Math.sqrt(energy[i] + 0.002);
    structure[i] /= scale;
    detail[i] = (gray[i] - smooth[i]) / scale;
  }
  const { shifts, periodicity } = lattice(structure);
  const repeatCount = shifts.length / 2;
  if (repeatCount < 2) throw new TextureQualityError('A repeating mesh pattern could not be established. Use a sharp, evenly lit close-up of the trained grid material.');
  const best = RADII.map(() => new Float64Array(PIXELS).fill(Infinity));
  const second = RADII.map(() => new Float64Array(PIXELS).fill(Infinity));
  for (const [shiftY, shiftX] of shifts) {
    const neighbor = RADII.map(() => new Float64Array(PIXELS).fill(Infinity));
    for (let dy = -1; dy <= 1; dy += 1) {
      for (let dx = -1; dx <= 1; dx += 1) {
        const errors = shiftedErrors(structure, detail, shiftY + dy, shiftX + dx);
        for (let r = 0; r < RADII.length; r += 1) {
          const radius = RADII[r];
          const minimumCount = Math.ceil((radius + 1) * (2 * radius + 1) * 0.5);
          for (let y = 0; y < SIZE; y += 1) {
            const y0 = Math.max(0, y - radius);
            const y1 = Math.min(SIZE, y + radius + 1);
            const countY = Math.max(0, Math.min(y + radius + 1, errors.y1) - Math.max(y - radius, errors.y0));
            for (let x = 0; x < SIZE; x += 1) {
              const countX = Math.max(0, Math.min(x + radius + 1, errors.x1) - Math.max(x - radius, errors.x0));
              const count = countY * countX;
              if (count < minimumCount) continue;
              const value = rectangleSum(errors.sums, y0, y1, Math.max(0, x - radius), Math.min(SIZE, x + radius + 1)) / count;
              const index = y * SIZE + x;
              neighbor[r][index] = Math.min(neighbor[r][index], value);
            }
          }
        }
      }
    }
    for (let r = 0; r < RADII.length; r += 1) {
      for (let i = 0; i < PIXELS; i += 1) {
        second[r][i] = Math.min(second[r][i], Math.max(best[r][i], neighbor[r][i]));
        best[r][i] = Math.min(best[r][i], neighbor[r][i]);
      }
    }
  }
  const maps = best.map((closest, r) => {
    const output = new Float64Array(PIXELS);
    for (let i = 0; i < PIXELS; i += 1) {
      const next = Number.isFinite(second[r][i]) ? second[r][i] : closest[i];
      output[i] = Number.isFinite(closest[i]) ? Math.max(0, (closest[i] + next) / 2) : 0;
    }
    return output;
  });
  return { local: maps[0], cell: maps[1], periodicity, repeatCount };
}

function median(values) {
  const sorted = values.slice().sort();
  return (sorted[PIXELS / 2 - 1] + sorted[PIXELS / 2]) / 2;
}

export function createTextureDetector(model) {
  if (!model || model.kind !== 'normal-lattice-v1' || model.image_size !== SIZE
      || !VARIANTS.has(model.variant) || typeof model.fit_scale !== 'number' || !Number.isFinite(model.fit_scale) || model.fit_scale <= 0
      || typeof model.tail_fraction !== 'number' || !Number.isFinite(model.tail_fraction) || model.tail_fraction <= 0 || model.tail_fraction > 1
      || (model.score_decimals ?? SCORE_DECIMALS) !== SCORE_DECIMALS) throw new Error('Unexpected texture detector artifact contract');
  const config = { ...model };
  return {
    score(rgb8) {
      if (!(rgb8 instanceof Uint8Array || rgb8 instanceof Uint8ClampedArray) || rgb8.length !== PIXELS * 3) throw new Error('Expected canonical interleaved 256×256 RGB8 pixels');
      const evidence = analyze(rgb8);
      const localMedian = ['relative', 'mixed', 'joint'].includes(config.variant) ? median(evidence.local) + 0.012 : 1;
      const cellMedian = config.variant === 'joint' ? median(evidence.cell) + 0.012 : 1;
      const map = new Float64Array(PIXELS);
      for (let i = 0; i < PIXELS; i += 1) {
        let value;
        if (config.variant === 'local') value = evidence.local[i];
        else if (config.variant === 'cell') value = evidence.cell[i];
        else if (config.variant === 'relative') value = evidence.local[i] / localMedian;
        else if (config.variant === 'mixed') value = evidence.local[i] / Math.sqrt(localMedian);
        else value = 0.6 * (evidence.local[i] / Math.sqrt(localMedian)) + 0.4 * (evidence.cell[i] / Math.sqrt(cellMedian));
        map[i] = value / config.fit_scale;
        if (!Number.isFinite(map[i]) || map[i] < 0) throw new Error('Texture detector produced an invalid anomaly map');
      }
      const sorted = map.slice().sort();
      const count = Math.max(1, Math.ceil(PIXELS * config.tail_fraction));
      let sum = 0;
      for (let i = PIXELS - count; i < PIXELS; i += 1) sum += sorted[i];
      const score = Math.floor((sum / count) * SCORE_QUANTIZER + 0.5) / SCORE_QUANTIZER;
      return { score, anomaly_map: Float32Array.from(map), map_size: SIZE, periodicity: evidence.periodicity, repeat_count: evidence.repeatCount };
    },
  };
}
