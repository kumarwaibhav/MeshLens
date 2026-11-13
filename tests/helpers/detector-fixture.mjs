import { createHash } from 'node:crypto';
/** Synthetic release fixture, not measured benchmark results. */
export function detectorFixture() {
  const model = Buffer.from(JSON.stringify({ image_size: 256, kind: 'normal-lattice-v1', variant: 'joint', tail_fraction: 0.005, fit_scale: 1, score_decimals: 8, threshold: 1.01, preprocessing: 'area-rgb8-v1' }));
  const sha = createHash('sha256').update(model).digest('hex');
  const metadata = {
    schema_version: 1, model_version: 'test-detector-v1', runtime: 'texture-js', image_size: 256, preprocessing: 'area-rgb8-v1', threshold: 1.01, decision: 'strict-greater-than', score_is_probability: false,
    export: { model_file: 'detector-model.json', model_sha256: sha, model_bytes: model.length }, outputs: { score_name: 'score', map_name: 'anomaly_map', map_size: 256 },
    calibration: { count: 52, alpha: 0.05, order_statistic_rank: 51, scores_sha256: 'a'.repeat(64) }, dataset: { manifest_sha256: 'b'.repeat(64), fit: 160, tune: 52, calibration: 52, test: 78 }, input_quality: { min_side: 256, max_aspect_ratio: 1.5 },
  };
  const evaluation = {
    schema_version: 1, model_version: metadata.model_version, model_sha256: sha, threshold: metadata.threshold, test_count: 78, test_normal: 21, test_defect: 57,
    model: { true_positive: 40, false_negative: 17, true_negative: 18, false_positive: 3, recall: 40 / 57, precision: 40 / 43, f1: 0.8, accuracy: 58 / 78, auroc: 0.9, samples: 78, threshold: metadata.threshold },
    coverage: { scored: 78, inconclusive: 0, total: 78, defective_inconclusive: 0, clean_inconclusive: 0 }, qualification: { status: 'benchmark_only', automated_line_inspection_qualified: false },
    protocol: { selection_used_test: false, source_manifest_sha256: metadata.dataset.manifest_sha256, development_manifest_sha256: 'c'.repeat(64) },
  };
  return { metadata, model, evaluation };
}
/** Worker double that really transfers the copied input buffer. */
export function textureWorkerFactory({ score = 1.2, onScore, onInitialize } = {}) {
  const workers = [];
  const createWorker = () => {
    const worker = {
      messages: [], terminated: false, terminate() { this.terminated = true; },
      postMessage(message, transfer) {
        const copied = structuredClone(message, { transfer: transfer || [] }); this.messages.push(copied);
        queueMicrotask(async () => {
          if (this.terminated) return;
          try {
            if (copied.type === 'initialize') {
              if (onInitialize) { await onInitialize(copied, this); return; }
              this.onmessage?.({ data: { type: 'ready', id: copied.id } }); return;
            }
            const result = onScore ? await onScore(copied, this) : { score, anomaly_map: new Float32Array(256 * 256).fill(score / 2), map_size: 256 };
            if (result !== undefined && !this.terminated) this.onmessage?.({ data: { type: 'result', id: copied.id, ...result } });
          } catch (error) { this.onmessage?.({ data: { type: 'error', id: copied.id, code: error.code, message: error.message } }); }
        });
      },
    }; workers.push(worker); return worker;
  }; return { workers, createWorker };
}
