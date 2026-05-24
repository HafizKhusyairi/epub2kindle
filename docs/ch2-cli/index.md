# Ch 2: CLI with argparse

This chapter walks through the command-line interface in `src/epub2kindle/cli.py` by following one real invocation — `epub2kindle --dry-run /some/folder/` — through every function it touches.

If you are new to argparse, read the [argparse tutorial](https://docs.python.org/3/howto/argparse.html) first. The [full argparse reference](https://docs.python.org/3/library/argparse.html) covers every option.

---

## Two entry points

There are two ways to invoke the tool:

```bash
epub2kindle file.epub          # installed script (from [project.scripts])
python -m epub2kindle file.epub  # module run
```

Both call the same function: `epub2kindle.cli.main()`.

**The installed script** (`epub2kindle`) is created by pip when you run `pip install .`. It's a small wrapper that calls the entry point declared in `pyproject.toml`:

```toml
[project.scripts]
epub2kindle = "epub2kindle.cli:main"
```

**The module run** (`python -m epub2kindle`) works because of `src/epub2kindle/__main__.py`:

```python
from .cli import main
main()
```

The `__main__.py` file is Python's hook for `python -m <package>`. It's two lines: import `main` and call it. Nothing else.

---

## Why `_make_parser()` is separate from `main()`

```python
def _make_parser() -> argparse.ArgumentParser:
    ...

def main(argv: list[str] | None = None) -> None:
    parser = _make_parser()
    args = parser.parse_args(argv)
    ...
```

If `main()` called `argparse.parse_args()` directly with no `argv` parameter, tests would need to spawn a subprocess to call the CLI. By accepting an `argv` list, tests can call `main(argv=["--dry-run", str(path)])` directly — no subprocess, no disk overhead, full control over inputs and captured output.

The `test_cli.py` tests _do_ use subprocess, but that's a deliberate choice for smoke-testing the installed entry point. See [Ch 4: Unit Tests](../ch4-testing/index.md) for the distinction.

---

## `argparse` field by field

Let's look at representative arguments to understand the argparse API:

### Positional argument (required)

```python
parser.add_argument(
    "files",
    nargs="+",           # one or more values
    metavar="FILE_OR_DIR",
    help="EPUB file(s) or folder(s) containing EPUBs (top-level only).",
)
```

- `nargs="+"`: one or more positional arguments, collected into a list (`args.files`)
- `metavar`: the name shown in `--help` output (overrides the ugly uppercase `FILES`)
- No `--` prefix: this is positional, not optional

### Flag with choices

```python
parser.add_argument(
    "--format",
    choices=["MOBI", "AZW3"],
    default="AZW3",
    help="Output format: AZW3/KF8 (default) or MOBI6.",
)
```

- `choices`: argparse rejects any value not in this list with a clear error
- `default`: if `--format` is not given, `args.format == "AZW3"`

### Boolean flag

```python
parser.add_argument(
    "--manga",
    action="store_true",
    help="Manga mode: when splitting landscape spreads, output right half before left.",
)
```

- `action="store_true"`: `args.manga` is `False` by default, `True` if `--manga` is passed

### Numeric flag with metavar

```python
parser.add_argument(
    "-c", "--cropping",
    type=int,
    default=2,
    choices=[0, 1, 2],
    metavar="{0,1,2}",
    help="Cropping: 0=off, 1=margins, 2=margins+page nums (default: 2).",
)
```

- `-c` is the short form; `--cropping` is the long form — both set `args.cropping`
- `type=int`: argparse converts the string to int and validates it
- `metavar="{0,1,2}"`: overrides the default `choices` display in help (which would show `{0,1,2}` in a less readable way)

### Mutually exclusive group

```python
verbosity = parser.add_mutually_exclusive_group()
verbosity.add_argument("-v", "--verbose", action="store_true", ...)
verbosity.add_argument("-q", "--quiet", action="store_true", ...)
```

Only one of `-v` and `-q` can be passed at a time. argparse enforces this and prints an error if both are given.

---

## Directory expansion: `_expand_paths()`

```python
def _expand_paths(raw_args: list[str]) -> list[Path]:
    paths: list[Path] = []
    for arg in raw_args:
        p = Path(arg)
        if p.is_dir():
            found = sorted(p.glob("*.epub"))
            if not found:
                log.error("No EPUB files found in directory: %s", p)
                sys.exit(1)
            paths.extend(found)
        else:
            paths.append(p)
    return paths
```

If an argument is a directory, glob `*.epub` in it (top-level only — no recursion). If the directory is empty of EPUBs, log the error and exit with code 1 immediately. This is the "fail early on bad input" pattern.

---

## The spinner

The spinner is an animated progress indicator on stderr, implemented as a daemon thread (see [`threading.Thread`](https://docs.python.org/3/library/threading.html#threading.Thread)):

```python
@contextlib.contextmanager
def _spinner(label: str, enabled: bool = True):
    if not enabled or not sys.stderr.isatty():
        yield
        return
    stop = threading.Event()

    def _spin():
        frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        for f in itertools.cycle(frames):
            if stop.is_set():
                break
            sys.stderr.write(f"\r{f} {label}")
            sys.stderr.flush()
            time.sleep(0.08)
        sys.stderr.write(f"\r{' ' * (len(label) + 3)}\r")
        sys.stderr.flush()

    t = threading.Thread(target=_spin, daemon=True)
    t.start()
    try:
        yield
    finally:
        stop.set()
        t.join()
```

Key design decisions:

**`daemon=True`**: A [daemon thread](https://docs.python.org/3/library/threading.html#threading.Thread.daemon) is killed when the main thread exits. Without this, if the conversion raises an uncaught exception and the process is about to die, the spinner thread would keep it alive indefinitely waiting for its next iteration.

**`stop = threading.Event()`**: [`threading.Event`](https://docs.python.org/3/library/threading.html#threading.Event) is a simple flag with thread-safe `.set()` and `.is_set()` methods. The spinner checks `stop.is_set()` each frame. The `finally` block sets it and calls `t.join()` — so the spinner always cleans up (erases itself from stderr) whether the conversion succeeded or failed.

**`sys.stderr.isatty()` guard**: The spinner must only run when stderr is a real terminal. In CI, when piped through `grep`, or when the output is captured (as in tests), `isatty()` returns `False` and the spinner is skipped entirely. Without this guard, test output would contain raw spinner characters.

The `@contextlib.contextmanager` decorator ([docs](https://docs.python.org/3/library/contextlib.html#contextlib.contextmanager)) is what makes `_spinner()` usable with `with`. Everything before `yield` is setup; everything after (in `finally`) is teardown — exactly analogous to `__enter__` and `__exit__` on a class.

**Used as a context manager**: Wraps the pipeline call:

```python
with _spinner(f"{counter}Converting  {epub_path.name}…", enabled=not args.quiet):
    outputs = _pipeline.run(extracted.image_dir, opts, source_epub=epub_path)
```

---

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | All conversions succeeded |
| `1` | Bad input, missing file, empty directory, env error |
| `2` | One or more conversions failed (but execution continued) |

The distinction between 1 and 2 matters for scripting: a caller can check `$?` and know whether the failure was a usage error or a runtime failure.

```python
if failed:
    sys.exit(2)
```

Note that `sys.exit(2)` is called _after_ the loop, not inside it. This allows all files to be attempted even if one fails — unless `--fail-fast` was passed, which adds a `break` inside the loop.

---

## `--dry-run`: inspect without writing

```python
if args.dry_run:
    from . import epub as epub_mod
    from dataclasses import replace as _dreplace

    for epub_path in epub_paths:
        try:
            extracted = epub_mod.extract(epub_path)
            ...
            print(f"[dry-run] {epub_path}")
            print(f"  profile={opts.profile}  title={opts.title!r}  author={opts.author!r}")
            ...
```

`--dry-run` calls `epub_mod.extract()` (reads the EPUB, extracts metadata) but never calls `_pipeline.run()` (no image processing, no file writing). This lets you verify that the EPUB is readable and see what options will be used — without producing any output files.

---

## Logging

```python
log = logging.getLogger("epub2kindle")
...
level = logging.WARNING if args.quiet else (logging.DEBUG if args.verbose else logging.INFO)
logging.basicConfig(format="%(levelname)s: %(message)s", level=level)
```

The package uses Python's standard [`logging`](https://docs.python.org/3/library/logging.html) module, not `print()`. If you have never used it before, the [logging HOWTO](https://docs.python.org/3/howto/logging.html) is a good starting point. The key idea: you log messages at a level (DEBUG, INFO, WARNING, ERROR) and configure once at the top of the program which levels to display. This means:

- You can silence it (`-q`) without patching `sys.stdout`
- Third-party code that imports epub2kindle as a library can configure logging their own way
- Tests can capture log output using pytest's `caplog` fixture
