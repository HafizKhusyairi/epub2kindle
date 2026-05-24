# Ch 4: Unit Tests

This chapter explains how the test suite is structured, the core pattern it uses, and how to add new tests. The key technique — building in-memory EPUB files from scratch in a factory function — teaches both testing craft and EPUB format knowledge simultaneously.

If you are new to pytest, the [pytest getting-started guide](https://docs.pytest.org/en/stable/getting-started.html) covers installation and your first test. The [how-to guides](https://docs.pytest.org/en/stable/how-to/index.html) cover specific topics as you need them.

---

## Running the tests

```bash
pip install -e ".[dev]"   # install pytest
pytest                     # run all tests
pytest -v                  # verbose (show each test name)
pytest tests/test_epub_extract.py   # run one file
pytest -k "test_basic"              # run tests matching a pattern
```

pytest discovers tests by finding files named `test_*.py` and functions named `test_*`. No configuration is needed — it works out of the box.

---

## `conftest.py`: shared fixtures

`tests/conftest.py` is a special file that pytest loads automatically before any tests in the same directory. It's where you put shared fixtures.

```python
@pytest.fixture
def make_epub(tmp_path):
    def _factory(**kwargs) -> pathlib.Path:
        data = build_epub(**kwargs)
        p = tmp_path / "test.epub"
        p.write_bytes(data)
        return p
    return _factory
```

A [`@pytest.fixture`](https://docs.pytest.org/en/stable/explanation/fixtures.html) is a function that pytest calls and injects as a parameter when a test declares it by name.

**`tmp_path`**: A [pytest built-in fixture](https://docs.pytest.org/en/stable/how-to/tmp_path.html) that provides a fresh temporary directory for each test. It's automatically cleaned up after the test completes. Always prefer `tmp_path` over `tempfile.mkdtemp()` — pytest manages the lifecycle for you.

**Factory fixture pattern**: `make_epub` doesn't return a Path directly; it returns a _callable_ (`_factory`). The test then calls it with keyword arguments:

```python
def test_basic_extraction(make_epub):
    p = make_epub(title="My Book", num_pages=3)
    ...
```

This lets one fixture handle many different configurations without separate fixture functions for each case.

---

## `build_epub()`: the in-memory EPUB builder

This is the heart of the test suite. It builds a complete, valid EPUB as a bytes object in memory:

```python
def build_epub(
    *,
    title: str = "Test Book",
    author: str = "Test Author",
    language: str = "en",
    num_pages: int = 2,
    image_subdir: str = "",
    percent_encode_images: bool = False,
    opf_subdir: str = "",
    include_encryption_xml: bool = False,
    include_encrypted_data: bool = False,
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr(opf_path, opf_content)
        # ... one XHTML page and one PNG per page
    return buf.getvalue()
```

**Why in-memory builders beat binary fixture files:**

Consider the alternative: keeping `test_basic.epub`, `test_nested_opf.epub`, `test_percent_encoded.epub`, etc. as binary files in `tests/data/`. Problems:

1. You can't see what's inside them without a tool
2. Changing the EPUB structure requires regenerating binary files
3. Edge cases require separate files — the collection grows
4. A single keyword argument to `build_epub()` covers all variants:

```python
build_epub(opf_subdir="OEBPS")           # OPF nested in subdirectory
build_epub(percent_encode_images=True)   # URLs with %20 encoding
build_epub(include_encryption_xml=True, include_encrypted_data=True)  # DRM
```

One factory function, nine test cases, zero binary files. (There is one real `.epub` in `tests/data/tiny.epub`, kept as a smoke test against a real-world EPUB.)

**[`io.BytesIO()`](https://docs.python.org/3/library/io.html#io.BytesIO) + [`zipfile.ZipFile`](https://docs.python.org/3/library/zipfile.html#zipfile.ZipFile)**: EPUB is a ZIP file. `io.BytesIO()` is an in-memory byte buffer that acts like a file handle. `zipfile.ZipFile(buf, "w")` writes ZIP entries to it without touching disk.

---

## Testing the happy path

```python
def test_basic_extraction(tmp_path):
    p = write_epub(tmp_path, build_epub(title="My Book", author="Alice", num_pages=3))
    result = extract(p)
    try:
        assert result.title == "My Book"
        assert result.authors == ["Alice"]
        assert result.language == "en"
        images = sorted(result.image_dir.iterdir())
        assert len(images) == 3
    finally:
        result.cleanup()
```

The `try/finally` ensures `result.cleanup()` is always called, even if an assertion fails. `cleanup()` removes the temporary directory that `extract()` created. Without this, temporary directories would accumulate during a test run.

---

## Testing error paths with `pytest.raises`

```python
def test_encrypted_epub_raises(tmp_path):
    p = write_epub(
        tmp_path,
        build_epub(include_encryption_xml=True, include_encrypted_data=True),
    )
    with pytest.raises(EncryptedEpubError):
        extract(p)
```

[`pytest.raises(SomeError)`](https://docs.pytest.org/en/stable/reference/reference.html#pytest.raises) is a context manager that asserts the block raises exactly that exception class. If no exception is raised, the test fails. If a different exception is raised, the test fails with the unexpected error.

You can also check the error message:

```python
with pytest.raises(ConversionError, match="No images found"):
    run_kcc(image_dir, opts)
```

`match=` is a regex applied to the string representation of the exception. Use it when the error type alone isn't specific enough.

---

## Testing binary file layout

`test_runner.py` reads the raw bytes of the output file and asserts on their content — bypassing the Python API entirely:

```python
def test_run_kcc_palmdb_signature(tmp_path):
    ...
    data = out.read_bytes()
    assert data[60:64] == b"BOOK", "PalmDB type should be BOOK"
    assert data[64:68] == b"MOBI", "PalmDB creator should be MOBI"
```

```python
def test_run_kcc_mobi_version_in_header(tmp_path):
    ...
    data = out.read_bytes()
    first_rec_offset = struct.unpack(">L", data[78:82])[0]
    mobi_version = struct.unpack(">L", data[first_rec_offset + 36:first_rec_offset + 40])[0]
    assert mobi_version == 6
```

This matters because:

- A test that calls `write_mobi()` and checks that a file was created only verifies the Python API
- A test that reads bytes 60-68 verifies the _file layout_ — what a Kindle firmware actually sees

If you accidentally swap the byte order of a field, or write it at the wrong offset, the Python API still works fine but the firmware can't read the file. Binary assertions catch this class of bug.

**[`struct.unpack(">L", data[78:82])`](https://docs.python.org/3/library/struct.html#struct.unpack)**: Read 4 bytes at offset 78 as a big-endian unsigned long. The `>` means big-endian (network byte order), `L` means unsigned long (4 bytes). MOBI uses big-endian throughout. The [struct format characters](https://docs.python.org/3/library/struct.html#format-characters) table lists all type codes.

---

## Subprocess tests vs direct `main()` tests

`test_cli.py` uses `subprocess.run()`:

```python
result = subprocess.run(
    [sys.executable, "-m", "epub2kindle", "--dry-run", str(tiny_epub)],
    capture_output=True,
    text=True,
    cwd=str(Path(__file__).parent.parent),
)
assert "dry-run" in result.stdout
```

**Why subprocess here?** These tests verify the entry point as an end-user would use it — they catch packaging bugs like a missing `__main__.py` or a broken entry point script. The `cwd` is set to the project root so Python can find the source installation.

**The tradeoff**: subprocess tests are slower (new Python interpreter per call), harder to debug (no stack trace on failure), and can't easily check internal state. Use them for smoke tests of the installed interface; use direct `main(argv=[...])` calls for unit tests of argument parsing.

---

## Coverage gaps

The current test suite covers:
- EPUB extraction (10 tests, including all error paths)
- Options validation (7 tests)
- Pipeline end-to-end with MOBI output (5 tests)
- CLI smoke tests (4 tests)

**Not covered:**
- AZW3 writer output (`_azw3_writer.py` — the most complex module)
- Image processor (`_image_processor.py` — grayscale, gamma, resize, landscape split)
- Multi-image ordering with a real manga EPUB

To add an AZW3 test, follow the pattern in `test_runner.py` but pass `output_format="AZW3"` to `Options` and assert on the binary layout (look for the `BOUNDARY` record, check that `data[60:64] == b"BOOK"`, etc.).
