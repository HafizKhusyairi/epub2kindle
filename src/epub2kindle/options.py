from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


# Device → (width, height) in pixels.
# Mirrors kindlecomicconverter.image.ProfileData.Profiles (factual data, not code).
_PROFILE_RESOLUTIONS: dict[str, tuple[int, int]] = {
    # Kindle
    "K1":     (600, 670),
    "K2":     (600, 670),
    "KDX":    (824, 1000),
    "K34":    (600, 800),
    "K57":    (600, 800),
    "KPW":    (758, 1024),
    "KV":     (1072, 1448),
    "KPW34":  (1072, 1448),
    "K810":   (600, 800),
    "KO":     (1264, 1680),
    "K11":    (1072, 1448),
    "KPW5":   (1236, 1648),
    "KPW6":   (1272, 1696),
    "KS1860": (1860, 1920),
    "KS1920": (1920, 1920),
    "KS1240": (1240, 1860),
    "KS1324": (1324, 1986),
    "KS":     (1860, 2480),
    "KCS":    (1272, 1696),
    "KS3":    (1986, 2648),
    "KSCS":   (1986, 2648),
    # Kobo
    "KoMT":   (600, 800),
    "KoG":    (768, 1024),
    "KoGHD":  (1072, 1448),
    "KoA":    (758, 1024),
    "KoAHD":  (1080, 1440),
    "KoAH2O": (1080, 1430),
    "KoAO":   (1404, 1872),
    "KoN":    (758, 1024),
    "KoC":    (1072, 1448),
    "KoCC":   (1072, 1448),
    "KoL":    (1264, 1680),
    "KoLC":   (1264, 1680),
    "KoF":    (1440, 1920),
    "KoS":    (1440, 1920),
    "KoE":    (1404, 1872),
    # reMarkable
    "Rmk1":   (1404, 1872),
    "Rmk2":   (1404, 1872),
    "RmkPP":  (1620, 2160),
    "RmkPPMove": (954, 1696),
    # Generic
    "OTHER":  (0, 0),
}


def profile_resolution(profile: str) -> tuple[int, int]:
    """Return (width, height) for a profile, or raise ValueError."""
    try:
        return _PROFILE_RESOLUTIONS[profile]
    except KeyError as e:
        raise ValueError(
            f"Unknown profile {profile!r}. Valid profiles: "
            f"{sorted(_PROFILE_RESOLUTIONS)}"
        ) from e


@dataclass(frozen=True)
class Options:
    profile: str = "KPW5"
    output_dir: Path | None = None
    manga: bool = False
    webtoon: bool = False
    hq: bool = True
    two_panel: bool = False
    splitter: int = 0
    upscale: bool = False
    stretch: bool = False
    gamma: float | None = None
    cropping: int = 2
    title: str | None = None
    author: str | None = None
    output_format: str = "MOBI"
    delete_input: bool = False

    def __post_init__(self) -> None:
        if self.profile not in _PROFILE_RESOLUTIONS:
            raise ValueError(
                f"Unknown profile {self.profile!r}. Valid profiles: "
                f"{sorted(_PROFILE_RESOLUTIONS)}"
            )
        if self.output_format not in ("MOBI", "AZW3"):
            raise ValueError(
                f"Unknown output_format {self.output_format!r} "
                "(only MOBI and AZW3 supported; both produce a .azw3 file)"
            )
        if self.splitter not in (0, 1, 2):
            raise ValueError("splitter must be 0, 1, or 2")
        if self.cropping not in (0, 1, 2):
            raise ValueError("cropping must be 0, 1, or 2")

    def output_extension(self) -> str:
        # We emit MOBI6 (file version 6). The .mobi extension is what Kindle's
        # library scanner expects for that format; .azw3 specifically signals
        # KF8 (file version 8) and a v6 file with an .azw3 extension is
        # rejected by the indexer.
        return ".mobi"

    def resolved_gamma(self) -> float:
        return self.gamma if self.gamma is not None else 1.0
