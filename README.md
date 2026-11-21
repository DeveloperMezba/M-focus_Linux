# FocusGuard for Windows

Focus timer with an analog dial + website blocking. Same look and features as the Linux version.
Works on Windows 8.1, 10 and 11 (64-bit).

## Get the .exe from GitHub
1. Upload this whole folder (including the hidden `.github` folder) to a GitHub repository.
2. Open the **Actions** tab -> **Build Windows exe** -> wait ~3-5 minutes for the green tick
   (or press **Run workflow**).
3. Open the finished run -> **Artifacts** -> download **FocusGuard-Windows** -> unzip -> `FocusGuard.exe`.
   (Tip: push a tag like `v1.0` and the exe is also attached under **Releases**.)

## Using it
Double-click `FocusGuard.exe`. Pick the minutes on the dial, press **Start focus session**,
and click **Yes** on the Windows permission (UAC) prompt. Sites are blocked until the timer ends,
even if the app is closed or the PC is restarted.

## How it works
- The block is written to `C:\Windows\System32\drivers\etc\hosts` and re-applied every 2 seconds
  by a background task (Task Scheduler, runs as SYSTEM) until the session ends.
- Session data: `C:\ProgramData\FocusGuard`. Your site lists: `%APPDATA%\FocusGuard\config.json`.

## Notes
- Windows Defender / SmartScreen may warn about an unsigned exe or a hosts-file change. Choose
  "More info" -> "Run anyway", or allow it in Defender.
- Windows 8.1 needs the normal Windows Updates installed (Universal C Runtime).
- Firefox with "DNS over HTTPS" turned on can ignore the hosts file; turn that off in Firefox settings.
- To remove everything: delete `C:\Program Files\FocusGuard`, `C:\ProgramData\FocusGuard`, and run
  `schtasks /Delete /TN FocusGuardEnforcer /F` in an admin Command Prompt.
