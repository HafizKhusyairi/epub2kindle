from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Profile codes from KCC's image.py::ProfileData.Profiles
_VALID_PROFILES = {
    "K1", "K2", "K11", "K34", "K57", "K810",
    "KDX", "KPW", "KV", "KPW34", "KPW5", "KO",
    "KCS", "KS", "KS3", "KSCS", "KS1860", "KS1920",
    # Kobo / reMarkable
    "KoHD", "KoF", "KoA", "KoAHD", "KoAH2O", "KoAO",
    "KoN", "KoL", "KoLH", "KoC", "KoCC", "KoE", "KoS",
    "RM", "RM2",
    # Generic
    "OTHER",
}


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
        if self.profile not in _VALID_PROFILES:
            raise ValueError(
                f"Unknown profile {self.profile!r}. Valid profiles: {sorted(_VALID_PROFILES)}"
            )
        if self.output_format not in ("MOBI", "EPUB", "CBZ"):
            raise ValueError(f"Unknown output_format {self.output_format!r}")
        if self.splitter not in (0, 1, 2):
            raise ValueError("splitter must be 0, 1, or 2")
        if self.cropping not in (0, 1, 2):
            raise ValueError("cropping must be 0, 1, or 2")

    def to_kcc_argv(self, image_dir: Path) -> list[str]:
        argv: list[str] = []

        argv += ["-p", self.profile]
        argv += ["-f", self.output_format]

        if self.hq:
            argv += ["-q"]

        argv += ["-c", str(self.cropping)]
        argv += ["-r", str(self.splitter)]

        if self.manga:
            argv += ["-m"]
        if self.webtoon:
            argv += ["-w"]
        if self.upscale:
            argv += ["-u"]
        if self.stretch:
            argv += ["-s"]
        if self.two_panel:
            argv += ["-2"]
        if self.gamma is not None:
            argv += ["-g", str(self.gamma)]

        output_dir = self.output_dir or image_dir.parent
        argv += ["-o", str(output_dir)]

        if self.title:
            argv += ["-t", self.title]
        if self.author:
            argv += ["-a", self.author]

        argv += [str(image_dir)]
        return argv
