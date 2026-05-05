"""Tests for epub.extract()."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from epub2kindle.epub import extract
from epub2kindle.errors import EncryptedEpubError, MalformedEpubError
from tests.conftest import build_epub


def write_epub(tmp_path: Path, data: bytes) -> Path:
    p = tmp_path / "test.epub"
    p.write_bytes(data)
    return p


def test_basic_extraction(tmp_path):
    p = write_epub(tmp_path, build_epub(title="My Book", author="Alice", num_pages=3))
    result = extract(p)
    try:
        assert result.title == "My Book"
        assert result.authors == ["Alice"]
        assert result.language == "en"
        images = sorted(result.image_dir.iterdir())
        assert len(images) == 3
        exts = {f.suffix for f in images}
        assert exts == {".png"}
    finally:
        result.cleanup()


def test_spine_ordering(tmp_path):
    p = write_epub(tmp_path, build_epub(num_pages=4))
    result = extract(p)
    try:
        images = sorted(result.image_dir.iterdir())
        names = [f.name for f in images]
        assert names == [f"{i:04d}.png" for i in range(len(names))]
    finally:
        result.cleanup()


def test_image_subdir(tmp_path):
    p = write_epub(tmp_path, build_epub(num_pages=2, image_subdir="images"))
    result = extract(p)
    try:
        assert len(list(result.image_dir.iterdir())) == 2
    finally:
        result.cleanup()


def test_nested_opf(tmp_path):
    p = write_epub(tmp_path, build_epub(num_pages=2, opf_subdir="OEBPS"))
    result = extract(p)
    try:
        assert len(list(result.image_dir.iterdir())) == 2
    finally:
        result.cleanup()


def test_percent_encoded_hrefs(tmp_path):
    p = write_epub(tmp_path, build_epub(num_pages=2, percent_encode_images=True))
    result = extract(p)
    try:
        assert len(list(result.image_dir.iterdir())) == 2
    finally:
        result.cleanup()


def test_encrypted_epub_raises(tmp_path):
    p = write_epub(
        tmp_path,
        build_epub(include_encryption_xml=True, include_encrypted_data=True),
    )
    with pytest.raises(EncryptedEpubError):
        extract(p)


def test_encryption_xml_without_data_is_ok(tmp_path):
    p = write_epub(
        tmp_path,
        build_epub(include_encryption_xml=True, include_encrypted_data=False),
    )
    result = extract(p)
    result.cleanup()


def test_missing_container_raises(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
    p = tmp_path / "bad.epub"
    p.write_bytes(buf.getvalue())
    with pytest.raises(MalformedEpubError):
        extract(p)


def test_empty_spine_raises(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>""")
        zf.writestr("content.opf", """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Empty</dc:title>
  </metadata>
  <manifest/>
  <spine/>
</package>""")
    p = tmp_path / "empty_spine.epub"
    p.write_bytes(buf.getvalue())
    with pytest.raises(MalformedEpubError):
        extract(p)


def test_not_a_zip_raises(tmp_path):
    p = tmp_path / "not_an_epub.epub"
    p.write_bytes(b"this is not a zip file")
    with pytest.raises(MalformedEpubError):
        extract(p)
