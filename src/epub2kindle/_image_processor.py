from __future__ import annotations

import io
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageOps

from .options import Options, profile_resolution


_JPEG_QUALITY = 85
_JPEG_QUALITY_HQ = 90


def _natural_sort_key(p: Path) -> tuple:
    return (len(p.stem), p.name)


def _list_image_files(image_dir: Path) -> list[Path]:
    files = [p for p in image_dir.iterdir() if p.is_file()]
    files.sort(key=lambda p: p.name)
    return files


def _split_double_page(img: Image.Image, manga: bool) -> list[Image.Image]:
    """Split a landscape (double-page spread) into two portrait pages."""
    w, h = img.size
    mid = w // 2
    left = img.crop((0, 0, mid, h))
    right = img.crop((mid, 0, w, h))
    return [right, left] if manga else [left, right]


def _is_landscape(img: Image.Image) -> bool:
    w, h = img.size
    return w > h


def _resize_for_device(
    img: Image.Image, target: tuple[int, int], *, stretch: bool, upscale: bool
) -> Image.Image:
    tw, th = target
    if tw == 0 or th == 0:
        return img
    iw, ih = img.size

    if stretch:
        return ImageOps.fit(img, (tw, th), method=Image.Resampling.LANCZOS)

    if not upscale and iw <= tw and ih <= th:
        return img

    return ImageOps.contain(img, (tw, th), method=Image.Resampling.LANCZOS)


def _apply_gamma(img: Image.Image, gamma: float) -> Image.Image:
    if gamma == 1.0:
        return img
    inv = 1.0 / gamma
    table = [int(((i / 255.0) ** inv) * 255 + 0.5) for i in range(256)]
    if img.mode == "L":
        return img.point(table)
    if img.mode in ("RGB", "RGBA"):
        return img.point(table * len(img.getbands()))
    return img.convert("L").point(table)


def _to_grayscale(img: Image.Image) -> Image.Image:
    if img.mode == "L":
        return img
    return img.convert("L")


def _encode_jpeg(img: Image.Image, hq: bool) -> bytes:
    if img.mode not in ("L", "RGB"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    quality = _JPEG_QUALITY_HQ if hq else _JPEG_QUALITY
    img.save(buf, format="JPEG", quality=quality, optimize=True, progressive=False)
    return buf.getvalue()


def _process_one(
    src: Path, options: Options, target: tuple[int, int], grayscale: bool
) -> list[Image.Image]:
    img = Image.open(src)
    img.load()

    pages: list[Image.Image]
    if _is_landscape(img):
        pages = _split_double_page(img, options.manga)
    else:
        pages = [img]

    out: list[Image.Image] = []
    for p in pages:
        if grayscale:
            p = _to_grayscale(p)
        if options.gamma is not None:
            p = _apply_gamma(p, options.gamma)
        p = _resize_for_device(
            p, target, stretch=options.stretch, upscale=options.upscale
        )
        out.append(p)

    return out


def process_images(
    image_dir: Path, options: Options
) -> list[tuple[str, bytes]]:
    """Process every image in ``image_dir`` and return [(page_id, jpeg_bytes), ...].

    Page order respects RTL when ``options.manga`` is True.
    """
    target = profile_resolution(options.profile)
    grayscale = _profile_is_color(options.profile) is False

    files = _list_image_files(image_dir)
    if not files:
        return []

    rendered: list[Image.Image] = []
    for src in files:
        try:
            rendered.extend(_process_one(src, options, target, grayscale))
        except Exception as e:
            raise RuntimeError(f"Failed to process {src.name}: {e}") from e

    out: list[tuple[str, bytes]] = []
    for idx, im in enumerate(rendered, start=1):
        page_id = f"{idx:04d}"
        out.append((page_id, _encode_jpeg(im, options.hq)))
    return out


def _profile_is_color(profile: str) -> bool:
    """Color e-readers (Kindle Colorsoft, Kobo Clara Colour) keep RGB images."""
    return profile in {"KCS", "KSCS", "KoCC", "KoLC"}
