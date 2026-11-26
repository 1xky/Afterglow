# Afterglow

Afterglow turns a phone screen into ambient lighting that follows a movie or other content on a PC or Android TV. The host samples colors locally and sends color palettes to paired phones over the local network. The phone opens the light in its browser.

## PC

1. On GitHub, choose **Code → Download ZIP** and extract it.
2. Open `Afterglow_pc/Afterglow` and use the launcher for your system.

| System | Launcher |
| --- | --- |
| Windows 11 | Double-click `Start Afterglow.cmd`. The Windows x64 Python runtime is included. |
| macOS (preview) | Install Python 3.10 or newer and run `sh "Start Afterglow.command"` in Terminal from the app folder. |
| Linux (preview) | Install Python 3.10 or newer and run `sh start-afterglow.sh` from the app folder. |

Connect the phone and computer to the same Wi-Fi, scan the pairing QR code, and tap **Start light** on the phone. Use **Test light** to check the connection, then start screen sync.

See the [PC setup guide](Afterglow_pc/Afterglow/README.md) for phone placement, screen sharing, and troubleshooting.

## Android TV

The [Android TV project](Afterglow_tv) is provided as source. Open it in Android Studio, install Android SDK 35 if prompted, and build an APK to install on your TV. The app targets TVs running Android 8.0 or later.

On the TV, open Afterglow and pair a phone on the same local network using the QR code. Select **Test light**, then **Start sync** and approve screen sharing on the TV.
