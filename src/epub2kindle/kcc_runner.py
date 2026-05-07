from __future__ import annotations

from pathlib import Path

from . import _pipeline
from .options import Options


def run_kcc(
    image_dir: Path, options: Options, source_epub: Path | None = None
) -> list[Path]:
    """Convert a folder of ordered images into a Kindle AZW3 file.

    Name retained for backwards-compat with existing callers/tests; this no
    longer invokes KCC — it runs the native pipeline.
    """
    return _pipeline.run(image_dir, options, source_epub=source_epub)
