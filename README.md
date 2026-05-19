# epub2kindle

A command-line tool that converts EPUB files (especially comic / manga EPUBs) to Kindle-native **MOBI** files for USB sideloading.

Pure Python. No external binaries required.

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

Output files are written as `<source-stem>.mobi` next to the input (or to `--output-dir` if given).

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `-p`, `--profile` | Kindle device profile (see below) | `KPW5` |
| `-o`, `--output-dir` | Output directory | alongside input |
| `--manga` | Right-to-left reading order | off |
| `--webtoon` | Webtoon/manhwa mode (no double-page split) | off |
| `--no-hq` | Lower JPEG quality (smaller files) | HQ on |
| `--upscale` | Upscale images smaller than device res | off |
| `--stretch` | Stretch images to fill device res | off |
| `--splitter {0,1,2}` | Double-page handling: 0=split, 1=rotate, 2=both | `0` |
| `-g`, `--gamma FLOAT` | Gamma correction | `1.0` |
| `-t`, `--title` | Override title | from EPUB |
| `-a`, `--author` | Override author | from EPUB |
| `--dry-run` | Show resolved options without writing files | off |
| `--keep-temp` | Keep extracted image dir (debug) | off |
| `--fail-fast` | Abort batch on first error | off |
| `-v` / `-q` | Verbose / quiet | normal |

The `-c`/`--cropping` flag is accepted for compatibility but currently has no effect (smart cropping algorithms aren't reimplemented yet — see Limitations).

### Device profiles

Common profiles: `KPW5` (Paperwhite 5/Sig Edition, default), `KPW6`, `KO` (Oasis 2/3), `KS` (Scribe), `KS3` (Scribe 3), `K11` (Kindle 11), `KCS` (Colorsoft). Kobo and reMarkable profiles are also accepted (`KoL`, `KoF`, `KoE`, `Rmk2`, …).

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
  → epub.py        extract images from spine
  → image_processor   resize/grayscale/gamma with Pillow
  → mobi_writer    pack into MOBI6 binary
  → output.mobi
```

Output is **MOBI6** (file version 6). Every Kindle since 2007 reads MOBI6.

## Limitations

- **Tested on Kindle Paperwhite 5.** Other devices should work but haven't been verified.
- **No smart cropping.** KCC's page-number-aware cropping, FFT-based rainbow-artifact removal, and inter-panel gutter detection are not reimplemented. For clean digital manga (e.g. Fanatical bundles) this is fine; for low-quality scans you may want a different tool.
- **DRM-protected EPUBs are rejected** — by design.
- **Comic / manga focused.** Text-heavy EPUBs with reflowable content will be flattened to one image per page; that's not what you want.
