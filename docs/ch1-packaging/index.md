# Ch 1: Python Packaging

This chapter explains how epub2kindle is packaged as a Python project — how the files are laid out, how `pip install` works, and how the version number flows from one file to the rest of the world.

If you are new to Python packaging, the [Packaging Python Projects tutorial](https://packaging.python.org/en/latest/tutorials/packaging-projects/) on the Python Packaging User Guide (PyPUG) is the recommended starting point. This chapter assumes you have skimmed it and focuses on the specific choices made in this codebase.

---

## The `src/` layout

The source code lives under `src/epub2kindle/`, not `epub2kindle/` at the root. This one-level indirection matters.

**Why it matters:** When you run `python` in the project root without installing anything, Python adds `.` to `sys.path`. If the package lived at `epub2kindle/` in the root, you could accidentally import it from the working tree — bypassing any packaging logic, ignoring the installed version, getting confused about which code is running. The `src/` prefix means a plain `python` invocation in the project root can never accidentally import the package; only the _installed_ copy is importable.

See the [src layout vs flat layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/) discussion on PyPUG for the full trade-off analysis.

**How to install it for development:**

```bash
pip install -e .          # editable install — changes take effect immediately
pip install -e ".[dev]"   # editable + pytest
pip install -e ".[docs]"  # editable + mkdocs
```

The `-e` ([editable install](https://pip.pypa.io/en/stable/topics/local-project-installs/#editable-installs)) flag tells pip to install a pointer into `src/epub2kindle/` rather than copying files. Your changes are visible immediately without reinstalling.

---

## `pyproject.toml` — field by field

This is the single configuration file for the project. Let's walk through each section. The canonical reference is [Writing your pyproject.toml](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/) on PyPUG.

### `[build-system]`

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

This declares the _build backend_ — the tool that turns your source tree into a distributable `.whl` file. We use **[hatchling](https://hatch.pypa.io/latest/config/build/)**, which has sensible defaults and zero-config dynamic versioning. The alternative is `setuptools`, which is older and more verbose. See the [build system section](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#declaring-the-build-backend) of the PyPUG guide for more options.

### `[project]`

```toml
[project]
name = "epub2kindle"
dynamic = ["version"]
description = "Convert EPUBs to Kindle MOBI6 for USB sideloading."
readme = "README.md"
license = { text = "ISC" }
requires-python = ">=3.10"
dependencies = [
    "Pillow>=9.3.0",
]
```

- `name`: the package name on PyPI and in `pip install`.
- `dynamic = ["version"]`: the version is _not_ a static string here — it is read from a file at build time. See the versioning section below.
- `requires-python`: pip enforces this. Users on Python 3.9 will get a clear error.
- `dependencies`: Pillow is the only runtime dependency. Everything else is stdlib. This is intentional — no external binary tools required. See [specifying dependencies](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#dependencies-optional-dependencies) on PyPUG for the full syntax, including version constraints like `>=9.3.0`.

### `[project.scripts]`

```toml
[project.scripts]
epub2kindle = "epub2kindle.cli:main"
```

This is the [entry point](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#creating-executable-scripts). When pip installs the package, it creates an executable script (on Linux/macOS: `~/.local/bin/epub2kindle`, on Windows: a `.exe` wrapper). That script calls `epub2kindle.cli.main()`.

You can verify this after installation:

```bash
which epub2kindle        # → ~/.local/bin/epub2kindle
cat $(which epub2kindle) # → #!/usr/bin/env python ... epub2kindle.cli:main
```

### `[project.optional-dependencies]`

```toml
[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-mock>=3.0",
]
dist = [
    "pyinstaller>=6.0",
    "pyinstaller-hooks-contrib>=2024.0",
]
docs = [
    "mkdocs>=1.6",
    "mkdocs-material>=9.5",
]
```

Optional dependency groups are [extras](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#dependencies-optional-dependencies). Install with `pip install -e ".[dev]"`. The groups are:

- `dev`: test tools (pytest) — used during development
- `dist`: PyInstaller — used when building standalone binaries for a release
- `docs`: MkDocs — used when writing or reading this guide

These are not installed by default so users who just want to convert EPUBs don't get testing tools.

### `[tool.hatch.version]`

```toml
[tool.hatch.version]
path = "src/epub2kindle/_version.py"
```

Hatchling reads the `__version__` variable from `_version.py` at build time and uses it as the package version. This is called _dynamic versioning_ — see [hatchling's version source docs](https://hatch.pypa.io/latest/version/) for other options (e.g., reading from a `__init__.py` or a `VERSION` file).

### `[tool.hatch.build.targets.wheel]`

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/epub2kindle"]
```

This tells hatchling to include the `src/epub2kindle/` directory in the wheel, and to strip the `src/` prefix so the installed package is just `epub2kindle`, not `src.epub2kindle`.

---

## Dynamic versioning: `_version.py`

The version lives in exactly one place:

```python
# src/epub2kindle/_version.py
__version__ = "0.2.0"
```

That's the whole file.

**At build time**, hatchling reads this file and embeds the version string in the wheel's metadata.

**At runtime**, the public `__init__.py` imports it:

```python
from ._version import __version__
```

So `epub2kindle.__version__` works after installation, and the version is never duplicated.

**To bump the version**: edit `_version.py`, commit, tag. That's all. Nothing else changes.

---

## The public API: `__init__.py`

`src/epub2kindle/__init__.py` defines what users see when they `import epub2kindle`.

### `__all__`

```python
__all__ = [
    "__version__",
    "Options",
    "convert",
    "convert_batch",
    "Epub2KindleError",
    "ConversionError",
    "EncryptedEpubError",
    "MalformedEpubError",
    "OutputDirError",
]
```

[`__all__`](https://docs.python.org/3/tutorial/modules.html#importing-from-a-package) is the _explicit_ public surface. Any name not in `__all__` is still importable by path (Python does not enforce privacy), but it signals "this is not part of the stable API." The `_pipeline`, `_mobi_writer`, and `_azw3_writer` modules are not in `__all__` and are not re-exported here.

### Deferred imports inside functions

```python
def convert(epub_path: str | Path, options: Options | None = None) -> list[Path]:
    from . import epub as epub_mod
    from . import _pipeline, preflight
    ...
```

The heavy imports (`epub`, `_pipeline`) happen inside the function, not at module level. This matters for PyInstaller startup time — the binary starts faster if it doesn't load Pillow just to import `epub2kindle`.

### Frozen dataclass with `replace()`

```python
opts = options
if options.title is None and extracted.title:
    opts = replace(opts, title=extracted.title)
```

`Options` is a [frozen dataclass](https://docs.python.org/3/library/dataclasses.html#frozen-instances) (see `options.py`). You can't mutate it — instead, [`dataclasses.replace()`](https://docs.python.org/3/library/dataclasses.html#dataclasses.replace) creates a copy with specific fields changed. This makes the conversion pipeline side-effect-free: the caller's `Options` object is never modified.

---

## The naming convention: public vs private

| Pattern | Example | Meaning |
|---------|---------|---------|
| No underscore | `epub.py`, `options.py`, `cli.py` | Public module, importable |
| Leading underscore | `_mobi_writer.py`, `_pipeline.py`, `_image_processor.py` | Internal module, not part of the stable API |

The underscore convention is Python's only privacy mechanism. It's a signal to other developers (including future you) that these modules may change without notice. The public API is only what's in `__init__.py.__all__`.
