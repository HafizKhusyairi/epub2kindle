# Ch 5: AZW3 / KF8

AZW3 is Kindle Format 8 (KF8) — the modern Kindle format that enables Panel View and higher-quality rendering. It is significantly more complex than MOBI6. This chapter explains every major component of `_azw3_writer.py` and, where relevant, explains it through the bugs that were encountered when fields were wrong.

Reference material:
- [MobileRead KF8 wiki](https://wiki.mobileread.com/wiki/KF8) — community-maintained reverse-engineered spec
- [MobileRead MOBI wiki](https://wiki.mobileread.com/wiki/MOBI) — covers fields shared with MOBI6
- Python [`struct` module](https://docs.python.org/3/library/struct.html) — used throughout for binary packing/unpacking (`>` = big-endian)

---

## Why not pure KF8?

A pure KF8 file (no MOBI6 section) is not recognized by the Kindle's library scanner. The firmware requires the MOBI6 section to be present as a "header" that the library reads for metadata. The actual content is rendered from the KF8 section. This is why the format is called a **joint MOBI6+KF8** file.

---

## Structure of a joint file

```
PalmDB record list (one entry per record across both sections)
│
├── MOBI6 section
│   ├── Record 0:     MOBI6 header (264 bytes — extended for joint file)
│   ├── Records 1–T:  Compressed HTML text (placeholder for library compatibility)
│   ├── Records T+1–T+N: JPEG images (shared with KF8)
│   ├── FLIS record
│   ├── FCIS record
│   ├── EOF record
│   └── BOUNDARY record   ← 8-byte literal b"BOUNDARY"
│
└── KF8 section
    ├── Record 0:     MOBI8 header (264 bytes)
    ├── Records 1–C:  Compressed XHTML+CSS content
    ├── CHUNK INDX records (header + data + CNCX)
    ├── SKEL INDX records (header + data)
    ├── FDST record
    ├── FLIS record
    ├── FCIS record
    └── EOF record
```

The JPEG images are stored only once (in the MOBI6 section) and referenced from the KF8 content.

---

## The BOUNDARY record

```python
b"BOUNDARY"
```

The BOUNDARY record is exactly 8 bytes: the ASCII string `BOUNDARY`. Its record index in the PalmDB list is stored in the MOBI6 header as an EXTH record:

```python
_EXTH_KF8_BOUNDARY = 121
...
recs.append((_EXTH_KF8_BOUNDARY, struct.pack(">I", kf8_base)))
```

`kf8_base` is the absolute record index of the BOUNDARY record. Kindle firmware reads this EXTH field from the MOBI6 header to find the start of the KF8 section.

---

## Base-32 image references

In KF8, images are referenced by `kindle:embed:NNNN` URLs:

```html
<img src="kindle:embed:0001?mime=image/jpg"/>
```

`NNNN` is a 4-digit base-32 number. The alphabet is:

```python
_B32 = '0123456789ABCDEFGHIJKLMNOPQRSTUV'
```

Digits 0–9 are `0`–`9`; digits 10–31 are `A`–`V` (uppercase). The reference resolves to image record index `kf8_image_base + decode(NNNN) - 1` in the MOBI6 image section.

!!! warning "The lowercase bug"
    The original implementation used lowercase `a-v` for digits 10–31. The result: only the first 10 images displayed (digits 0–9 work in any case). Starting from image 11, the embed refs were invalid and the Kindle showed blank pages.
    The fix: change the alphabet constant from `'0123456789abcdefghijklmnopqrstuv'` to `'0123456789ABCDEFGHIJKLMNOPQRSTUV'`.

```python
def _to_base32(n: int) -> str:
    if n == 0:
        return '0'
    chars: list[str] = []
    while n:
        chars.append(_B32[n & 0x1F])
        n >>= 5
    return ''.join(reversed(chars))
```

For image index 1 (first image): `_to_base32(1).zfill(4)` → `"0001"`.

---

## The global text stream

The KF8 content is a single concatenated byte stream of XHTML:

```
[skeleton for page 0] [chunk for page 0]
[skeleton for page 1] [chunk for page 1]
...
[skeleton for page N] [chunk for page N]
[CSS]
```

This stream is split into 4096-byte chunks and each chunk is PalmDOC-compressed and stored as a content record.

### Skeleton: the empty HTML wrapper

```python
def _build_skeleton(page_num: int, aid_body: str, tw: int, th: int) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<!DOCTYPE html>'
        '<html ...>'
        '<head>...</head>'
        f'<body style="background-color:#000000;" aid="{aid_body}"></body>'
        '</html>'
    ).encode('utf-8')
```

The skeleton is an _empty_ HTML page. The body element has an `aid=` attribute — an identifier that the CHUNK INDX uses to tell the firmware where to inject the chunk content.

### Chunk: the image div

```python
def _build_image_chunk(*, aid_div: str, aid_amzn: str, embed_ref: str, iw: int, ih: int) -> bytes:
    return (
        f'\n<div style="text-align:center;" aid="{aid_div}">\n'
        f'<div style="display:none;" data-AmznRemoved="mobi7" aid="{aid_amzn}">.</div>\n'
        f'<img{dim} src="kindle:embed:{embed_ref}?mime=image/jpg"/>\n'
        f'</div>\n'
    ).encode('utf-8')
```

The chunk is what actually displays the image. It contains:
- An outer `<div>` with a center-align style and an `aid=` identifier
- A hidden `<div data-AmznRemoved="mobi7">` — this is a mobi7 compatibility placeholder. The `data-AmznRemoved` attribute signals to KF8 firmware that this element exists only for MOBI7 fallback compatibility and should be suppressed.
- The actual `<img>` tag with the `kindle:embed:NNNN` reference

### AID strings

Each element that needs to be indexed gets an `aid=` attribute (AID = Anchor ID). AIDs are base-32 encoded integers:

```python
_AIDS_PER_PAGE = 3   # body, image_div, mobi7_placeholder

# For page i:
aid_body  = _to_base32(i * 3 + 0)
aid_div   = _to_base32(i * 3 + 1)
aid_amzn  = _to_base32(i * 3 + 2)
```

The firmware uses AIDs to correlate CHUNK INDX entries to DOM nodes.

---

## TBS: trailing byte sequences

!!! warning "The white-screen bug"
    The original implementation produced white (blank) screens on the Kindle despite the file being structurally valid.
    Root cause: missing TBS bytes. Without them, the firmware reads the last 1–2 bytes of each compressed record as a TBS size value, strips that many bytes from the end of the record, and corrupts the content.

Each content record ends with exactly 2 TBS bytes:

```python
records.append(_palmdoc_compress(chunk) + b"\x00\x81")
```

The MOBI8 header declares this via `extra_data_flags=0b11` (bits 0 and 1):
- Bit 0: multibyte character overlap
- Bit 1: TBS (Trailing Byte Sequences)

The TBS bytes are stripped right-to-left:
1. `\x81` — backward-VIQE encoded size=1, strip 1 byte (the size byte itself — empty TBS)
2. `\x00` — multibyte: lower 2 bits = 0, strip 1 byte

The Kindle firmware strips TBS unconditionally in comic mode regardless of what `extra_data_flags` says. The bytes must be there.

---

## SKEL INDX

SKEL INDX is an index that tells the firmware the byte range of each skeleton in the global text stream.

One entry per page:

```python
for i in range(n):
    label = f"SKEL{i:010d}".encode()
    entry = (
        bytes([len(label)]) + label
        + bytes([0x0A])                       # control byte
        + _encint(chunks_per_page) + _encint(chunks_per_page)  # chunk count (written twice)
        + _encint(start) + _encint(length)    # skeleton byte range
        + _encint(start) + _encint(length)    # repeated (Calibre quirk)
    )
```

`start` and `length` are byte offsets in the global decompressed text stream.

Values are encoded with `_encint()` — VIQE (Variable Integer Quantity Encoding), where each byte contributes 7 bits and the last byte has its high bit set:

```python
def _encint(value: int) -> bytes:
    byts = bytearray()
    while True:
        byts.append(value & 0x7F)
        value >>= 7
        if value == 0:
            break
    byts[0] |= 0x80   # high bit on last byte
    byts.reverse()
    return bytes(byts)
```

---

## CHUNK INDX + CNCX

CHUNK INDX indexes the chunk content within each skeleton. The CNCX (Compiled NCX) pool holds the XPath strings that identify where each chunk is inserted.

### CNCX pool

For each chunk, the CNCX holds an XPath expression referencing the parent skeleton element by AID:

```python
aid = _to_base32(page_idx * _AIDS_PER_PAGE)   # the body element's AID
s = f"P-//*[@aid='{aid}']".encode()
```

This XPath means "the element with this AID in the parsed document". The firmware looks up the skeleton's DOM, finds the element with this AID, and inserts the chunk content there.

### CHUNK INDX entry

Each chunk entry encodes:

```python
label_val = abs_insert_positions[page_idx] + preceding_len
label = f"{label_val:010d}".encode()

entry = (
    bytes([len(label)]) + label
    + bytes([0x0F])              # control byte
    + _encint(cncx_offsets[i])  # offset into CNCX pool
    + _encint(page_idx)         # which skeleton (file number)
    + _encint(seq_num)          # global sequential chunk index
    + _encint(preceding_len)    # start position within skeleton's chunk block
    + _encint(chunk_len)        # this chunk's byte length
)
```

`abs_insert_positions[page_idx]` is the byte position in the global stream where the skeleton's `</body>` is — the insertion point for chunks.

---

## FDST: flow data section table

```python
def _build_fdst_record(flow_lengths: list[int]) -> bytes:
    out.write(b"FDST")
    out.write(struct.pack(">II", 12, n))   # header: offset=12, count=n
    offset = 0
    for size in flow_lengths:
        out.write(struct.pack(">II", offset, offset + size))   # start, end
        offset += size
```

FDST maps flow indices to byte ranges in the global stream:
- Flow 0: the XHTML content (all skeletons + chunks)
- Flow 1: the CSS (`@page`, `body` styles)

!!! warning "The text_length bug"
    The `text_length` field in the MOBI8 header and in the FCIS record must be set to the XHTML flow length only — **not** the total stream length including CSS.
    Using total length (XHTML + CSS) caused FCIS to report the wrong text size, which the firmware detected as a malformed file.

```python
xhtml_length = sum(len(s) + len(c) for s, c in zip(skeletons, chunks))
css_length = len(_CSS_FLOW)
flow_lengths = [xhtml_length, css_length]

# text_length → xhtml_length only
```

---

## Comic EXTH flags

The MOBI6 section of a joint file needs a specific set of EXTH records for the Kindle library scanner to classify the file as a comic:

| Type | Name | Value | Effect |
|------|------|-------|--------|
| 122 | COMIC_TRUE_1 | `b"true"` | Comic mode flag |
| 123 | COMIC_TYPE | `b"comic"` | Enables comic layout |
| 124 | COMIC_PANEL | `b"none"` | Panel view layout type |
| 126 | COMIC_RES | `b"1264x1680"` | Device viewport resolution |
| 127 | COMIC_TRUE_2 | `b"true"` | Comic mode flag |
| 128 | COMIC_TRUE_3 | `b"true"` | Comic mode flag |
| 129 | COMIC_THUMB | `b"kindle:embed:0001"` | Cover thumbnail ref |
| 542 | COMIC_MZON | `b"mzOn"` | Library indexing signal |
| 501 | CONTENT_TYPE | `b"PDOC"` | Personal document (not DRM-checked) |

`PDOC` (personal document) vs `EBOK` (ebook) matters: `EBOK` triggers a DRM verification check that sideloaded files fail. `PDOC` is the correct type for manually transferred files.

---

## The MOBI8 header (264 bytes)

The KF8 section's record 0 contains a 264-byte MOBI8 header. Key fields beyond what MOBI6 has:

```python
w32(chunk_index)      # orth_index = chunk_idx (KCC pattern)
...
w32(fdst_record)      # FDST record index
w32(fdst_count)       # number of flows = 2
w32(fcis_record)
w32(flis_record)
...
w32(0b11)             # extra_data_flags: TBS + multibyte
w32(ncx_index)        # 0xFFFFFFFF = none
w32(chunk_index)      # CHUNK INDX record index
w32(skel_index)       # SKEL INDX record index
```

The 264-byte size (vs 232 for MOBI6) accommodates the additional KF8 fields.

---

## `write_azw3()` assembly steps

Reading `write_azw3()` in the source reveals a numbered sequence:

1. Build per-page skeletons and chunks
2. Concatenate into a global XHTML stream + CSS stream
3. Compute skeleton and chunk byte positions (for SKEL/CHUNK INDX)
4. Split stream into 4096-byte PalmDOC-compressed records with TBS bytes
5. Build SKEL INDX records
6. Build CHUNK INDX + CNCX records
7. Build FDST record
8. Build KF8 FLIS/FCIS/EOF records
9. Build the MOBI6 section (header + placeholder HTML + images + FLIS/FCIS/EOF + BOUNDARY)
10. Build KF8 record 0 (MOBI8 header) — requires all KF8 record counts
11. Assemble all records in the joint order
12. Compute PalmDB offsets and write the file

This ordering is strict: you need step 4 to know how many content records exist before building the KF8 header in step 10, and you need all record sizes from both sections before computing offsets in step 12.
