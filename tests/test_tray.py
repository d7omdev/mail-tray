from concurrent.futures import Future
from importlib.resources import files

import pytest
from unittest.mock import MagicMock, patch

from mailtray import storage
from mailtray.core import Message
from mailtray.settings import Settings
from mailtray.tray import Gtk, GLib, MailTray


def test_tray_baselines_then_notifies_only_new_mail(tmp_path, monkeypatch):
    initialized, _ = Gtk.init_check([])
    assert initialized
    account = {'id': 'gmail:google:me@example.com', 'provider': 'gmail', 'email': 'me@example.com'}
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    indicator = MagicMock()
    notification = MagicMock()
    with patch('mailtray.tray.storage.accounts', return_value=[account]), \
         patch.object(MailTray, 'poll', return_value=True), \
         patch('mailtray.tray.AyatanaAppIndicator3.Indicator.new', return_value=indicator), \
         patch('mailtray.tray.Notify.Notification.new', return_value=notification) as create:
        tray = MailTray()
        try:
            icon = indicator.set_icon_full.call_args.args
            assert icon[0].endswith('/icons/mail-tray.png')
            assert icon[1] == 'Mail Tray'
            assert files('mailtray').joinpath('icons', 'mail-tray.png').is_file()
            old = Message('1', 'Old', 'Earlier', 'https://example.com/1')
            first = Future()
            first.set_result(([old], 1))
            tray.pending[account['id']] = first
            tray.collect()
            create.assert_not_called()
            second = Future()
            second.set_result(([Message('2', 'New', 'Now', 'https://example.com/2'), old], 2))
            tray.pending[account['id']] = second
            tray.collect()
            create.assert_called_once()
            assert notification.add_action.call_count == 2
            notification.add_action.assert_any_call(
                'default', 'Open mail', tray.open_notification, 'https://example.com/2'
            )
            notification.add_action.assert_any_call(
                'open', 'Open mail', tray.open_notification, 'https://example.com/2'
            )
            notification.show.assert_called_once()
            assert notification in tray.notifications
            with patch('mailtray.tray.Gio.AppInfo.launch_default_for_uri') as launch:
                tray.open_notification(notification, 'default', 'https://example.com/2')
                item = next(item for item in tray.menu.get_children()
                            if isinstance(item, Gtk.MenuItem) and 'New · Now' in item.get_label())
                item.activate()
                assert launch.call_count == 2
                launch.assert_any_call('https://example.com/2', None)
            tray.notification_closed(notification)
            assert notification not in tray.notifications
            assert len(tray.recent) == 1
            assert '2 unread' in indicator.set_title.call_args.args[0]
        finally:
            tray.executor.shutdown()
            GLib.source_remove(tray.poll_source)
            GLib.source_remove(tray.results_source)
            GLib.source_remove(tray.accounts_source)


def test_account_row_opens_inbox_and_removed_account_disappears(tmp_path, monkeypatch):
    initialized, _ = Gtk.init_check([])
    assert initialized
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    account = {'id': 'gmail:google:me@example.com', 'provider': 'gmail', 'email': 'me@example.com'}
    records = [account]
    with patch('mailtray.tray.storage.accounts', side_effect=lambda: list(records)), \
         patch('mailtray.tray.AyatanaAppIndicator3.Indicator.new', return_value=MagicMock()), \
         patch.object(MailTray, 'poll', return_value=True):
        tray = MailTray()
        try:
            rows = [item for item in tray.menu.get_children() if isinstance(item, Gtk.MenuItem)]
            account_row = next(item for item in rows if 'me@example.com' in item.get_label())
            assert account_row.get_sensitive()
            with patch.object(MailTray, 'open_url') as open_url:
                account_row.activate()
                open_url.assert_called_once_with(
                    'https://mail.google.com/mail/u/?authuser=me%40example.com#inbox'
                )
            tray.errors[account['id']] = 'Check connection or reauthorize'
            tray.refresh_menu()
            error_row = next(item for item in tray.menu.get_children()
                             if isinstance(item, Gtk.MenuItem) and 'connection error' in item.get_label())
            with patch.object(MailTray, 'open_setup') as open_setup:
                error_row.activate()
                open_setup.assert_called_once()
            tray.recent = [(account['id'], Message('1', 'Sender', 'Subject', 'https://example.com'))]
            tray.unread[account['id']] = 3
            tray.state[account['id']] = {'ids': ['1']}
            late_result = Future()
            late_result.set_result(([Message('2', 'Sender', 'Late', 'https://example.com/2')], 4))
            tray.pending[account['id']] = late_result
            records.clear()
            tray.sync_accounts()
            with patch.object(tray, 'notify') as notify:
                tray.collect()
                notify.assert_not_called()
            assert tray.recent == []
            assert tray.pending == {}
            assert tray.unread == {}
            assert tray.state == {}
            assert storage.load(storage.state_dir() / 'seen.json', {}) == {}
            assert not any('me@example.com' in item.get_label() for item in tray.menu.get_children()
                           if isinstance(item, Gtk.MenuItem))
        finally:
            tray.executor.shutdown()
            GLib.source_remove(tray.poll_source)
            GLib.source_remove(tray.results_source)
            GLib.source_remove(tray.accounts_source)


def test_empty_tray_offers_and_launches_setup(tmp_path, monkeypatch):
    initialized, _ = Gtk.init_check([])
    assert initialized
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    with patch('mailtray.tray.storage.accounts', return_value=[]), \
         patch('mailtray.tray.AyatanaAppIndicator3.Indicator.new', return_value=MagicMock()), \
         patch('mailtray.tray.GLib.idle_add') as idle, \
         patch.object(MailTray, 'poll', return_value=True):
        tray = MailTray()
        try:
            idle.assert_called_once_with(tray.open_setup)
            assert any(isinstance(item, Gtk.MenuItem) and item.get_label() == 'Connect an account…'
                       for item in tray.menu.get_children())
            with patch('mailtray.tray.subprocess.Popen') as launch:
                tray.open_setup()
                assert launch.call_args.args[0][-2:] == ['mailtray', 'setup']
        finally:
            tray.executor.shutdown()
            GLib.source_remove(tray.poll_source)
            GLib.source_remove(tray.results_source)
            GLib.source_remove(tray.accounts_source)


@pytest.mark.parametrize('provider', ['gmail', 'zoho'])
def test_notification_uses_provider_logo(provider):
    tray = MailTray.__new__(MailTray)
    tray.settings = Settings()
    tray.notifications = []
    message = Message('1', 'Sender', 'Subject', 'https://example.com/1')
    account = {'provider': provider, 'email': 'me@example.com'}
    with patch('mailtray.tray.Notify.Notification.new') as create:
        tray.notify(account, message)
    icon = create.call_args.args[2]
    assert icon == str(files('mailtray').joinpath('icons', f'{provider}.png'))
    assert files('mailtray').joinpath('icons', f'{provider}.png').is_file()
