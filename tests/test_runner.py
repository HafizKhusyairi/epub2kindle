"""Tests for the native pipeline."""
from __future__ import annotations

import io
import struct
from pathlib import Path

import pytest
from PIL import Image

from epub2kindle.errors import ConversionError
from epub2kindle._pipeline import run as run_kcc
from epub2kindle.options import Options


def _write_solid_png(path: Path, size=(400, 600), color=(200, 200, 200)) -> None:
    img = Image.new("RGB", size, color=color)
    img.save(path, format="PNG")


def _populate_image_dir(image_dir: Path, n: int = 2) -> None:
    image_dir.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        _write_solid_png(image_dir / f"{i:04d}.png")


def test_run_kcc_writes_mobi(tmp_path):
    image_dir = tmp_path / "images"
    output_dir = tmp_path / "output"
    _populate_image_dir(image_dir, n=2)

    opts = Options(output_dir=output_dir, title="Test Book", author="Alice")
    result = run_kcc(image_dir, opts)

    assert len(result) == 1
    out = result[0]
    assert out.suffix == ".mobi"
    assert out.exists()
    assert out.stat().st_size > 0


def test_run_kcc_palmdb_signature(tmp_path):
    image_dir = tmp_path / "images"
    output_dir = tmp_path / "output"
    _populate_image_dir(image_dir, n=1)

    opts = Options(output_dir=output_dir, title="T", author="A")
    [out] = run_kcc(image_dir, opts)

    data = out.read_bytes()
    assert data[60:64] == b"BOOK", "PalmDB type should be BOOK"
    assert data[64:68] == b"MOBI", "PalmDB creator should be MOBI"


def test_run_kcc_mobi_version_in_header(tmp_path):
    image_dir = tmp_path / "images"
    output_dir = tmp_path / "output"
    _populate_image_dir(image_dir, n=1)

    opts = Options(output_dir=output_dir, title="T", author="A")
    [out] = run_kcc(image_dir, opts)

    data = out.read_bytes()
    first_rec_offset = struct.unpack(">L", data[78:82])[0]
    # Per dualmetafix: mobi_version is at offset 36 of record 0
    # (rec0 = 16-byte PalmDOC header + MOBI header; field is at offset 20 of MOBI header).
    mobi_version = struct.unpack(">L", data[first_rec_offset + 36:first_rec_offset + 40])[0]
    assert mobi_version == 6, f"expected MOBI6 version=6, got {mobi_version}"


def test_run_kcc_raises_when_no_images(tmp_path):
    image_dir = tmp_path / "empty"
    image_dir.mkdir()
    opts = Options(output_dir=tmp_path / "out", title="T", author="A")
    with pytest.raises(ConversionError, match="No images found"):
        run_kcc(image_dir, opts)


def test_run_kcc_uses_source_epub_stem_for_output(tmp_path):
    image_dir = tmp_path / "images"
    _populate_image_dir(image_dir, n=1)
    fake_epub = tmp_path / "MyBook Vol 1.epub"
    fake_epub.write_bytes(b"not a real epub")

    opts = Options(output_dir=tmp_path, title="T", author="A")
    [out] = run_kcc(image_dir, opts, source_epub=fake_epub)

    assert out.name == "MyBook Vol 1.mobi"
