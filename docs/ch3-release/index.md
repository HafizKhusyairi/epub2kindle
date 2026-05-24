# Ch 3: Version & Release

This chapter traces a single `git tag v0.3.0 && git push origin v0.3.0` through every downstream artifact: version bump → commit → tag → GitHub Actions → four platform binaries → GitHub Release.

---

## Semantic versioning

Version numbers follow the [Semantic Versioning](https://semver.org/) specification (`MAJOR.MINOR.PATCH`):

| Part | When to bump | Example |
|------|-------------|---------|
| MAJOR | Breaking change to the Python API or CLI flags | `0.x.y` → `1.0.0` |
| MINOR | New feature, backwards-compatible | `0.2.0` → `0.3.0` |
| PATCH | Bug fix, no new features | `0.2.0` → `0.2.1` |

For this project, a "breaking change" means existing scripts that call `epub2kindle` or `epub2kindle.convert()` would stop working. Adding a new `--flag` is a minor change. Fixing a bug in the AZW3 writer is a patch.

---

## Single source of truth

The version is defined in exactly one place:

```python
# src/epub2kindle/_version.py
__version__ = "0.2.0"
```

To release a new version:

```bash
# 1. Edit _version.py
#    Change "0.2.0" to "0.3.0"

# 2. Commit
git add src/epub2kindle/_version.py
git commit -m "bump version to 0.3.0"

# 3. Tag
git tag v0.3.0

# 4. Push both the commit and the tag
git push origin main
git push origin v0.3.0
```

The tag push triggers GitHub Actions. That's all — nothing else needs to change.

---

## The release workflow: `release.yml`

If you are new to GitHub Actions, the [Understanding GitHub Actions](https://docs.github.com/en/actions/about-github-actions/understanding-github-actions) overview explains the key concepts: workflows, jobs, steps, and runners.

```yaml
on:
  workflow_dispatch:   # manual trigger from the GitHub Actions tab
  push:
    tags:
      - 'v*'          # any tag starting with v
```

**Two triggers** (see [events that trigger workflows](https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows)):
- `push: tags: ['v*']` — fires automatically when you push a `v*` tag
- `workflow_dispatch` — lets you manually trigger the workflow from the GitHub Actions tab, useful for testing the workflow itself without pushing a real tag

```yaml
permissions:
  contents: write
```

The workflow needs write permission to create a GitHub Release and upload files. Without this, the `softprops/action-gh-release` step would fail with a 403.

---

## Build matrix: four jobs in parallel

The [matrix strategy](https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/running-variations-of-jobs-in-a-workflow) runs one job per entry in `matrix.include`, each on a different runner, in parallel.

```yaml
jobs:
  build:
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        include:
          - os: ubuntu-latest
            artifact_name: epub2kindle
            asset_name: epub2kindle-linux

          - os: windows-latest
            artifact_name: epub2kindle.exe
            asset_name: epub2kindle-windows.exe

          - os: macos-latest
            artifact_name: epub2kindle
            asset_name: epub2kindle-macos-arm64

          - os: macos-13
            artifact_name: epub2kindle
            asset_name: epub2kindle-macos-x86_64
```

**`fail-fast: false`**: If the Windows build fails, the Linux and macOS builds continue. Without this setting, GitHub cancels all running jobs as soon as any one job fails — losing the already-completed Linux binary.

**`macos-latest` vs `macos-13`**: GitHub's `macos-latest` runner is ARM64 (Apple Silicon). `macos-13` is the last Intel (x86_64) runner. Using both produces native binaries for both architectures without any cross-compilation.

**`artifact_name` vs `asset_name`**: PyInstaller always names the output after the spec's `name=` field (`epub2kindle` or `epub2kindle.exe`). The matrix variables are used to rename it to the platform-specific asset name before uploading.

---

## PyInstaller: what it does

[PyInstaller](https://pyinstaller.org/en/stable/) bundles your Python script + all its dependencies + the Python interpreter itself into a single executable file. Users do not need Python installed.

The build chain for each platform:

```
pip install .                    # install the package
pip install pyinstaller          # install the bundler
pyinstaller epub2kindle.spec     # build the binary
```

The `.spec` file controls exactly what goes into the bundle.

---

## The `.spec` file

The `.spec` file is a Python script that PyInstaller executes to learn what to bundle. See the [spec file docs](https://pyinstaller.org/en/stable/spec-files.html) for the full reference.

```python
_pil_hidden = collect_submodules('PIL')
_pil_exclude = {
    'PIL.ImageTk', 'PIL._imagingtk', 'PIL._tkinter_finder',
    'PIL.ImageQt', 'PIL.ImageGrab', 'PIL.ImageWin', 'PIL.PSDraw',
}
hidden_imports = [m for m in _pil_hidden if m not in _pil_exclude]
```

Pillow has many sub-modules for GUI integrations (Tkinter, Qt, Windows GDI) that PyInstaller can't auto-detect as unused. `collect_submodules('PIL')` finds them all; the exclusion set removes the GUI ones, since epub2kindle is a CLI tool.

```python
a = Analysis(
    ['_entry.py'],            # entry point script
    ...
    hiddenimports=hidden_imports,
    excludes=['tkinter', '_tkinter', 'unittest', 'test', 'distutils'],
    ...
)
```

**`excludes`**: Tkinter is explicitly excluded to save ~10 MB. `unittest`, `test`, and `distutils` are excluded for the same reason — they're never used at runtime.

```python
exe = EXE(
    ...
    name='epub2kindle',
    strip=False,      # strip=True can break macOS binaries
    upx=False,        # UPX unavailable on CI runners; triggers Windows Defender false positives
    target_arch=None, # inherits from build host: ARM64 on macos-latest, x86_64 on macos-13
    ...
)
```

- **`strip=False`**: On macOS, stripping the binary can corrupt the code signature that Apple's security framework expects. Safe to leave off.
- **`upx=False`**: UPX compresses executables, but it's not installed on GitHub-hosted runners. More importantly, Windows Defender flags UPX-packed binaries as suspicious. Better to skip it.
- **`target_arch=None`**: Inherit the architecture from the build host. On `macos-latest` (ARM64 runner) this produces an ARM64 binary; on `macos-13` (x86_64 runner) it produces an x86_64 binary. No cross-compilation flags needed.

---

## `_entry.py` vs `__main__.py`

The spec uses `_entry.py` as the entry point, not `__main__.py`. Why?

```python
# _entry.py
from epub2kindle.cli import main

if __name__ == '__main__':
    main()
```

```python
# src/epub2kindle/__main__.py
from .cli import main
main()
```

`__main__.py` uses a _relative import_ (`from .cli`). Relative imports work inside a package but break when a file is run directly as a script (`python _entry.py`). PyInstaller runs the entry point file as a script, so it needs absolute imports. `_entry.py` exists solely for this reason.

---

## The rename step

PyInstaller always names the output after `name='epub2kindle'` in the spec. The rename step in the workflow gives it a platform-specific name before uploading:

```yaml
- name: Rename artifact (Linux / macOS)
  if: runner.os != 'Windows'
  run: mv dist/epub2kindle dist/${{ matrix.asset_name }}
```

So `dist/epub2kindle` becomes `dist/epub2kindle-linux` (or `-macos-arm64`, etc.) before the upload step.

---

## Uploading to GitHub Releases

```yaml
- name: Upload to GitHub Release
  uses: softprops/action-gh-release@v2
  with:
    files: dist/${{ matrix.asset_name }}
    fail_on_unmatched_files: true
```

`softprops/action-gh-release` creates a GitHub Release (if one doesn't exist for this tag) and uploads the file. Because four jobs run in parallel, all four binaries are uploaded to the same release, each from its own runner.

`fail_on_unmatched_files: true` makes the step fail if the file doesn't exist — catching renames or path errors early instead of silently uploading nothing.
