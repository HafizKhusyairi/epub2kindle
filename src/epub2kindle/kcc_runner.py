from __future__ import annotations

import contextlib
import io
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from .errors import ConversionError
from .options import Options


def run_kcc(image_dir: Path, options: Options, source_epub: Path | None = None) -> list[Path]:
    final_dir = Path(options.output_dir) if options.output_dir else (source_epub.parent if source_epub else image_dir.parent)
    final_dir.mkdir(parents=True, exist_ok=True)

    # Use a private temp dir for KCC output so we can cleanly identify what it produced
    with TemporaryDirectory(prefix="epub2kindle-out-") as tmp_out:
        tmp_out_path = Path(tmp_out)

        # Point options at the temp output dir
        from dataclasses import replace
        tmp_opts = replace(options, output_dir=tmp_out_path)
        argv = tmp_opts.to_kcc_argv(image_dir)

        try:
            import kindlecomicconverter.comic2ebook as c2e
            with contextlib.redirect_stdout(io.StringIO()):
                c2e.main(argv)
        except SystemExit as e:
            if e.code not in (None, 0):
                raise ConversionError(f"KCC exited with code {e.code}") from e
        except Exception as e:
            raise ConversionError(f"KCC raised an exception: {e}") from e

        produced = list(tmp_out_path.iterdir())

        # Drop intermediate EPUBs when targeting MOBI
        if options.output_format == "MOBI":
            produced = [f for f in produced if f.suffix.lower() != ".epub"]

        # Move results to the final destination
        final_paths: list[Path] = []
        for f in produced:
            dest = final_dir / f.name
            shutil.move(str(f), dest)
            final_paths.append(dest)

    return sorted(final_paths)
