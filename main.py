"""FocusGuard for Windows - entry point.

  FocusGuard.exe                          open the app
  FocusGuard.exe --ctl start <min> <d..>  (internal) elevated: start a locked session
  FocusGuard.exe --enforcer               (internal) SYSTEM task: keep the block applied
  FocusGuard.exe --selftest <file>        (internal) used by the GitHub build to smoke-test
"""
import sys


def main():
    args = sys.argv[1:]

    # Qt is imported lazily so the background modes start fast and need no display.
    if args and args[0] == "--enforcer":
        import fg_core
        return fg_core.enforcer_main()
    if args and args[0] == "--ctl":
        import fg_core
        return fg_core.ctl_main(args[1:])
    if args and args[0] == "--selftest":
        import fg_ui
        return fg_ui.selftest(args[1] if len(args) > 1 else "selftest.txt")

    import fg_ui
    app, window = fg_ui.run_gui()
    return app.exec() if hasattr(app, "exec") else app.exec_()


if __name__ == "__main__":
    sys.exit(main())
