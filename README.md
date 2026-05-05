# epub2kindle

Convert EPUB files to Kindle-optimized MOBIs via [Kindle Comic Converter (KCC)](https://github.com/ciromattia/kcc).

Linux only. Designed for comic and manga EPUBs.

## Requirements

- Python 3.10+
- `p7zip-full` system package (`sudo apt install p7zip-full`)
- `kindlegen` binary on `PATH` (required for MOBI output)
  - Amazon discontinued public downloads; obtain `kindlegen_linux_2.6_i386_v2_9.tar.gz` from the Internet Archive
  - Extract and install:
    ```bash
    tar xzf kindlegen_linux_2.6_i386_v2_9.tar.gz kindlegen
    mv kindlegen ~/.local/bin/
    ```
## Installation

```bash
git clone https://github.com/YOUR_USERNAME/epub2kindle.git
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

# Dry run — show KCC argv without converting
epub2kindle --dry-run my-manga.epub
```

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `-p`, `--profile` | Kindle device profile | `KPW5` |
| `-o`, `--output-dir` | Output directory | alongside input |
| `--manga` | Right-to-left reading order | off |
| `--webtoon` | Webtoon mode | off |
| `--no-hq` | Disable high-quality upscaling | HQ on |
| `--upscale` | Upscale images smaller than device res | off |
| `--gamma FLOAT` | Gamma correction (default: auto) | auto |
| `--cropping INT` | 0=off, 1=margins, 2=margins+page nums | `2` |
| `-t`, `--title` | Override title (default: from EPUB) | EPUB metadata |
| `-a`, `--author` | Override author (default: from EPUB) | EPUB metadata |
| `--dry-run` | Print KCC argv, don't convert | off |
| `--keep-temp` | Keep extracted image dir (debug) | off |
| `--fail-fast` | Abort batch on first error | off |
| `-v` / `-q` | Verbose / quiet | normal |

## Exit codes

- `0` — all conversions succeeded
- `1` — usage error
- `2` — one or more conversions failed

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
