"""Fixtures for building minimal in-memory EPUBs."""
from __future__ import annotations

import io
import zipfile

import pytest


def _xhtml_page(image_href: str) -> bytes:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Page</title></head>
<body><img src="{image_href}" alt="page"/></body>
</html>""".encode()


def _tiny_png() -> bytes:
    """1x1 white PNG."""
    import base64
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwADhQGAWjR9awAAAABJRU5ErkJggg=="
    )


def build_epub(
    *,
    title: str = "Test Book",
    author: str = "Test Author",
    language: str = "en",
    num_pages: int = 2,
    image_subdir: str = "",
    percent_encode_images: bool = False,
    opf_subdir: str = "",
    include_encryption_xml: bool = False,
    include_encrypted_data: bool = False,
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("mimetype", "application/epub+zip")

        opf_path = f"{opf_subdir}/content.opf" if opf_subdir else "content.opf"

        container_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="{opf_path}" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""
        zf.writestr("META-INF/container.xml", container_xml)

        if include_encryption_xml:
            if include_encrypted_data:
                enc_xml = """<?xml version="1.0"?>
<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container"
            xmlns:enc="http://www.w3.org/2001/04/xmlenc#">
  <enc:EncryptedData/>
</encryption>"""
            else:
                enc_xml = """<?xml version="1.0"?>
<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container"/>"""
            zf.writestr("META-INF/encryption.xml", enc_xml)

        opf_dir = opf_subdir or ""
        img_dir = image_subdir or ""

        manifest_items = []
        spine_items = []
        png_data = _tiny_png()

        for i in range(num_pages):
            page_id = f"page{i}"
            img_id = f"img{i}"
            img_name = f"image{i}.png"
            if percent_encode_images:
                img_href_in_xhtml = f"my%20image{i}.png"
                img_name_enc = f"my image{i}.png"
            else:
                img_href_in_xhtml = img_name
                img_name_enc = img_name

            if img_dir:
                img_zip_path = f"{img_dir}/{img_name_enc}" if not opf_dir else f"{opf_dir}/{img_dir}/{img_name_enc}"
                img_opf_href = f"{img_dir}/{img_href_in_xhtml}"
                img_xhtml_href = img_href_in_xhtml if not img_dir else f"../{img_dir}/{img_href_in_xhtml}" if opf_dir else f"{img_dir}/{img_href_in_xhtml}"
            else:
                img_zip_path = img_name_enc if not opf_dir else f"{opf_dir}/{img_name_enc}"
                img_opf_href = img_href_in_xhtml
                img_xhtml_href = img_href_in_xhtml

            zf.writestr(img_zip_path, png_data)

            xhtml_zip_path = f"page{i}.xhtml" if not opf_dir else f"{opf_dir}/page{i}.xhtml"
            zf.writestr(xhtml_zip_path, _xhtml_page(img_xhtml_href))

            manifest_items.append(
                f'<item id="{page_id}" href="page{i}.xhtml" media-type="application/xhtml+xml"/>'
            )
            manifest_items.append(
                f'<item id="{img_id}" href="{img_opf_href}" media-type="image/png"/>'
            )
            spine_items.append(f'<itemref idref="{page_id}"/>')

        opf_content = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>{title}</dc:title>
    <dc:creator>{author}</dc:creator>
    <dc:language>{language}</dc:language>
  </metadata>
  <manifest>
    {"".join(manifest_items)}
  </manifest>
  <spine>
    {"".join(spine_items)}
  </spine>
</package>"""
        zf.writestr(opf_path, opf_content)

    return buf.getvalue()


@pytest.fixture
def make_epub(tmp_path):
    def _factory(**kwargs) -> "pathlib.Path":
        import pathlib
        data = build_epub(**kwargs)
        p = tmp_path / "test.epub"
        p.write_bytes(data)
        return p
    return _factory
