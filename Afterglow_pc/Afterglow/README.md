# Afterglow

Afterglow turns your phone screen into a soft, moving gradient sampled from the movie on your laptop. The laptop processes capture locally and sends small color palettes and light settings to paired phones over your local network.

## Start on Windows 11

1. Extract the entire ZIP. Double-click **Start Afterglow.cmd** and keep its window open. If Windows asks about network access, enable it for the network you trust and are using to connect your phone.
2. Put the phone and laptop on the same Wi-Fi network, or connect the laptop to the phone's Wi-Fi hotspot or USB tethering. Under **Pair your phone**, scan the QR code or open the address and enter the pairing code. Tap **Start light**. If several network addresses appear, choose the one your phone can reach. The QR code updates to match.
3. Click **Test light**. When you see the sample gradient, click **Start screen sync** and put the movie into fullscreen on any connected monitor. Afterglow uses DirectX Desktop Duplication when available and falls back to Windows GDI capture.
4. Focus a different fullscreen window to switch capture to it. If the active window leaves fullscreen, the light fades to black until you focus a fullscreen window again. Close the launcher window to end the session.

The ZIP includes the Windows x64 runtime. For a different Windows architecture, run `python afterglow.py` using a locally installed Python 3.10 or newer. Run `afterglow.py --port 9876` with Python to choose a different port if the default port, 8765, is in use.

## Position the phone

For a starting position, prop the phone in landscape behind the center of the laptop screen with the phone's display facing the wall. Leave space between the phone and wall for the light to spread. A light-colored wall and a dim room make the effect easier to see. Leave **Mirror the gradient** on for this position.

The placement menu also supports either side, upright below the display, or flat on the desk. If the phone lies flat, place it screen-up. On the phone, tap the gradient and open **Placement** to set its own side, orientation, or mirror setting. Choose **Use laptop setting** to follow the dashboard again. You can pair multiple phones with the same code and give each a different position.

Select your placement and orientation under **Light settings**, then click **View phone setup video**. Each placement has a landscape and a portrait guide.

**Brightness boost** lifts darker colors. **Light intensity** controls the overall output, and **Vividness** gives more weight to saturated colors in each zone. Set Vividness to 0% for neutral sampling or raise it if strong colors look washed out on the wall. Use **Test light** to compare settings. Afterglow saves the dashboard defaults in `afterglow-settings.json` beside `afterglow.py`, and each phone remembers its own overrides in its browser.

The receiver tries to keep the screen on while it is open. If your browser or phone still dims, extend the display timeout. Android's **Stay awake** developer setting also keeps the display on while it is charging.

## macOS and Linux preview

Install Python 3.10 or newer and use a desktop browser with screen sharing support.

- **macOS.** Double-click **Start Afterglow.command** in the extracted folder. From Terminal, you can also run `sh "Start Afterglow.command"`.
- **Linux.** From the extracted folder, run `./start-afterglow.sh`. You can also run `sh start-afterglow.sh`.

Open the dashboard, click **Start screen sync**, and select the movie's tab, window, or display from the browser's picker. Chromium-based browsers can sample in a worker. Afterglow uses video and canvas sampling when that worker path is unavailable. The same capture option is available as **Share a tab or window** on Windows.

Fullscreen the movie after sharing and leave the dashboard tab open. If your browser pauses capture in the background, keep the dashboard visible in a separate window or display. On macOS, allow the browser to capture your screen if prompted. On Linux, window sharing depends on your desktop's screen-sharing support. The light fades out if shared frames stop arriving.

## If the light stays dark

- Try **Test light** to confirm the phone is receiving colors, then try an unprotected local video or YouTube.
- DRM-protected playback may appear black in capture, depending on the service, browser, and playback path.
- If the phone cannot open the pairing page, reload the desktop dashboard after switching networks. Check the laptop's firewall for the active network and try a different listed address. Guest Wi-Fi and some tethering configurations isolate devices.
