"""
Screenshot the running frontend to PNG files.

Why this exists: the usual routes do not work in this environment. A desktop
screen grab fails because the process has no interactive session, and the
in-app browser can render a page but cannot write the image to disk. So we
drive headless Edge over the Chrome DevTools Protocol, which can do both.

It is also the only way to capture a RESULT screen: those need a file upload
and a form submit, so a plain `--screenshot` CLI run only ever catches the
empty landing view.

Usage
-----
    # start the backend and the dev server first, then:
    ./.venv/Scripts/python.exe tools/shoot_ui.py

    ./.venv/Scripts/python.exe tools/shoot_ui.py --out demo_data/shots --width 1440

Requires `websocket-client` (already in the venv) and Microsoft Edge, which
ships with Windows. Files land in demo_data/shots/, which is gitignored --
screenshots of demo documents are build output, not source.

Note the app must be reached at `localhost`, not `127.0.0.1`: the backend's
CORS policy names `http://localhost:3000`, and a mismatched origin fails
preflight, which surfaces in the UI as "could not reach the server".
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

# The page text we echo back contains typographic characters the Windows
# console's cp1252 cannot encode, and an UnicodeEncodeError while *printing*
# would abort a capture run that had otherwise succeeded.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

try:
    import websocket  # type: ignore
except ImportError:
    sys.exit("websocket-client is required:  pip install websocket-client")

EDGE_CANDIDATES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)

APP_URL = "http://localhost:3000/"
DEBUG_PORT = 9333


def find_edge() -> str:
    for path in EDGE_CANDIDATES:
        if os.path.exists(path):
            return path
    sys.exit("Microsoft Edge not found; adjust EDGE_CANDIDATES.")


class Chrome:
    """A very small CDP client: enough to navigate, run JS and grab a picture."""

    def __init__(self, width: int, height: int) -> None:
        self.profile = tempfile.mkdtemp(prefix="shoot_ui_")
        self.process = subprocess.Popen(
            [
                find_edge(),
                "--headless=new",
                "--disable-gpu",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
                "--disable-backgrounding-occluded-windows",
                "--no-first-run",
                "--no-default-browser-check",
                "--hide-scrollbars",
                f"--remote-debugging-port={DEBUG_PORT}",
                # Recent Chromium rejects DevTools websocket connections whose
                # Origin it does not recognise, which is every non-browser
                # client. Without this the handshake fails with 403.
                "--remote-allow-origins=*",
                f"--user-data-dir={self.profile}",
                f"--window-size={width},{height}",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.socket = websocket.create_connection(self._page_ws(), timeout=30)
        self.message_id = 0

    def _page_ws(self) -> str:
        # The debug port takes a moment to come up; poll rather than sleep-guess.
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                raw = urllib.request.urlopen(
                    f"http://127.0.0.1:{DEBUG_PORT}/json", timeout=2
                ).read()
                for target in json.loads(raw):
                    if target.get("type") == "page":
                        return target["webSocketDebuggerUrl"]
            except Exception:
                pass
            time.sleep(0.5)
        raise SystemExit("Edge did not expose a debugging target in time.")

    def send(self, method: str, **params):
        self.message_id += 1
        self.socket.send(json.dumps({"id": self.message_id, "method": method,
                                     "params": params}))
        while True:
            message = json.loads(self.socket.recv())
            if message.get("id") == self.message_id:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error']}")
                return message.get("result", {})

    def navigate(self, url: str, settle: float = 3.0) -> None:
        self.send("Page.enable")
        self.send("Page.navigate", url=url)
        time.sleep(settle)

    def js(self, expression: str, settle: float = 0.0):
        result = self.send(
            "Runtime.evaluate",
            expression=f"(async () => {{ {expression} }})()",
            awaitPromise=True,
            returnByValue=True,
        )
        if settle:
            time.sleep(settle)
        return result.get("result", {}).get("value")

    def shoot(self, path: Path) -> None:
        # captureBeyondViewport gets the whole page, not just the fold.
        data = self.send("Page.captureScreenshot", format="png",
                         captureBeyondViewport=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(data["data"]))
        print(f"  wrote {path}  ({path.stat().st_size // 1024} KB)")

    def close(self) -> None:
        try:
            self.socket.close()
        finally:
            self.process.terminate()
            shutil.rmtree(self.profile, ignore_errors=True)


# The upload inputs are React-controlled: assigning `files` then dispatching
# `change` lets React read the file, after which it clears the input so the
# same file can be picked again. That is why we do not assert on files.length.
ATTACH_AND_SUBMIT = """
// The verify flow is stepped: pick a document type before the upload field
// exists. Walk that step automatically when no file input is present yet, so
// the script keeps working whether the flow is one screen or several.
let inputs = [...document.querySelectorAll('input[type=file]')];
if (!inputs.length) {
  const pick = [...document.querySelectorAll('button,[role=button],label')]
    .find(e => /aadhaar/i.test(e.innerText) && !/identity check/i.test(e.innerText));
  if (pick) { pick.click(); await new Promise(r => setTimeout(r, 1200)); }
  inputs = [...document.querySelectorAll('input[type=file]')];
}
if (!inputs.length) return 'no file input on this view';
const blob = await (await fetch('%(asset)s')).blob();
const dt = new DataTransfer();
dt.items.add(new File([blob], '%(name)s', {type: 'image/png'}));
inputs[0].files = dt.files;
inputs[0].dispatchEvent(new Event('change', {bubbles: true}));
await new Promise(r => setTimeout(r, 500));
const btn = [...document.querySelectorAll('button')]
  .find(b => /run check|verify|check document|submit/i.test(b.innerText));
if (!btn) return 'no submit button found';
btn.click();
// Generous: the request is a real round trip, and the verdict reveal is
// animated on top of it. Screenshotting early catches a spinner.
await new Promise(r => setTimeout(r, 6000));
return document.body.innerText.split(/\\s*\\n+\\s*/).join(' | ').slice(0, 160);
"""

CLICK_TEXT = """
const el = [...document.querySelectorAll('button,a,[role=button]')]
  .find(e => new RegExp(%(pattern)s, 'i').test(e.innerText));
if (!el) return 'not found';
el.click();
await new Promise(r => setTimeout(r, 1500));
return 'clicked';
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="demo_data/shots")
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=1600)
    parser.add_argument("--url", default=APP_URL)
    args = parser.parse_args()

    out = Path(args.out)
    browser = Chrome(args.width, args.height)
    try:
        print(f"Shooting {args.url} at {args.width}x{args.height}")

        browser.navigate(args.url, settle=4.0)
        browser.shoot(out / "01_home.png")

        # Whatever the entry view is, try to reach the verification flow.
        browser.js(CLICK_TEXT % {"pattern": "'verify|check a document|get started|start'"},
                   settle=1.0)
        browser.shoot(out / "02_verify.png")

        print(browser.js(ATTACH_AND_SUBMIT % {
            "asset": "/demo/genuine_back_qr.png", "name": "genuine_back_qr.png"}))
        browser.shoot(out / "03_result_genuine.png")

        browser.js(CLICK_TEXT % {"pattern": "'check another|new check|verify another'"},
                   settle=1.0)
        print(browser.js(ATTACH_AND_SUBMIT % {
            "asset": "/demo/tampered_back_qr.png", "name": "tampered_back_qr.png"}))
        browser.shoot(out / "04_result_forged.png")

        browser.js(CLICK_TEXT % {"pattern": "'dashboard'"}, settle=1.5)
        browser.shoot(out / "05_dashboard.png")

        print("done")
        return 0
    finally:
        browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
