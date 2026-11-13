export const INSPECTION_PREPROCESSING = 'area-rgb8-v1';

function areaWindows(sourceSize, outputSize) {
  return Array.from({ length: outputSize }, (_, index) => {
    const start = index * sourceSize;
    const end = start + sourceSize;
    const first = Math.floor(start / outputSize);
    const stop = Math.ceil(end / outputSize);
    const weights = new Uint16Array(stop - first);
    for (let pixel = first; pixel < stop; pixel += 1) {
      weights[pixel - first] = Math.min(end, (pixel + 1) * outputSize)
        - Math.max(start, pixel * outputSize);
    }
    return { first, weights };
  });
}

function compositeOnWhite(channel, alpha) {
  return Math.floor((channel * alpha + 255 * (255 - alpha) + 127) / 255);
}

/** Resize native decoded RGBA pixels with the same integer area filter as Python. */
export function inspectionRgb8(rgba, width, height, size) {
  if (
    !(rgba instanceof Uint8Array || rgba instanceof Uint8ClampedArray)
    || !Number.isInteger(width) || width < 32 || width > 4096
    || !Number.isInteger(height) || height < 32 || height > 4096
    || width * height > 16_000_000 || rgba.length !== width * height * 4
    || !Number.isInteger(size) || size < 8 || size > 1024
  ) {
    throw new Error('Inspection needs a bounded still RGBA image and a valid output size.');
  }
  const result = new Uint8Array(size * size * 3);
  if (width === size && height === size) {
    for (let pixel = 0; pixel < width * height; pixel += 1) {
      const offset = pixel * 4;
      const alpha = rgba[offset + 3];
      for (let channel = 0; channel < 3; channel += 1) {
        result[pixel * 3 + channel] = compositeOnWhite(rgba[offset + channel], alpha);
      }
    }
    return result;
  }

  const horizontalWindows = areaWindows(width, size);
  const verticalWindows = areaWindows(height, size);
  const rowStride = size * 3;
  const horizontal = new Uint32Array(height * rowStride);
  for (let row = 0; row < height; row += 1) {
    for (let x = 0; x < size; x += 1) {
      const { first, weights } = horizontalWindows[x];
      const target = row * rowStride + x * 3;
      for (let tap = 0; tap < weights.length; tap += 1) {
        const offset = (row * width + first + tap) * 4;
        const alpha = rgba[offset + 3];
        const weight = weights[tap];
        for (let channel = 0; channel < 3; channel += 1) {
          horizontal[target + channel] += compositeOnWhite(rgba[offset + channel], alpha) * weight;
        }
      }
    }
  }

  const area = width * height;
  const rounding = Math.floor(area / 2);
  for (let y = 0; y < size; y += 1) {
    const { first, weights } = verticalWindows[y];
    for (let offset = 0; offset < rowStride; offset += 1) {
      let sum = 0;
      for (let tap = 0; tap < weights.length; tap += 1) {
        sum += horizontal[(first + tap) * rowStride + offset] * weights[tap];
      }
      result[y * rowStride + offset] = Math.floor((sum + rounding) / area);
    }
  }
  return result;
}
