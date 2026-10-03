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
from .providers import fetch


class MailTray:
    def __init__(self) -> None:
        self.accounts = storage.accounts()
        self.state = storage.load(storage.state_dir() / "seen.json", {})
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.pending: dict[str, Future] = {}
        self.unread: dict[str, int] = {}
        self.errors: dict[str, str] = {}
        self.recent: list[Message] = []
        self.notifications: list[Notify.Notification] = []
        self.indicator = AyatanaAppIndicator3.Indicator.new(
            "mail-tray", "mail-unread", AyatanaAppIndicator3.IndicatorCategory.COMMUNICATIONS
        )
        self.menu = Gtk.Menu()
        self.refresh_menu()
        self.indicator.set_menu(self.menu)
        self.indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
        self.poll_source = GLib.timeout_add_seconds(60, self.poll)
        self.results_source = GLib.timeout_add(250, self.collect)
        self.poll()
        if not self.accounts:
            GLib.idle_add(self.open_setup)

    @staticmethod
    def open_setup() -> bool:
        subprocess.Popen([sys.executable, "-m", "mailtray", "setup"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return False

    def poll(self) -> bool:
        self.accounts = storage.accounts()
        self.refresh_menu()
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
                    self.recent.insert(0, message)
                    try:
                        self.notify(account, message)
                    except GLib.Error:
                        print("Mail Tray: Could not deliver desktop notification; use the tray menu", file=sys.stderr)
                self.recent = self.recent[:10]
            except Exception:
                # Do not leak OAuth tokens or response bodies into desktop UI.
                self.errors[aid] = "Check connection or reauthorize"
            self.refresh_menu()
        return True

    def notify(self, account: dict, message: Message) -> None:
        provider = account["provider"]
        icon = str(files("mailtray").joinpath("icons", f"{provider}.png"))
        notification = Notify.Notification.new(
            f"New mail · {account['email']}", f"{message.sender}\n{message.subject}", icon
        )
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
        self.add_item(title, sensitive=False)
        if not self.accounts:
            self.add_item("No accounts. Run: python -m mailtray setup gmail|zoho", sensitive=False)
        for account in self.accounts:
            aid = account["id"]
            count = self.unread.get(aid, '…')
            suffix = '+' if account['provider'] == 'zoho' and isinstance(count, int) and count >= 200 else ''
            text = f"{account['email']}: {count}{suffix} unread"
            if aid in self.errors:
                text += " · connection error"
            self.add_item(text, sensitive=False)
        if self.recent:
            self.menu.append(Gtk.SeparatorMenuItem())
            for message in self.recent:
                label = f"{message.sender[:35]} · {message.subject[:50]}"
                self.add_item(label, lambda item, url=message.url: self.open_url(url))
        self.menu.append(Gtk.SeparatorMenuItem())
        self.add_item("Set up accounts…", lambda item: self.open_setup())
        self.add_item("Check now", lambda item: self.poll())
        self.add_item("Quit", lambda item: self.quit())
        self.menu.show_all()

    def add_item(self, label: str, callback=None, sensitive: bool = True) -> None:
        item = Gtk.MenuItem.new_with_label(label)
        item.set_sensitive(sensitive)
        if callback is not None:
            item.connect("activate", callback)
        self.menu.append(item)

    def quit(self) -> None:
        GLib.source_remove(self.poll_source)
        GLib.source_remove(self.results_source)
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
