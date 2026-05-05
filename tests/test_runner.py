"""Tests for kcc_runner.run_kcc() using a monkeypatched comic2ebook.main."""
from __future__ import annotations

from pathlib import Path

import pytest

from epub2kindle.errors import ConversionError
from epub2kindle.kcc_runner import run_kcc
from epub2kindle.options import Options


def _make_stub_main(output_dir: Path, filenames: list[str]):
    def _stub_main(argv):
        for name in filenames:
            (output_dir / name).write_bytes(b"fake mobi content")
    return _stub_main


def test_run_kcc_returns_new_files(tmp_path, monkeypatch):
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    import epub2kindle.kcc_runner as runner_mod
    monkeypatch.setattr(
        runner_mod,
        "run_kcc",
        lambda image_dir, options: _patched_run(image_dir, options, output_dir),
    )

    opts = Options(output_dir=output_dir, title="T", author="A")

    import kindlecomicconverter.comic2ebook as c2e  # noqa — may not be installed
    pytest.importorskip("kindlecomicconverter")

    import epub2kindle.kcc_runner as runner

    def fake_main(argv):
        (output_dir / "book.mobi").write_bytes(b"fake")

    monkeypatch.setattr("kindlecomicconverter.comic2ebook.main", fake_main)

    result = runner.run_kcc(image_dir, opts)
    assert any(p.name == "book.mobi" for p in result)


def _patched_run(image_dir, options, output_dir):
    pass


def test_run_kcc_deletes_intermediate_epub(tmp_path, monkeypatch):
    pytest.importorskip("kindlecomicconverter")
    import epub2kindle.kcc_runner as runner

    image_dir = tmp_path / "images"
    image_dir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    def fake_main(argv):
        (output_dir / "book.mobi").write_bytes(b"fake mobi")
        (output_dir / "book.epub").write_bytes(b"intermediate epub")

    monkeypatch.setattr("kindlecomicconverter.comic2ebook.main", fake_main)

    opts = Options(output_dir=output_dir, title="T", author="A", output_format="MOBI")
    result = runner.run_kcc(image_dir, opts)

    assert not (output_dir / "book.epub").exists()
    assert any(p.name == "book.mobi" for p in result)


def test_run_kcc_raises_conversion_error_on_bad_exit(tmp_path, monkeypatch):
    pytest.importorskip("kindlecomicconverter")
    import epub2kindle.kcc_runner as runner

    image_dir = tmp_path / "images"
    image_dir.mkdir()

    def fake_main(argv):
        raise SystemExit(1)

    monkeypatch.setattr("kindlecomicconverter.comic2ebook.main", fake_main)

    opts = Options(title="T", author="A")
    with pytest.raises(ConversionError):
        runner.run_kcc(image_dir, opts)


def test_run_kcc_raises_conversion_error_on_exception(tmp_path, monkeypatch):
    pytest.importorskip("kindlecomicconverter")
    import epub2kindle.kcc_runner as runner

    image_dir = tmp_path / "images"
    image_dir.mkdir()

    def fake_main(argv):
        raise RuntimeError("KCC exploded")

    monkeypatch.setattr("kindlecomicconverter.comic2ebook.main", fake_main)

    opts = Options(title="T", author="A")
    with pytest.raises(ConversionError, match="KCC exploded"):
        runner.run_kcc(image_dir, opts)
