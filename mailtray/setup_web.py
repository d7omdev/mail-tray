"""Single-user loopback setup wizard. Never serves credentials or tokens back to a browser."""

import errno
import json
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import parse_qs, urlsplit

from . import storage
from .setup_service import REGIONS, connect_account


class SetupState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.csrf = secrets.token_urlsafe(32)
        self.nonce = secrets.token_urlsafe(20)
        self.stage = "ready"
        self.message = "Choose a provider to get started."
        self.provider = ""
        self.mailboxes: list[dict] = []
        self.choice = threading.Event()
        self.selected: int | None = None

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "stage": self.stage, "message": self.message, "provider": self.provider,
                "mailboxes": [a["primaryEmailAddress"] for a in self.mailboxes],
                "accounts": [{"provider": a["provider"], "email": a["email"]}
                             for a in storage.accounts()],
            }

    def start(self, provider: str, client_id: str, client_secret: str, region: str) -> bool:
        with self.lock:
            if self.stage in ("authorizing", "choosing"):
                return False
            self.stage = "authorizing"
            self.message = "Browser sign-in is opening. Finish consent, then return here."
            self.provider = provider
            self.mailboxes = []
            self.selected = None
            self.choice.clear()
        threading.Thread(target=self._connect, args=(provider, client_id, client_secret, region),
                         daemon=True).start()
        return True

    def _select_mailbox(self, accounts: list[dict]) -> int:
        with self.lock:
            self.mailboxes = accounts
            self.stage = "choosing"
            self.message = "Choose which Zoho mailbox to connect."
        if not self.choice.wait(120):
            raise TimeoutError("Mailbox selection timed out. Start the connection again.")
        with self.lock:
            assert self.selected is not None
            return self.selected

    def select(self, index: int) -> bool:
        with self.lock:
            if self.stage != "choosing" or index not in range(len(self.mailboxes)):
                return False
            self.selected = index
            self.stage = "authorizing"
            self.message = "Saving your selected mailbox securely…"
            self.choice.set()
            return True

    def _connect(self, provider: str, client_id: str, client_secret: str, region: str) -> None:
        try:
            account = connect_account(provider, client_id, client_secret, region, self._select_mailbox)
            with self.lock:
                self.stage = "connected"
                self.message = (f"{account['email']} is connected. If Mail Tray is running, it will "
                                "check this inbox within a minute; otherwise open Mail Tray from your app launcher.")
        except (ValueError, RuntimeError, TimeoutError, OSError) as exc:
            # Only curated local validation and setup errors are shown, never raw HTTP/token payloads.
            message = ("Zoho callback port 8765 is already in use. Close the other app and retry."
                       if provider == "zoho" and isinstance(exc, OSError)
                       and exc.errno == errno.EADDRINUSE else str(exc))
            with self.lock:
                self.stage = "error"
                self.message = message
        except Exception:
            with self.lock:
                self.stage = "error"
                self.message = "Connection failed. Check keyring access and your provider configuration, then retry."
        finally:
            client_secret = ""  # Do not retain credentials in wizard state.
            with self.lock:
                self.mailboxes = []


def make_server() -> ThreadingHTTPServer:
    state = SetupState()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass  # No request logs: submitted forms contain OAuth client credentials.

        def _allowed(self) -> bool:
            host = self.headers.get("Host", "")
            origin = self.headers.get("Origin")
            expected = f"http://127.0.0.1:{self.server.server_port}"
            return host == f"127.0.0.1:{self.server.server_port}" and (not origin or origin == expected)

        def _send(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'none'; img-src 'self'; "
                             f"script-src 'nonce-{state.nonce}'; style-src 'nonce-{state.nonce}'; "
                             "connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if not self._allowed():
                self._send(403, b"Forbidden", "text/plain")
                return
            path = urlsplit(self.path).path
            if path == "/":
                template = files("mailtray").joinpath("setup.html").read_text(encoding="utf-8")
                page = template.replace("__CSRF__", state.csrf).replace("__NONCE__", state.nonce)
                self._send(200, page.encode(), "text/html; charset=utf-8")
            elif path == "/status":
                self._send(200, json.dumps(state.snapshot()).encode(), "application/json")
            elif path in ("/icons/gmail.png", "/icons/zoho.png"):
                icon = files("mailtray").joinpath("icons", path.rsplit("/", 1)[-1])
                self._send(200, icon.read_bytes(), "image/png")
            else:
                self._send(404, b"Not found", "text/plain")

        def do_POST(self) -> None:
            if not self._allowed() or not secrets.compare_digest(self.headers.get("X-Setup-Token", ""), state.csrf):
                self._send(403, b"Forbidden", "text/plain")
                return
            length = self.headers.get("Content-Length", "")
            if (self.headers.get("Content-Type", "").split(";")[0] != "application/x-www-form-urlencoded"
                    or not length.isdecimal() or int(length) > 4096):
                self._send(400, b"Invalid form", "text/plain")
                return
            fields = parse_qs(self.rfile.read(int(length)).decode("utf-8", errors="replace"),
                              keep_blank_values=True)
            path = urlsplit(self.path).path
            if path == "/connect":
                provider = fields.get("provider", [""])[0]
                region = fields.get("region", [""])[0]
                client_id = fields.get("client_id", [""])[0].strip()
                client_secret = fields.get("client_secret", [""])[0].strip()
                if (provider not in ("gmail", "zoho") or region not in REGIONS
                        or not client_id or len(client_id) > 512 or len(client_secret) > 512
                        or (provider == "zoho" and not client_secret)):
                    self._send(400, b"Check your provider, region, client ID and secret", "text/plain")
                elif state.start(provider, client_id, client_secret, region):
                    self._send(202, b"Sign-in started", "text/plain")
                else:
                    self._send(409, b"Finish the current connection first", "text/plain")
            elif path == "/select":
                index = fields.get("index", [""])[0]
                if index.isdecimal() and state.select(int(index)):
                    self._send(200, b"Mailbox selected", "text/plain")
                else:
                    self._send(400, b"Choose a mailbox from the list", "text/plain")
            elif path == "/close":
                if state.snapshot()["stage"] in ("authorizing", "choosing"):
                    self._send(409, b"Finish the current sign-in before closing setup", "text/plain")
                else:
                    self._send(200, b"Setup closed", "text/plain")
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                self._send(404, b"Not found", "text/plain")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.state = state
    return server


def run() -> None:
    server = make_server()
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"Mail Tray setup: {url} (Ctrl+C to close)")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
