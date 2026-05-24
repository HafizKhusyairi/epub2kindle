# epub2kindle

A vibe-coded, open-source command-line tool that converts comic / manga EPUB files — individually or in batch — to Kindle-native **AZW3** files for USB sideloading.

Pure Python. No proprietary dependencies, no external binaries.

## Download

Download a standalone executable from the [Releases page](https://github.com/HafizKhusyairi/epub2kindle/releases). No Python required.

| Platform | File |
|----------|------|
| Linux | `epub2kindle-linux` |
| Windows | `epub2kindle-windows.exe` |
| macOS (Apple Silicon) | `epub2kindle-macos-arm64` |
| macOS (Intel) | `epub2kindle-macos-x86_64` |

**Linux/macOS:** make the file executable after downloading, then run it:

```bash
chmod +x epub2kindle-linux   # or epub2kindle-macos-arm64 / epub2kindle-macos-x86_64
./epub2kindle-linux my-manga.epub
```

**Windows:** run it directly from a command prompt:

```cmd
epub2kindle-windows.exe my-manga.epub
```

## Installation from source

Requires Python 3.10+. Pillow is installed automatically. No `kindlegen`, no `7z`, no Kindle Comic Converter.

```bash
git clone https://github.com/HafizKhusyairi/epub2kindle.git
cd epub2kindle
pip install .
```

## Usage

```bash
# Convert a single file
epub2kindle my-manga.epub

# Convert all EPUBs in a folder (top-level only)
epub2kindle /path/to/folder/

# Batch with options
epub2kindle --manga --profile KPW5 -o ~/Kindle/ vol1.epub vol2.epub

# Dry run — show resolved options without converting
epub2kindle --dry-run my-manga.epub
```

Output files are written as `<source-stem>.azw3` next to the input (or to `--output-dir` if given).

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `-p`, `--profile` | Kindle device profile (see below) | `KPW5` |
| `-o`, `--output-dir` | Output directory | alongside input |
| `--format {MOBI,AZW3}` | Output format: AZW3/KF8 or MOBI6 | `AZW3` |
| `--manga` | Right-to-left reading order | off |
| `-c`, `--cropping {0,1,2}` | Cropping: 0=off, 1=margins, 2=margins+page nums | `2` |
| `--no-hq` | Lower JPEG quality (smaller files) | HQ on |
| `--upscale` | Upscale images smaller than device res | off |
| `--stretch` | Stretch images to fill device res | off |
| `-g`, `--gamma FLOAT` | Gamma correction | `1.0` |
| `-t`, `--title` | Override title | from EPUB |
| `-a`, `--author` | Override author | from EPUB |
| `--dry-run` | Show resolved options without writing files | off |
| `--keep-temp` | Keep extracted image dir (debug) | off |
| `--fail-fast` | Abort batch on first error | off |
| `-v` / `-q` | Verbose / quiet | normal |

### Device profiles

Common Kindle profiles: `KPW5` (Paperwhite 5/Sig Edition, default), `KPW6`, `KO` (Oasis 2/3), `KS` (Scribe), `KS3` (Scribe 3), `K11` (Kindle 11), `KCS` (Colorsoft). Kobo profiles are also accepted (`KoL`, `KoF`, `KoE`, `KoA`, …).

> **Kobo users:** Kobo does not read AZW3. Pass `--format MOBI` to produce a MOBI file that Kobo can open.

Run `epub2kindle --profile BOGUS my.epub` to see the full list in the error message, or check `_PROFILE_RESOLUTIONS` in `src/epub2kindle/options.py`.

## Python API

```python
from epub2kindle import convert, convert_batch, Options

# Single file
paths = convert("my-manga.epub", Options(manga=True))

# Batch
results = convert_batch(["vol1.epub", "vol2.epub"], Options(output_dir="/tmp/kindle"))
for epub, outcome in results.items():
    if isinstance(outcome, Exception):
        print(f"FAILED {epub}: {outcome}")
    else:
        print(f"OK {epub} → {outcome}")
```

## Exit codes

- `0` — all conversions succeeded
- `1` — usage error
- `2` — one or more conversions failed

## How it works

```
source.epub
  → epub.py           extract images from spine
  → image_processor   resize/grayscale/gamma with Pillow
  → azw3_writer       pack into AZW3 (joint MOBI6+KF8) binary   [default]
  → mobi_writer       pack into MOBI6 binary                     [--format MOBI]
  → output.azw3 / output.mobi
```

The default output is **AZW3** (joint MOBI6+KF8), which enables Panel View on supported Kindles. Pass `--format MOBI` to produce a plain MOBI6 file instead; every Kindle since 2007 reads both formats.

## Limitations

- **Tested on Kindle Paperwhite 5.** Other devices should work but haven't been verified.
- **No smart cropping.** The `--cropping` flag is accepted and the crop level is stored, but the cropping pass is not yet applied during image processing.
- **DRM-protected EPUBs are rejected** — by design.
- **Comic / manga focused.** Text-heavy EPUBs with reflowable content will be flattened to one image per page; that's not what you want.
