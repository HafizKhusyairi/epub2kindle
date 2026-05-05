from __future__ import annotations

import io
import posixpath
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from urllib.parse import unquote
from xml.etree import ElementTree as ET

from .errors import EncryptedEpubError, MalformedEpubError

_NS = {
    "container": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "xhtml": "http://www.w3.org/1999/xhtml",
    "xlink": "http://www.w3.org/1999/xlink",
    "svg": "http://www.w3.org/2000/svg",
}

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif"}


@dataclass
class ExtractedEpub:
    image_dir: Path
    title: str
    authors: list[str]
    language: str | None
    cover_path: Path | None
    source_path: Path
    _tmpdir: object = field(default=None, repr=False, compare=False)

    def cleanup(self) -> None:
        if self._tmpdir is not None:
            self._tmpdir.cleanup()
            self._tmpdir = None


def _find_text(element: ET.Element, tag: str, ns: dict) -> str | None:
    el = element.find(tag, ns)
    return el.text.strip() if el is not None and el.text else None


def _resolve_href(base_dir: str, href: str) -> str:
    href = unquote(href)
    if base_dir:
        return posixpath.normpath(posixpath.join(base_dir, href))
    return posixpath.normpath(href)


def _sniff_extension(data: bytes, original_ext: str) -> str:
    if original_ext.lower() in _IMAGE_EXTENSIONS:
        return original_ext.lower()
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        fmt = (img.format or "").lower()
        if fmt == "jpeg":
            return ".jpg"
        if fmt:
            return f".{fmt}"
    except Exception:
        pass
    return original_ext or ".jpg"


def _check_drm(zf: zipfile.ZipFile) -> None:
    try:
        enc_xml = zf.read("META-INF/encryption.xml")
    except KeyError:
        return
    try:
        root = ET.fromstring(enc_xml)
    except ET.ParseError:
        return
    ns = {"enc": "http://www.w3.org/2001/04/xmlenc#"}
    if root.findall(".//enc:EncryptedData", ns):
        raise EncryptedEpubError(
            "This EPUB is DRM-protected and cannot be converted."
        )


def _get_opf_path(zf: zipfile.ZipFile) -> str:
    try:
        container_xml = zf.read("META-INF/container.xml")
    except KeyError:
        raise MalformedEpubError("Missing META-INF/container.xml")
    try:
        root = ET.fromstring(container_xml)
    except ET.ParseError as e:
        raise MalformedEpubError(f"Cannot parse container.xml: {e}") from e
    rootfile = root.find(".//container:rootfile", _NS)
    if rootfile is None:
        raise MalformedEpubError("No rootfile element in container.xml")
    path = rootfile.get("full-path")
    if not path:
        raise MalformedEpubError("rootfile element missing full-path attribute")
    return path


def _parse_opf(zf: zipfile.ZipFile, opf_path: str):
    try:
        opf_data = zf.read(opf_path)
    except KeyError:
        raise MalformedEpubError(f"OPF file not found: {opf_path}")
    try:
        root = ET.fromstring(opf_data)
    except ET.ParseError as e:
        raise MalformedEpubError(f"Cannot parse OPF: {e}") from e
    return root


def _collect_images_from_xhtml(xhtml_data: bytes, xhtml_path: str) -> list[str]:
    xhtml_dir = str(PurePosixPath(xhtml_path).parent)
    try:
        root = ET.fromstring(xhtml_data)
    except ET.ParseError:
        return []

    images: list[str] = []
    for tag in ("xhtml:img", "img", "{http://www.w3.org/1999/xhtml}img"):
        for el in root.iter(tag):
            src = el.get("src") or el.get("xlink:href")
            if src:
                images.append(_resolve_href(xhtml_dir, src))

    for tag in (
        "svg:image",
        "{http://www.w3.org/2000/svg}image",
        "image",
    ):
        for el in root.iter(tag):
            href = el.get("{http://www.w3.org/1999/xlink}href") or el.get("href")
            if href and not href.startswith("data:"):
                images.append(_resolve_href(xhtml_dir, href))

    return images


def extract(epub_path: Path) -> ExtractedEpub:
    epub_path = Path(epub_path)
    try:
        zf = zipfile.ZipFile(epub_path, "r")
    except (zipfile.BadZipFile, OSError) as e:
        raise MalformedEpubError(f"Cannot open EPUB: {e}") from e

    with zf:
        _check_drm(zf)

        opf_path = _get_opf_path(zf)
        opf_dir = str(PurePosixPath(opf_path).parent)
        opf_root = _parse_opf(zf, opf_path)

        # Build manifest
        manifest: dict[str, str] = {}
        manifest_ns = opf_root.find(".//opf:manifest", _NS)
        if manifest_ns is None:
            manifest_ns = opf_root.find(".//{http://www.idpf.org/2007/opf}manifest")
        if manifest_ns is not None:
            for item in manifest_ns:
                item_id = item.get("id")
                href = item.get("href")
                if item_id and href:
                    resolved = _resolve_href(opf_dir, href)
                    manifest[item_id] = resolved

        # Read spine
        spine_el = opf_root.find(".//opf:spine", _NS)
        if spine_el is None:
            spine_el = opf_root.find(".//{http://www.idpf.org/2007/opf}spine")
        if spine_el is None:
            raise MalformedEpubError("EPUB has no spine element")

        spine_idrefs = [
            item.get("idref")
            for item in spine_el
            if item.get("idref")
        ]
        if not spine_idrefs:
            raise MalformedEpubError("EPUB spine is empty")

        # Determine cover image id from OPF metadata
        cover_item_id: str | None = None
        for meta in opf_root.iter():
            if meta.get("name") == "cover":
                cover_item_id = meta.get("content")
                break

        # Collect images in spine order
        seen: set[str] = set()
        ordered_images: list[str] = []

        for idref in spine_idrefs:
            xhtml_path = manifest.get(idref)
            if not xhtml_path:
                continue
            try:
                xhtml_data = zf.read(xhtml_path)
            except KeyError:
                continue
            for img_path in _collect_images_from_xhtml(xhtml_data, xhtml_path):
                if img_path not in seen:
                    seen.add(img_path)
                    ordered_images.append(img_path)

        # Extract metadata
        title = _find_text(opf_root, ".//dc:title", _NS) or epub_path.stem
        authors = [
            el.text.strip()
            for el in opf_root.findall(".//dc:creator", _NS)
            if el.text
        ]
        language = _find_text(opf_root, ".//dc:language", _NS)

        # Copy images into a subdirectory named after the title so KCC uses it as the output filename
        import re
        safe_title = re.sub(r"[^\w\-. ]", "_", title or epub_path.stem)[:80].strip()
        tmpdir = TemporaryDirectory(prefix="epub2kindle-")
        tmp_path = Path(tmpdir.name) / safe_title
        tmp_path.mkdir()

        cover_path: Path | None = None
        cover_src = manifest.get(cover_item_id or "") if cover_item_id else None

        # Prepend cover as 0000 if it exists and isn't already first
        if cover_src and cover_src in seen and ordered_images and ordered_images[0] != cover_src:
            ordered_images.insert(0, cover_src)
        elif cover_src and cover_src not in seen:
            ordered_images.insert(0, cover_src)

        for idx, img_zip_path in enumerate(ordered_images):
            try:
                data = zf.read(img_zip_path)
            except KeyError:
                continue
            orig_ext = PurePosixPath(img_zip_path).suffix
            ext = _sniff_extension(data, orig_ext)
            filename = f"{idx:04d}{ext}"
            dest = tmp_path / filename
            dest.write_bytes(data)
            if img_zip_path == cover_src:
                cover_path = dest

    return ExtractedEpub(
        image_dir=tmp_path,
        title=title,
        authors=authors,
        language=language,
        cover_path=cover_path,
        source_path=epub_path,
        _tmpdir=tmpdir,
    )
