from __future__ import annotations

import os
import shutil
from pathlib import Path

from .errors import (
    KCCImportError,
    KindleGenNotFoundError,
    OutputDirError,
    SevenZipNotFoundError,
)
from .options import Options

_kcc_checked = False


def check_environment(options: Options) -> None:
    global _kcc_checked

    if options.output_format == "MOBI" and shutil.which("kindlegen") is None:
        raise KindleGenNotFoundError()

    if shutil.which("7z") is None:
        raise SevenZipNotFoundError()

    if options.output_dir is not None:
        out = Path(options.output_dir)
        if not out.exists():
            try:
                out.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                raise OutputDirError(f"Cannot create output directory {out}: {e}") from e
        if not os.access(out, os.W_OK):
            raise OutputDirError(f"Output directory is not writable: {out}")

    if not _kcc_checked:
        try:
            import kindlecomicconverter.comic2ebook  # noqa: F401
        except ImportError as e:
            raise KCCImportError(e) from e
        _kcc_checked = True


def reset_preflight_cache() -> None:
    global _kcc_checked
    _kcc_checked = False
