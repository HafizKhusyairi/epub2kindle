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
    cropping: int = 2
    hq: bool = True
    upscale: bool = False
    stretch: bool = False
    gamma: float | None = None
    title: str | None = None
    author: str | None = None
    output_format: str = "AZW3"
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
                "(supported: MOBI, AZW3)"
            )
        if self.cropping not in (0, 1, 2):
            raise ValueError("cropping must be 0, 1, or 2")

    def output_extension(self) -> str:
        if self.output_format == "AZW3":
            return ".azw3"
        # MOBI6 (file version 6) must use .mobi; .azw3 signals KF8 (version 8)
        # and the Kindle indexer rejects a v6 file with an .azw3 extension.
        return ".mobi"

    def resolved_gamma(self) -> float:
        return self.gamma if self.gamma is not None else 1.0
