# M Focus

Focus timer + website/app blocker for Linux (Debian / Cinnamon, PyQt6).

## Install / update
    sudo apt install python3-pyqt6 python3-pyqt6.qtmultimedia pkexec
    ./install.sh          # run as your normal user; run it again to update
Then search "M Focus" in the menu.

## Remove
    ./uninstall.sh

## Using it
- Focus: drag the ring (or scroll / arrow keys) to pick minutes, one click per minute.
  Single = one session. Pomodoro = rounds of focus with breaks (sites open during breaks).
- Blocklist: category switches, your own sites, and apps to close (use the process name).
- Insights: today, 7 days, streak, calendar heatmap, hours of the day, top labels.
- Settings: Dark/Light themes, daily goal, sound, notifications, "allow ending early".

## How it works
A small root service (mfocus.service) edits /etc/hosts and closes listed apps only
while a focus phase runs, so it still works if the window is closed. Closing the window
during a session keeps M Focus in the tray. Only time the service actually observed is
credited to your history.

## Notes
- Starting a session may not ask for a password (polkit rule). Ending early always does.
- Browsers using DNS-over-HTTPS can bypass /etc/hosts: turn "secure DNS" off in the browser.
- It does not touch the old FocusGuard. If both are installed, disable the old service:
  sudo systemctl disable --now focusguard
