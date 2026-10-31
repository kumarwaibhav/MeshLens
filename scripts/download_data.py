#!/usr/bin/env python3
"""Acquire and verify the pinned MVTec AD grid research dataset.

Owner: Kumar Waibhav Akshat <kwa.waibhav@gmail.com>.
Dataset rights remain with MVTec Software GmbH and original authors.
"""

from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path, PureWindowsPath
import random
import shutil
import tarfile
import tempfile
import time
import urllib.request
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
REVISION = "dc1c313de9de1be8e41fe6818dc43caac8601efa"
ARCHIVE_SHA256 = "d94a9a651cbfaee22c94d06cf8fa8204a590c872362de0489eb34f1645328de8"
ARCHIVE_BYTES = 160_763_852
MANIFEST_SHA256 = "178b4090f2486c820f3be2df9580e60be643d7cf7817eb8cd1cb3024a950708f"
MASKS_SHA256 = "ab3b77fd3708004eb5bef8b54d086975fdc0e75d477865ae995306c97ae94411"
URL = (
    f"https://huggingface.co/datasets/XavierZXY/MvT-tar/resolve/{REVISION}/grid.tar.xz"
)
EXPECTED_COUNTS = {
    "train/good": 264,
    "test/good": 21,
    "test/bent": 12,
    "test/broken": 12,
    "test/glue": 11,
    "test/metal_contamination": 11,
    "test/thread": 11,
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_checked(archive: Path, destination: Path) -> None:
    destination = destination.resolve()
    with tarfile.open(archive, "r:xz") as stream:
        members, targets, total = [], set(), 0
        for member in stream:
            total += member.size
            if len(members) >= 650 or member.size < 0 or total > 500_000_000:
                raise ValueError("Archive exceeds the documented grid dataset bounds")
            target = (destination / member.name).resolve()
            if (
                "\\" in member.name
                or PureWindowsPath(member.name).is_absolute()
                or target in targets
                or not target.is_relative_to(destination)
                or not (member.isfile() or member.isdir())
            ):
                raise ValueError(f"Unsafe archive member: {member.name}")
            targets.add(target)
            members.append(member)
        stream.extractall(destination, members=members, filter="data")


def verify_reference_metadata(root: Path) -> None:
    for relative, expected in [
        ("data/manifest.csv", MANIFEST_SHA256),
        ("data/mask_checksums.json", MASKS_SHA256),
    ]:
        path = root / relative
        if path.exists() and file_sha256(path) != expected:
            raise ValueError(
                f"Pinned reference metadata differs: {relative}; restore the tracked file before auditing"
            )


def audit_dataset(root: Path = ROOT, write_metadata: bool = True) -> dict:
    root = Path(root)
    verify_reference_metadata(root)
    raw = root / "data/raw/grid"
    if raw.is_symlink() or any(path.is_symlink() for path in raw.rglob("*")):
        raise ValueError("Dataset symlinks are unsupported")
    actual = {key: len(list((raw / key).glob("*.png"))) for key in EXPECTED_COUNTS}
    if actual != EXPECTED_COUNTS:
        raise ValueError(
            f"Unexpected source counts: {actual}; expected {EXPECTED_COUNTS}. Run --repair to restore raw data."
        )
    normal = sorted((raw / "train/good").glob("*.png"))
    random.Random(42).shuffle(normal)
    roles = {
        path: "fit" if i < 160 else "tune" if i < 212 else "calibration"
        for i, path in enumerate(normal)
    }
    rows, digests = [], set()
    for path in sorted(
        list((raw / "train").glob("*/*.png")) + list((raw / "test").glob("*/*.png"))
    ):
        digest = file_sha256(path)
        if digest in digests:
            raise ValueError(f"Duplicate source image: {path}")
        digests.add(digest)
        with Image.open(path) as image:
            if image.format != "PNG" or image.size != (1024, 1024):
                raise ValueError(f"Unexpected source image: {path}")
            image.verify()
        defect = path.parent.name
        mask = raw / "ground_truth" / defect / f"{path.stem}_mask.png"
        if defect != "good" and not mask.is_file():
            raise ValueError(f"Missing defect annotation: {mask}")
        rows.append(
            {
                "path": path.relative_to(root).as_posix(),
                "split": roles.get(path, "test"),
                "label": int(defect != "good"),
                "defect_type": defect,
                "sha256": digest,
                "mask_path": mask.relative_to(root).as_posix()
                if defect != "good"
                else "",
            }
        )
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    manifest_bytes = stream.getvalue().encode("utf-8")
    if hashlib.sha256(manifest_bytes).hexdigest() != MANIFEST_SHA256:
        raise ValueError(
            "Raw dataset image checksums/paths differ from pinned canonical manifest; use --repair"
        )
    masks = [
        {"path": path.relative_to(root).as_posix(), "sha256": file_sha256(path)}
        for path in sorted((raw / "ground_truth").glob("*/*.png"))
    ]
    mask_bytes = (json.dumps(masks, indent=2) + "\n").encode("utf-8")
    if len(masks) != 57 or hashlib.sha256(mask_bytes).hexdigest() != MASKS_SHA256:
        raise ValueError(
            "Raw dataset mask checksums/paths differ from pinned canonical annotations; use --repair"
        )
    for item in masks:
        with Image.open(root / item["path"]) as mask:
            if mask.format != "PNG" or mask.size != (1024, 1024):
                raise ValueError(f"Invalid source mask: {item['path']}")
            mask.verify()
    provenance = {
        "dataset": "MVTec AD",
        "category": "grid",
        "image_count": len(rows),
        "mask_count": len(masks),
        "official_source": "https://www.mvtec.com/research-teaching/datasets/mvtec-ad",
        "license": "CC-BY-NC-SA-4.0",
        "license_url": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
        "copyright": "MVTec Software GmbH and original authors",
        "mirror_url": URL,
        "mirror_revision": REVISION,
        "archive_sha256": ARCHIVE_SHA256,
        "source_counts": actual,
        "split_counts": {
            role: sum(r["split"] == role for r in rows)
            for role in ["fit", "tune", "calibration", "test"]
        },
        "split_seed": 42,
        "duplicate_image_hashes": 0,
        "manifest_sha256": MANIFEST_SHA256,
        "audit_scope": "Pinned archive/canonical image and mask hashes checked; not independently byte-compared with a separate official download.",
        "selection_policy": "Fit160/tune52/calibration52 normal train images; official test78 excluded from model and threshold selection.",
        "project_owner": "Kumar Waibhav Akshat <kwa.waibhav@gmail.com>",
    }
    provenance_path = root / "data/provenance.json"
    if provenance_path.is_file():
        recorded = json.loads(provenance_path.read_text())
        for key in [
            "archive_sha256",
            "mirror_revision",
            "manifest_sha256",
            "image_count",
            "mask_count",
            "source_counts",
            "split_counts",
            "split_seed",
        ]:
            if recorded.get(key) != provenance[key]:
                raise ValueError(
                    f"Recorded dataset provenance disagrees with pinned source: {key}"
                )
        provenance = recorded
    outputs = [
        (root / "data/manifest.csv", manifest_bytes),
        (root / "data/mask_checksums.json", mask_bytes),
        (provenance_path, (json.dumps(provenance, indent=2) + "\n").encode()),
    ]
    if not write_metadata and any(not path.is_file() for path, _ in outputs):
        raise ValueError(
            "Pinned dataset reference metadata is missing; restore the tracked files"
        )
    if write_metadata:
        (root / "data").mkdir(parents=True, exist_ok=True)
        for path, content in outputs:
            if not path.exists():
                path.write_bytes(content)
    print(json.dumps(provenance, indent=2), flush=True)
    return provenance


def download_archive(archive: Path) -> None:
    if archive.is_file() and file_sha256(archive) == ARCHIVE_SHA256:
        return
    partial = archive.with_suffix(".xz.part")
    for attempt in range(3):
        try:
            request = urllib.request.Request(
                URL, headers={"User-Agent": "MeshLens/1.0 educational-research"}
            )
            print(
                f"Downloading pinned grid archive ({ARCHIVE_BYTES} bytes), attempt {attempt + 1}/3...",
                flush=True,
            )
            with (
                urllib.request.urlopen(request, timeout=60) as response,
                partial.open("wb") as output,
            ):
                transferred = 0
                while chunk := response.read(1024 * 1024):
                    transferred += len(chunk)
                    if transferred > ARCHIVE_BYTES:
                        raise ValueError("Source archive exceeds pinned download size")
                    output.write(chunk)
            if transferred != ARCHIVE_BYTES or file_sha256(partial) != ARCHIVE_SHA256:
                raise ValueError(
                    "Source archive checksum/size mismatch; no extraction performed"
                )
            partial.replace(archive)
            return
        except (OSError, ValueError) as error:
            partial.unlink(missing_ok=True)
            if attempt == 2:
                raise ValueError(
                    f"Pinned archive download failed after3 attempts: {error}"
                ) from error
            time.sleep(attempt + 1)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Read-only audit of all raw images and recorded hashes",
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help="Restore raw images from a staged and verified pinned archive",
    )
    args = parser.parse_args(argv)
    if args.verify_only and args.repair:
        parser.error("--verify-only cannot be combined with --repair")
    raw = ROOT / "data/raw/grid"
    backup = raw.with_name("grid.repair-backup")
    try:
        verify_reference_metadata(ROOT)
        if args.repair and backup.exists():
            if not raw.exists():
                backup.replace(raw)
            else:
                audit_dataset(ROOT, write_metadata=False)
                shutil.rmtree(backup)
        if args.verify_only or (raw.exists() and not args.repair):
            audit_dataset(ROOT, write_metadata=not args.verify_only)
            return
        cache = ROOT / "data/cache"
        cache.mkdir(parents=True, exist_ok=True)
        archive = cache / "grid.tar.xz"
        download_archive(archive)
        raw.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".grid-stage-", dir=raw.parent
        ) as temporary:
            unpacked = Path(temporary)
            extract_checked(archive, unpacked)
            candidates = [path.parent.parent for path in unpacked.rglob("train/good")]
            if len(candidates) != 1:
                raise ValueError("Expected exactly one grid dataset in source archive")
            stage_root = unpacked / "validated"
            staged_raw = stage_root / "data/raw/grid"
            staged_raw.parent.mkdir(parents=True)
            candidates[0].replace(staged_raw)
            audit_dataset(stage_root)
            if raw.exists():
                raw.replace(backup)
            try:
                staged_raw.replace(raw)
                audit_dataset(ROOT)
            except BaseException:
                if raw.exists():
                    shutil.rmtree(raw)
                if backup.exists():
                    backup.replace(raw)
                raise
            if backup.exists():
                shutil.rmtree(backup)
    except (OSError, ValueError, tarfile.TarError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
