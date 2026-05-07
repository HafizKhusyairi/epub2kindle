from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Iterable

from ._version import __version__
from .errors import (
    ConversionError,
    EncryptedEpubError,
    Epub2KindleError,
    MalformedEpubError,
    OutputDirError,
)
from .options import Options

__all__ = [
    "__version__",
    "Options",
    "convert",
    "convert_batch",
    "Epub2KindleError",
    "ConversionError",
    "EncryptedEpubError",
    "MalformedEpubError",
    "OutputDirError",
]


def convert(epub_path: str | Path, options: Options | None = None) -> list[Path]:
    from . import epub as epub_mod
    from . import _pipeline, preflight

    options = options or Options()
    epub_path = Path(epub_path)

    preflight.check_environment(options)

    extracted = epub_mod.extract(epub_path)
    try:
        opts = options
        if options.title is None and extracted.title:
            opts = replace(opts, title=extracted.title)
        if options.author is None and extracted.authors:
            opts = replace(opts, author=extracted.authors[0])
        return _pipeline.run(extracted.image_dir, opts, source_epub=epub_path)
    finally:
        extracted.cleanup()


def convert_batch(
    epub_paths: Iterable[str | Path],
    options: Options | None = None,
    fail_fast: bool = False,
) -> dict[Path, list[Path] | Exception]:
    from . import preflight

    options = options or Options()
    preflight.check_environment(options)

    results: dict[Path, list[Path] | Exception] = {}
    for raw in epub_paths:
        p = Path(raw)
        try:
            results[p] = convert(p, options)
        except Exception as exc:
            results[p] = exc
            if fail_fast:
                break
    return results
