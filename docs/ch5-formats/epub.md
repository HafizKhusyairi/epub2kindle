# Ch 5: EPUB

EPUB is the input format. `epub.py` reads it and produces a directory of sequentially numbered images.

The [EPUB 3 overview](https://www.w3.org/TR/epub-overview-33/) on W3C is the authoritative spec. For the older EPUB 2 format (which most manga EPUBs use), see the [IDPF EPUB 2 spec](https://idpf.org/epub/201). This chapter focuses on what epub2kindle actually parses — a subset of EPUB 2 that is sufficient for comic/manga content.

---

## EPUB is a ZIP file

An EPUB file is a ZIP archive with a `.epub` extension. You can rename any `.epub` to `.zip` and open it with any archive tool.

```python
zf = zipfile.ZipFile(epub_path, "r")
```

This is the first line of `extract()`. Python's [`zipfile`](https://docs.python.org/3/library/zipfile.html) module reads ZIP archives without any external tools. If the file is not a valid ZIP, `zipfile.BadZipFile` is raised and converted to `MalformedEpubError`.

---

## Fixed entry point: `META-INF/container.xml`

Every EPUB has this file at this exact path. It's the only fixed location in the format — everything else can be at arbitrary paths. `container.xml` names the OPF file:

```xml
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf"
              media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
```

All XML parsing uses Python's built-in [`xml.etree.ElementTree`](https://docs.python.org/3/library/xml.etree.elementtree.html). In code:

```python
def _get_opf_path(zf: zipfile.ZipFile) -> str:
    container_xml = zf.read("META-INF/container.xml")
    root = ET.fromstring(container_xml)
    rootfile = root.find(".//container:rootfile", _NS)
    return rootfile.get("full-path")   # → "OEBPS/content.opf"
```

---

## The OPF file: manifest + spine + metadata

The OPF (Open Packaging Format) file is the table of contents for the EPUB. It has three parts:

### Manifest: id → file path

```xml
<manifest>
  <item id="page0" href="page0.xhtml" media-type="application/xhtml+xml"/>
  <item id="img0"  href="images/image0.png" media-type="image/png"/>
  ...
</manifest>
```

The manifest maps every file ID to its path inside the ZIP. In code:

```python
for item in manifest_ns:
    item_id = item.get("id")
    href = item.get("href")
    resolved = _resolve_href(opf_dir, href)
    manifest[item_id] = resolved    # {"page0": "OEBPS/page0.xhtml", ...}
```

### Spine: reading order by ID

```xml
<spine>
  <itemref idref="page0"/>
  <itemref idref="page1"/>
  <itemref idref="page2"/>
</spine>
```

The spine lists item IDs in the order they should be read. The manifest maps those IDs to XHTML file paths. In code:

```python
spine_idrefs = [item.get("idref") for item in spine_el]
```

### Metadata: title, author, language

```xml
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
  <dc:title>My Manga</dc:title>
  <dc:creator>Artist Name</dc:creator>
  <dc:language>ja</dc:language>
</metadata>
```

---

## Three-level image lookup

Finding the images requires three nested lookups:

```
OPF spine  →  itemref idref="page0"
OPF manifest  →  id="page0" href="page0.xhtml"
XHTML content  →  <img src="images/image0.png"/>
```

```python
for idref in spine_idrefs:
    xhtml_path = manifest.get(idref)          # level 1: spine → XHTML path
    xhtml_data = zf.read(xhtml_path)
    for img_path in _collect_images_from_xhtml(xhtml_data, xhtml_path):  # level 2+3
        if img_path not in seen:
            ordered_images.append(img_path)
```

`_collect_images_from_xhtml()` parses the XHTML and finds `<img src="...">` and `<svg:image href="...">` elements. It handles three namespace variants because EPUB publishers are inconsistent:

```python
for tag in ("xhtml:img", "img", "{http://www.w3.org/1999/xhtml}img"):
    for el in root.iter(tag):
        ...
```

---

## Resolving relative paths

Image hrefs in XHTML are relative to the XHTML file's location. An image at `images/image0.png` in an XHTML file at `OEBPS/page0.xhtml` resolves to `OEBPS/images/image0.png` in the ZIP.

```python
def _resolve_href(base_dir: str, href: str) -> str:
    href = unquote(href)    # decode %20 → space, etc.
    if base_dir:
        return posixpath.normpath(posixpath.join(base_dir, href))
    return posixpath.normpath(href)
```

[`posixpath.normpath`](https://docs.python.org/3/library/posixpath.html) collapses `./` and `../` components. [`urllib.parse.unquote`](https://docs.python.org/3/library/urllib.parse.html#urllib.parse.unquote) handles percent-encoded characters — some EPUB publishers encode spaces as `%20` in hrefs.

---

## DRM detection

```python
def _check_drm(zf: zipfile.ZipFile) -> None:
    try:
        enc_xml = zf.read("META-INF/encryption.xml")
    except KeyError:
        return    # no encryption.xml → not DRM protected
    root = ET.fromstring(enc_xml)
    ns = {"enc": "http://www.w3.org/2001/04/xmlenc#"}
    if root.findall(".//enc:EncryptedData", ns):
        raise EncryptedEpubError("This EPUB is DRM-protected...")
```

The presence of `encryption.xml` alone is not enough — some EPUBs include an empty `encryption.xml` for structural reasons. The file must contain `<enc:EncryptedData>` elements to be considered DRM-protected.

---

## Output: numbered images in a temp directory

After extraction, images are written to a temporary directory as `0000.png`, `0001.png`, etc.:

```python
for idx, img_zip_path in enumerate(ordered_images):
    data = zf.read(img_zip_path)
    orig_ext = PurePosixPath(img_zip_path).suffix
    ext = _sniff_extension(data, orig_ext)
    filename = f"{idx:04d}{ext}"
    dest = tmp_path / filename
    dest.write_bytes(data)
```

`_sniff_extension()` uses PIL to detect the actual image format if the file extension is missing or wrong — some EPUBs use `.img` or no extension for images.

The `ExtractedEpub` dataclass holds the path to this temp directory, along with metadata. The caller is responsible for calling `extracted.cleanup()` when done.

---

## Code walkthrough summary

| Function | What it does |
|----------|-------------|
| `extract(epub_path)` | Main entry point — orchestrates everything |
| `_check_drm(zf)` | Reject DRM-protected EPUBs |
| `_get_opf_path(zf)` | Read `container.xml` → OPF path |
| `_parse_opf(zf, opf_path)` | Parse OPF XML → ElementTree root |
| `_collect_images_from_xhtml(data, path)` | Parse XHTML → list of resolved image paths |
| `_resolve_href(base_dir, href)` | Resolve relative path + decode percent-encoding |
| `_sniff_extension(data, ext)` | Detect image format from bytes if extension is unreliable |
