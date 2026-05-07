from __future__ import annotations

import os
from pathlib import Path

from .errors import OutputDirError
from .options import Options


def check_environment(options: Options) -> None:
    if options.output_dir is not None:
        out = Path(options.output_dir)
        if not out.exists():
            try:
                out.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                raise OutputDirError(
                    f"Cannot create output directory {out}: {e}"
                ) from e
        if not os.access(out, os.W_OK):
            raise OutputDirError(f"Output directory is not writable: {out}")


def reset_preflight_cache() -> None:
    """No-op kept for backwards compatibility."""
    return None
