/** Validate bounded still-image containers before asking the browser to decode them. */
export const IMAGE_LIMITS = Object.freeze({ maxBytes: 12 * 1024 * 1024, minSide: 32, maxSide: 4096, maxPixels: 16_000_000 });
const ascii = (bytes, offset, count) => String.fromCharCode(...bytes.subarray(offset, offset + count));
const bytesOf = (value) => value instanceof Uint8Array ? value : new Uint8Array(value);
function dimensions(width, height, limits) {
  if (!Number.isInteger(width) || !Number.isInteger(height) || width < limits.minSide || height < limits.minSide
      || width > limits.maxSide || height > limits.maxSide || width * height > limits.maxPixels) {
    throw new Error('Choose a still image with sides from 32 to 4096 pixels and at most 16 megapixels.');
  }
  return { width, height };
}
export function validateImageBytes(value, options = {}) {
  const bytes = bytesOf(value); const limits = { ...IMAGE_LIMITS, ...options };
  if (!bytes.length || bytes.length > limits.maxBytes) throw new Error('Choose a PNG, JPEG, or WebP still image up to 12 MiB.');
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const invalid = () => { throw new Error('The image is truncated, malformed, or uses an unsupported format.'); };
  const animated = () => { throw new Error('Animated images are unsupported. Choose a still PNG, JPEG, or WebP image.'); };
  if (bytes.length >= 8 && [137, 80, 78, 71, 13, 10, 26, 10].every((n, i) => bytes[i] === n)) {
    let offset = 8; let size; let hasData = false; let ended = false;
    while (offset < bytes.length) {
      if (offset + 12 > bytes.length) invalid();
      const length = view.getUint32(offset); const type = ascii(bytes, offset + 4, 4);
      if (length > bytes.length - offset - 12) invalid();
      if (!size && type !== 'IHDR') invalid();
      if (type === 'IHDR') {
        if (size || length !== 13) invalid();
        size = dimensions(view.getUint32(offset + 8), view.getUint32(offset + 12), limits);
      }
      if (['acTL', 'fcTL', 'fdAT'].includes(type)) animated();
      if (type === 'IDAT' && length > 0) hasData = true;
      offset += length + 12;
      if (type === 'IEND') { if (length !== 0 || offset !== bytes.length) invalid(); ended = true; break; }
    }
    if (!size || !hasData || !ended) invalid();
    return { format: 'png', ...size };
  }
  if (bytes.length >= 4 && bytes[0] === 255 && bytes[1] === 216) {
    if (bytes.at(-2) !== 255 || bytes.at(-1) !== 217) invalid();
    let offset = 2;
    while (offset < bytes.length - 2) {
      if (bytes[offset++] !== 255) invalid();
      while (bytes[offset] === 255) offset += 1;
      const marker = bytes[offset++];
      if (marker === 0 || marker === 0xda || marker === 0xd9) invalid();
      if (marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) continue;
      if (offset + 2 > bytes.length) invalid();
      const length = view.getUint16(offset);
      if (length < 2 || offset + length > bytes.length) invalid();
      if ([0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf].includes(marker)) {
        if (length < 8) invalid();
        return { format: 'jpeg', ...dimensions(view.getUint16(offset + 5), view.getUint16(offset + 3), limits) };
      }
      offset += length;
    }
    invalid();
  }
  if (bytes.length >= 12 && ascii(bytes, 0, 4) === 'RIFF' && ascii(bytes, 8, 4) === 'WEBP') {
    if (view.getUint32(4, true) + 8 !== bytes.length) invalid();
    let offset = 12; let size; let hasImage = false;
    const uint24 = (index) => bytes[index] + bytes[index + 1] * 256 + bytes[index + 2] * 65536;
    while (offset < bytes.length) {
      if (offset + 8 > bytes.length) invalid();
      const type = ascii(bytes, offset, 4); const length = view.getUint32(offset + 4, true); const p = offset + 8;
      if (length > bytes.length - p || p + length + (length % 2) > bytes.length) invalid();
      if (type === 'ANIM' || type === 'ANMF') animated();
      let candidate;
      if (type === 'VP8X') {
        if (length !== 10) invalid();
        if (bytes[p] & 2) animated();
        candidate = dimensions(uint24(p + 4) + 1, uint24(p + 7) + 1, limits);
      } else if (type === 'VP8 ') {
        if (length < 10 || bytes[p + 3] !== 0x9d || bytes[p + 4] !== 0x01 || bytes[p + 5] !== 0x2a) invalid();
        candidate = dimensions(view.getUint16(p + 6, true) & 0x3fff, view.getUint16(p + 8, true) & 0x3fff, limits); hasImage = true;
      } else if (type === 'VP8L') {
        if (length < 5 || bytes[p] !== 0x2f) invalid();
        const packed = view.getUint32(p + 1, true);
        candidate = dimensions((packed & 0x3fff) + 1, ((packed >>> 14) & 0x3fff) + 1, limits); hasImage = true;
      }
      if (candidate) { if (size && (size.width !== candidate.width || size.height !== candidate.height)) invalid(); size = candidate; }
      offset = p + length + (length % 2);
    }
    if (!size || !hasImage) invalid();
    return { format: 'webp', ...size };
  }
  invalid();
}

export function validateMetadata(metadata) {
  const shape = metadata?.input_shape;
  const fractions = [metadata?.score?.top_fraction, metadata?.score_top_fraction, metadata?.top_fraction].filter((v) => v !== undefined);
  if (!metadata || metadata.schema_version !== 1 || metadata.image_size !== 256 || metadata.input_name !== 'image' || metadata.output_name !== 'reconstruction'
      || JSON.stringify(shape) !== '[1,3,256,256]' || !Number.isFinite(metadata.threshold) || metadata.threshold < 0 || metadata.threshold > 1
      || !fractions.length || fractions.some((f) => !Number.isFinite(f) || f <= 0 || f > 1 || f !== fractions[0])
      || ![null, undefined, 'none'].includes(metadata.score?.smoothing) || typeof metadata.model_version !== 'string' || !metadata.model_version
      || !/^[a-f0-9]{64}$/.test(metadata.export?.model_sha256 ?? '')
      || !Number.isSafeInteger(metadata.export?.model_bytes) || metadata.export.model_bytes < 1 || metadata.export.model_bytes > 2_000_000
      || metadata.model_path !== 'model.onnx' || metadata.calibration?.strict_greater_than !== true || metadata.score?.is_probability !== false
      || metadata.score?.pixel_count !== Math.ceil(256 * 256 * fractions[0])
      || metadata.input?.color !== 'RGB' || metadata.input?.layout !== 'NCHW' || metadata.input?.dtype !== 'float32'
      || JSON.stringify(metadata.input?.range) !== '[0,1]' || metadata.input?.alpha_compositing !== 'opaque white before resize'
      || metadata.input?.min_side !== IMAGE_LIMITS.minSide || metadata.input?.max_side !== IMAGE_LIMITS.maxSide
      || metadata.input?.max_pixels !== IMAGE_LIMITS.maxPixels || metadata.input?.max_file_bytes !== IMAGE_LIMITS.maxBytes
      || JSON.stringify(metadata.input?.supported_upload_formats) !== '["PNG","JPEG","WEBP"]') {
    throw new Error('The model metadata does not match the supported numerical contract.');
  }
  return metadata;
}
export async function sha256Hex(value, { cryptoProvider = globalThis.crypto, loadHash = () => import('./vendor/noble/sha2.js') } = {}) {
  const bytes = bytesOf(value);
  const digest = cryptoProvider?.subtle ? new Uint8Array(await cryptoProvider.subtle.digest('SHA-256', bytes)) : (await loadHash()).sha256(bytes);
  return Array.from(digest, (n) => n.toString(16).padStart(2, '0')).join('');
}
export async function verifyAsset(value, expectedSha) {
  if (!/^[a-f0-9]{64}$/.test(expectedSha ?? '') || await sha256Hex(value) !== expectedSha) throw new Error('An application asset failed its SHA-256 integrity check. Reload or retry the model load.');
  return bytesOf(value);
}
