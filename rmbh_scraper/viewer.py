"""Serve the slideshow viewer (viewer/index.html) together with the data directory.

URL layout served on http://127.0.0.1:<port>/ :
    /viewer/...  -> <project>/viewer/
    /data/...    -> the crawl's data directory (listings.json + images/)
so the viewer's default `../data/listings.json` works for any --data-dir.
"""

from __future__ import annotations

import errno
import functools
import logging
import os
import posixpath
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

log = logging.getLogger(__name__)

VIEWER_DIR = Path(__file__).resolve().parent.parent / "viewer"


class _Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, mounts: dict[str, Path], **kw):
        self.mounts = mounts
        super().__init__(*args, directory=str(VIEWER_DIR), **kw)

    def translate_path(self, path: str) -> str:
        path = posixpath.normpath(unquote(urlsplit(path).path))
        parts = [p for p in path.split("/") if p and p not in (".", "..")]
        if not parts:
            return str(VIEWER_DIR / "index.html")
        root = self.mounts.get(parts[0])
        if root is None:
            return str(VIEWER_DIR / "__missing__")
        return str(root.joinpath(*parts[1:]))

    def do_GET(self) -> None:  # noqa: N802
        if urlsplit(self.path).path in ("", "/"):
            self.send_response(302)
            self.send_header("Location", "/viewer/")
            self.end_headers()
            return
        super().do_GET()

    def end_headers(self) -> None:
        if self.path.endswith(".json"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt: str, *args) -> None:  # keep the console quiet
        log.debug("viewer: " + fmt, *args)


def _bind(handler, host: str, port: int) -> ThreadingHTTPServer:
    for p in [port, *range(port + 1, port + 20), 0]:
        try:
            return ThreadingHTTPServer((host, p), handler)
        except OSError as e:
            if e.errno != errno.EADDRINUSE:
                raise
    raise OSError("nenhuma porta livre encontrada")


def serve(data_dir: str | Path = "data", host: str = "127.0.0.1", port: int = 8000, open_browser: bool = True) -> None:
    """Serve the viewer and block until Ctrl+C."""
    if not (VIEWER_DIR / "index.html").exists():
        raise FileNotFoundError(f"apresentação não encontrada em {VIEWER_DIR}")
    data_dir = Path(data_dir).resolve()
    if not (data_dir / "listings.json").exists():
        log.warning("%s ainda não tem listings.json; execute `crawl` primeiro", data_dir)
    handler = functools.partial(_Handler, mounts={"viewer": VIEWER_DIR, "data": data_dir})
    httpd = _bind(handler, host, port)
    url = f"http://{host}:{httpd.server_address[1]}/viewer/"
    log.info("apresentação disponível em %s  (Ctrl+C para parar)", url)
    print(f"\nApresentação: {url}  (pressione Ctrl+C para parar)", flush=True)
    if open_browser and os.environ.get("RMBH_NO_BROWSER") != "1":
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\napresentação encerrada")
    finally:
        httpd.server_close()
