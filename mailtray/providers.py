"""Read-only REST clients for recent Inbox mail and unread counts."""

from html import unescape
from urllib.parse import quote

import requests

from .auth import token_for
from .core import Message


def get(url: str, token: str, provider: str, **params: object) -> dict:
    prefix = "Bearer" if provider == "gmail" else "Zoho-oauthtoken"
    response = requests.get(url, headers={"Authorization": f"{prefix} {token}"},
                            params=params or None, timeout=20)
    response.raise_for_status()
    data = response.json()
    if provider == "zoho" and str(data.get("status", {}).get("code", "200")) != "200":
        raise RuntimeError("Zoho Mail API rejected the request")
    return data


def gmail_mail(account: dict, token: str) -> tuple[list[Message], int]:
    base = "https://gmail.googleapis.com/gmail/v1/users/me"
    listing = get(f"{base}/messages", token, "gmail", labelIds="INBOX", maxResults=50)
    labels = get(f"{base}/labels/INBOX", token, "gmail")
    result = []
    for item in listing.get("messages", []):
        detail = get(f"{base}/messages/{quote(item['id'], safe='')}", token, "gmail",
                     format="metadata", metadataHeaders=["From", "Subject"])
        headers = {h["name"].lower(): h["value"] for h in detail.get("payload", {}).get("headers", [])}
        url = f"https://mail.google.com/mail/u/?authuser={quote(account['email'], safe='')}#all/{quote(detail['threadId'], safe='')}"
        result.append(Message(item["id"], headers.get("from", "Unknown sender"),
                              headers.get("subject", "(no subject)"), url,
                              "UNREAD" in detail.get("labelIds", [])))
    return result, int(labels.get("messagesUnread", 0))


def zoho_mail(account: dict, token: str) -> tuple[list[Message], int]:
    host = f"https://mail.zoho.{account['region']}"
    root = f"{host}/api/accounts"
    aid = quote(account["account_id"], safe="")
    folders = get(f"{root}/{aid}/folders", token, "zoho")["data"]
    inbox = next((folder for folder in folders if folder.get("folderType") == "Inbox" and
                  str(folder.get("path", "")).lower() == "/inbox"), None)
    if inbox is None:
        raise RuntimeError("Zoho Inbox folder not found")
    base = f"{root}/{aid}/messages/view"
    folder_id = inbox["folderId"]
    data = get(base, token, "zoho", folderId=folder_id, start=1, limit=50)
    # Zoho does not document stable per-message web URLs; open the Inbox instead.
    messages = [Message(str(row["messageId"]), unescape(row.get("fromAddress") or row.get("sender") or "Unknown sender"),
                        unescape(row.get("subject") or "(no subject)"), f"{host}/zm/#mail/folder/inbox",
                        str(row.get("status")) == "0") for row in data.get("data", [])]
    unread = get(base, token, "zoho", folderId=folder_id, status="unread", start=1, limit=200)
    count = len(unread.get("data", []))
    return messages, count


def fetch(account: dict) -> tuple[list[Message], int]:
    token = token_for(account)
    if account["provider"] == "gmail":
        return gmail_mail(account, token)
    return zoho_mail(account, token)
