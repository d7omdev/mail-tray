"""OAuth authorization-code flow with localhost callback and keyring token storage."""

import base64
import hashlib
import json
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

import keyring
import requests

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
ZOHO_SCOPES = "ZohoMail.accounts.READ,ZohoMail.folders.READ,ZohoMail.messages.READ"
SERVICE = "mail-tray"


def secret_get(account_id: str) -> dict:
    value = keyring.get_password(SERVICE, account_id)
    if not value:
        raise RuntimeError(f"No saved OAuth credentials for {account_id}; run setup again")
    return json.loads(value)


def secret_set(account_id: str, value: dict) -> None:
    keyring.set_password(SERVICE, account_id, json.dumps(value))


def token_url(account: dict) -> str:
    if account["provider"] == "gmail":
        return GOOGLE_TOKEN
    return f"https://accounts.zoho.{account['region']}/oauth/v2/token"


def token_for(account: dict) -> str:
    account_id = account["id"]
    data = secret_get(account_id)
    if data.get("expires_at", 0) > time.time() + 120:
        return data["access_token"]
    params = {"grant_type": "refresh_token", "refresh_token": data["refresh_token"],
              "client_id": data["client_id"]}
    if data.get("client_secret"):
        params["client_secret"] = data["client_secret"]
    response = requests.post(token_url(account), data=params, timeout=20)
    response.raise_for_status()
    result = response.json()
    if "access_token" not in result:
        raise RuntimeError(f"Token refresh failed: {result.get('error', 'unknown error')}")
    data.update(access_token=result["access_token"],
                expires_at=time.time() + int(result.get("expires_in", 3600)))
    if result.get("refresh_token"):
        data["refresh_token"] = result["refresh_token"]
    secret_set(account_id, data)
    return data["access_token"]


def authorize(provider: str, client_id: str, client_secret: str = "", region: str = "com") -> dict:
    """Open browser; accept exactly one callback on loopback, protected by state/PKCE."""
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    received: dict[str, str] = {}
    event = threading.Event()

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parts = urlsplit(self.path)
            params = parse_qs(parts.query)
            if parts.path != "/callback" or params.get("state", [""])[0] != state:
                self.send_error(400, "Invalid OAuth callback")
                return
            received.update({name: values[0] for name, values in params.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Sign-in received. Return to Mail Tray setup to check the final connection status. You may close this tab.")
            event.set()

        def log_message(self, format: str, *args: object) -> None:
            pass  # Do not log authorization codes.

    port = 8765 if provider == "zoho" else 0
    server = HTTPServer(("127.0.0.1", port), Callback)
    server.timeout = 1
    redirect = f"http://127.0.0.1:{server.server_port}/callback"
    params = {"client_id": client_id, "redirect_uri": redirect, "response_type": "code",
              "state": state, "access_type": "offline", "prompt": "consent",
              "code_challenge": challenge, "code_challenge_method": "S256"}
    if provider == "gmail":
        params["scope"] = GOOGLE_SCOPE
        auth_url = GOOGLE_AUTH
    else:
        params["scope"] = ZOHO_SCOPES
        auth_url = f"https://accounts.zoho.{region}/oauth/v2/auth"
    try:
        url = auth_url + "?" + urlencode(params)
        print(f"Opening authorization page: {url}")
        webbrowser.open(url)
        deadline = time.monotonic() + 180
        while not event.is_set() and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if not event.is_set():
        raise TimeoutError("No OAuth callback within 3 minutes")
    if "error" in received:
        raise RuntimeError(f"Authorization declined: {received['error']}")
    payload = {"client_id": client_id, "client_secret": client_secret,
               "redirect_uri": redirect, "grant_type": "authorization_code",
               "code": received["code"], "code_verifier": verifier}
    token_endpoint = GOOGLE_TOKEN if provider == "gmail" else f"https://accounts.zoho.{region}/oauth/v2/token"
    response = requests.post(token_endpoint, data=payload, timeout=20)
    response.raise_for_status()
    data = response.json()
    if not data.get("refresh_token"):
        raise RuntimeError(f"No refresh token returned ({data.get('error', 'check consent settings')})")
    return {"client_id": client_id, "client_secret": client_secret,
            "access_token": data["access_token"], "refresh_token": data["refresh_token"],
            "expires_at": time.time() + int(data.get("expires_in", 3600))}
