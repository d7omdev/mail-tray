"""Linux AppIndicator tray UI; network work stays off the GTK main loop."""

import subprocess
import sys
from concurrent.futures import Future, ThreadPoolExecutor
from importlib.resources import files

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
gi.require_version("Notify", "0.7")
from gi.repository import AyatanaAppIndicator3, Gio, GLib, Gtk, Notify

from . import storage
from .core import Message, SeenState, reconcile
from .providers import fetch, inbox_url
from .settings import load_settings, settings_path


class MailTray:
    def __init__(self) -> None:
        self.settings = load_settings()
        self.accounts = storage.accounts()
        self.state = storage.load(storage.state_dir() / "seen.json", {})
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.pending: dict[str, Future] = {}
        self.unread: dict[str, int] = {}
        self.errors: dict[str, str] = {}
        self.recent: list[tuple[str, Message]] = []
        self.notifications: list[Notify.Notification] = []
        self.indicator = AyatanaAppIndicator3.Indicator.new(
            "mail-tray", "mail-tray", AyatanaAppIndicator3.IndicatorCategory.COMMUNICATIONS
        )
        self.indicator.set_icon_full(str(files("mailtray").joinpath("icons", "mail-tray.png")),
                                     "Mail Tray")
        self.menu = Gtk.Menu()
        self.refresh_menu()
        self.indicator.set_menu(self.menu)
        self.indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
        self.poll_source = GLib.timeout_add_seconds(self.settings.poll_interval_seconds, self.poll)
        self.results_source = GLib.timeout_add(250, self.collect)
        self.accounts_source = GLib.timeout_add_seconds(2, self.sync_accounts)
        self.poll()
        if not self.accounts and self.settings.open_setup_on_first_run:
            GLib.idle_add(self.open_setup)

    @staticmethod
    def open_setup() -> bool:
        subprocess.Popen([sys.executable, "-m", "mailtray", "setup"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return False

    def sync_accounts(self) -> bool:
        current = storage.accounts()
        previous_ids = {account["id"] for account in self.accounts}
        current_ids = {account["id"] for account in current}
        if current != self.accounts:
            for identifier in previous_ids - current_ids:
                future = self.pending.pop(identifier, None)
                if future is not None:
                    future.cancel()
                self.unread.pop(identifier, None)
                self.errors.pop(identifier, None)
                self.state.pop(identifier, None)
            if previous_ids - current_ids:
                try:
                    storage.save(storage.state_dir() / "seen.json", self.state)
                except OSError:
                    print("Mail Tray: Could not clear old notification history", file=sys.stderr)
            self.recent = [(identifier, message) for identifier, message in self.recent
                           if identifier in current_ids]
            self.accounts = current
            self.refresh_menu()
            if current_ids - previous_ids:
                self.poll()
        return True

    def poll(self) -> bool:
        self.sync_accounts()
        for account in self.accounts:
            if account["id"] not in self.pending:
                self.pending[account["id"]] = self.executor.submit(fetch, account)
        return True

    def collect(self) -> bool:
        for account in self.accounts:
            aid = account["id"]
            future = self.pending.get(aid)
            if future is None or not future.done():
                continue
            del self.pending[aid]
            try:
                messages, unread = future.result()
                state = SeenState.from_dict(self.state.get(aid, {}))
                fresh = reconcile(state, messages)
                self.state[aid] = state.to_dict()
                storage.save(storage.state_dir() / "seen.json", self.state)
                self.unread[aid] = unread
                self.errors.pop(aid, None)
                for message in fresh:
                    self.recent.insert(0, (aid, message))
                    try:
                        self.notify(account, message)
                    except GLib.Error:
                        print("Mail Tray: Could not deliver desktop notification; use the tray menu", file=sys.stderr)
                self.recent = self.recent[:self.settings.recent_items]
            except Exception:
                # Do not leak OAuth tokens or response bodies into desktop UI.
                self.errors[aid] = "Check connection or reauthorize"
            self.refresh_menu()
        return True

    def notify(self, account: dict, message: Message) -> None:
        if not self.settings.notifications_enabled:
            return
        provider = account["provider"]
        icon = str(files("mailtray").joinpath("icons", f"{provider}.png"))
        body = f"{message.sender}\n{message.subject}" if self.settings.show_preview else "New message"
        notification = Notify.Notification.new(f"New mail · {account['email']}", body, icon)
        # Many daemons invoke "default" when the notification body is clicked.
        notification.add_action("default", "Open mail", self.open_notification, message.url)
        notification.add_action("open", "Open mail", self.open_notification, message.url)
        notification.connect("closed", self.notification_closed)
        self.notifications.append(notification)  # Keep callbacks alive until dismissal.
        notification.show()

    def notification_closed(self, notification: Notify.Notification) -> None:
        if notification in self.notifications:
            self.notifications.remove(notification)

    @staticmethod
    def open_url(url: str) -> None:
        try:
            Gio.AppInfo.launch_default_for_uri(url, None)
        except GLib.Error:
            print("Mail Tray: Could not open browser; check your default browser settings", file=sys.stderr)

    @staticmethod
    def open_notification(notification: Notify.Notification, action: str, url: str) -> None:
        MailTray.open_url(url)

    def refresh_menu(self) -> None:
        for item in self.menu.get_children():
            self.menu.remove(item)
        total = sum(self.unread.values())
        capped = any(a["provider"] == "zoho" and self.unread.get(a["id"], 0) >= 200
                     for a in self.accounts)
        title = f"Mail Tray · {total}{'+' if capped else ''} unread"
        self.indicator.set_title(title)
        for account in self.accounts:
            aid = account["id"]
            count = self.unread.get(aid)
            suffix = '+' if account['provider'] == 'zoho' and count is not None and count >= 200 else ''
            unread = f"{count}{suffix} unread" if count is not None else "Checking…"
            name = "Gmail" if account["provider"] == "gmail" else "Zoho"
            address = account["email"]
            if len(address) > 30:
                address = address[:27] + "…"
            text = f"{name} · {address} · {unread}"
            if aid in self.errors:
                self.add_item(f"{name} · {address} · connection error", lambda item: self.open_setup())
                continue
            try:
                url = inbox_url(account)
            except (ValueError, KeyError):
                self.add_item(f"{name} · invalid account settings", lambda item: self.open_setup())
            else:
                self.add_item(text, lambda item, url=url: self.open_url(url))
        if self.recent:
            self.menu.append(Gtk.SeparatorMenuItem())
            for _, message in self.recent:
                label = f"{message.sender[:35]} · {message.subject[:50]}"
                self.add_item(label, lambda item, url=message.url: self.open_url(url))
        if self.accounts or self.recent:
            self.menu.append(Gtk.SeparatorMenuItem())
        self.add_item("Manage accounts…" if self.accounts else "Connect an account…",
                      lambda item: self.open_setup())
        self.add_item("Open settings file…", lambda item: self.open_settings())
        self.add_item("Check now", lambda item: self.poll())
        self.add_item("Quit", lambda item: self.quit())
        self.menu.show_all()

    def add_item(self, label: str, callback=None, sensitive: bool = True) -> None:
        item = Gtk.MenuItem.new_with_label(label)
        item.set_sensitive(sensitive)
        if callback is not None:
            item.connect("activate", callback)
        self.menu.append(item)

    @staticmethod
    def open_settings() -> None:
        MailTray.open_url(Gio.File.new_for_path(str(settings_path())).get_uri())

    def quit(self) -> None:
        GLib.source_remove(self.poll_source)
        GLib.source_remove(self.results_source)
        GLib.source_remove(self.accounts_source)
        self.indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.PASSIVE)
        self.executor.shutdown(wait=False, cancel_futures=True)
        Gtk.main_quit()


def run() -> None:
    initialized, _ = Gtk.init_check([])
    if not initialized:
        raise RuntimeError("A graphical GTK desktop session is required")
    if not Notify.init("Mail Tray"):
        raise RuntimeError("Desktop notifications are unavailable")
    tray = MailTray()
    try:
        Gtk.main()
    finally:
        tray.executor.shutdown(wait=False, cancel_futures=True)
        Notify.uninit()
