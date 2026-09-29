"""Pure executable discovery shared with isolated provider workers."""

import os
import shutil
from pathlib import Path


def resolve_cli(binary: str) -> str | None:
    found = shutil.which(binary)
    if found:
        return str(Path(found).resolve())
    for directory in (
        Path.home() / '.local/bin',
        Path.home() / '.npm-global/bin',
        Path('/opt/homebrew/bin'),
        Path('/usr/local/bin'),
    ):
        candidate = directory / binary
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
    return None
