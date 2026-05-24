"""Native MOBI6 writer.

Produces a Mobipocket file (file version 6) from a list of processed images
plus minimal metadata. The output is a Kindle-native binary that sideloads
via USB on every Kindle since 2007.

We deliberately use MOBI6 rather than KF8 for image-only content: MOBI6's
``<img recindex="N"/>`` references are well-documented and don't require the
INDX/Skel/Frag record machinery that KF8 needs for content discovery.

Format references:
  - https://wiki.mobileread.com/wiki/MOBI
  - Calibre writer2/main.py (authoritative MOBI6 header field layout, FCIS/FLIS)
  - KindleUnpack source (binary layout cross-check)
"""
from __future__ import annotations

import io
import struct
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence


# Palm Database constants
_PDB_NAME_LEN = 32
_PDB_HEADER_LEN = 78
_PDB_RECORD_ENTRY_LEN = 8

_PDB_TYPE = b"BOOK"
_PDB_CREATOR = b"MOBI"

# PalmDOC compression types
_COMPRESSION_NONE = 1
_COMPRESSION_PALMDOC = 2

# Text encoding (UTF-8)
_TEXT_ENC_UTF8 = 65001

# Mobi types
_MOBI_TYPE_BOOK = 2

# MOBI6 file version
_MOBI6_VERSION = 6

_MOBI_HEADER_LEN = 232

# Maximum text record size (PalmDOC convention)
_MAX_TEXT_RECORD = 4096

# EXTH record type codes
_EXTH_AUTHOR = 100
_EXTH_PUBLISHER = 101
_EXTH_DESCRIPTION = 103
_EXTH_ASIN = 113
_EXTH_HAS_FAKE_COVER = 203
_EXTH_CREATOR_SOFT = 204
_EXTH_CREATOR_MAJ = 205
_EXTH_CREATOR_MIN = 206
_EXTH_CREATOR_BUILD = 207
_EXTH_CONTENT_TYPE = 501  # 'EBOK'
_EXTH_TITLE = 503
_EXTH_LANGUAGE = 524
_EXTH_WRITING_MODE = 525


@dataclass
class BookMetadata:
    title: str
    authors: list[str] = field(default_factory=list)
    language: str = "en"
    publisher: str = ""
    asin: str = field(default_factory=lambda: str(uuid.uuid4()))


def _utf8(s: str) -> bytes:
    return s.encode("utf-8")


def _pad_to(data: bytes, size: int, fill: bytes = b"\x00") -> bytes:
    if len(data) >= size:
        return data[:size]
    return data + fill * (size - len(data))


def _pad_record(data: bytes, alignment: int = 4) -> bytes:
    rem = len(data) % alignment
    if rem == 0:
        return data
    return data + b"\x00" * (alignment - rem)


def _build_html(image_count: int) -> bytes:
    """One concatenated HTML document, one image per page.

    ``<img recindex="N"/>`` is 1-based, zero-padded to 5 digits (KindleGen
    convention), and refers to the Nth image record (offset from the first
    image record declared in the MOBI header).

    Uses HTML 3/4 conventions (``<a name>`` not ``<a id>``) since Mobipocket
    predates HTML5.
    """
    pages = [
        f'<div style="margin:0;padding:0;page-break-after:always"><img recindex="{n:05d}" style="display:block"/></div>'
        for n in range(1, image_count + 1)
    ]
    html = (
        '<html><head>'
        '<style type="text/css">body{margin:0;padding:0}img{display:block}</style>'
        '</head>'
        '<body style="margin:0;padding:0">' + ''.join(pages) + '</body></html>'
    )
    return html.encode("utf-8")


def _build_exth(metadata: BookMetadata, *, manga: bool = False) -> bytes:
    records: list[tuple[int, bytes]] = []
    for author in metadata.authors:
        records.append((_EXTH_AUTHOR, _utf8(author)))
    if metadata.publisher:
        records.append((_EXTH_PUBLISHER, _utf8(metadata.publisher)))
    records.append((_EXTH_TITLE, _utf8(metadata.title)))
    records.append((_EXTH_LANGUAGE, _utf8(metadata.language)))
    records.append((_EXTH_ASIN, _utf8(metadata.asin)))
    records.append((_EXTH_CONTENT_TYPE, b"EBOK"))
    records.append((_EXTH_HAS_FAKE_COVER, b"\x00\x00\x00\x00"))
    records.append((_EXTH_WRITING_MODE, b"horizontal-rl" if manga else b"horizontal-lr"))
    # Creator fields matching KindleGen values; Kindle firmware may require them.
    records.append((_EXTH_CREATOR_SOFT, b"\x00\x00\x00\xc9"))
    records.append((_EXTH_CREATOR_MAJ, b"\x00\x00\x00\x02"))
    records.append((_EXTH_CREATOR_MIN, b"\x00\x00\x00\x09"))
    records.append((_EXTH_CREATOR_BUILD, b"\x00\x00\x00\x00"))

    body = b""
    for rec_type, value in records:
        body += struct.pack(">LL", rec_type, 8 + len(value)) + value

    total_len = 12 + len(body)
    header = b"EXTH" + struct.pack(">LL", total_len, len(records))
    block = header + body

    pad = (4 - len(block) % 4) % 4
    return block + b"\x00" * pad


def _build_mobi_header(
    *,
    text_record_count: int,
    first_image_record: int,
    first_nonbook_record: int,
    flis_record: int,
    fcis_record: int,
    last_content_record: int,
    title_offset_in_record0: int,
    title_length: int,
) -> bytes:
    """Build the MOBI6 header. Layout verified against Calibre's writer2/main.py."""
    out = io.BytesIO()

    def w32(val: int) -> None:
        out.write(struct.pack(">L", val & 0xFFFFFFFF))

    def w16(val: int) -> None:
        out.write(struct.pack(">H", val & 0xFFFF))

    out.write(b"MOBI")                  # 0x00
    w32(_MOBI_HEADER_LEN)               # 0x04 header length
    w32(_MOBI_TYPE_BOOK)                # 0x08 type = book
    w32(_TEXT_ENC_UTF8)                 # 0x0c encoding
    w32(int(time.time()) & 0xFFFFFFFF)  # 0x10 unique id
    w32(_MOBI6_VERSION)                 # 0x14 file version
    out.write(b"\xff" * 8)              # 0x18 unknown
    w32(0xFFFFFFFF)                     # 0x20 secondary index = none
    out.write(b"\xff" * 28)             # 0x24 unknown
    w32(first_nonbook_record)           # 0x40 first non-text record
    w32(title_offset_in_record0)        # 0x44 full name offset
    w32(title_length)                   # 0x48 full name length
    w32(0x09)                           # 0x4c locale = English
    out.write(b"\x00" * 8)             # 0x50 input/output language
    w32(_MOBI6_VERSION)                 # 0x58 format version
    w32(first_image_record)             # 0x5c first image record
    out.write(b"\x00" * 16)            # 0x60 HUFF/CDIC/DATP = none
    w32(0x50)                           # 0x70 EXTH flags (bit6=present, bit4=unknown)
    out.write(b"\x00" * 32)            # 0x74 unknown
    w32(0xFFFFFFFF)                     # 0x94 DRM offset = none
    w32(0xFFFFFFFF)                     # 0x98 DRM count = none
    w32(0)                              # 0x9c DRM size
    w32(0)                              # 0xa0 DRM flags
    out.write(b"\x00" * 12)            # 0xa4 unknown
    w16(1)                              # 0xb0 first content record
    w16(last_content_record)            # 0xb2 last content record
    w32(1)                              # 0xb4 unknown constant
    w32(fcis_record)                    # 0xb8 FCIS record number
    w32(1)                              # 0xbc FCIS count
    w32(flis_record)                    # 0xc0 FLIS record number
    w32(1)                              # 0xc4 FLIS count
    out.write(b"\x00" * 8)             # 0xc8 unknown
    w32(0xFFFFFFFF)                     # 0xd0 unknown
    w32(0)                              # 0xd4 unknown (Calibre writes 0)
    w32(0xFFFFFFFF)                     # 0xd8 unknown
    w32(0xFFFFFFFF)                     # 0xdc unknown
    w32(1)                              # 0xe0 extra_data_flags: bit0 = overlap bytes present
    w32(0xFFFFFFFF)                     # 0xe4 primary index = none

    result = out.getvalue()
    assert len(result) == _MOBI_HEADER_LEN
    return result


def _build_palmdoc_header(text_length: int, text_record_count: int) -> bytes:
    """The 16-byte PalmDOC header. ``text_length`` is the UNCOMPRESSED size."""
    return struct.pack(
        ">HHLHHHH",
        _COMPRESSION_PALMDOC,  # compression: 2 = PalmDOC
        0,                     # unused
        text_length,           # uncompressed text length
        text_record_count,     # number of text records
        _MAX_TEXT_RECORD,      # max record size
        0,                     # encryption: 0 = none
        0,                     # unknown
    )


def _build_record0(
    *,
    uncompressed_text_length: int,
    text_record_count: int,
    first_image_record: int,
    first_nonbook_record: int,
    flis_record: int,
    fcis_record: int,
    last_content_record: int,
    metadata: BookMetadata,
    manga: bool = False,
) -> bytes:
    """Assemble record 0: PalmDOC header + MOBI header + EXTH + title."""
    title_bytes = _utf8(metadata.title)
    title_length = len(title_bytes)

    palmdoc = _build_palmdoc_header(uncompressed_text_length, text_record_count)
    exth = _build_exth(metadata, manga=manga)

    title_offset_in_record0 = len(palmdoc) + _MOBI_HEADER_LEN + len(exth)

    mobi_header = _build_mobi_header(
        text_record_count=text_record_count,
        first_image_record=first_image_record,
        first_nonbook_record=first_nonbook_record,
        flis_record=flis_record,
        fcis_record=fcis_record,
        last_content_record=last_content_record,
        title_offset_in_record0=title_offset_in_record0,
        title_length=title_length,
    )

    record = palmdoc + mobi_header + exth + title_bytes
    return _pad_record(record, 4)


def _build_eof_record() -> bytes:
    """Mobipocket end-of-file marker."""
    return b"\xe9\x8e\x0d\x0a"


def _palmdoc_compress(data: bytes) -> bytes:
    """PalmDOC-format pass-through. Output is valid for compression=2.

    The PalmDOC algorithm allows back-reference compression but does not
    require it — a stream that only uses the literal/escape primitives is
    fully valid. We use this minimal form because:

      - Our HTML payload is small (<4 KB per page) and image-dominated.
      - Modern Kindle firmware refuses ``compression=1`` (uncompressed)
        in MOBI6 records, but happily accepts ``compression=2`` with
        no actual back-references.

    Decompression rules (per the PalmDOC spec):
      - 0x00:           literal NUL
      - 0x01..0x08:     length-prefix, followed by N literal bytes
      - 0x09..0x7F:     literal byte
      - 0x80..0xBF:     two-byte LZ77 back-reference (we never emit these)
      - 0xC0..0xFF:     space + (byte XOR 0x80) shorthand (we never emit these)

    Bytes that fall outside the literal ranges are wrapped in a 1..8-byte
    length-prefixed escape group.
    """
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        c = data[i]
        if c == 0 or 9 <= c <= 0x7F:
            out.append(c)
            i += 1
        else:
            # 0x01..0x08 or 0x80..0xFF — pack up to 8 escape-bytes together.
            j = i
            while j < n and j - i < 8:
                cc = data[j]
                if cc == 0 or 9 <= cc <= 0x7F:
                    break
                j += 1
            run = data[i:j]
            out.append(len(run))  # length 1..8 doubles as the escape marker
            out.extend(run)
            i = j
    return bytes(out)


def _build_flis_record() -> bytes:
    """FLIS record. Byte-exact match to KindleGen output (36 bytes)."""
    return (
        b"FLIS"
        + struct.pack(">I", 8)             # constant
        + struct.pack(">H", 65)            # constant
        + struct.pack(">H", 0)             # constant
        + struct.pack(">I", 0)             # constant (0, not 0xFFFFFFFF)
        + struct.pack(">I", 0xFFFFFFFF)    # constant
        + struct.pack(">H", 1)             # constant
        + struct.pack(">H", 3)             # constant
        + struct.pack(">I", 3)             # constant
        + struct.pack(">I", 1)             # constant
        + struct.pack(">I", 0xFFFFFFFF)    # constant
    )


def _build_fcis_record(text_length: int) -> bytes:
    """FCIS record (44 bytes). Layout matches Calibre writer2/main.py."""
    return (
        b"FCIS"
        + struct.pack(">I", 20)
        + struct.pack(">I", 16)
        + struct.pack(">I", 1)
        + struct.pack(">I", 0)
        + struct.pack(">I", text_length)
        + struct.pack(">I", 0)
        + struct.pack(">I", 32)
        + struct.pack(">I", 8)
        + struct.pack(">H", 1)
        + struct.pack(">H", 1)
        + struct.pack(">I", 0)
    )


def _split_text_records(text: bytes) -> list[bytes]:
    if not text:
        return [b""]
    return [text[i:i + _MAX_TEXT_RECORD] for i in range(0, len(text), _MAX_TEXT_RECORD)]


def _build_palmdb_header(name: bytes, record_count: int) -> bytes:
    now = int(time.time()) + 2082844800  # Mac/Palm epoch (Jan 1 1904)
    name_padded = _pad_to(name[:_PDB_NAME_LEN], _PDB_NAME_LEN)
    return (
        name_padded
        + struct.pack(
            ">HHLLLLLL4s4sLL H",
            0,                 # attributes
            0,                 # version
            now,               # creation date
            now,               # modification date
            0,                 # last backup date
            0,                 # modification number
            0,                 # app info ID
            0,                 # sort info ID
            _PDB_TYPE,
            _PDB_CREATOR,
            now & 0xFFFFFFFF,  # unique ID seed
            0,                 # next record list ID
            record_count,      # number of records (uint16)
        )
    )


def _safe_pdb_name(title: str) -> bytes:
    name = title.encode("ascii", errors="replace")[:_PDB_NAME_LEN - 1]
    return name + b"\x00"


def write_mobi(
    images: Sequence[tuple[str, bytes]],
    metadata: BookMetadata,
    output_path: Path,
    *,
    manga: bool = False,
) -> None:
    """Write a MOBI6 file to ``output_path``.

    Args:
      images: list of ``(page_id, jpeg_bytes)`` in display order.
      metadata: book metadata.
      output_path: where to write the file.
      manga: if True, sets EXTH writing-mode to ``horizontal-rl`` (RTL page progression).
    """
    if not images:
        raise ValueError("write_mobi: at least one image is required")

    # 1. Build a single HTML document for all pages, then PalmDOC-compress it.
    html = _build_html(len(images))
    uncompressed_text_length = len(html)
    compressed = _palmdoc_compress(html)
    # extra_data_flags = 1 means each text record ends with a 1-byte overlap
    # count. For ASCII-only HTML the overlap is always zero, so append \x00.
    text_records = [chunk + b"\x00" for chunk in _split_text_records(compressed)]

    # 2. Image records (raw JPEG bytes; no padding — readers index by record
    #    offsets, and JPEG decoders stop at the JPEG EOI marker so trailing
    #    bytes never appear, but extra padding can confuse some firmware).
    image_records = [bytes(jpeg) for _, jpeg in images]

    # 3. Build FLIS/FCIS/EOF records.
    flis_record_data = _build_flis_record()
    fcis_record_data = _build_fcis_record(uncompressed_text_length)
    eof_record = _build_eof_record()

    # 4. Standard MOBI6 layout:
    #      rec 0:                    header
    #      rec 1..N:                 compressed text
    #      rec N+1..N+M:             images  (first_nonbook = first_image)
    #      rec N+M+1:                FLIS
    #      rec N+M+2:                FCIS
    #      rec N+M+3:                EOF
    n_text = len(text_records)
    n_images = len(image_records)

    first_image_record = 1 + n_text
    last_image_record = first_image_record + n_images - 1
    flis_idx = last_image_record + 1
    fcis_idx = flis_idx + 1
    eof_idx = fcis_idx + 1
    total_records = eof_idx + 1

    # 5. Build record 0 with all final indices known.
    record0 = _build_record0(
        uncompressed_text_length=uncompressed_text_length,
        text_record_count=n_text,
        first_image_record=first_image_record,
        first_nonbook_record=first_image_record,
        flis_record=flis_idx,
        fcis_record=fcis_idx,
        last_content_record=last_image_record,
        metadata=metadata,
        manga=manga,
    )

    # 6. Assemble all records in their layout order.
    all_records: list[bytes] = [record0]
    for r in text_records:
        all_records.append(r)
    all_records.extend(image_records)
    all_records.append(flis_record_data)
    all_records.append(fcis_record_data)
    all_records.append(eof_record)

    assert len(all_records) == total_records, (
        f"record count mismatch: got {len(all_records)}, expected {total_records}"
    )

    # 7. PalmDB header + record list + 2-byte gap + records.
    pdb_name = _safe_pdb_name(metadata.title)
    pdb_header = _build_palmdb_header(pdb_name, total_records)

    record_list_size = total_records * _PDB_RECORD_ENTRY_LEN
    first_record_offset = _PDB_HEADER_LEN + record_list_size + 2

    record_list = io.BytesIO()
    cursor = first_record_offset
    for idx, rec in enumerate(all_records):
        record_list.write(struct.pack(">L", cursor))
        record_list.write(struct.pack(">L", (idx * 2) & 0xFFFFFF))
        cursor += len(rec)

    body = io.BytesIO()
    body.write(pdb_header)
    body.write(record_list.getvalue())
    body.write(b"\x00\x00")  # gap
    for rec in all_records:
        body.write(rec)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(body.getvalue())
