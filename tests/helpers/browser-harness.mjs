/** Run actual app.js functions with deterministic DOM/media/runtime doubles.
 * Native decoding, real cameras, layout and WASM are checked separately.
 */
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { File } from 'node:buffer';
import { createHash, webcrypto } from 'node:crypto';
const root = new URL('../../', import.meta.url);
export function deferred() {
  let resolve; let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
class Element {
  constructor(tag = 'div', id = '') {
    Object.assign(this, { tagName: tag.toUpperCase(), id, children: [], listeners: new Map(), attributes: new Map(), dataset: {},
      hidden: false, disabled: false, checked: true, value: '', _text: '', _classes: new Set(), isConnected: true });
    this.parentElement = { classList: { add() {}, remove() {} } };
    this.classList = {
      add: (...names) => names.forEach((name) => this._classes.add(name)),
      remove: (...names) => names.forEach((name) => this._classes.delete(name)),
      contains: (name) => this._classes.has(name),
      toggle: (name, force) => { const active = force ?? !this._classes.has(name); if (active) this._classes.add(name); else this._classes.delete(name); return active; },
    };
  }
  set className(value) { this._classes = new Set(String(value).split(/\s+/).filter(Boolean)); }
  get className() { return [...this._classes].join(' '); }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map((item) => typeof item === 'string' ? item : item.textContent).join(''); }
  set innerHTML(_value) { throw new Error('Unsafe HTML sink in application test'); }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  append(...nodes) { this.children.push(...nodes); }
  appendChild(node) { this.children.push(node); return node; }
  replaceChildren(...nodes) { this._text = ''; this.children = [...nodes]; }
  addEventListener(name, callback, options = {}) { const list = this.listeners.get(name) || []; list.push({ callback, options }); this.listeners.set(name, list); }
  removeEventListener(name, callback) { this.listeners.set(name, (this.listeners.get(name) || []).filter((item) => item.callback !== callback)); }
  async dispatch(name, properties = {}) {
    const event = { target: this, currentTarget: this, preventDefault() {}, ...properties };
    for (const item of [...(this.listeners.get(name) || [])]) { await item.callback(event); if (item.options.once) this.removeEventListener(name, item.callback); }
  }
  querySelectorAll(selector) {
    const descendants = this.children.flatMap((node) => typeof node === 'string' ? [] : [node, ...node.querySelectorAll(selector)]);
    return descendants.filter((node) => selector === node.tagName.toLowerCase() || (selector.startsWith('.') && node.classList.contains(selector.slice(1))));
  }
  click() { this.clicked = true; return this.dispatch('click'); }
  focus() { this.focused = true; }
  remove() { this.removed = true; }
}
export async function browserHarness(options = {}) {
  const html = await readFile(new URL('web/index.html', root), 'utf8'); const nodes = new Map();
  class ImageData { constructor(data, width, height) { Object.assign(this, { data, width, height }); } }
  const drawCalls = [];
  const makeElement = (tag, id = '') => {
    const node = new Element(tag, id);
    if (tag === 'canvas') {
      let source;
      const context = { fillRect() {}, drawImage: (value) => { source = value; drawCalls.push(value); },
        getImageData: (_x, _y, width, height) => {
          const bytes = new Uint8ClampedArray(width * height * 4); const color = source?.color || [0, 0, 0, 255];
          for (let index = 0; index < bytes.length; index += 4) bytes.set(color, index);
          return new ImageData(bytes, width, height);
        }, putImageData(value) { node.lastImageData = value; } };
      node.getContext = () => context;
    }
    return node;
  };
  for (const match of html.matchAll(/<(\w+)[^>]*\bid="([^"]+)"[^>]*>/g)) {
    const node = makeElement(match[1], match[2]); node.hidden = /\shidden(?:\s|>)/.test(match[0]); node.disabled = /\sdisabled(?:\s|>)/.test(match[0]);
    node.dataset.view = /data-view="([^"]+)"/.exec(match[0])?.[1]; node.className = /class="([^"]+)"/.exec(match[0])?.[1] || '';
    node.value = /\bvalue="([^"]+)"/.exec(match[0])?.[1] || ''; nodes.set(node.id, node);
  }
  const byId = (id) => { if (!nodes.has(id)) nodes.set(id, makeElement(id === 'inspection-canvas' ? 'canvas' : 'div', id)); return nodes.get(id); };
  const documentEvents = new Element('document'); const windowEvents = new Element('window');
  const document = { body: makeElement('body'), hidden: false, getElementById: byId, createElement: makeElement, createTextNode: (value) => String(value),
    querySelectorAll: (selector) => [...nodes.values()].filter((node) => selector.startsWith('.') && node.classList.contains(selector.slice(1))),
    addEventListener: documentEvents.addEventListener.bind(documentEvents), removeEventListener: documentEvents.removeEventListener.bind(documentEvents) };
  const timers = new Map(); let nextTimer = 1;
  const logs = []; const fetchCalls = []; const bitmaps = []; const disposals = { input: 0, output: 0, session: 0 };
  const metadataBytes = await readFile(new URL('artifacts/metadata.json', root)); const metadata = JSON.parse(metadataBytes);
  const samplesBytes = await readFile(new URL('artifacts/samples.json', root)); const samples = JSON.parse(samplesBytes);
  const evaluationBytes = await readFile(new URL('reports/metrics.json', root)); const evaluation = JSON.parse(evaluationBytes);
  const model = await readFile(new URL('artifacts/model.onnx', root));
  const entry = (value) => ({ sha256: createHash('sha256').update(value).digest('hex'), bytes: value.length });
  const release = { schema_version: 1, model_version: metadata.model_version,
    assets: { 'metadata.json': entry(metadataBytes), 'samples.json': entry(samplesBytes), 'evaluation.json': entry(evaluationBytes), 'model.onnx': entry(model) }, samples: {} };
  for (const item of samples.samples) release.samples[item.filename] = entry(await readFile(new URL(`artifacts/samples/${item.filename}`, root)));
  let currentSession;
  const makeSession = () => {
    const size = metadata.image_size;
    currentSession = { inputNames: ['image'], outputNames: ['reconstruction'],
      inputMetadata: [{ name: 'image', type: 'float32', isTensor: true, dimensions: [1, 3, size, size], shape: [1, 3, size, size] }],
      outputMetadata: [{ name: 'reconstruction', type: 'float32', isTensor: true, dimensions: [1, 3, size, size], shape: [1, 3, size, size] }],
      async run(feeds) { if (options.run) return options.run(feeds, currentSession); return { reconstruction: { data: Float32Array.from(feeds.image.data), dims: feeds.image.dims, type: 'float32', dispose() { disposals.output += 1; } } }; },
      async release() { disposals.session += 1; } };
    return currentSession;
  };
  const ort = { env: { wasm: {} }, Tensor: class Tensor { constructor(type, data, dims) { Object.assign(this, { type, data, dims }); } dispose() { disposals.input += 1; } },
    InferenceSession: { async create(...args) { return options.createSession ? options.createSession(args, makeSession) : makeSession(); } } };
  const response = (data, status = 200) => {
    const bytes = typeof data === 'object' && !(data instanceof Uint8Array) ? Buffer.from(JSON.stringify(data)) : Buffer.from(data);
    return { ok: status >= 200 && status < 300, status, headers: new Headers(), json: async () => JSON.parse(bytes.toString()), blob: async () => new Blob([bytes]),
      arrayBuffer: async () => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) };
  };
  const defaultFetch = async (url) => {
    const pathname = String(url).split('?')[0];
    if (pathname.endsWith('/release.json')) return response(release);
    if (pathname.endsWith('/metadata.json')) return response(metadataBytes);
    if (pathname.endsWith('/samples.json')) return response(samplesBytes);
    if (pathname.endsWith('/evaluation.json')) return response(evaluationBytes);
    if (pathname.endsWith('/model.onnx')) return response(model);
    const sample = samples.samples.find((item) => pathname.endsWith(item.filename));
    return sample ? response(await readFile(new URL(`artifacts/samples/${sample.filename}`, root))) : response('missing', 404);
  };
  const makeBitmap = (properties = {}) => { const bitmap = { width: 256, height: 256, closed: false, close() { this.closed = true; }, ...properties }; bitmaps.push(bitmap); return bitmap; };
  Object.assign(byId('camera-video'), { readyState: 4, videoWidth: 64, videoHeight: 64, width: 0, height: 0, play: options.play || (async () => {}), pause() {} });
  const context = { document, navigator: { mediaDevices: { getUserMedia: options.getUserMedia || (async () => { throw new Error('No camera configured'); }) } },
    location: { origin: 'https://meshlens.test', protocol: 'https:' }, localStorage: { getItem: options.getItem || (() => options.history ?? null), setItem: options.setItem || (() => {}), removeItem() {} },
    crypto: webcrypto, ImageData, File, Blob, Headers, URL, TextEncoder, TextDecoder, AbortController, Uint8Array, Uint8ClampedArray, Float32Array, ArrayBuffer, DataView, Buffer,
    performance: { now: () => 5 }, console: { error: (...args) => logs.push(args), log: (...args) => logs.push(args), warn: (...args) => logs.push(args) },
    setTimeout: (callback, delay) => { const id = nextTimer++; timers.set(id, { callback, delay }); return id; }, clearTimeout: (id) => timers.delete(id),
    requestAnimationFrame: (callback) => { queueMicrotask(callback); return 1; }, cancelAnimationFrame() {}, createImageBitmap: options.createImageBitmap || (async () => makeBitmap()),
    fetch: async (...args) => { fetchCalls.push(args); return options.fetch ? options.fetch(...args, { response, defaultFetch }) : defaultFetch(...args); }, __loadOrt: async () => ort };
  context.window = { addEventListener: windowEvents.addEventListener.bind(windowEvents), isSecureContext: true };
  let source = await readFile(new URL('web/app.js', root), 'utf8');
  for (const match of [...source.matchAll(/import\s*\{([^}]+)\}\s*from\s*['"](\.[^'"]+)['"];?/g)]) {
    const namespace = await import(new URL(match[2], new URL('web/app.js', root)));
    for (const binding of match[1].split(',').map((value) => value.trim()).filter(Boolean)) { const [exported, local = exported] = binding.split(/\s+as\s+/); context[local] = namespace[exported]; }
    source = source.replace(match[0], '');
  }
  source = source.replace(/await import\(['"]\/vendor\/ort\.wasm\.min\.mjs['"]\)/g, 'await __loadOrt()');
  source = source.replace(/(?:void\s+)?\binitialize\(\);\s*$/, '');
  source += '\n;globalThis.__app = { state, elements, initialize, readHistory, persistHistory, normalizeSamples, renderMetadata, updateControls, setInput, loadFile, loadSample, manualSample, inspect, stopReplay, toggleReplay, stopCamera, toggleCamera, drawView, renderHistory, download };';
  vm.runInNewContext(source, context, { filename: 'web/app.js', timeout: 1000 }); const app = context.__app;
  const ready = ({ size = 32 } = {}) => { Object.assign(app.state, { metadata, evaluation, release, samples: samples.samples.map((item, index) => ({ ...item, index, url: `/assets/samples/${item.filename}` })),
    imageSize: size, threshold: metadata.threshold, topFraction: metadata.top_fraction, session: makeSession(), ort, ready: true }); app.updateControls(); };
  const sampleFile = async (name = 'mesh.png') => new File([await readFile(new URL(`artifacts/samples/${samples.samples[0].filename}`, root))], name, { type: 'image/png' });
  return { app, byId, nodes, context, document, timers, logs, fetchCalls, bitmaps, disposals, ort, metadata, samples, evaluation, model, release, response, defaultFetch, makeBitmap, ready, sampleFile, drawCalls,
    get session() { return currentSession; }, async fireTimer(id = timers.keys().next().value) { const task = timers.get(id); if (!task) return; timers.delete(id); await task.callback(); },
    dispatchDocument: (name, properties) => documentEvents.dispatch(name, properties), dispatchWindow: (name, properties) => windowEvents.dispatch(name, properties) };
}
export function cameraStream() {
  const track = new Element('track'); Object.assign(track, { readyState: 'live', stops: 0 }); track.stop = () => { track.readyState = 'ended'; track.stops += 1; };
  return { track, getTracks: () => [track], getVideoTracks: () => [track], active: true };
}
