# Third-party notices

## MVTec AD grid data

Images and masks are from MVTec AD, copyright MVTec Software GmbH and the original authors.

- Official source: https://www.mvtec.com/research-teaching/datasets/mvtec-ad
- License: Creative Commons Attribution-NonCommercial-ShareAlike 4.0
- Terms: https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode

Raw acquisition and bundled samples retain these terms. The complete data package preserves
the source `license.txt` and `readme.txt`. MIT licensing for original source code does not
replace the data terms or establish commercial rights for dataset-derived artifacts.

The acquisition revision, archive SHA256, verification scope, image manifest and mask digests
are retained in `data/provenance.json`, `data/manifest.csv` and `data/mask_checksums.json`.
Matching a pinned mirror hash is not an independent comparison with an official download.

## Libraries

PyTorch, NumPy, SciPy, scikit-learn, Pillow, Matplotlib, ONNX, ONNX Runtime and ONNX Runtime Web
retain their original licenses. Python/npm locks identify tested releases. The installed
ONNX Runtime Web 1.23.2 npm package omits its license/notice files, so the project retains
unmodified version-matched upstream copies in `third_party/onnxruntime/`. Their source URLs,
byte counts and SHA256 digests are recorded in that directory's `provenance.json`; the static
build bundles them with the browser runtime.

The browser SHA256 fallback additionally uses `@noble/hashes` 2.4.0 under the MIT license.
Its upstream license must accompany the bundled browser modules in the static build.
