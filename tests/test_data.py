"""Dataset integrity and extraction security, including source-only checkouts."""
from collections import Counter
import csv
import hashlib
import io
import json
from pathlib import Path
import tarfile

import pytest

from scripts.download_data import extract_checked, file_sha256
from meshlens.core import read_manifest

FIELDS = ['path', 'split', 'label', 'defect_type', 'sha256', 'mask_path']


def write_manifest(root: Path, rows: list[dict]) -> None:
    (root / 'data').mkdir(parents=True, exist_ok=True)
    with (root / 'data/manifest.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def row(index=0, split='fit', label=0):
    role = 'train/good' if split != 'test' else ('test/broken' if label else 'test/good')
    return {'path': f'data/raw/grid/{role}/{index:03}.png', 'split': split,
            'label': label, 'defect_type': 'broken' if label else 'good',
            'sha256': hashlib.sha256(f'image-{index}'.encode()).hexdigest(),
            'mask_path': f'data/raw/grid/ground_truth/broken/{index:03}_mask.png' if label else ''}


def make_archive(path: Path, name: str, kind=tarfile.REGTYPE, size=5):
    with tarfile.open(path, 'w:xz') as stream:
        info = tarfile.TarInfo(name)
        info.type = kind
        if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
            info.linkname = '../../outside.txt'
        if kind == tarfile.REGTYPE:
            info.size = size
            stream.addfile(info, io.BytesIO(b'x' * size))
        else:
            stream.addfile(info)


def test_safe_regular_archive_and_exact_file_hash(tmp_path):
    archive = tmp_path / 'safe.tar.xz'
    make_archive(archive, 'grid/train/good/000.png')
    output = tmp_path / 'unpacked'
    output.mkdir()
    extract_checked(archive, output)
    file = output / 'grid/train/good/000.png'
    assert file.read_bytes() == b'xxxxx'
    assert file_sha256(file) == hashlib.sha256(b'xxxxx').hexdigest()


@pytest.mark.parametrize('name,kind', [
    ('../../outside.txt', tarfile.REGTYPE),
    ('/tmp/meshlens-untrusted.txt', tarfile.REGTYPE),
    ('grid/link', tarfile.SYMTYPE),
    ('grid/hardlink', tarfile.LNKTYPE),
    ('grid/pipe', tarfile.FIFOTYPE),
])
def test_untrusted_archive_members_are_rejected_before_extraction(tmp_path, name, kind):
    archive = tmp_path / 'unsafe.tar.xz'
    make_archive(archive, name, kind)
    output = tmp_path / 'unpacked'
    output.mkdir()
    with pytest.raises(ValueError, match='Unsafe'):
        extract_checked(archive, output)
    assert list(output.rglob('*')) == []
    assert not (tmp_path.parent / 'outside.txt').exists()


def test_extraction_rejects_member_count_bomb(tmp_path):
    archive = tmp_path / 'many.tar.xz'
    with tarfile.open(archive, 'w:xz') as stream:
        for index in range(651):
            item = tarfile.TarInfo(f'grid/dir-{index}')
            item.type = tarfile.DIRTYPE
            stream.addfile(item)
    output = tmp_path / 'unpacked'
    output.mkdir()
    with pytest.raises(ValueError, match='bounds'):
        extract_checked(archive, output)
    assert list(output.iterdir()) == []


def test_manifest_can_be_validated_without_raw_images(tmp_path):
    rows = [row(0, 'fit'), row(1, 'tune'), row(2, 'calibration'), row(3, 'test', 1)]
    write_manifest(tmp_path, rows)
    result = read_manifest(tmp_path)
    assert len(result) == 4
    assert all(not (tmp_path / item['path']).exists() for item in result)
    assert {item['split'] for item in result} == {'fit', 'tune', 'calibration', 'test'}


@pytest.mark.parametrize('split', ['fit', 'tune', 'calibration'])
def test_anomalies_cannot_enter_normal_development_splits(tmp_path, split):
    write_manifest(tmp_path, [row(0, split, 1)])
    with pytest.raises(ValueError):
        read_manifest(tmp_path)


@pytest.mark.parametrize('path', ['/etc/passwd', '../outside.png', 'data/../../outside.png',
                                  r'C:\Users\someone\private.png', r'..\outside.png'])
def test_manifest_rejects_file_path_escape(tmp_path, path):
    item = row()
    item['path'] = path
    write_manifest(tmp_path, [item])
    with pytest.raises(ValueError):
        read_manifest(tmp_path)


def test_manifest_rejects_same_image_bytes_across_splits(tmp_path):
    rows = [row(0, 'fit'), row(1, 'calibration')]
    rows[1]['sha256'] = rows[0]['sha256']
    write_manifest(tmp_path, rows)
    with pytest.raises(ValueError):
        read_manifest(tmp_path)


@pytest.mark.parametrize('field,value', [('split', 'unknown'), ('label', 'not-a-label'), ('sha256', 'invalid')])
def test_manifest_rejects_invalid_schema_values(tmp_path, field, value):
    item = row()
    item[field] = value
    write_manifest(tmp_path, [item])
    with pytest.raises(ValueError):
        read_manifest(tmp_path)


def test_committed_manifest_preserves_normal_only_splits_and_untouched_test(project_root):
    rows = read_manifest(project_root)
    assert Counter(item['split'] for item in rows) == {'fit': 160, 'tune': 52, 'calibration': 52, 'test': 78}
    assert len({item['sha256'] for item in rows}) == len(rows) == 342
    for item in rows:
        if item['split'] != 'test':
            assert int(item['label']) == 0
            assert '/train/good/' in item['path']
        else:
            assert '/test/' in item['path']
    test_rows = [item for item in rows if item['split'] == 'test']
    assert Counter(int(item['label']) for item in test_rows) == {0: 21, 1: 57}
    provenance = json.loads((project_root / 'data/provenance.json').read_text())
    assert provenance['manifest_sha256'] == file_sha256(project_root / 'data/manifest.csv')
    assert provenance['split_seed'] == 42


def test_available_raw_dataset_matches_all_committed_hashes(project_root):
    rows = read_manifest(project_root)
    present = [(project_root / item['path']).is_file() for item in rows]
    if not (project_root / 'data/raw').exists():
        pytest.skip('Full raw dataset intentionally excluded; run scripts/download_data.py for the complete audit.')
    assert all(present), 'Partial raw dataset: restore all 342 pinned images before the full integrity audit.'
    for item in rows:
        assert file_sha256(project_root / item['path']) == item['sha256'], item['path']
    masks = json.loads((project_root / 'data/mask_checksums.json').read_text())
    assert len(masks) == 57
    expected_masks = {item['mask_path'] for item in rows if item['label'] == 1}
    assert len(expected_masks) == 57
    assert {item['path'] for item in masks} == expected_masks
    for item in masks:
        assert file_sha256(project_root / item['path']) == item['sha256'], item['path']
