from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mailtray import storage
from mailtray.settings import Settings, load_settings
from mailtray.tray import Gtk, GLib, MailTray


def test_first_run_creates_private_xdg_settings(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    settings = load_settings()
    path = tmp_path / 'mail-tray' / 'settings.ini'
    assert path.exists()
    assert path.stat().st_mode & 0o777 == 0o600
    assert (settings.poll_interval_seconds, settings.recent_items) == (60, 10)
    assert settings.notifications_enabled and settings.show_preview
    assert settings.open_setup_on_first_run
    text = path.read_text()
    assert 'poll_interval_seconds = 60' in text
    assert 'client_secret' not in text and 'access_token' not in text


def test_config_cli_prints_path_without_credentials(tmp_path, monkeypatch, capsys):
    from mailtray.__main__ import main
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    monkeypatch.setattr('sys.argv', ['mail-tray', 'config'])
    main()
    assert capsys.readouterr().out.strip() == str(tmp_path / 'mail-tray/settings.ini')


def test_settings_are_editable_and_used_by_tray(tmp_path, monkeypatch):
    initialized, _ = Gtk.init_check([])
    assert initialized
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path))
    path = storage.config_dir() / 'settings.ini'
    path.parent.mkdir()
    path.write_text('[General]\npoll_interval_seconds = 90\nopen_setup_on_first_run = false\n'
                    '[Notifications]\nenabled = false\nshow_preview = false\n'
                    '[Tray]\nrecent_items = 3\n')
    settings = load_settings()
    assert settings == Settings(90, False, False, False, 3)
    indicator = MagicMock()
    with patch('mailtray.tray.storage.accounts', return_value=[]), \
         patch('mailtray.tray.AyatanaAppIndicator3.Indicator.new', return_value=indicator), \
         patch('mailtray.tray.GLib.idle_add') as idle, \
         patch('mailtray.tray.GLib.timeout_add_seconds', return_value=150) as timer, \
         patch.object(MailTray, 'poll', return_value=True):
        tray = MailTray()
        try:
            timer.assert_any_call(90, tray.poll)
            timer.assert_any_call(2, tray.sync_accounts)
            idle.assert_not_called()
            assert tray.settings.recent_items == 3
            with patch('mailtray.tray.Notify.Notification.new') as create:
                from mailtray.core import Message
                tray.notify({'provider': 'gmail', 'email': 'me@example.com'},
                            Message('1', 'Alice', 'Subject', 'https://example.com'))
                create.assert_not_called()
        finally:
            tray.executor.shutdown()
            GLib.source_remove(tray.results_source)


def test_preview_setting_hides_sender_and_subject():
    from mailtray.core import Message
    tray = MailTray.__new__(MailTray)
    tray.settings = Settings(show_preview=False)
    tray.notifications = []
    message = Message('1', 'Private sender', 'Private subject', 'https://example.com/1')
    with patch('mailtray.tray.Notify.Notification.new') as create:
        tray.notify({'provider': 'gmail', 'email': 'user@example.com'}, message)
    assert create.call_args.args[1] == 'New message'
    assert 'Private' not in str(create.call_args)


@pytest.mark.parametrize('bad', [
    '[General]\npoll_interval_seconds = 0\n',
    '[General]\npoll_interval_seconds = not-a-number\n',
    '[Notifications]\nenabled = maybe\n',
    '[Tray]\nrecent_items = 101\n',
    '[General\nbroken = true\n',
])
def test_bad_settings_fail_without_overwriting(tmp_path, monkeypatch, bad):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    path = storage.config_dir() / 'settings.ini'
    path.parent.mkdir()
    path.write_text(bad)
    with pytest.raises(ValueError, match='settings.ini'):
        load_settings()
    assert path.read_text() == bad
