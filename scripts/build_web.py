"""Build MeshLens static app from the frozen local model."""

from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def main():
    dest = ROOT / "dist"
    dest.mkdir(exist_ok=True)
    shutil.copytree(ROOT / "web", dest, dirs_exist_ok=True)
    assets = dest / "assets"
    assets.mkdir(exist_ok=True)
    for name in ["model.onnx", "metadata.json", "samples.json"]:
        shutil.copy2(ROOT / "artifacts" / name, assets / name)
    shutil.copytree(ROOT / "artifacts/samples", assets / "samples", dirs_exist_ok=True)
    vendor = dest / "vendor"
    vendor.mkdir(exist_ok=True)
    source = ROOT / "node_modules/onnxruntime-web/dist"
    for name in [
        "ort.wasm.min.mjs",
        "ort-wasm-simd-threaded.mjs",
        "ort-wasm-simd-threaded.wasm",
    ]:
        shutil.copy2(source / name, vendor / name)
    for name in ["metrics.json", "technical_report.pdf"]:
        p = ROOT / "reports" / name
        if p.is_file():
            shutil.copy2(p, assets / name)
    shutil.copy2(ROOT / "reports/metrics.json", assets / "evaluation.json")
    for name in ["LICENSE", "ThirdPartyNotices.txt"]:
        p = source.parent / name
        if p.exists():
            shutil.copy2(p, vendor / name)
    print("MeshLens static app built in dist/")


if __name__ == "__main__":
    main()
