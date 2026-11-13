"""Reproduce educational assets from the unchanged frozen model and benchmark gallery.

Uses the existing inference dependencies. Never trains, calibrates, or edits model data.
"""
from __future__ import annotations
import hashlib
import io
import json
from pathlib import Path
import zipfile
import numpy as np
import onnxruntime as ort
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def main() -> None:
    metadata = json.loads((ROOT / 'artifacts/metadata.json').read_text())
    samples = json.loads((ROOT / 'artifacts/samples.json').read_text())['samples']
    model = (ROOT / 'artifacts/model.onnx').read_bytes()
    expected_hash = '8b846f0b029c3f6c11b15f47c2ebd10aa059296959bdbbb549e7cf15c7bccfd4'
    if digest(model) != expected_hash:
        raise ValueError('The educational walkthrough requires the audited frozen model.')
    sample = next(item for item in samples if item['filename'] == 'bent-000.png')
    original_bytes = (ROOT / 'artifacts/samples' / sample['filename']).read_bytes()
    if digest(original_bytes) != sample['sha256']:
        raise ValueError('Walkthrough input checksum mismatch.')
    rgb = np.asarray(Image.open(io.BytesIO(original_bytes)).convert('RGB'))
    if rgb.shape != (256, 256, 3):
        raise ValueError('Walkthrough input must be the verified 256x256 derivative.')
    tensor = np.transpose(rgb.astype(np.float32) / np.float32(255), (2, 0, 1))[None].copy()
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(model, sess_options=options, providers=['CPUExecutionProvider'])
    output = session.run(['reconstruction'], {'image': tensor})[0][0]
    # Match browser JS double arithmetic, followed by Float32Array residual storage.
    residual = ((tensor[0].astype(np.float64) - output.astype(np.float64)) ** 2).mean(axis=0).astype(np.float32)
    top_count = int(np.ceil(residual.size * metadata['top_fraction']))
    score = float(np.sort(residual, axis=None)[-top_count:].mean(dtype=np.float64))
    if abs(score - sample['expected_score']) > 3e-8:
        raise ValueError(f'Walkthrough inference no longer agrees with frozen score: {score}')
    scale = max(float(np.sort(residual, axis=None)[int(residual.size * .995)]), 1e-7)
    normalized = np.minimum(1, residual.astype(np.float64) / scale)
    stops = np.array([[24, 63, 65], [48, 115, 116], [94, 164, 130], [210, 190, 109], [239, 128, 69], [229, 64, 45]])
    position = normalized * 5
    lower = np.minimum(4, np.floor(position).astype(int))
    blend = (position - lower)[..., None]
    color = stops[lower] * (1 - blend) + stops[lower + 1] * blend
    mix = (.12 + normalized * .68)[..., None]
    overlay = np.rint(color * mix + rgb * (1 - mix)).clip(0, 255).astype(np.uint8)
    destination = ROOT / 'web/walkthrough'
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'original.png').write_bytes(original_bytes)
    Image.fromarray(np.rint(np.transpose(output, (1, 2, 0)) * 255).clip(0, 255).astype(np.uint8)).save(destination / 'reconstruction.png')
    Image.fromarray(overlay).save(destination / 'residual.png')
    provenance = {'schema_version': 1, 'model_version': metadata['model_version'], 'model_sha256': expected_hash,
                  'source_sample': sample, 'runtime': f'onnxruntime {ort.__version__} CPU', 'observed_score': score,
                  'visualization': 'Actual reconstruction and browser-equivalent relative residual overlay; not probability or validated segmentation.',
                  'license': 'CC BY-NC-SA 4.0; MVTec Software GmbH and original authors',
                  'files': {name: digest((destination / name).read_bytes()) for name in ['original.png', 'reconstruction.png', 'residual.png']}}
    (destination / 'provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    # Reproducing historical AE evidence must preserve the active detector kit.
    kit = ROOT / 'web/downloads/MeshLens-18-Autoencoder-Baseline.zip'
    kit.parent.mkdir(parents=True, exist_ok=True)
    readme = '''# MeshLens — 18 already-measured benchmark examples

These are 256x256 derivatives of the MVTec AD Grid test images used in the app.
They are replay examples, NOT new independent validation data.

1. Open MeshLens and use Upload or drop an image.
2. Choose images/good-000.png: normal; expected Within learned range.
3. Choose images/bent-000.png: known defect; expected Review recommended.
4. Choose images/bent-001.png: known defect; expected Within learned range.
   Step 4 demonstrates a missed defect. A low score does not establish defect-free material.
5. Compare Original, Reconstruction, and Error map; then read the known label
   in manifest.json. Uploading a local file does not automatically know its label.

The manifest provides all labels, source paths, frozen expected scores and SHA256
checksums. Small numeric runtime differences are possible. The fixed limit is
0.02402208368407517; only strictly larger scores recommend review.
The error map is relative to each image, not a probability or a validated boundary.

For genuinely new data, capture similar mesh under controlled focus, lighting,
viewpoint and scale. Label it independently before measuring misses and false alarms.
All images in the complete Grid benchmark already belong to this experiment.

Official dataset: https://www.mvtec.com/research-teaching/datasets/mvtec-ad
Dataset copyright: MVTec Software GmbH and original authors.
License: CC BY-NC-SA 4.0 (noncommercial).
https://creativecommons.org/licenses/by-nc-sa/4.0/
Original data license and readme are included. Dataset terms also apply to derivatives.
Project: https://github.com/kumarwaibhav/MeshLens
'''
    entries = {'README.md': readme.encode(), 'manifest.json': (json.dumps({'model_version': metadata['model_version'], 'threshold': metadata['threshold'], 'scope': 'Already-evaluated Grid test images; 256x256 derivatives; replay only.', 'samples': samples}, indent=2) + '\n').encode(),
               'DATASET-LICENSE.txt': (ROOT / 'data/raw/grid/license.txt').read_bytes(),
               'DATASET-README.txt': (ROOT / 'data/raw/grid/readme.txt').read_bytes()}
    for item in samples:
        data = (ROOT / 'artifacts/samples' / item['filename']).read_bytes()
        if digest(data) != item['sha256']:
            raise ValueError('Starter example checksum mismatch.')
        entries['images/' + item['filename']] = data
    # Deterministic ZIP avoids needless binary churn across reproductions.
    with zipfile.ZipFile(kit, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content in sorted(entries.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, content)
    print(json.dumps({'score': score, 'expected_score': sample['expected_score'], 'kit_bytes': kit.stat().st_size, 'images': len(samples)}))

if __name__ == '__main__':
    main()
