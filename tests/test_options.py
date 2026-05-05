"""Tests for Options and to_kcc_argv()."""
from __future__ import annotations

from pathlib import Path

import pytest

from epub2kindle.options import Options


def test_defaults():
    opts = Options()
    assert opts.profile == "KPW5"
    assert opts.hq is True
    assert opts.manga is False
    assert opts.output_format == "MOBI"


def test_invalid_profile():
    with pytest.raises(ValueError, match="Unknown profile"):
        Options(profile="INVALID")


def test_invalid_cropping():
    with pytest.raises(ValueError):
        Options(cropping=5)


def test_invalid_splitter():
    with pytest.raises(ValueError):
        Options(splitter=3)


def test_to_kcc_argv_defaults(tmp_path):
    opts = Options(title="My Manga", author="Alice")
    argv = opts.to_kcc_argv(tmp_path)
    assert "-p" in argv
    assert "KPW5" in argv
    assert "-f" in argv
    assert "MOBI" in argv
    assert "-q" in argv
    assert "-t" in argv
    assert "My Manga" in argv
    assert "-a" in argv
    assert "Alice" in argv
    assert str(tmp_path) == argv[-1]


def test_to_kcc_argv_manga(tmp_path):
    opts = Options(manga=True, title="T", author="A")
    argv = opts.to_kcc_argv(tmp_path)
    assert "--manga" in argv


def test_to_kcc_argv_no_hq(tmp_path):
    opts = Options(hq=False, title="T", author="A")
    argv = opts.to_kcc_argv(tmp_path)
    assert "-q" not in argv


def test_to_kcc_argv_gamma(tmp_path):
    opts = Options(gamma=1.8, title="T", author="A")
    argv = opts.to_kcc_argv(tmp_path)
    assert "-g" in argv
    assert "1.8" in argv


def test_to_kcc_argv_output_dir(tmp_path):
    out = tmp_path / "output"
    opts = Options(output_dir=out, title="T", author="A")
    argv = opts.to_kcc_argv(tmp_path / "images")
    assert "-o" in argv
    assert str(out) in argv


def test_to_kcc_argv_no_title(tmp_path):
    opts = Options()
    argv = opts.to_kcc_argv(tmp_path)
    assert "-t" not in argv
    assert "-a" not in argv
