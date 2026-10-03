# Mail Tray

A local Linux tray app that checks the Inbox of Gmail and Zoho Mail every minute and displays desktop notifications for newly arrived messages. The first check establishes a baseline (no flood of old mail). Supports multiple accounts. No mail passwords or message bodies are stored. OAuth tokens and OAuth client credentials go into your desktop keyring; only account identifiers and a bounded list of seen message IDs go into XDG config/state files.

## Install

Requires Python 3.10+, a graphical Linux session with a StatusNotifier tray, desktop notifications, a browser, and a working Secret Service/keyring backend (GNOME Keyring or KWallet). In Hyprland, use a bar with a tray module and a notification daemon. **Arch Linux, Debian or Ubuntu:** from the project directory run:

```sh
./install.sh
```

The installer shows the distribution package command and asks for `sudo` through your normal package manager. It creates `.venv-gtk` using the system's GTK bindings (no Qt download), installs the small Python dependencies, adds a Mail Tray application launcher if that filename is free, then opens the local setup page. Your existing `.venv` and any existing desktop launcher are left alone. Keep this project folder in place, because the launcher points to it. To install without opening the browser: `MAIL_TRAY_SKIP_SETUP=1 ./install.sh`.

On other distributions, install GTK 3, PyGObject, libnotify and Ayatana AppIndicator GObject-introspection bindings with your package manager, then run:

```sh
/usr/bin/python3 -m venv --system-site-packages .venv-gtk
.venv-gtk/bin/pip install -e .
.venv-gtk/bin/mail-tray setup
```

If `import gi` fails in the venv, use the distribution's Python; a normal isolated venv or a separately installed Python cannot see the system GTK bindings. If an existing `.venv-gtk` was made with the wrong Python, create a **new** system-site-packages venv with a different name and install there; the installer will not delete your environment.

### Guided setup (recommended)

Run `.venv-gtk/bin/mail-tray setup` at any time, or choose **Set up accounts…** from the tray menu. The first run also opens setup when no accounts exist. The local page shows connected accounts and the live sign-in result, provides separate Gmail/Zoho instructions with direct links to the right provider console pages, and collects client ID/secret without placing them in a URL. Finish provider sign-in in the browser, then return to the setup tab to check for **Account connected** (the OAuth callback tab only confirms receipt, not success). If you have multiple Zoho mailboxes, pick one in the setup page. Close setup with its button when done. Run `.venv-gtk/bin/mail-tray` to start notifications; if the tray app was already running, it notices new accounts at the next check (within 60 seconds).

Gmail: use a dedicated Google Cloud project, enable Gmail API, set up OAuth consent, add your own Google account in **Audience → Test users** if in Testing mode, and create an **OAuth client → Desktop app**. The OAuth app name shown by Google comes from your Cloud project, not Mail Tray. It requests `gmail.readonly` (restricted scope; distributing publicly needs Google verification). Testing-mode refresh tokens may expire after 7 days. Workspace admins may separately restrict Gmail API access.

Zoho: create a **Server-based Application** in the Zoho API Console with redirect URI **`http://127.0.0.1:8765/callback`** exactly. If the console rejects loopback HTTP for that client type, do not use a remote redirect you don't control. Pick the correct Zoho region in setup; port 8765 must be free. Only `ZohoMail.accounts.READ`, `ZohoMail.folders.READ`, and `ZohoMail.messages.READ` are requested.

### Terminal setup (still available)

```sh
.venv-gtk/bin/mail-tray setup gmail
.venv-gtk/bin/mail-tray setup zoho --region eu  # replace eu with your Zoho region
```

Terminal and web setup use the same OAuth verification, keyring and account storage. Never share your OAuth client secret or tokens in chat.

### Run

```sh
.venv-gtk/bin/mail-tray
```

Right-click the tray icon to see account unread counts, recent new mail, **Set up accounts…**, **Check now**, and **Quit**. Click a notification (or its **Open mail** button) to open it in your default browser if your notification daemon supports actions; recent messages remain available in the tray menu otherwise. Notifications show the provider's Gmail or Zoho Mail icon. Gmail opens the thread. Zoho opens the Inbox because Zoho does not document stable per-message web links. If the browser does not launch, check that a default HTTPS browser is configured. Unread counts are exact for Gmail and capped at **200+** for Zoho. Notifications only scan the 50 most recent Inbox messages each minute, so more than 50 arrivals between checks may be missed. Notifications are generated for new Inbox arrivals even if already marked read. Not a push service: laptop/app must be running. Email subject/sender appear on the lock screen if your desktop displays notifications there.

To start automatically after login, use your desktop's autostart settings to run the absolute path to `.venv-gtk/bin/mail-tray`. No service or autostart entry is installed automatically.

## Testing

```sh
.venv-gtk/bin/pip install -e '.[test]'
.venv-gtk/bin/python -m pytest -q
```

Notification icon sources: [Gmail product logo](https://fonts.gstatic.com/s/i/productlogos/gmail_2020q4/v10/192px.svg) and [Zoho Mail product logo](https://www.zoho.com/sites/zweb/images/productlogos/mail.svg). These logos belong to their respective owners.

Provider references: [Gmail messages.list](https://developers.google.com/workspace/gmail/api/guides/list-messages), [Zoho Mail OAuth](https://www.zoho.com/mail/help/api/using-oauth-2.html), [Zoho list emails](https://www.zoho.com/mail/help/api/get-emails-list.html).
