"""python -m laiaudio: the GTK app on Linux; on Windows, the native app that install.ps1 builds."""
from .desktop import WINDOWS

if WINDOWS:
    import os

    from .paths import DATA_DIR

    os.startfile(DATA_DIR / "app" / "Laiaudio.exe")  # noqa: S606
else:
    from .app import main

    main()
