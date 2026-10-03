"""Human-editable, non-secret XDG settings; account records stay in accounts.json."""

import configparser
import os
from dataclasses import dataclass
from pathlib import Path

from .storage import config_dir


@dataclass(frozen=True)
class Settings:
    poll_interval_seconds: int = 60
    open_setup_on_first_run: bool = True
    notifications_enabled: bool = True
    show_preview: bool = True
    recent_items: int = 10


def settings_path() -> Path:
    return config_dir() / "settings.ini"


def load_settings() -> Settings:
    """Create defaults once, preserve user edits, reject invalid values explicitly."""
    path = settings_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    defaults = Settings()
    text = ("# Mail Tray settings (no secrets). Restart Mail Tray after changes.\n"
            "# Accounts: accounts.json; OAuth secrets: desktop keyring.\n\n"
            "[General]\n"
            f"poll_interval_seconds = {defaults.poll_interval_seconds}\n"
            f"open_setup_on_first_run = {str(defaults.open_setup_on_first_run).lower()}\n\n"
            "[Notifications]\n"
            f"enabled = {str(defaults.notifications_enabled).lower()}\n"
            f"show_preview = {str(defaults.show_preview).lower()}\n\n"
            "[Tray]\n"
            f"recent_items = {defaults.recent_items}\n")
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(text)
    config = configparser.ConfigParser(interpolation=None)
    try:
        with path.open(encoding="utf-8") as file:
            config.read_file(file)
        poll = config.getint("General", "poll_interval_seconds", fallback=defaults.poll_interval_seconds)
        recent = config.getint("Tray", "recent_items", fallback=defaults.recent_items)
        if not 15 <= poll <= 3600 or not 1 <= recent <= 30:
            raise ValueError("poll_interval_seconds must be 15–3600 and recent_items must be 1–30")
        return Settings(
            poll_interval_seconds=poll,
            open_setup_on_first_run=config.getboolean("General", "open_setup_on_first_run",
                                                  fallback=defaults.open_setup_on_first_run),
            notifications_enabled=config.getboolean("Notifications", "enabled",
                                                    fallback=defaults.notifications_enabled),
            show_preview=config.getboolean("Notifications", "show_preview",
                                           fallback=defaults.show_preview),
            recent_items=recent,
        )
    except (ValueError, configparser.Error) as exc:
        raise ValueError(f"Invalid Mail Tray settings in {path}: {exc}") from exc
