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
import shutil
import subprocess
import sys
import threading
import time
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


class _Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second server bind a port that is already in
    # use, so a leftover viewer would silently share :8000. Ask for exclusivity there.
    allow_reuse_address = os.name != "nt"
    daemon_threads = True


def _bind(handler, host: str, port: int) -> ThreadingHTTPServer:
    for p in [port, *range(port + 1, port + 20), 0]:
        try:
            return _Server((host, p), handler)
        except OSError as e:
            if e.errno != errno.EADDRINUSE:
                raise
    raise OSError("nenhuma porta livre encontrada")


def find_chromium() -> str | None:
    """Path to Chrome or Edge (or Chromium), which support a real full-screen start."""
    cands: list[Path] = []
    if os.name == "nt":
        bases = [os.environ.get(v) for v in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        for rel in ("Google/Chrome/Application/chrome.exe", "Microsoft/Edge/Application/msedge.exe"):
            cands += [Path(b, rel) for b in bases if b]
    elif sys.platform == "darwin":
        cands += [Path(f"/Applications/{a}.app/Contents/MacOS/{a}") for a in ("Google Chrome", "Microsoft Edge", "Chromium")]
    for c in cands:
        if c.is_file():
            return str(c)
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _launch_fullscreen(url: str, profile_dir: Path) -> subprocess.Popen | None:
    """Open `url` as a full-screen app window (F11 leaves full screen).

    A dedicated profile makes this a separate browser process, so the full-screen
    flags apply even if the browser is already open, the viewer's settings persist,
    and we can tell when the window is closed."""
    exe = find_chromium()
    if not exe:
        return None
    profile_dir.mkdir(parents=True, exist_ok=True)
    args = [exe, f"--app={url}", "--start-fullscreen", f"--user-data-dir={profile_dir}",
            "--no-first-run", "--no-default-browser-check", "--hide-crash-restore-bubble",
            "--disable-features=Translate"]
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def serve(
    data_dir: str | Path = "data",
    host: str = "127.0.0.1",
    port: int = 8000,
    open_browser: bool = True,
    fullscreen: bool = False,
) -> None:
    """Serve the viewer. Blocks until Ctrl+C, or until the full-screen window is closed."""
    if not (VIEWER_DIR / "index.html").exists():
        raise FileNotFoundError(f"apresentação não encontrada em {VIEWER_DIR}")
    data_dir = Path(data_dir).resolve()
    if not (data_dir / "listings.json").exists():
        log.warning("%s ainda não tem listings.json; execute `crawl` primeiro", data_dir)
    handler = functools.partial(_Handler, mounts={"viewer": VIEWER_DIR, "data": data_dir})
    httpd = _bind(handler, host, port)
    url = f"http://{host}:{httpd.server_address[1]}/viewer/"
    log.info("apresentação disponível em %s", url)
    proc = None
    if open_browser and os.environ.get("RMBH_NO_BROWSER") != "1":
        if fullscreen:
            proc = _launch_fullscreen(url, data_dir / ".navegador")
            if proc is None:
                log.warning("Chrome/Edge não encontrado; abrindo o navegador padrão (use F11 para tela cheia)")
        if proc is None:
            threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    if proc is None:
        print(f"\nApresentação: {url}  (pressione Ctrl+C para parar)", flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\napresentação encerrada")
        finally:
            httpd.server_close()
        return

    print(f"\nApresentação em tela cheia: {url}", flush=True)
    print("Feche a janela da apresentação (Alt+F4) para encerrar.  F11 sai da tela cheia.", flush=True)
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    started = time.monotonic()
    try:
        while proc.poll() is None:  # polling keeps Ctrl+C working on Windows
            time.sleep(0.3)
        if time.monotonic() - started < 5:
            # the browser handed the URL to a viewer window that was already open
            print("Uma janela da apresentação já estava aberta; pressione Ctrl+C para parar.", flush=True)
            while worker.is_alive():
                worker.join(0.5)
        else:
            print("\napresentação encerrada")
    except KeyboardInterrupt:
        print("\napresentação encerrada")
    finally:
        httpd.shutdown()
        httpd.server_close()
