from __future__ import annotations

import re
from pathlib import Path

from . import _mobi_writer, _azw3_writer, _image_processor
from ._mobi_writer import BookMetadata
from .errors import ConversionError
from .options import Options, profile_resolution


_FILENAME_INVALID = re.compile(r"[^\w\-. ]")


def _sanitize_filename(stem: str) -> str:
    cleaned = _FILENAME_INVALID.sub("_", stem).strip()
    return cleaned[:120] or "book"


def _resolve_output_path(
    image_dir: Path, options: Options, source_epub: Path | None
) -> Path:
    if options.output_dir is not None:
        out_dir = Path(options.output_dir)
    elif source_epub is not None:
        out_dir = source_epub.parent
    else:
        out_dir = image_dir.parent

    if source_epub is not None:
        stem = source_epub.stem
    elif options.title:
        stem = options.title
    else:
        stem = image_dir.name

    return out_dir / f"{_sanitize_filename(stem)}{options.output_extension()}"


def _build_metadata(options: Options) -> BookMetadata:
    title = options.title or "Untitled"
    authors = [options.author] if options.author else []
    return BookMetadata(title=title, authors=authors)


def run(
    image_dir: Path,
    options: Options,
    source_epub: Path | None = None,
) -> list[Path]:
    output_path = _resolve_output_path(image_dir, options, source_epub)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        images = _image_processor.process_images(image_dir, options)
    except Exception as e:
        raise ConversionError(f"Image processing failed: {e}") from e

    if not images:
        raise ConversionError(f"No images found in {image_dir}")

    metadata = _build_metadata(options)

    try:
        if options.output_format == "AZW3":
            _azw3_writer.write_azw3(
                images, metadata, output_path,
                manga=options.manga,
                target=profile_resolution(options.profile),
            )
        else:
            _mobi_writer.write_mobi(images, metadata, output_path, manga=options.manga)
    except Exception as e:
        raise ConversionError(f"Writing failed: {e}") from e

    return [output_path]
