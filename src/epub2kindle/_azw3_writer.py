"""Native KF8/AZW3 writer.

Produces a Kindle Format 8 (KF8) file from a list of processed images plus
minimal metadata.

KF8 architecture (distinct from MOBI6):
  - Content is stored as a single concatenated UTF-8 byte stream in which each
    page is represented as a skeleton (empty HTML wrapper) followed by one chunk:
    chunk0 = image div (with data-AmznRemoved mobi7 sentinel), matching KCC output.
  - That stream is split into 4096-byte PalmDOC-compressed records.
  - Two INDX trees tell Kindle where each skeleton starts (SKEL INDX) and where
    each chunk's content should be inserted into its skeleton (CHUNK INDX).
  - An FDST record maps the flow structure (one XHTML flow for a comic).
  - MOBI8 header is 264 bytes; file_version=8.

Format references:
  - https://wiki.mobileread.com/wiki/MOBI
  - Calibre writer8/ (mobi.py, index.py, skeleton.py) — authoritative layout
  - KindleUnpack — canonical reverse-engineered field layouts
  - KindleGen/KCC output — authoritative XHTML structure for comics
"""
from __future__ import annotations

import io
import struct
import time
from pathlib import Path
from typing import Sequence

from ._mobi_writer import (
    BookMetadata,
    _build_flis_record,
    _build_palmdb_header,
    _build_eof_record,
    _pad_record,
    _palmdoc_compress,
    _safe_pdb_name,
    _utf8,
    _build_fcis_record as _m6_build_fcis,
    _build_html as _m6_build_html,
    _split_text_records,
)

_MOBI6_HEADER_LEN = 232  # must match _MOBI_HEADER_LEN in _mobi_writer.py


# --------------------------------------------------------------------------- #
# Constants                                                                    #
# --------------------------------------------------------------------------- #

_PDB_HEADER_LEN = 78
_PDB_RECORD_ENTRY_LEN = 8
_PALMDOC_HEADER_LEN = 16
_MOBI8_HEADER_LEN = 264
_INDX_HEADER_LEN = 192
_MAX_TEXT_RECORD = 4096

_TEXT_ENC_UTF8 = 65001
_MOBI_TYPE_BOOK = 2
_MOBI8_VERSION = 8

_EXTH_AUTHOR = 100
_EXTH_PUBLISHER = 101
_EXTH_PRODUCER = 108
_EXTH_ASIN = 113
_EXTH_NUM_RESOURCES = 125
_EXTH_COMIC_TRUE_1 = 122   # "true" — comic flag
_EXTH_COMIC_TYPE = 123     # "comic"
_EXTH_COMIC_PANEL = 124    # "none" — panel view layout type
_EXTH_COMIC_RES = 126      # device resolution string e.g. "1264x1680"
_EXTH_COMIC_TRUE_2 = 127   # "true"
_EXTH_COMIC_TRUE_3 = 128   # "true"
_EXTH_COMIC_THUMB = 129    # thumbnail reference e.g. "kindle:embed:0001"
_EXTH_KF8_UNKNOWN = 131    # kf8_unknown_count (n_pages + 1 empirically)
_EXTH_COMIC_MZON = 542     # "mzOn" — required for library indexing (KCC/KindleGen)
_EXTH_300_BLOB = (
    b"\x01" + b"\x00" * 14 + b"\x80" + b"\x00" * 16
    + b"\x00\x00\x00\x00"  # last 4 bytes: unknown, placeholder zeros
)
_EXTH_KF8_BOUNDARY = 121   # absolute record index of the BOUNDARY record (= KF8 base)
_EXTH_HAS_FAKE_COVER = 203
_EXTH_COVER_OFFSET = 201
_EXTH_THUMB_OFFSET = 202
_EXTH_CREATOR_SOFT = 204
_EXTH_CREATOR_MAJ = 205
_EXTH_CREATOR_MIN = 206
_EXTH_CREATOR_BUILD = 207
_EXTH_CONTENT_TYPE = 501
_EXTH_TITLE = 503
_EXTH_LANGUAGE = 524
_EXTH_WRITING_MODE = 525
_EXTH_BUILD_ID = 535
_EXTH_SOURCE = 547

# 3 AIDs per page: 0=body  1=image_div  2=mobi7_placeholder
_AIDS_PER_PAGE = 3

# Base-32 digit alphabet — uppercase A-V for digits 10-31, matching KindleGen/Calibre writer output
_B32 = '0123456789ABCDEFGHIJKLMNOPQRSTUV'


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _to_base32(n: int) -> str:
    """Encode a non-negative integer in base 32 (Calibre's aid encoding)."""
    if n == 0:
        return '0'
    chars: list[str] = []
    while n:
        chars.append(_B32[n & 0x1F])
        n >>= 5
    return ''.join(reversed(chars))


def _encint(value: int) -> bytes:
    """VIQE forward encoding (big-endian, 7 bits/byte, high bit on last byte)."""
    byts = bytearray()
    while True:
        byts.append(value & 0x7F)
        value >>= 7
        if value == 0:
            break
    byts[0] |= 0x80
    byts.reverse()
    return bytes(byts)


def _align4(data: bytes) -> bytes:
    rem = len(data) % 4
    return data if rem == 0 else data + b"\x00" * (4 - rem)


# --------------------------------------------------------------------------- #
# XHTML skeleton and chunk (1 per page)                                        #
# --------------------------------------------------------------------------- #

_CSS_FLOW = (
    '@page {\nmargin: 0;\n}\n'
    'body {\ndisplay: block;\nmargin: 0;\npadding: 0;\n}\n'
).encode('utf-8')


def _build_skeleton(page_num: int, aid_body: str, tw: int, th: int) -> bytes:
    """Empty HTML wrapper for one page."""
    viewport = f'<meta name="viewport" content="width={tw}, height={th}"/>' if tw and th else ''
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<!DOCTYPE html>'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
        '<head>'
        f'<title>page-{page_num:05d}</title>'
        '<link href="kindle:flow:0001?mime=text/css" type="text/css" rel="stylesheet"/>'
        f'{viewport}'
        '</head>'
        f'<body style="background-color:#000000;" aid="{aid_body}"></body>'
        '</html>'
    ).encode('utf-8')


def _jpeg_size(data: bytes) -> tuple[int, int]:
    """Parse (width, height) from JPEG SOF marker."""
    i = 2  # skip SOI
    while i + 4 < len(data):
        if data[i] != 0xFF:
            break
        marker = data[i + 1]
        i += 2
        if marker == 0xD9:
            break
        if marker in (0xC0, 0xC1, 0xC2):
            h = struct.unpack_from(">H", data, i + 3)[0]
            w = struct.unpack_from(">H", data, i + 5)[0]
            return w, h
        seg_len = struct.unpack_from(">H", data, i)[0]
        i += seg_len
    return 0, 0


def _build_image_chunk(*, aid_div: str, aid_amzn: str, embed_ref: str, iw: int, ih: int) -> bytes:
    """Single chunk per page: image div + mobi7 display:none placeholder."""
    dim = f' width="{iw}" height="{ih}"' if iw and ih else ''
    return (
        f'\n<div style="text-align:center;" aid="{aid_div}">\n'
        f'<div style="display:none;" data-AmznRemoved="mobi7" aid="{aid_amzn}">.</div>\n'
        f'<img{dim} src="kindle:embed:{embed_ref}?mime=image/jpg"/>\n'
        f'</div>\n'
    ).encode('utf-8')


# --------------------------------------------------------------------------- #
# Text stream → content records                                                #
# --------------------------------------------------------------------------- #

def _split_stream_into_records(stream: bytes) -> list[bytes]:
    """Split the global text stream into palmdoc-compressed 4096-byte records.

    extra_data_flags=3: bit0=multibyte char, bit1=TBS (Trailing Byte Sequences).
    The Kindle firmware unconditionally strips TBS from KF8 records regardless of
    the declared flag value. Without valid TBS bytes the firmware backward-reads
    content bytes as a TBS size, strips random amounts, and corrupts every record.

    Trailing layout (right to left, stripped in order):
      \\x81  — empty TBS: backward-VIQE size=1, strip 1 byte (size byte only)
      \\x00  — multibyte char: lower-2-bits=0 → strip 1 byte
    """
    records: list[bytes] = []
    offset = 0
    while offset < len(stream):
        chunk = stream[offset: offset + _MAX_TEXT_RECORD]
        records.append(_palmdoc_compress(chunk) + b"\x00\x81")
        offset += len(chunk)
    return records


# --------------------------------------------------------------------------- #
# FDST record                                                                  #
# --------------------------------------------------------------------------- #

def _build_fdst_record(flow_lengths: list[int]) -> bytes:
    """Flow Data Section Table — one entry per XHTML/CSS flow."""
    n = len(flow_lengths)
    out = io.BytesIO()
    out.write(b"FDST")
    out.write(struct.pack(">II", 12, n))
    offset = 0
    for size in flow_lengths:
        out.write(struct.pack(">II", offset, offset + size))
        offset += size
    return out.getvalue()


# --------------------------------------------------------------------------- #
# INDX helpers                                                                 #
# --------------------------------------------------------------------------- #

# SKEL TAGX: chunk_count (tag1, vpe=1, mask=0x03) + geometry (tag6, vpe=2, mask=0x0C)
_SKEL_TAGX = (
    b"TAGX"
    + struct.pack(">II", 24, 1)
    + bytes([1, 1, 3, 0])
    + bytes([6, 2, 12, 0])
    + bytes([0, 0, 0, 1])
)

# CHUNK TAGX: cncx_offset (tag2) + file_number (tag3) + seq_num (tag4) + geometry (tag6)
_CHUNK_TAGX = (
    b"TAGX"
    + struct.pack(">II", 32, 1)
    + bytes([2, 1, 1, 0])
    + bytes([3, 1, 2, 0])
    + bytes([4, 1, 4, 0])
    + bytes([6, 2, 8, 0])
    + bytes([0, 0, 0, 1])
)


def _build_indx_header_record(
    *,
    num_entries: int,
    num_data_records: int,
    num_cncx: int,
    tagx: bytes,
    last_label: bytes,
) -> bytes:
    tagx_aligned = _align4(tagx)

    geometry_raw = bytes([len(last_label)]) + last_label + struct.pack(">H", num_entries)
    geometry_aligned = _align4(geometry_raw)

    idxt_entry_pos = _INDX_HEADER_LEN + len(tagx_aligned)
    idxt = _align4(b"IDXT" + struct.pack(">H", idxt_entry_pos))

    idxt_offset = _INDX_HEADER_LEN + len(tagx_aligned) + len(geometry_aligned)

    hdr = io.BytesIO()
    hdr.write(b"INDX")
    hdr.write(struct.pack(">I", _INDX_HEADER_LEN))
    hdr.write(b"\x00" * 8)
    hdr.write(struct.pack(">I", 2))                   # type=2 header record
    hdr.write(struct.pack(">I", idxt_offset))
    hdr.write(struct.pack(">I", num_data_records))
    hdr.write(struct.pack(">I", _TEXT_ENC_UTF8))
    hdr.write(struct.pack(">I", 0xFFFFFFFF))
    hdr.write(struct.pack(">I", num_entries))
    hdr.write(b"\x00" * 12)
    hdr.write(struct.pack(">I", num_cncx))
    hdr.write(b"\x00" * 124)
    hdr.write(struct.pack(">I", _INDX_HEADER_LEN))   # tagx_offset
    hdr.write(b"\x00" * 8)
    assert hdr.tell() == _INDX_HEADER_LEN

    return hdr.getvalue() + tagx_aligned + geometry_aligned + idxt


def _build_indx_data_record(entry_bytes: bytes, idxt_offsets: list[int]) -> bytes:
    entry_aligned = _align4(entry_bytes)
    idxt_raw = b"IDXT" + b"".join(struct.pack(">H", o) for o in idxt_offsets)
    idxt_aligned = _align4(idxt_raw)

    idxt_block_offset = _INDX_HEADER_LEN + len(entry_aligned)

    hdr = io.BytesIO()
    hdr.write(b"INDX")
    hdr.write(struct.pack(">I", _INDX_HEADER_LEN))
    hdr.write(b"\x00" * 4)
    hdr.write(struct.pack(">I", 1))                   # type=1 data record
    hdr.write(b"\x00" * 4)
    hdr.write(struct.pack(">I", idxt_block_offset))
    hdr.write(struct.pack(">I", len(idxt_offsets)))
    hdr.write(b"\xff" * 8)
    hdr.write(b"\x00" * 156)
    assert hdr.tell() == _INDX_HEADER_LEN

    return hdr.getvalue() + entry_aligned + idxt_aligned


# --------------------------------------------------------------------------- #
# SKEL INDX                                                                    #
# --------------------------------------------------------------------------- #

def _build_skel_indx(
    skel_starts: list[int],
    skel_lengths: list[int],
    chunks_per_page: int = 3,
) -> list[bytes]:
    """SKEL INDX: [header_record, data_record].

    One entry per page.  chunk_count is encoded twice per entry (Calibre quirk).
    """
    n = len(skel_starts)
    entries_io = io.BytesIO()
    idxt_offsets: list[int] = []

    for i in range(n):
        label = f"SKEL{i:010d}".encode()
        start = skel_starts[i]
        length = skel_lengths[i]

        entry = (
            bytes([len(label)]) + label
            + bytes([0x0A])
            + _encint(chunks_per_page) + _encint(chunks_per_page)
            + _encint(start) + _encint(length)
            + _encint(start) + _encint(length)
        )

        idxt_offsets.append(_INDX_HEADER_LEN + entries_io.tell())
        entries_io.write(entry)

    last_label = f"SKEL{n - 1:010d}".encode()
    data_record = _build_indx_data_record(entries_io.getvalue(), idxt_offsets)
    header_record = _build_indx_header_record(
        num_entries=n,
        num_data_records=1,
        num_cncx=0,
        tagx=_SKEL_TAGX,
        last_label=last_label,
    )
    return [header_record, data_record]


# --------------------------------------------------------------------------- #
# CHUNK INDX + CNCX                                                            #
# --------------------------------------------------------------------------- #

def _build_chunk_indx(
    abs_insert_positions: list[int],
    chunk_lengths_per_page: list[list[int]],
) -> list[bytes]:
    """CHUNK INDX: [header_record, data_record, cncx_record].

    For each page i, there are len(chunk_lengths_per_page[i]) chunks.
    - abs_insert_positions[i]: absolute byte offset in global stream where all
      chunks for page i are inserted into skeleton i (= the </body> position).
    - chunk_lengths_per_page[i][j]: byte length of the j-th chunk of page i.

    CHUNK INDX entry geometry (verified against KindleGen reference):
    - label: abs_insert_pos + sum(preceding chunk lengths within same page)
    - start_pos: sum(preceding chunk lengths within same page)
    - length: this chunk's length
    - file_number: page index (= skeleton index)
    - sequence_number: global sequential chunk index
    """
    # Flatten to a list of (page_idx, chunk_idx_within_page, chunk_length) tuples
    all_chunks: list[tuple[int, int, int]] = []
    for i, lengths in enumerate(chunk_lengths_per_page):
        for j, length in enumerate(lengths):
            all_chunks.append((i, j, length))

    n_total_chunks = len(all_chunks)

    # CNCX pool
    cncx_io = io.BytesIO()
    cncx_offsets: list[int] = []
    for i, (page_idx, chunk_j, _) in enumerate(all_chunks):
        aid = _to_base32(page_idx * _AIDS_PER_PAGE)
        s = f"P-//*[@aid='{aid}']".encode()
        cncx_offsets.append(cncx_io.tell())
        cncx_io.write(_encint(len(s)) + s)
    cncx_record = _align4(cncx_io.getvalue())

    entries_io = io.BytesIO()
    idxt_offsets: list[int] = []
    seq_num = 0

    for i, (page_idx, chunk_j, chunk_len) in enumerate(all_chunks):
        preceding_len = sum(chunk_lengths_per_page[page_idx][:chunk_j])
        label_val = abs_insert_positions[page_idx] + preceding_len
        label = f"{label_val:010d}".encode()

        entry = (
            bytes([len(label)]) + label
            + bytes([0x0F])
            + _encint(cncx_offsets[i])
            + _encint(page_idx)
            + _encint(seq_num)
            + _encint(preceding_len)
            + _encint(chunk_len)
        )

        idxt_offsets.append(_INDX_HEADER_LEN + entries_io.tell())
        entries_io.write(entry)
        seq_num += 1

    last_label = f"{abs_insert_positions[-1] + sum(chunk_lengths_per_page[-1][:-1]):010d}".encode()
    data_record = _build_indx_data_record(entries_io.getvalue(), idxt_offsets)
    header_record = _build_indx_header_record(
        num_entries=n_total_chunks,
        num_data_records=1,
        num_cncx=1,
        tagx=_CHUNK_TAGX,
        last_label=last_label,
    )
    return [header_record, data_record, cncx_record]


# --------------------------------------------------------------------------- #
# MOBI8 header and record 0                                                    #
# --------------------------------------------------------------------------- #

def _build_mobi8_header(
    *,
    text_length: int,
    last_text_record: int,
    first_non_text_record: int,
    first_resource_record: int,
    fdst_record: int,
    fdst_count: int,
    fcis_record: int,
    flis_record: int,
    ncx_index: int,
    chunk_index: int,
    skel_index: int,
    title_offset_in_record0: int,
    title_length: int,
) -> bytes:
    """264-byte MOBI8 header."""
    out = io.BytesIO()

    def w32(val: int) -> None:
        out.write(struct.pack(">I", val & 0xFFFFFFFF))

    out.write(b"MOBI")
    w32(_MOBI8_HEADER_LEN)
    w32(_MOBI_TYPE_BOOK)
    w32(_TEXT_ENC_UTF8)
    w32(int(time.time()) & 0xFFFFFFFF)
    w32(_MOBI8_VERSION)
    w32(chunk_index)                           # orth_index = chunk_idx (KCC pattern)
    w32(0xFFFFFFFF)                            # meta_infl_index=NULL
    out.write(b"\xff" * 32)                    # extra_index0-7
    w32(first_non_text_record)
    w32(title_offset_in_record0)
    w32(title_length)
    w32(0x0409)                                # language_code=en-US
    w32(0)
    w32(0)
    w32(_MOBI8_VERSION)
    w32(first_resource_record)
    out.write(b"\x00" * 16)                    # huff_*
    w32(0x50)                                  # exth_flags
    out.write(b"\x00" * 32)
    w32(0xFFFFFFFF)                            # unknown_index=NULL
    w32(0xFFFFFFFF)                            # drm_offset=NULL
    w32(0)
    w32(0)
    w32(0)
    out.write(b"\x00" * 8)
    w32(fdst_record)
    w32(fdst_count)
    w32(fcis_record)
    w32(1)
    w32(flis_record)
    w32(1)
    out.write(b"\x00" * 8)
    w32(0xFFFFFFFF)                            # srcs_record=NULL
    w32(0)
    out.write(b"\xff" * 8)
    w32(0b11)                                  # extra_data_flags: bit0=multibyte, bit1=TBS (required for Kindle comic mode)
    w32(ncx_index)
    w32(chunk_index)
    w32(skel_index)
    w32(0xFFFFFFFF)                            # datp_index=NULL
    w32(0xFFFFFFFF)                            # guide_index=NULL
    out.write(b"\xff" * 4)
    out.write(b"\x00" * 4)
    out.write(b"\xff" * 4)
    out.write(b"\x00" * 4)

    result = out.getvalue()
    assert len(result) == _MOBI8_HEADER_LEN, len(result)
    return result


def _build_exth(
    metadata: BookMetadata,
    *,
    manga: bool = False,
    num_images: int = 0,
    target: tuple[int, int] = (0, 0),
    n_pages: int = 0,
) -> bytes:
    tw, th = target
    records: list[tuple[int, bytes]] = []
    records.append((_EXTH_ASIN, _utf8(metadata.asin)))
    records.append((_EXTH_CONTENT_TYPE, b"PDOC"))
    for author in metadata.authors:
        records.append((_EXTH_AUTHOR, _utf8(author)))
    records.append((_EXTH_COMIC_TRUE_1, b"true"))
    records.append((_EXTH_COMIC_TYPE, b"comic"))
    records.append((_EXTH_COMIC_PANEL, b"none"))
    if tw and th:
        records.append((_EXTH_COMIC_RES, f"{tw}x{th}".encode()))
    records.append((_EXTH_COMIC_TRUE_2, b"true"))
    records.append((_EXTH_COMIC_TRUE_3, b"true"))
    records.append((_EXTH_PRODUCER, b"epub2kindle"))
    records.append((_EXTH_COMIC_MZON, b"mzOn"))
    records.append((_EXTH_LANGUAGE, _utf8(metadata.language)))
    records.append((527, b"rtl" if manga else b"ltr"))
    records.append((_EXTH_WRITING_MODE, b"horizontal-rl" if manga else b"horizontal-lr"))
    records.append((_EXTH_COMIC_THUMB, b"kindle:embed:0001"))
    records.append((_EXTH_KF8_UNKNOWN, struct.pack(">I", n_pages + 1)))
    records.append((300, _EXTH_300_BLOB))
    records.append((_EXTH_CREATOR_SOFT, b"\x00\x00\x00\xc9"))
    records.append((_EXTH_CREATOR_MAJ, b"\x00\x00\x00\x02"))
    records.append((_EXTH_CREATOR_MIN, b"\x00\x00\x00\x09"))
    records.append((_EXTH_BUILD_ID, b"epub2kindle"))
    records.append((_EXTH_CREATOR_BUILD, b"\x00\x00\x00\x00"))
    records.append((_EXTH_SOURCE, b"epub2kindle"))
    records.append((_EXTH_NUM_RESOURCES, struct.pack(">I", 0)))
    records.append((_EXTH_COVER_OFFSET, struct.pack(">I", 0)))
    records.append((_EXTH_HAS_FAKE_COVER, struct.pack(">I", 0)))
    records.append((_EXTH_THUMB_OFFSET, struct.pack(">I", 0)))

    body = b""
    for rec_type, value in records:
        body += struct.pack(">II", rec_type, 8 + len(value)) + value

    total_len = 12 + len(body)
    block = b"EXTH" + struct.pack(">II", total_len, len(records)) + body
    pad = (4 - len(block) % 4) % 4
    return block + b"\x00" * pad


def _build_palmdoc_header_kf8(text_length: int, last_text_record: int) -> bytes:
    return struct.pack(
        ">HHLHHHH",
        2,                   # compression=2 (PalmDOC)
        0,
        text_length,
        last_text_record,
        _MAX_TEXT_RECORD,
        0,
        0,
    )


def _build_record0(
    *,
    text_length: int,
    n_text_records: int,
    first_non_text_record: int,
    first_resource_record: int,
    fdst_record: int,
    fdst_count: int,
    fcis_record: int,
    flis_record: int,
    ncx_index: int,
    chunk_index: int,
    skel_index: int,
    metadata: BookMetadata,
    manga: bool = False,
    num_images: int = 0,
    target: tuple[int, int] = (0, 0),
    n_pages: int = 0,
) -> bytes:
    title_bytes = _utf8(metadata.title)

    palmdoc = _build_palmdoc_header_kf8(text_length, n_text_records)
    exth = _build_exth(metadata, manga=manga, num_images=num_images,
                       target=target, n_pages=n_pages)

    title_offset_in_record0 = _PALMDOC_HEADER_LEN + _MOBI8_HEADER_LEN + len(exth)

    mobi = _build_mobi8_header(
        text_length=text_length,
        last_text_record=n_text_records,
        first_non_text_record=first_non_text_record,
        first_resource_record=first_resource_record,
        fdst_record=fdst_record,
        fdst_count=fdst_count,
        fcis_record=fcis_record,
        flis_record=flis_record,
        ncx_index=ncx_index,
        chunk_index=chunk_index,
        skel_index=skel_index,
        title_offset_in_record0=title_offset_in_record0,
        title_length=len(title_bytes),
    )

    record = palmdoc + mobi + exth + title_bytes + b"\x00" * 8192
    return _pad_record(record, 4)


# --------------------------------------------------------------------------- #
# FCIS (KF8 variant, 52 bytes)                                                 #
# --------------------------------------------------------------------------- #

def _build_kf8_fcis(text_length: int) -> bytes:
    return (
        b"FCIS\x00\x00\x00\x14\x00\x00\x00\x10\x00\x00\x00\x02\x00\x00\x00\x00"
        + struct.pack(">I", text_length)
        + b"\x00\x00\x00\x00\x00\x00\x00\x28\x00\x00\x00\x00\x00\x00\x00"
        + b"\x28\x00\x00\x00\x08\x00\x01\x00\x01\x00\x00\x00\x00"
    )


# --------------------------------------------------------------------------- #
# MOBI6 section for joint MOBI6+KF8 file                                       #
# --------------------------------------------------------------------------- #

def _build_mobi6_joint_record0(
    *,
    text_length: int,
    n_text_records: int,
    first_image_record: int,
    first_nonbook_record: int,
    flis_record: int,
    fcis_record: int,
    last_image_record: int,
    kf8_base: int,
    metadata: BookMetadata,
    manga: bool = False,
    target: tuple[int, int] = (0, 0),
    n_images: int = 0,
    n_pages: int = 0,
) -> bytes:
    """MOBI6 record 0 for joint file with correct flags for Kindle library indexing.

    Differences from standalone MOBI6 (_mobi_writer.py):
      - exth_flags=0x850  (0x800 = KF8-linked signal, required for library to see file)
      - extra_data_flags=3  (TBS + multibyte, matching KCC)
      - content_type=PDOC  (sideloaded personal doc, not EBOK which triggers DRM check)
      - full comic EXTH records (122-131) so scanner categorises as comic
      - 8192-byte padding (same as KF8 record 0, KindleGen convention)
    """
    tw, th = target
    title_bytes = _utf8(metadata.title)

    # 16-byte PalmDoc header
    palmdoc = struct.pack(">HHLHHHH", 2, 0, text_length, n_text_records, 4096, 0, 0)

    # EXTH records
    recs: list[tuple[int, bytes]] = []
    recs.append((_EXTH_ASIN,          _utf8(metadata.asin)))
    recs.append((_EXTH_CONTENT_TYPE,  b"PDOC"))
    for author in metadata.authors:
        recs.append((_EXTH_AUTHOR, _utf8(author)))
    recs.append((_EXTH_COMIC_TRUE_1,  b"true"))
    recs.append((_EXTH_COMIC_TYPE,    b"comic"))
    recs.append((_EXTH_COMIC_PANEL,   b"none"))
    if tw and th:
        recs.append((_EXTH_COMIC_RES, f"{tw}x{th}".encode()))
    recs.append((_EXTH_COMIC_TRUE_2,  b"true"))
    recs.append((_EXTH_COMIC_TRUE_3,  b"true"))
    recs.append((_EXTH_PRODUCER,      b"epub2kindle"))
    recs.append((_EXTH_COMIC_MZON,    b"mzOn"))
    recs.append((_EXTH_LANGUAGE,      _utf8(metadata.language)))
    recs.append((527,                 b"rtl" if manga else b"ltr"))
    recs.append((_EXTH_WRITING_MODE,  b"horizontal-rl" if manga else b"horizontal-lr"))
    recs.append((_EXTH_COMIC_THUMB,   b"kindle:embed:0001"))
    recs.append((_EXTH_KF8_UNKNOWN,   struct.pack(">I", n_pages + 1)))
    recs.append((300,                 _EXTH_300_BLOB))
    recs.append((_EXTH_CREATOR_SOFT,  b"\x00\x00\x00\xc9"))
    recs.append((_EXTH_CREATOR_MAJ,   b"\x00\x00\x00\x02"))
    recs.append((_EXTH_CREATOR_MIN,   b"\x00\x00\x00\x09"))
    recs.append((_EXTH_BUILD_ID,      b"epub2kindle"))
    recs.append((_EXTH_CREATOR_BUILD, b"\x00\x00\x00\x00"))
    recs.append((_EXTH_SOURCE,        b"epub2kindle"))
    recs.append((_EXTH_NUM_RESOURCES, struct.pack(">I", n_images)))
    recs.append((_EXTH_COVER_OFFSET,  struct.pack(">I", 0)))
    recs.append((_EXTH_HAS_FAKE_COVER,struct.pack(">I", 0)))
    recs.append((_EXTH_THUMB_OFFSET,  struct.pack(">I", 0)))
    recs.append((_EXTH_KF8_BOUNDARY,  struct.pack(">I", kf8_base)))

    exth_body = b"".join(struct.pack(">II", rt, 8 + len(v)) + v for rt, v in recs)
    exth_raw = b"EXTH" + struct.pack(">II", 12 + len(exth_body), len(recs)) + exth_body
    exth = exth_raw + b"\x00" * ((4 - len(exth_raw) % 4) % 4)

    _M6J_HDR_LEN = 264  # KindleGen always writes 264-byte MOBI6 header for joint files
    title_offset = 16 + _M6J_HDR_LEN + len(exth)

    # MOBI6 header — 264-byte form matching KindleGen joint-file output.
    # Extra 32 bytes vs standalone MOBI6 (232) are 8 null index fields.
    mh = io.BytesIO()
    def w32(v: int) -> None: mh.write(struct.pack(">I", v & 0xFFFFFFFF))
    def w16(v: int) -> None: mh.write(struct.pack(">H", v & 0xFFFF))
    mh.write(b"MOBI")
    w32(_M6J_HDR_LEN)
    w32(2)                              # type = book
    w32(65001)                          # encoding = UTF-8
    w32(int(time.time()) & 0xFFFFFFFF)
    w32(6)                              # file_version = 6
    mh.write(b"\xff" * 8)
    w32(0xFFFFFFFF)                     # secondary index = none
    mh.write(b"\xff" * 28)
    w32(first_nonbook_record)
    w32(title_offset)
    w32(len(title_bytes))
    w32(0x0409)                         # locale = en-US (LCID)
    mh.write(b"\x00" * 8)
    w32(6)                              # format version = 6
    w32(first_image_record)
    mh.write(b"\x00" * 16)
    w32(0x850)                          # exth_flags: 0x40=EXTH, 0x10=unk, 0x800=KF8-linked
    mh.write(b"\x00" * 32)
    w32(0xFFFFFFFF)                     # DRM offset = none
    w32(0xFFFFFFFF)                     # DRM count = none
    w32(0)
    w32(0)
    mh.write(b"\x00" * 12)
    w16(1)                              # first content record
    w16(last_image_record)
    w32(1)
    w32(fcis_record)
    w32(1)
    w32(flis_record)
    w32(1)
    mh.write(b"\x00" * 8)
    w32(fcis_record)                       # last MOBI6 record index (KCC pattern)
    w32(1)
    w32(0xFFFFFFFF)
    w32(0xFFFFFFFF)
    w32(0b11)                           # extra_data_flags: bit0=multibyte, bit1=TBS
    w32(first_nonbook_record)           # primary index = first_nonbook (KCC pattern)
    mh.write(b"\xff" * 20 + b"\x00" * 4 + b"\xff" * 4 + b"\x00" * 4)  # extended index fields (KCC pattern)
    mobi_hdr = mh.getvalue()
    assert len(mobi_hdr) == _M6J_HDR_LEN, len(mobi_hdr)

    record_raw = palmdoc + mobi_hdr + exth + title_bytes + b"\x00" * 8192
    return _pad_record(record_raw, 4)


def _build_mobi6_section_records(
    image_records: list[bytes],
    metadata: BookMetadata,
    *,
    manga: bool = False,
    target: tuple[int, int] = (0, 0),
    n_pages: int = 0,
) -> list[bytes]:
    """Build MOBI6 section records for joint file (no EOF — BOUNDARY follows).

    Record layout:
      0:       MOBI6 header (8KB padded, PDOC, 0x850 exth_flags, comic EXTH)
      1:       compressed HTML text  (ends with \\x00\\x81 for extra_data_flags=3)
      2..2+M:  JPEG images  (first_img = 2 for single text record)
      ..+FLIS
      ..+FCIS
    """
    n_images = len(image_records)
    html = _m6_build_html(n_images)
    text_len = len(html)
    compressed = _palmdoc_compress(html)
    # extra_data_flags=3: TBS (\x81, encodes "strip 1 byte") + multibyte overlap (\x00)
    text_recs = [chunk + b'\x00\x81' for chunk in _split_text_records(compressed)]
    n_text = len(text_recs)

    first_img = 1 + n_text
    last_img  = first_img + n_images - 1
    flis_idx  = last_img + 1
    fcis_idx  = flis_idx + 1
    # BOUNDARY follows the MOBI6 section; KF8 base = MOBI6 record count + 1
    # MOBI6 records: record0(1) + text(n_text) + images(n_images) + flis(1) + fcis(1)
    mobi6_count = 1 + n_text + n_images + 2
    kf8_base = mobi6_count + 1  # +1 for the BOUNDARY record

    record0 = _build_mobi6_joint_record0(
        text_length=text_len,
        n_text_records=n_text,
        first_image_record=first_img,
        first_nonbook_record=first_img,
        flis_record=flis_idx,
        fcis_record=fcis_idx,
        last_image_record=last_img,
        kf8_base=kf8_base,
        metadata=metadata,
        manga=manga,
        target=target,
        n_images=n_images,
        n_pages=n_pages,
    )

    return [record0] + text_recs + image_records + [_build_flis_record(), _m6_build_fcis(text_len)]


# --------------------------------------------------------------------------- #
# Public entry point                                                            #
# --------------------------------------------------------------------------- #

def write_azw3(
    images: Sequence[tuple[str, bytes]],
    metadata: BookMetadata,
    output_path: Path,
    *,
    manga: bool = False,
    target: tuple[int, int] = (0, 0),
) -> None:
    """Write a KF8/AZW3 file to ``output_path``.

    Args:
      images:      list of ``(page_id, jpeg_bytes)`` in display order.
      metadata:    book metadata.
      output_path: destination path (should have .azw3 extension).
      manga:       if True, sets EXTH writing-mode to horizontal-rl (RTL).
      target:      device (width, height) in pixels, for viewport and img tags.
    """
    if not images:
        raise ValueError("write_azw3: at least one image is required")

    n_pages = len(images)
    tw, th = target

    # ------------------------------------------------------------------ #
    # 1.  Per-page skeleton + 1 chunk (image div)                        #
    # ------------------------------------------------------------------ #
    skeletons: list[bytes] = []
    all_page_chunks: list[list[bytes]] = []   # [page][chunk_j]
    insert_positions_in_skel: list[int] = []

    for i in range(n_pages):
        base     = i * _AIDS_PER_PAGE
        aid_body = _to_base32(base)
        aid_div  = _to_base32(base + 1)
        aid_amzn = _to_base32(base + 2)

        img_idx   = i + 1                         # 1-based
        embed_ref = _to_base32(img_idx).zfill(4)

        jpeg_bytes = images[i][1]
        iw, ih = _jpeg_size(jpeg_bytes)
        if not (iw and ih):                       # fallback to device target if parse fails
            iw, ih = tw, th

        skel   = _build_skeleton(i + 1, aid_body, iw, ih)  # viewport = actual image size
        chunk0 = _build_image_chunk(aid_div=aid_div, aid_amzn=aid_amzn,
                                    embed_ref=embed_ref, iw=iw, ih=ih)

        insert_pos = skel.index(b'</body>')

        skeletons.append(skel)
        all_page_chunks.append([chunk0])
        insert_positions_in_skel.append(insert_pos)

    # ------------------------------------------------------------------ #
    # 2.  Global text stream: skel0+c1_0+c2_0+c3_0 + skel1+...          #
    # ------------------------------------------------------------------ #
    global_stream = b"".join(
        skeletons[i] + b"".join(all_page_chunks[i])
        for i in range(n_pages)
    )
    xhtml_length = len(global_stream)
    total_text_length = xhtml_length + len(_CSS_FLOW)  # XHTML + CSS flow

    # ------------------------------------------------------------------ #
    # 3.  Byte offsets                                                     #
    # ------------------------------------------------------------------ #
    skel_starts: list[int] = []
    pos = 0
    for i in range(n_pages):
        skel_starts.append(pos)
        pos += len(skeletons[i]) + sum(len(c) for c in all_page_chunks[i])

    skel_lengths  = [len(s) for s in skeletons]
    chunk_lengths_per_page = [[len(c) for c in chunks] for chunks in all_page_chunks]

    abs_insert_positions = [
        skel_starts[i] + insert_positions_in_skel[i]
        for i in range(n_pages)
    ]

    # ------------------------------------------------------------------ #
    # 4.  Content records (XHTML stream + CSS flow appended)              #
    # ------------------------------------------------------------------ #
    content_records = _split_stream_into_records(global_stream + _CSS_FLOW)
    n_content_records = len(content_records)

    # ------------------------------------------------------------------ #
    # 5.  Image records                                                    #
    # ------------------------------------------------------------------ #
    image_records = [bytes(jpeg) for _, jpeg in images]
    n_images = len(image_records)

    # ------------------------------------------------------------------ #
    # 6.  INDX structures                                                  #
    # ------------------------------------------------------------------ #
    skel_records  = _build_skel_indx(skel_starts, skel_lengths, chunks_per_page=1)
    chunk_records = _build_chunk_indx(abs_insert_positions, chunk_lengths_per_page)

    # ------------------------------------------------------------------ #
    # 7.  FDST — flow 0: XHTML pages, flow 1: CSS                        #
    # ------------------------------------------------------------------ #
    fdst_record_data = _build_fdst_record([xhtml_length, len(_CSS_FLOW)])
    fdst_count = 2

    # ------------------------------------------------------------------ #
    # 8.  KF8 record layout (0-indexed relative to KF8 section base)     #
    #   KF8[0]       : MOBI8 header                                       #
    #   KF8[1..R]    : content records                                    #
    #   KF8[R+1..R+3]: CHUNK INDX (header + data + cncx)                 #
    #   KF8[R+4..R+5]: SKEL INDX  (header + data)                        #
    #   KF8[R+6]     : FDST  ← first_resource_record points here         #
    #   KF8[R+7]     : FLIS                                               #
    #   KF8[R+8]     : FCIS                                               #
    #   KF8[R+9]     : EOF                                                #
    #
    # Images live in the MOBI6 section (before BOUNDARY).  KF8 first_img #
    # points to FDST to signal "no KF8 image records".  The Kindle        #
    # firmware resolves kindle:embed:NNNN via MOBI6's first_img.          #
    # ------------------------------------------------------------------ #
    R = n_content_records

    chunk_idx     = R + 1
    skel_idx      = R + 4
    fdst_idx      = R + 6   # first_resource_record also = fdst_idx (no KF8 images)
    flis_idx      = R + 7
    fcis_idx      = R + 8
    eof_idx       = R + 9
    kf8_count     = eof_idx + 1

    # ------------------------------------------------------------------ #
    # 9.  Build KF8 record 0                                              #
    # ------------------------------------------------------------------ #
    record0 = _build_record0(
        text_length=xhtml_length,
        n_text_records=n_content_records,
        first_non_text_record=chunk_idx,
        first_resource_record=fdst_idx,   # points to FDST = no KF8 images
        fdst_record=fdst_idx,
        fdst_count=fdst_count,
        fcis_record=fcis_idx,
        flis_record=flis_idx,
        ncx_index=0xFFFFFFFF,
        chunk_index=chunk_idx,
        skel_index=skel_idx,
        metadata=metadata,
        manga=manga,
        num_images=n_images,
        target=target,
        n_pages=n_pages,
    )

    # ------------------------------------------------------------------ #
    # 10. Assemble KF8 records                                            #
    # ------------------------------------------------------------------ #
    kf8_records: list[bytes] = [record0]
    kf8_records.extend(content_records)
    kf8_records.extend(chunk_records)
    kf8_records.extend(skel_records)
    kf8_records.append(fdst_record_data)
    kf8_records.append(_build_flis_record())
    kf8_records.append(_build_kf8_fcis(xhtml_length))
    kf8_records.append(_build_eof_record())

    assert len(kf8_records) == kf8_count

    # ------------------------------------------------------------------ #
    # 11. MOBI6 section + BOUNDARY + KF8 = joint MOBI6+KF8 file          #
    # ------------------------------------------------------------------ #
    mobi6_records = _build_mobi6_section_records(
        image_records, metadata, manga=manga, target=target, n_pages=n_pages,
    )
    all_records = mobi6_records + [b'BOUNDARY'] + kf8_records

    # ------------------------------------------------------------------ #
    # 12. Write PalmDB container                                          #
    # ------------------------------------------------------------------ #
    total_records = len(all_records)
    pdb_name   = _safe_pdb_name(metadata.title)
    pdb_header = _build_palmdb_header(pdb_name, total_records)

    record_list_size  = total_records * _PDB_RECORD_ENTRY_LEN
    first_record_offset = _PDB_HEADER_LEN + record_list_size + 2

    record_list = io.BytesIO()
    cursor = first_record_offset
    for idx, rec in enumerate(all_records):
        record_list.write(struct.pack(">I", cursor))
        record_list.write(struct.pack(">I", (idx * 2) & 0xFFFFFF))
        cursor += len(rec)

    body = io.BytesIO()
    body.write(pdb_header)
    body.write(record_list.getvalue())
    body.write(b"\x00\x00")
    for rec in all_records:
        body.write(rec)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(body.getvalue())
