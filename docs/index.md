# epub2kindle — Developer Guide

This is not the user-facing README. This guide is for you, the developer — the person who needs to understand _why_ the code is shaped the way it is and how to keep it working.

The guide covers five topics, all taught through the actual codebase:

| Chapter | What you will learn |
|---------|---------------------|
| [Ch 1: Python Packaging](ch1-packaging/index.md) | How `pyproject.toml`, hatchling, and the `src/` layout work together |
| [Ch 2: CLI with argparse](ch2-cli/index.md) | How the command-line interface is structured and tested |
| [Ch 3: Version & Release](ch3-release/index.md) | How a git tag turns into four platform binaries on GitHub |
| [Ch 4: Unit Tests](ch4-testing/index.md) | How the test suite is written and how to extend it |
| [Ch 5: File Formats](ch5-formats/index.md) | EPUB, MOBI6, and AZW3/KF8 — the formats this app reads and writes |

## Reading order

If you are new to the project, read in chapter order. Chapter 5 (File Formats) is the longest and most technical — read the EPUB section first, then MOBI6, then AZW3.

## Serving this guide locally

Install the docs dependencies and start the live-reload server:

```bash
pip install -e ".[docs]"
mkdocs serve
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000). The page reloads whenever you save a `.md` file.

To build a static copy:

```bash
mkdocs build   # output goes to site/
```

## How it works (30-second version)

```
source.epub
  → epub.py           extract images from spine (ZIP → OPF → XHTML → img)
  → _image_processor  resize / grayscale / gamma with Pillow
  → _azw3_writer      pack into AZW3 (joint MOBI6+KF8) binary   [default]
  → _mobi_writer      pack into MOBI6 binary                     [--format MOBI]
  → output.azw3 / output.mobi
```

Pure Python. Pillow is the only runtime dependency — no `kindlegen`, no external converters.
