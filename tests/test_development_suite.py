import csv
import hashlib
import json

import numpy as np
import pytest

from scripts.make_development_suite import DEFECTS, make_suite, simulate_defect


@pytest.mark.parametrize("defect_type", DEFECTS)
def test_development_defects_keep_source_and_are_repeatable(defect_type):
    y, x = np.mgrid[:512, :512]
    wires = ((x + y // 4) % 31 < 6) | ((x - y // 2) % 37 < 6)
    source = np.where(wires, 64, 181).astype(np.uint8)
    unchanged = source.copy()

    result = simulate_defect(source, defect_type, 892)

    assert np.array_equal(source, unchanged)
    assert result.shape == source.shape and result.dtype == source.dtype
    assert 0 < np.count_nonzero(result != source) < source.size * 0.1
    assert np.array_equal(result, simulate_defect(source, defect_type, 892))


def test_corrupt_source_leaves_no_partial_development_suite(tmp_path):
    root = tmp_path / "repository"
    data = root / "data"
    data.mkdir(parents=True)
    manifest = data / "manifest.csv"
    with manifest.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("path", "split", "label", "defect_type", "sha256", "mask_path"))
        for i in range(52):
            expected = hashlib.sha256(str(i).encode("ascii")).hexdigest()
            writer.writerow((f"data/raw/grid/train/good/{i:03}.png", "tune", 0, "good", expected, ""))
    (data / "provenance.json").write_text(json.dumps({
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "split_counts": {"tune": 52},
    }), encoding="utf-8")
    corrupted = root / "data/raw/grid/train/good/000.png"
    corrupted.parent.mkdir(parents=True)
    corrupted.write_bytes(b"changed source")
    output = tmp_path / "development"

    with pytest.raises(ValueError, match="Tuning image checksum mismatch"):
        make_suite(root, output)

    assert not output.exists()
    assert not list(tmp_path.glob(".development-*"))
