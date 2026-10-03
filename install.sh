#!/usr/bin/env bash
# Install Mail Tray with distribution GTK bindings; no Qt download or root pip.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
PYTHON="${MAIL_TRAY_PYTHON:-/usr/bin/python3}"
if [[ ! -x "$PYTHON" ]]; then
  echo "System Python is missing: $PYTHON" >&2; exit 1
fi
if command -v pacman >/dev/null 2>&1; then
  echo "Installing GTK bindings for Arch Linux…"
  sudo pacman -S --needed python python-gobject gtk3 libayatana-appindicator libnotify
elif command -v apt-get >/dev/null 2>&1; then
  echo "Installing GTK bindings for Debian/Ubuntu…"
  sudo apt-get install python3 python3-venv python3-pip python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 gir1.2-notify-0.7
else
  echo "Unsupported package manager. Install GTK 3, PyGObject, Ayatana AppIndicator and libnotify introspection packages, then follow README.md." >&2
  exit 1
fi
if [[ ! -e .venv-gtk/pyvenv.cfg ]]; then
  "$PYTHON" -m venv --system-site-packages .venv-gtk
fi
if ! .venv-gtk/bin/python -c 'import gi; gi.require_version("Gtk", "3.0"); gi.require_version("AyatanaAppIndicator3", "0.1"); gi.require_version("Notify", "0.7")' >/dev/null 2>&1; then
  echo "Existing .venv-gtk cannot import system GTK. Do not reuse this environment; see README.md for recovery." >&2
  exit 1
fi
.venv-gtk/bin/python -m pip install -e .
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
DESKTOP="$APP_DIR/mail-tray.desktop"
mkdir -p "$APP_DIR"
if [[ ! -e "$DESKTOP" ]]; then
  if [[ "$ROOT" == *'"'* || "$ROOT" == *$'\n'* || "$ROOT" == *'%'* ]]; then
    echo "Installed Python package; desktop launcher skipped because the project path has unsupported characters." >&2
  else
    cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=Mail Tray
Comment=Gmail and Zoho Mail notifications
Exec="$ROOT/.venv-gtk/bin/mail-tray"
Icon=mail-unread
Terminal=false
Categories=Network;Email;
EOF
    echo "Added application launcher: $DESKTOP"
  fi
else
  echo "Existing launcher left untouched: $DESKTOP"
fi
printf '\nInstalled. Run from your app launcher, or use: %s/.venv-gtk/bin/mail-tray\n' "$ROOT"
if [[ "${MAIL_TRAY_SKIP_SETUP:-0}" != 1 && ( -n "${DISPLAY:-}" || -n "${WAYLAND_DISPLAY:-}" ) ]]; then
  echo "Opening guided setup… (Ctrl+C to exit)"
  .venv-gtk/bin/mail-tray setup
else
  printf 'To set up later: %s/.venv-gtk/bin/mail-tray setup\n' "$ROOT"
fi
