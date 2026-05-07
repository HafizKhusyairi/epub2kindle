from __future__ import annotations

import argparse
import contextlib
import itertools
import logging
import sys
import threading
import time
from pathlib import Path

from .errors import Epub2KindleError
from .options import Options

log = logging.getLogger("epub2kindle")


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


def _make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="epub2kindle",
        description="Convert EPUB files to Kindle MOBI6 for USB sideloading.",
    )
    parser.add_argument(
        "files",
        nargs="+",
        metavar="FILE_OR_DIR",
        help="EPUB file(s) or folder(s) containing EPUBs (top-level only).",
    )
    parser.add_argument(
        "-p", "--profile",
        default="KPW5",
        metavar="PROFILE",
        help="Kindle device profile (default: KPW5).",
    )
    parser.add_argument(
        "-o", "--output-dir",
        metavar="DIR",
        help="Output directory (default: alongside input file).",
    )
    parser.add_argument(
        "--manga",
        action="store_true",
        help="Right-to-left reading order.",
    )
    parser.add_argument(
        "--webtoon",
        action="store_true",
        help="Webtoon/manhwa mode.",
    )
    parser.add_argument(
        "--no-hq",
        action="store_true",
        help="Disable high-quality JPEG encoding.",
    )
    parser.add_argument(
        "--two-panel",
        action="store_true",
        help="Landscape two-panel mode.",
    )
    parser.add_argument(
        "--splitter",
        type=int,
        default=0,
        choices=[0, 1, 2],
        metavar="{0,1,2}",
        help="Double-page handling: 0=split, 1=rotate, 2=both (default: 0).",
    )
    parser.add_argument(
        "-u", "--upscale",
        action="store_true",
        help="Upscale images smaller than device resolution.",
    )
    parser.add_argument(
        "--stretch",
        action="store_true",
        help="Stretch images to fill device resolution.",
    )
    parser.add_argument(
        "-g", "--gamma",
        type=float,
        metavar="FLOAT",
        help="Gamma correction (default: 1.0).",
    )
    parser.add_argument(
        "-c", "--cropping",
        type=int,
        default=2,
        choices=[0, 1, 2],
        metavar="{0,1,2}",
        help="Cropping: 0=off, 1=margins, 2=margins+page nums (default: 2).",
    )
    parser.add_argument(
        "-t", "--title",
        metavar="TEXT",
        help="Override title (default: from EPUB metadata).",
    )
    parser.add_argument(
        "-a", "--author",
        metavar="TEXT",
        help="Override author (default: from EPUB metadata).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List inputs and resolved options without writing any files.",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep extracted image directory after conversion (for debugging).",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Abort batch on first failure.",
    )
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output.",
    )
    verbosity.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress non-error output.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _make_parser()
    args = parser.parse_args(argv)

    level = logging.WARNING if args.quiet else (logging.DEBUG if args.verbose else logging.INFO)
    logging.basicConfig(format="%(levelname)s: %(message)s", level=level)

    options = Options(
        profile=args.profile,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        manga=args.manga,
        webtoon=args.webtoon,
        hq=not args.no_hq,
        two_panel=args.two_panel,
        splitter=args.splitter,
        upscale=args.upscale,
        stretch=args.stretch,
        gamma=args.gamma,
        cropping=args.cropping,
        title=args.title,
        author=args.author,
    )

    epub_paths = _expand_paths(args.files)

    if not args.dry_run:
        from . import preflight
        try:
            preflight.check_environment(options)
        except Epub2KindleError as e:
            log.error("%s", e)
            sys.exit(1)

    if args.dry_run:
        from . import epub as epub_mod
        from dataclasses import replace as _dreplace

        for epub_path in epub_paths:
            try:
                extracted = epub_mod.extract(epub_path)
                opts = options
                if options.title is None and extracted.title:
                    opts = _dreplace(opts, title=extracted.title)
                if options.author is None and extracted.authors:
                    opts = _dreplace(opts, author=extracted.authors[0])
                print(f"[dry-run] {epub_path}")
                print(f"  profile={opts.profile}  title={opts.title!r}  author={opts.author!r}")
                print(f"  images_dir={extracted.image_dir}")
                if not args.keep_temp:
                    extracted.cleanup()
            except Epub2KindleError as e:
                log.error("%s: %s", epub_path, e)
        return

    total = len(epub_paths)
    failed = 0
    for idx, epub_path in enumerate(epub_paths, 1):
        counter = f"[{idx}/{total}] " if total > 1 else ""
        try:
            from . import epub as epub_mod, _pipeline
            from dataclasses import replace as _dreplace

            log.info("%sExtracting  %s", counter, epub_path.name)
            extracted = epub_mod.extract(epub_path)
            try:
                opts = options
                if options.title is None and extracted.title:
                    opts = _dreplace(opts, title=extracted.title)
                if options.author is None and extracted.authors:
                    opts = _dreplace(opts, author=extracted.authors[0])

                with _spinner(f"{counter}Converting  {epub_path.name}…", enabled=not args.quiet):
                    outputs = _pipeline.run(extracted.image_dir, opts, source_epub=epub_path)

                for out in outputs:
                    log.info("%sOK          %s → %s", counter, epub_path.name, out.name)
            finally:
                if not args.keep_temp:
                    extracted.cleanup()
        except Epub2KindleError as e:
            log.error("%sFAILED      %s: %s", counter, epub_path.name, e)
            failed += 1
            if args.fail_fast:
                break
        except Exception as e:
            log.error("%sFAILED      %s: unexpected error: %s", counter, epub_path.name, e)
            failed += 1
            if args.fail_fast:
                break

    if failed:
        sys.exit(2)
