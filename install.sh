#!/usr/bin/env bash
# Install a wheel with the distribution Python, like clipse-gui; never create a venv.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
PYTHON="${MAIL_TRAY_PYTHON:-/usr/bin/python3}"
if [[ ! -x "$PYTHON" ]]; then
  echo "Distribution Python not found: $PYTHON" >&2; exit 1
fi
if command -v pacman >/dev/null 2>&1; then
  sudo pacman -S --needed python python-gobject gtk3 libayatana-appindicator libnotify \
    python-requests python-keyring python-build python-installer python-setuptools python-wheel
elif command -v apt-get >/dev/null 2>&1; then
  sudo apt-get install python3 python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 \
    gir1.2-notify-0.7 python3-requests python3-keyring python3-build \
    python3-installer python3-setuptools python3-wheel
else
  echo "Unsupported package manager. Install GTK, PyGObject, libnotify, Ayatana AppIndicator, requests, keyring, python-build, python-installer and setuptools with your distribution and see README.md." >&2
  exit 1
fi
if ! "$PYTHON" -c 'import gi, requests, keyring; gi.require_version("Gtk", "3.0"); gi.require_version("AyatanaAppIndicator3", "0.1"); gi.require_version("Notify", "0.7")'; then
  echo "System Python cannot load Mail Tray's distro dependencies." >&2; exit 1
fi
"$PYTHON" -m build --wheel --no-isolation --outdir "$ROOT/dist"
wheel="$(ls -t "$ROOT"/dist/mail_tray-*.whl | head -1)"
USER_BASE="$("$PYTHON" -m site --user-base)"
"$PYTHON" -m installer --prefix="$USER_BASE" --overwrite-existing "$wheel"
BIN="$USER_BASE/bin/mail-tray"
if [[ ! -x "$BIN" ]]; then
  echo "Installation did not create $BIN" >&2; exit 1
fi
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/128x128/apps"
install -Dm644 "$ROOT/mailtray/icons/mail-tray.png" "$ICON_DIR/mail-tray.png"
DESKTOP="$APP_DIR/mail-tray.desktop"
mkdir -p "$APP_DIR"
if [[ "$BIN" == *'"'* || "$BIN" == *$'\n'* || "$BIN" == *'%'* ]]; then
  echo "Skipping desktop launcher: Python user-base path cannot be encoded safely." >&2
else
  # Update only the launcher created by the previous venv-based installer.
  if [[ -f "$DESKTOP" ]] && grep -qE '^Exec="[^"]*/\.venv-gtk/bin/mail-tray"$' "$DESKTOP" && grep -q '^Name=Mail Tray$' "$DESKTOP"; then
    if [[ ! -e "$DESKTOP.previous" ]]; then
      cp "$DESKTOP" "$DESKTOP.previous"
    fi
    cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=Mail Tray
Comment=Gmail and Zoho Mail notifications
Exec="$BIN"
Icon=mail-tray
Terminal=false
Categories=Network;Email;
EOF
    echo "Updated previous Mail Tray launcher (backup: $DESKTOP.previous)"
  elif [[ ! -e "$DESKTOP" ]]; then
    cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=Mail Tray
Comment=Gmail and Zoho Mail notifications
Exec="$BIN"
Icon=mail-tray
Terminal=false
Categories=Network;Email;
EOF
  elif grep -Fxq "Exec=\"$BIN\"" "$DESKTOP" && grep -Fxq 'Icon=mail-tray' "$DESKTOP"; then
    echo "Mail Tray desktop launcher is already current."
  else
    echo "Keeping existing custom launcher unchanged: $DESKTOP" >&2
  fi
fi
printf '\nInstalled Mail Tray without a virtual environment. CLI: %s\n' "$BIN"
"$BIN" config
if [[ ":$PATH:" != *":$(dirname "$BIN"):"* ]]; then
  printf 'Add %s to PATH to run mail-tray by name.\n' "$(dirname "$BIN")"
fi
if [[ "${MAIL_TRAY_SKIP_SETUP:-0}" != 1 && ( -n "${DISPLAY:-}" || -n "${WAYLAND_DISPLAY:-}" ) ]]; then
  "$BIN" setup
else
  printf 'To set up later: %s setup\n' "$BIN"
fi
