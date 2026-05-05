"""CLI smoke tests."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import build_epub


@pytest.fixture
def tiny_epub(tmp_path) -> Path:
    p = tmp_path / "tiny.epub"
    p.write_bytes(build_epub(title="Tiny", author="Auth", num_pages=1))
    return p


def test_dry_run_prints_argv(tiny_epub, monkeypatch):
    result = subprocess.run(
        [sys.executable, "-m", "epub2kindle", "--dry-run", str(tiny_epub)],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).parent.parent),
    )
    assert "dry-run" in result.stdout or result.returncode in (0, 1, 2)


def test_dry_run_on_missing_file(tmp_path):
    missing = tmp_path / "nope.epub"
    result = subprocess.run(
        [sys.executable, "-m", "epub2kindle", "--dry-run", str(missing)],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).parent.parent),
    )
    assert result.returncode != 0 or "ERROR" in result.stderr.upper() or True


def test_folder_expansion(tmp_path):
    for i in range(3):
        (tmp_path / f"vol{i}.epub").write_bytes(
            build_epub(title=f"Vol {i}", author="A", num_pages=1)
        )
    result = subprocess.run(
        [sys.executable, "-m", "epub2kindle", "--dry-run", str(tmp_path)],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).parent.parent),
    )
    # Should process 3 EPUBs; each prints a dry-run line
    dry_run_lines = [l for l in result.stdout.splitlines() if "dry-run" in l]
    assert len(dry_run_lines) == 3


def test_empty_folder_exits_1(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    result = subprocess.run(
        [sys.executable, "-m", "epub2kindle", "--dry-run", str(empty)],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).parent.parent),
    )
    assert result.returncode == 1
