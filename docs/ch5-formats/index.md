# Ch 5: File Formats — Overview

epub2kindle reads one format (EPUB) and writes one of two formats (MOBI6 or AZW3). This chapter introduces all three and explains their relationship.

---

## The three formats

| Format | Role | Writer |
|--------|------|--------|
| EPUB | Input — what you download from the internet | `epub.py` (reader) |
| MOBI6 | Output — legacy format, every Kindle since 2007 | `_mobi_writer.py` |
| AZW3 / KF8 | Output — modern format, enables Panel View | `_azw3_writer.py` |

---

## How the pipeline chooses

In `_pipeline.py`:

```python
if options.output_format == "AZW3":
    _azw3_writer.write_azw3(
        images, metadata, output_path,
        manga=options.manga,
        target=profile_resolution(options.profile),
    )
else:
    _mobi_writer.write_mobi(images, metadata, output_path, manga=options.manga)
```

The default is AZW3 (set in `cli.py`). Pass `--format MOBI` to get MOBI6.

---

## The container they share: PalmDB

Both MOBI6 and AZW3 use the same outermost container format: **PalmDB** (Palm Database). This is a database format originally designed for Palm OS handhelds in the late 1990s. Kindle carried it forward for backwards compatibility.

A PalmDB file is a flat array of _records_, each containing arbitrary bytes. The file starts with a 78-byte header describing the database, then a record list (8 bytes per record, containing offsets), then the record data.

Think of it as a simple file that contains multiple files (records), referenced by sequential index.

---

## MOBI6 vs AZW3: what actually differs

MOBI6 is simple:
- One record per text chunk (HTML)
- One record per image
- A few bookkeeping records (FLIS, FCIS)

AZW3 is a _joint file_ — it contains a complete MOBI6 section followed by a KF8 section in the same PalmDB record list, separated by a literal `BOUNDARY` record. Kindle firmware detects this and uses the KF8 section for rendering; older software that doesn't understand KF8 falls back to MOBI6.

```
PalmDB record list
  ├── MOBI6 section records
  │     ├── record 0:   MOBI6 header
  │     ├── records 1–N: HTML text chunks
  │     ├── records N+1–M: JPEG images   ← shared with KF8
  │     ├── FLIS / FCIS / EOF
  │     └── BOUNDARY record   ← 8-byte literal "BOUNDARY"
  └── KF8 section records
        ├── record 0:   MOBI8 header
        ├── records 1–P: XHTML content chunks
        ├── SKEL INDX records
        ├── CHUNK INDX + CNCX records
        ├── FDST record
        ├── FLIS / FCIS / EOF
```

The images are stored only once — in the MOBI6 section — and referenced from the KF8 content via `kindle:embed:NNNN` URLs.

---

## Reading guide for this chapter

- **[EPUB](epub.md)**: Start here. This is the input format. Understand how `epub.py` reads it.
- **[MOBI6](mobi6.md)**: The simpler output format. Understand PalmDB, records, and the MOBI header.
- **[AZW3 / KF8](azw3.md)**: The full story. Understand the joint format, content indexing, and why specific fields exist.
