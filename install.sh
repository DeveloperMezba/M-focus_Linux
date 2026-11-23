#!/bin/bash
# M Focus installer / updater. Run as your normal user (it asks for sudo itself).
set -e
cd "$(dirname "$0")"
if [ "$(id -u)" = 0 ]; then
  echo "Please run this as your normal user, not with sudo."; exit 1
fi
if ! python3 -c "import PyQt6.QtWidgets" 2>/dev/null; then
  echo "PyQt6 is missing. Install it first:"
  echo "  sudo apt install python3-pyqt6 python3-pyqt6.qtmultimedia pkexec"
  exit 1
fi
command -v pkexec >/dev/null || { echo "pkexec is missing:  sudo apt install pkexec"; exit 1; }

echo "==> Installing the blocking service (needs sudo)"
sudo bash -c '
set -e
install -d -m 755 /usr/local/lib/mfocus /var/lib/mfocus
install -m 755 enforcer.py ctl_start.py ctl_stop.py /usr/local/lib/mfocus/
install -m 644 mfocus.service /etc/systemd/system/mfocus.service
install -m 644 org.mfocus.policy /usr/share/polkit-1/actions/org.mfocus.policy
systemctl daemon-reload
systemctl enable mfocus.service >/dev/null 2>&1
'

echo "==> Installing the app for $USER"
APP="$HOME/.local/share/mfocus"
mkdir -p "$APP" "$HOME/.local/share/applications" "$HOME/.local/share/icons/hicolor/scalable/apps"
install -m 755 mfocus.py "$APP/mfocus.py"
install -m 644 mfocus.svg "$APP/mfocus.svg"
install -m 644 mfocus.svg "$HOME/.local/share/icons/hicolor/scalable/apps/mfocus.svg"
cat > "$HOME/.local/share/applications/mfocus.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=M Focus
Comment=Focus timer and distraction blocker
Exec=/usr/bin/python3 $APP/mfocus.py
Icon=mfocus
Terminal=false
Categories=Utility;
StartupWMClass=mfocus.py
DESKTOP
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
gtk-update-icon-cache -q "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

echo
echo "Done. Open the menu and search for 'M Focus'."
