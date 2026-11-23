#!/bin/bash
# Removes M Focus completely (settings and history are kept unless you delete them).
set -e
echo "==> Removing the service (needs sudo)"
sudo bash -c '
systemctl stop mfocus.service 2>/dev/null || true
rm -f /var/lib/mfocus/state.json
# with no session left, one pass of the enforcer cleans its block out of /etc/hosts
[ -f /usr/local/lib/mfocus/enforcer.py ] && /usr/bin/python3 /usr/local/lib/mfocus/enforcer.py || true
systemctl disable mfocus.service 2>/dev/null || true
rm -f /etc/systemd/system/mfocus.service /usr/share/polkit-1/actions/org.mfocus.policy
rm -rf /usr/local/lib/mfocus
systemctl daemon-reload
'
rm -rf "$HOME/.local/share/mfocus" "$HOME/.local/share/applications/mfocus.desktop" \
       "$HOME/.local/share/icons/hicolor/scalable/apps/mfocus.svg"
echo "Removed. History is still in /var/lib/mfocus and settings in ~/.config/mfocus."
