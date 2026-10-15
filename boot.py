"""Show a readable startup error even when launched without a console."""

from pathlib import Path
import ctypes
import os
import traceback


try:
    from main import main

    main()
except Exception as error:
    folder = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ProMeeting"
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "startup-error.log").open("a", encoding="utf-8") as output:
        traceback.print_exc(file=output)
    ctypes.windll.user32.MessageBoxW(
        None, f"Không thể mở Pro Meeting:\n{error}\n\nLog: {folder / 'startup-error.log'}",
        "Pro Meeting", 0x10,
    )
