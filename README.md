# Mail Tray

A local Linux tray app that checks Gmail and Zoho Mail Inbox and displays desktop notifications for newly arrived messages. The first check establishes a baseline (no flood of old mail). Supports multiple accounts. No mail passwords or message bodies are stored.

## Install

Requires Python 3.10+, a graphical Linux session with a StatusNotifier tray, desktop notifications, a browser, and a Secret Service/keyring backend (GNOME Keyring or KWallet). In Hyprland, use a bar with a tray module and a notification daemon. From the project directory on **Arch Linux, Debian 12+ or Ubuntu 24.04+**, run:

```sh
./install.sh
# Or, if you already have just installed:
just install
```

The script uses your distribution's package manager for GTK/PyGObject, requests, keyring and Python build tools (it may ask for `sudo`), builds a wheel without build isolation, installs it into your Python **user site** (typically `~/.local/`) without any venv, and registers the branded desktop launcher/icon. The installed CLI is **`mail-tray`**; `~/.local/bin` must be on your `PATH` (the script warns if it isn't). The installer opens guided setup unless `MAIL_TRAY_SKIP_SETUP=1` is set. It neither deletes old `.venv`/`.venv-gtk` folders nor changes saved account data. It updates only its previous venv-based desktop launcher (backing it up); a custom launcher is left alone. The installed wheel works after you move the source folder.

For a source build without the installer, run `just build` (requires `just`, distro Python build tools and dependencies). On other distributions, install GTK 3, PyGObject, libnotify, Ayatana AppIndicator, requests, keyring, python-build, python-installer and setuptools from your package manager, then build with `/usr/bin/python3 -m build --wheel --no-isolation` and install with `/usr/bin/python3 -m installer --prefix="$(/usr/bin/python3 -m site --user-base)" dist/mail_tray-*.whl`. Avoid `sudo pip` into the system Python.

### Guided setup (recommended)

Run `mail-tray setup` at any time, or choose **Connect an account…** (no accounts yet) or **Manage accounts…** from the tray menu. The first run also opens setup when no accounts exist. The responsive local page shows connected accounts and the live sign-in result, provides separate Gmail/Zoho instructions with direct links to the right provider console pages, and collects client ID/secret without placing them in a URL. Use **Remove** beside a connected account and confirm to delete its saved keyring credentials, account record and seen-message IDs; it does not delete mail at the provider. Removal also clears the account from a running tray within about 2 seconds. Finish provider sign-in in the browser, then return to the setup tab to check for **Account connected** (the OAuth callback tab only confirms receipt, not success). If you have multiple Zoho mailboxes, pick one in the setup page. Close setup with its button when done. Run `mail-tray` (or open **Mail Tray** from your application launcher) to start notifications; if the tray app was already running, it notices newly connected accounts within about 2 seconds and starts checking them.

Gmail: use a dedicated Google Cloud project, enable Gmail API, set up OAuth consent, add your own Google account in **Audience → Test users** if in Testing mode, and create an **OAuth client → Desktop app**. The OAuth app name shown by Google comes from your Cloud project, not Mail Tray. It requests `gmail.readonly` (restricted scope; distributing publicly needs Google verification). Testing-mode refresh tokens may expire after 7 days. Workspace admins may separately restrict Gmail API access.

Zoho: create a **Server-based Application** in the Zoho API Console with redirect URI **`http://127.0.0.1:8765/callback`** exactly. If the console rejects loopback HTTP for that client type, do not use a remote redirect you don't control. Pick the correct Zoho region in setup; port 8765 must be free. Only `ZohoMail.accounts.READ`, `ZohoMail.folders.READ`, and `ZohoMail.messages.READ` are requested.

### Terminal setup (still available)

```sh
mail-tray setup gmail
mail-tray setup zoho --region eu  # replace eu with your Zoho region
```

Terminal and web setup use the same OAuth verification, keyring and account storage. Never share your OAuth client secret or tokens in chat.

### Run

```sh
mail-tray
```

Open the tray menu to see account unread counts and recent new mail. Account rows open that inbox; **Manage accounts…** opens setup to connect or remove accounts. **Open settings file…**, **Check now**, and **Quit** are below. The menu's visual style is drawn by your desktop panel, not by Mail Tray. Click a notification (or its **Open mail** button) to open it in your default browser if your notification daemon supports actions; recent messages remain available in the tray menu otherwise. Notifications show the provider's Gmail or Zoho Mail icon. Gmail opens the thread. Zoho opens the Inbox because Zoho does not document stable per-message web links. If the browser does not launch, check that a default HTTPS browser is configured. Unread counts are exact for Gmail and capped at **200+** for Zoho. Notifications only scan the 50 most recent Inbox messages per check (every minute by default), so more than 50 arrivals between checks may be missed. Notifications are generated for new Inbox arrivals even if already marked read. Not a push service: laptop/app must be running. Email subject/sender appear on the lock screen if your desktop displays notifications there.

To start automatically after login, add `mail-tray` in your desktop's autostart settings. No service or autostart entry is installed automatically.

## Files and settings

- **Accounts:** `~/.config/mail-tray/accounts.json` (or `$XDG_CONFIG_HOME/mail-tray/accounts.json`) — provider, email and (for Zoho) mailbox ID; no OAuth tokens or passwords.
- **Preferences:** `~/.config/mail-tray/settings.ini` (or `$XDG_CONFIG_HOME/mail-tray/settings.ini`) — created by the installer or `mail-tray config`, with editable settings: `poll_interval_seconds` (15–3600), `open_setup_on_first_run`, `enabled` and `show_preview` under `[Notifications]`, and `recent_items` under `[Tray]` (1–30). Restart Mail Tray after editing. `mail-tray config` prints the exact location; **Open settings file…** is in the tray menu.
- **OAuth credentials:** your desktop's Secret Service keyring under `mail-tray` (not in the config file).
- **Notification deduplication:** `~/.local/state/mail-tray/seen.json` (or `$XDG_STATE_HOME/mail-tray/seen.json`) — recent message IDs only.

For example, to check every two minutes and hide sender/subject in desktop notifications, edit `settings.ini`:

```ini
[General]
poll_interval_seconds = 120

[Notifications]
enabled = true
show_preview = false
```

Unspecified settings keep their defaults; invalid values cause a clear startup error rather than overwriting your file. The app does not delete your accounts or tokens when you reinstall. The app icon is its own Mail Tray artwork; Gmail/Zoho logos appear only on provider notifications.

## Testing

```sh
/usr/bin/python3 -m pytest -q  # after installing your distro's python3-pytest package
```

Notification icon sources: [Gmail product logo](https://fonts.gstatic.com/s/i/productlogos/gmail_2020q4/v10/192px.svg) and [Zoho Mail product logo](https://www.zoho.com/sites/zweb/images/productlogos/mail.svg). These logos belong to their respective owners.

Provider references: [Gmail messages.list](https://developers.google.com/workspace/gmail/api/guides/list-messages), [Zoho Mail OAuth](https://www.zoho.com/mail/help/api/using-oauth-2.html), [Zoho list emails](https://www.zoho.com/mail/help/api/get-emails-list.html).
