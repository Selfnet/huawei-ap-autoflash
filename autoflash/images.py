"""Atomic claim/release of (metadata.json, sysupgrade.bin) image pairs.

Multiple workers pull from the same images_dir. To avoid two workers picking
the same pair, we move the .json file into the worker's tmp dir using
os.rename(); whichever worker's rename succeeds owns the pair. Losers (race
loss = FileNotFoundError on rename) try the next candidate.

On worker failure, restore() moves the pair back to the images dir so a
later run can retry it.
"""

from __future__ import annotations

import os
import random
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ClaimedImage:
    metadata: Path  # path inside the worker's tmpdir
    sysupgrade: Path
    origin_dir: Path  # where to restore on failure

    def restore(self):
        """Move the pair back to the images directory."""
        for f in (self.metadata, self.sysupgrade):
            if f.exists():
                dst = self.origin_dir / f.name
                shutil.move(str(f), str(dst))


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
        meta_dst = tmp_dir / meta_src.name
        try:
            os.rename(meta_src, meta_dst)
        except (FileNotFoundError, OSError):
            # Lost the race for this pair, try the next.
            continue
        # We own the .json; the .bin is ours by convention.
        sys_dst = tmp_dir / sys_src.name
        try:
            os.rename(sys_src, sys_dst)
        except FileNotFoundError:
            # .bin disappeared; put .json back and try next.
            os.rename(meta_dst, meta_src)
            continue
        return ClaimedImage(
            metadata=meta_dst, sysupgrade=sys_dst, origin_dir=images_dir
        )
    raise FileNotFoundError(f"No image pairs available in {images_dir}")
