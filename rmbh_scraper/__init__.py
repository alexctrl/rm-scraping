"""Requests-based scraper/API for www.rmbhimoveis.com.br listings."""

from .client import RENT, SALE, RMBHClient
from .crawler import Crawler

__all__ = ["RMBHClient", "Crawler", "RENT", "SALE"]


def _detect_version() -> str:
    # release zips carry a stamped _version.py (see .github/workflows/release.yml)
    try:
        from ._version import version

        return version
    except ImportError:
        pass
    # a git checkout: derive it from the nearest vX.Y.Z tag
    import subprocess
    from pathlib import Path

    try:
        out = subprocess.run(
            ["git", "describe", "--tags", "--match", "v[0-9]*", "--dirty", "--always"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
        return out[1:] if out.startswith("v") else f"0.0.0+{out}"
    except (OSError, subprocess.SubprocessError):
        return "0.0.0+desconhecida"


__version__ = _detect_version()
