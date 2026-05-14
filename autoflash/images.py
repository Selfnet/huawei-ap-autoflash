"""Atomic claim/release of (metadata.json, sysupgrade.bin) image pairs.

Multiple workers pull from the same images_dir. To avoid two workers picking
the same pair we claim atomically by renaming the .json to a hidden marker
*within the same directory* (cross-filesystem rename would fail with EXDEV);
whichever worker's rename succeeds owns the pair. The claimed files are
then moved (shutil.move, cross-fs OK) into the worker's tmp dir.

On worker failure, restore() moves the pair back to the images dir so a
later run can retry it.
"""

from __future__ import annotations

import os
import random
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ClaimedImage:
    metadata: Path  # path inside the worker's tmpdir
    sysupgrade: Path
    origin_dir: Path  # where to restore on failure
    original_name: str  # name of the .json (without dir) for restore

    def restore(self):
        """Move the pair back to the images directory under their original names."""
        meta_dst = self.origin_dir / self.original_name
        sys_dst = self.origin_dir / (Path(self.original_name).stem + ".bin")
        if self.metadata.exists():
            shutil.move(str(self.metadata), str(meta_dst))
        if self.sysupgrade.exists():
            shutil.move(str(self.sysupgrade), str(sys_dst))


def claim(images_dir: Path, tmp_dir: Path) -> ClaimedImage:
    """Atomically claim an image pair from images_dir into tmp_dir.

    Raises FileNotFoundError if no images are available.
    """
    candidates = list(images_dir.glob("*.json"))
    random.shuffle(candidates)
    for meta_src in candidates:
        sys_src = meta_src.with_suffix(".bin")
        if not sys_src.exists():
            continue

        # Same-filesystem atomic rename to mark the .json as claimed by us.
        marker = images_dir / f".claimed-{uuid.uuid4().hex}-{meta_src.name}"
        try:
            os.rename(meta_src, marker)
        except FileNotFoundError:
            continue  # Lost the race for this pair.
        except OSError:
            # Same-fs rename should never fail for non-race reasons here;
            # bubble it up so the worker reports a real error.
            raise

        # We own the pair now. Move to (possibly cross-fs) tmp dir.
        meta_dst = tmp_dir / meta_src.name
        sys_dst = tmp_dir / sys_src.name
        shutil.move(str(marker), str(meta_dst))
        try:
            shutil.move(str(sys_src), str(sys_dst))
        except FileNotFoundError:
            # .bin disappeared between glob and now; put .json back.
            shutil.move(str(meta_dst), str(meta_src))
            continue

        return ClaimedImage(
            metadata=meta_dst,
            sysupgrade=sys_dst,
            origin_dir=images_dir,
            original_name=meta_src.name,
        )

    raise FileNotFoundError(f"No image pairs available in {images_dir}")
