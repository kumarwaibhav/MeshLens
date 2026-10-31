/** MeshLens numerical contracts, shared by browser inference and verification. */
function positiveInteger(value, name) {
  if (!Number.isInteger(value) || value <= 0) throw new RangeError(`${name} must be a positive integer.`);
}

export function preprocessRGBA(rgba, width, height) {
  positiveInteger(width, 'width'); positiveInteger(height, 'height');
  const count = width * height;
  if (!rgba || rgba.length !== count * 4) throw new RangeError('RGBA dimensions do not match the image.');
  const output = new Float32Array(count * 3);
  for (let index = 0; index < count; index += 1) {
    for (let channel = 0; channel < 4; channel += 1) {
      const value = rgba[index * 4 + channel];
      if (!Number.isFinite(value) || value < 0 || value > 255) throw new RangeError('RGBA values must be finite bytes.');
    }
    output[index] = rgba[index * 4] / 255;
    output[count + index] = rgba[index * 4 + 1] / 255;
    output[count * 2 + index] = rgba[index * 4 + 2] / 255;
  }
  return output;
}

export function computeResidual(input, reconstruction, { width, height, channels = 3 } = {}) {
  positiveInteger(width, 'width'); positiveInteger(height, 'height'); positiveInteger(channels, 'channels');
  const count = width * height;
  if (!input || !reconstruction || input.length !== count * channels || reconstruction.length !== input.length) {
    throw new RangeError('Reconstruction and input tensor shapes must agree.');
  }
  const result = new Float32Array(count);
  for (let pixel = 0; pixel < count; pixel += 1) {
    let error = 0;
    for (let channel = 0; channel < channels; channel += 1) {
      const original = input[channel * count + pixel]; const rebuilt = reconstruction[channel * count + pixel];
      if (!Number.isFinite(original) || !Number.isFinite(rebuilt)) throw new RangeError('Tensor values must be finite.');
      const difference = original - rebuilt; error += difference * difference;
    }
    result[pixel] = error / channels;
  }
  return result;
}

/** Optional replicated-edge box average; the frozen deployed score uses no smoothing. */
export function boxSmooth(values, width, height, kernel = 1) {
  positiveInteger(width, 'width'); positiveInteger(height, 'height'); positiveInteger(kernel, 'kernel');
  if (kernel % 2 !== 1 || values.length !== width * height) throw new RangeError('Smoothing needs an odd kernel and matching map.');
  if (kernel === 1) return Float32Array.from(values);
  const radius = Math.floor(kernel / 2); const temporary = new Float32Array(values.length); const result = new Float32Array(values.length);
  for (let y = 0; y < height; y += 1) for (let x = 0; x < width; x += 1) {
    let sum = 0;
    for (let offset = -radius; offset <= radius; offset += 1) sum += values[y * width + Math.max(0, Math.min(width - 1, x + offset))];
    temporary[y * width + x] = sum / kernel;
  }
  for (let y = 0; y < height; y += 1) for (let x = 0; x < width; x += 1) {
    let sum = 0;
    for (let offset = -radius; offset <= radius; offset += 1) sum += temporary[Math.max(0, Math.min(height - 1, y + offset)) * width + x];
    result[y * width + x] = sum / kernel;
  }
  return result;
}

export function scoreResidual(values, topFraction = 0.01) {
  if (!values || values.length === 0) throw new RangeError('The residual map cannot be empty.');
  if (!Number.isFinite(topFraction) || topFraction <= 0 || topFraction > 1) throw new RangeError('The score fraction must be in (0, 1].');
  const ordered = Float32Array.from(values);
  for (const value of ordered) if (!Number.isFinite(value) || value < 0) throw new RangeError('Residual values must be finite and nonnegative.');
  ordered.sort(); const count = Math.max(1, Math.ceil(ordered.length * topFraction)); let total = 0;
  for (let index = ordered.length - count; index < ordered.length; index += 1) total += ordered[index];
  return total / count;
}

export function classify(score, threshold) {
  if (!Number.isFinite(score) || !Number.isFinite(threshold) || score < 0 || threshold < 0) throw new RangeError('The score and threshold must be finite and nonnegative.');
  return score > threshold;
}

export function reconstructionRGBA(values, width, height) {
  positiveInteger(width, 'width'); positiveInteger(height, 'height'); const count = width * height;
  if (!values || values.length !== count * 3) throw new RangeError('Expected an RGB NCHW tensor.');
  const rgba = new Uint8ClampedArray(count * 4);
  for (let index = 0; index < count; index += 1) {
    for (let channel = 0; channel < 3; channel += 1) {
      const value = values[channel * count + index];
      if (!Number.isFinite(value)) throw new RangeError('Reconstruction values must be finite.');
      rgba[index * 4 + channel] = Math.max(0, Math.min(1, value)) * 255;
    }
    rgba[index * 4 + 3] = 255;
  }
  return rgba;
}

export function csvEscape(value) {
  let text = String(value ?? '');
  if (/^\s*[=+\-@]/u.test(text)) text = `'${text}`;
  return `"${text.replaceAll('"', '""')}"`;
}
