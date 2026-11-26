# Afterglow

Turn a spare phone into ambient lighting that follows what's on your PC or Android TV. Afterglow samples the screen locally and sends small color palettes over your Wi-Fi. Open the light in your phone's browser.

## Download

Choose your platform under **Assets** on the [latest release](https://github.com/1xky/Afterglow/releases/latest).

| Platform | Download | Start here |
| --- | --- | --- |
| Windows 11 (x64) | `Afterglow-Windows-x64.zip` | Extract the ZIP and double-click `Start Afterglow.cmd`. Python is included. |
| macOS (preview) | `Afterglow-macOS.zip` | Install Python 3.10+, extract the ZIP, and run `sh "Start Afterglow.command"` in Terminal from the extracted folder. |
| Linux (preview) | `Afterglow-Linux.zip` | Install Python 3.10+, extract the ZIP, and run `sh start-afterglow.sh` from the extracted folder. |
| Android TV (preview) | `Afterglow-Android-TV-preview.apk` | If available, install the APK on an Android 8.0+ TV that supports sideloading. |

While release downloads are unavailable, [download the source ZIP](https://github.com/1xky/Afterglow/archive/refs/heads/main.zip). The PC launchers are in `Afterglow_pc/Afterglow`. For TV, open [Afterglow_tv](Afterglow_tv) in Android Studio, install Android SDK 35, and build the APK.

## First run

1. Open Afterglow on the PC or TV and connect your phone to the same Wi-Fi.
2. Scan the pairing QR code, tap **Start light** on the phone, and select **Test light** on the host.
3. On PC, try placing the phone sideways behind the center of your display with its screen facing the wall. Select **Start screen sync**, then fullscreen the movie. On macOS and Linux, choose what to share in the browser picker. On TV, select **Start sync** and approve screen sharing.

## Features

- **Live color gradients.** The phone shows a blend of colors from different parts of the screen.
- **QR pairing on your local network.** Pair multiple phones, each with its own placement. The PC can also connect through a phone hotspot or USB tethering.
- **Adjustable light on PC.** Set intensity, vividness, brightness boost, and mirroring. Choose from five phone placements, with short setup videos for landscape and portrait.
- **Flexible PC capture.** Windows supports fullscreen capture. Browser sharing can capture a tab, window, or display where supported.

If the light stays dark, try **Test light** and an unprotected video. Protected playback may appear black in screen capture. See the [PC setup guide](Afterglow_pc/Afterglow/README.md) for more help.
