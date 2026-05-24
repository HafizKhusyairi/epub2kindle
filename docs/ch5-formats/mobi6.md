# Ch 5: MOBI6

MOBI6 is the legacy Kindle format. It's simpler than AZW3 and supported by every Kindle since 2007. This chapter explains the binary layout of the file produced by `_mobi_writer.py`.

The [MobileRead MOBI wiki page](https://wiki.mobileread.com/wiki/MOBI) is the best community reference for the format. The [PalmDB wiki page](https://wiki.mobileread.com/wiki/PDB) covers the outer container. Python's [`struct` module](https://docs.python.org/3/library/struct.html) is used throughout to read and write binary fields — if you haven't used it before, review the [format characters table](https://docs.python.org/3/library/struct.html#format-characters) and note that `>` means big-endian.

---

## PalmDB: the outer container

Every MOBI file is a PalmDB (Palm Database) file. PalmDB is a simple record-based format:

```
[PalmDB header — 78 bytes]
[Record list   — 8 bytes × N records]
[Gap           — 2 bytes (always 0x0000)]
[Record 0 data]
[Record 1 data]
...
[Record N data]
```

The 78-byte header identifies the file type (`BOOK`) and creator (`MOBI`). The record list is an array where each entry is: 4-byte absolute byte offset of the record + 4-byte attribute/UID field.

**The key constraint**: record offsets must be written _before_ any record data, but you don't know the offset of record N until you know the sizes of records 0 through N-1. This is why `write_mobi()` builds all records first, then computes offsets:

```python
cursor = first_record_offset
for idx, rec in enumerate(all_records):
    record_list.write(struct.pack(">L", cursor))    # offset
    record_list.write(struct.pack(">L", (idx * 2) & 0xFFFFFF))  # attr
    cursor += len(rec)
```

---

## Record layout

```python
# Step 4 in write_mobi():
# rec 0:        header
# rec 1..N:     compressed text
# rec N+1..N+M: images  (first_nonbook = first_image)
# rec N+M+1:    FLIS
# rec N+M+2:    FCIS
# rec N+M+3:    EOF

first_image_record = 1 + n_text
flis_idx = first_image_record + n_images
fcis_idx = flis_idx + 1
eof_idx  = fcis_idx + 1
```

For a 5-page comic (5 images, 1 text record):

| Record # | Content |
|----------|---------|
| 0 | PalmDOC header + MOBI header + EXTH + title |
| 1 | Compressed HTML (all pages, one text chunk) |
| 2 | JPEG image for page 1 |
| 3 | JPEG image for page 2 |
| 4 | JPEG image for page 3 |
| 5 | JPEG image for page 4 |
| 6 | JPEG image for page 5 |
| 7 | FLIS |
| 8 | FCIS |
| 9 | EOF |

---

## Record 0: the three-part header

Record 0 contains three concatenated structures:

```python
record = palmdoc + mobi_header + exth + title_bytes
```

### PalmDOC header (16 bytes)

```python
struct.pack(
    ">HHLHHHH",
    2,                    # compression: 2 = PalmDOC format
    0,                    # unused
    text_length,          # UNCOMPRESSED text length
    text_record_count,    # number of text records
    4096,                 # max record size
    0,                    # encryption: 0 = none
    0,                    # unknown
)
```

`text_length` is the uncompressed size. The firmware decompresses each text record and uses this value to know when it has the complete text.

### MOBI header (232 bytes)

The MOBI header starts with the 4-byte magic `MOBI` and contains all the record indices and offsets the firmware needs:

Key fields (byte offsets relative to start of MOBI header):

| Offset | Field | Value |
|--------|-------|-------|
| 0x00 | Magic | `b"MOBI"` |
| 0x04 | Header length | 232 |
| 0x14 | File version | 6 |
| 0x40 | First non-book record | = first_image_record |
| 0x5c | First image record | = first_image_record |
| 0x70 | EXTH flags | 0x50 (EXTH present) |
| 0xb8 | FCIS record number | = fcis_idx |
| 0xc0 | FLIS record number | = flis_idx |
| 0xe0 | extra_data_flags | 1 (overlap byte present) |

The `extra_data_flags` field is critical. Bit 0 set means each text record ends with a 1-byte "overlap count". In practice this byte is always `\x00` for ASCII HTML, but the firmware reads it to know how many bytes to skip at the record boundary when decompressing across records.

---

## HTML: the text content

The MOBI6 HTML is one document with one `<div>` per image:

```python
f'<div style="margin:0;padding:0;page-break-after:always"><img recindex="{n:05d}" style="display:block"/></div>'
```

`recindex="N"` is the MOBI-specific attribute that tells the renderer which image record to display. It is 1-based (starts at 1, not 0) and refers to an offset from `first_image_record`. So `recindex="00001"` means image record `first_image_record + 1 - 1 = first_image_record`.

---

## PalmDOC compression

The HTML is compressed before being stored:

```python
compressed = _palmdoc_compress(html)
text_records = [chunk + b"\x00" for chunk in _split_text_records(compressed)]
```

PalmDOC compression is a simple encoding. The rules for decompression:
- `0x00`: literal NUL byte
- `0x01`–`0x08`: length prefix — the next N bytes are literals
- `0x09`–`0x7F`: literal byte (passes through unchanged)
- `0x80`–`0xBF`: LZ77 back-reference (we never emit these)
- `0xC0`–`0xFF`: space shorthand (we never emit these)

Our implementation only uses the literal rules — bytes that don't fall in `0x09`–`0x7F` get wrapped in a length-prefixed escape. This is valid because PalmDOC decoders must handle all encodings, and the literal-only form is a correct subset. Modern Kindle firmware refuses `compression=1` (uncompressed) for MOBI6 records but happily accepts `compression=2` with no back-references.

Each text record is split at 4096 bytes and gets a trailing `\x00` (the overlap byte declared by `extra_data_flags=1`).

---

## EXTH: metadata key-value pairs

EXTH is a variable-length block of typed records appended after the MOBI header:

```
b"EXTH"          4 bytes  magic
total_length      4 bytes  total EXTH block length including header
record_count      4 bytes  number of records

[for each record:]
type              4 bytes  record type code
length            4 bytes  total length including type+length fields (= 8 + len(value))
value             length-8 bytes  record value
```

The block is padded to a 4-byte boundary with `\x00` bytes.

Key EXTH types used:

| Type | Name | Example value |
|------|------|---------------|
| 100 | Author | `b"Artist Name"` |
| 503 | Title | `b"My Manga"` |
| 524 | Language | `b"ja"` |
| 525 | Writing mode | `b"horizontal-rl"` (manga) |
| 204–207 | Creator soft/maj/min/build | match KindleGen values |

The `horizontal-rl` writing mode tells the Kindle to flip the reading direction for manga (right-to-left page progression).

---

## FLIS and FCIS

These are fixed-layout bookend records required by Kindle firmware:

**FLIS** (36 bytes): a fixed constant. Its bytes are the same for every MOBI file. The format is not documented; the values were reverse-engineered by matching KindleGen output.

**FCIS** (44 bytes): contains the uncompressed text length:

```python
def _build_fcis_record(text_length: int) -> bytes:
    return (
        b"FCIS"
        + struct.pack(">I", 20)   # constant
        + struct.pack(">I", 16)   # constant
        ...
        + struct.pack(">I", text_length)  # ← matches PalmDOC header
        ...
    )
```

The `text_length` in FCIS must match the `text_length` in the PalmDOC header. Mismatches can cause the firmware to display empty pages or fail to open the file.

---

## EOF marker

The last record is 4 bytes: `b"\xe9\x8e\x0d\x0a"`. This is the Mobipocket end-of-file sentinel. Without it, some older Kindle firmware may report the file as truncated.

---

## The assembly in `write_mobi()`

Reading `write_mobi()` in order reveals a two-pass structure:

**Pass 1** — build all record data:
```python
html = _build_html(len(images))
compressed = _palmdoc_compress(html)
text_records = [chunk + b"\x00" for chunk in _split_text_records(compressed)]
image_records = [bytes(jpeg) for _, jpeg in images]
flis_record_data = _build_flis_record()
fcis_record_data = _build_fcis_record(uncompressed_text_length)
eof_record = _build_eof_record()
```

**Compute indices** (now we know how many records of each type):
```python
first_image_record = 1 + n_text
flis_idx = first_image_record + n_images
...
```

**Build record 0** (needs all indices):
```python
record0 = _build_record0(..., first_image_record=first_image_record, flis_record=flis_idx, ...)
```

**Pass 2** — compute offsets and assemble:
```python
cursor = first_record_offset
for rec in all_records:
    record_list.write(struct.pack(">L", cursor))
    cursor += len(rec)
```

This ordering is mandatory. You can't write the record list until you know the size of every record, and you can't build record 0 until you know `first_image_record`.
