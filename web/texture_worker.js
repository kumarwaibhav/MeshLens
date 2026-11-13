import { createTextureDetector } from './texture_detector.js';
let detector = null;
self.onmessage = ({ data }) => {
  const id = data?.id;
  try {
    if (!Number.isSafeInteger(id) || id < 1) throw new Error('Invalid detector request.');
    if (data.type === 'initialize') {
      if (detector) throw new Error('The detector worker is already initialized.');
      detector = createTextureDetector(data.model); self.postMessage({ type: 'ready', id });
    } else if (data.type === 'score' && detector) {
      const result = detector.score(data.rgb8); self.postMessage({ type: 'result', id, ...result }, [result.anomaly_map.buffer]);
    } else throw new Error('The detector worker is not ready.');
  } catch (error) { self.postMessage({ type: 'error', id, message: String(error.message || 'The detector could not inspect this input.'), code: error.code === 'mesh-pattern-unavailable' ? error.code : 'detector-runtime-unavailable' }); }
};
