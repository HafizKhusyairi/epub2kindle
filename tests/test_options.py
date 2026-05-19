"""Tests for Options."""
from __future__ import annotations

import pytest

from epub2kindle.options import Options, profile_resolution


def test_defaults():
    opts = Options()
    assert opts.profile == "KPW5"
    assert opts.hq is True
    assert opts.manga is False
    assert opts.output_format == "MOBI"
    assert opts.output_extension() == ".mobi"


def test_invalid_profile():
    with pytest.raises(ValueError, match="Unknown profile"):
        Options(profile="INVALID")



def test_invalid_output_format():
    with pytest.raises(ValueError, match="Unknown output_format"):
        Options(output_format="CBZ")


def test_profile_resolution_known():
    assert profile_resolution("KPW5") == (1236, 1648)
    assert profile_resolution("KS") == (1860, 2480)


def test_profile_resolution_unknown():
    with pytest.raises(ValueError, match="Unknown profile"):
        profile_resolution("BOGUS")


def test_resolved_gamma_default():
    assert Options().resolved_gamma() == 1.0


def test_resolved_gamma_explicit():
    assert Options(gamma=1.8).resolved_gamma() == 1.8
