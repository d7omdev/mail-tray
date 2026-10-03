"""Shared account connection for the terminal and the local setup page."""

from collections.abc import Callable

import keyring
import requests

from . import storage
from .auth import SERVICE, authorize, secret_set
from .providers import get

REGIONS = ("com", "eu", "in", "com.au", "jp", "ca", "com.cn")


def connect_account(provider: str, client_id: str, client_secret: str, region: str = "com",
                    select_mailbox: Callable[[list[dict]], int] | None = None) -> dict:
    if provider not in ("gmail", "zoho") or region not in REGIONS:
        raise ValueError("Choose Gmail or Zoho and a supported region")
    client_id = client_id.strip()
    client_secret = client_secret.strip()
    if not client_id or len(client_id) > 512 or len(client_secret) > 512:
        raise ValueError("Enter a valid client ID and secret (up to 512 characters each)")
    if provider == "zoho" and not client_secret:
        raise ValueError("Zoho requires a client secret")
    credentials = authorize(provider, client_id, client_secret, region)
    token = credentials["access_token"]
    try:
        if provider == "gmail":
            profile = get("https://gmail.googleapis.com/gmail/v1/users/me/profile", token, "gmail")
            email = profile["emailAddress"]
            extra = {}
        else:
            accounts = get(f"https://mail.zoho.{region}/api/accounts", token, "zoho")["data"]
            if not accounts:
                raise RuntimeError("No Zoho mailboxes found for this login")
            selected = select_mailbox(accounts) if len(accounts) > 1 and select_mailbox else 0
            if not isinstance(selected, int) or selected not in range(len(accounts)):
                raise ValueError("Choose a valid mailbox")
            mailbox = accounts[selected]
            email = mailbox["primaryEmailAddress"]
            extra = {"account_id": str(mailbox["accountId"]), "region": region}
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        if provider == "gmail" and status == 403:
            raise RuntimeError("Gmail refused access (403). Enable the Gmail API in your OAuth project, "
                               "then check Workspace admin restrictions if applicable.") from None
        raise RuntimeError(f"{provider.title()} API refused access ({status or 'unknown status'}). "
                           "Check the API setup and mailbox permissions.") from None
    identifier = f"{provider}:{region if provider == 'zoho' else 'google'}:{email}"
    account = {"id": identifier, "provider": provider, "email": email, **extra}
    existing = storage.accounts()
    secret_set(identifier, credentials)  # Fail closed if secure storage is unavailable.
    storage.save(storage.config_dir() / "accounts.json", {
        "accounts": [a for a in existing if a["id"] != identifier] + [account]
    })
    return account


def remove_account(identifier: str) -> dict:
    """Forget one connected mailbox without affecting any other account."""
    accounts = storage.accounts()
    account = next((item for item in accounts if item["id"] == identifier), None)
    if account is None:
        raise ValueError("This account is not connected. Refresh setup and try again.")
    try:
        if keyring.get_password(SERVICE, identifier) is not None:
            keyring.delete_password(SERVICE, identifier)
    except keyring.errors.KeyringError as exc:
        raise RuntimeError("Could not remove credentials from the desktop keyring. "
                           "Unlock the keyring and retry.") from exc
    storage.save(storage.config_dir() / "accounts.json", {
        "accounts": [item for item in accounts if item["id"] != identifier]
    })
    path = storage.state_dir() / "seen.json"
    state = storage.load(path, {})
    cleared = True
    if identifier in state:
        try:
            storage.save(path, {key: value for key, value in state.items() if key != identifier})
        except OSError:
            cleared = False  # Account is removed; don't claim history was cleared.
    return {"email": account["email"], "state_cleared": cleared}
