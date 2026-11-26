import {example, Gradient} from "./gradient.js";
import {readFrame, SAMPLE_INTERVAL, sendFrame} from "./capture.js";
import {drawPairingQR} from "./pairing-qr.js";

const $ = id => document.getElementById(id);
const preview = new Gradient($("preview"));
const controls = [$("capture"), $("test-light"), $("browser-capture")];
const placements = {
  center: {name: "Behind the center", auto: "landscape",
    tip: "Center the phone behind the screen and leave a gap to the wall."},
  left: {name: "Behind the left edge", auto: "portrait",
    tip: "Use the screen’s left edge as seen from your seat. Aim the phone at the wall."},
  right: {name: "Behind the right edge", auto: "portrait",
    tip: "Use the screen’s right edge as seen from your seat. Aim the phone at the wall."},
  below: {name: "Upright below the screen", auto: "landscape",
    tip: "Use a raised display with room underneath. Tilt the phone toward the wall."},
  flat: {name: "Flat on the desk", auto: "landscape",
    tip: "Lay the phone screen-up behind the laptop. Leave space by the wall."}
};
const setupGuide = $("setup-guide");
const guideVideo = $("guide-video");
const statuses = {
  idle: "Off", demo: "Test light", waiting: "Waiting", live: "Live", unavailable: "Unavailable"
};

let info;
let state;
let stream;
let stopCapture;
let captureGeneration;
let captureFailure;
let dashboardEvents;
let online = false;
let actionPending = false;
let settingsPending = 0;
const adjusting = new Set();
let settingsQueue = Promise.resolve();
let copyLink = "";

async function json(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const details = await response.json().catch(() => ({}));
    throw new Error(details.error || "Could not reach Afterglow. Check that its window is open.");
  }
  return response.json();
}

function command(settings) {
  return json("/api/command", {
    method: "POST",
    headers: {"Content-Type": "application/json", "X-Afterglow": "desktop"},
    body: JSON.stringify(settings)
  });
}

function showError(id, message = "") {
  $(id).textContent = message;
  $(id).hidden = !message;
}

function updateAddress() {
  const address = $("network").value;
  $("phone-address").value = address ? `http://${address}:${info.port}/light` : "";
  copyLink = address ? `${$("phone-address").value}#${info.code}` : "";
  $("copy-link").disabled = !copyLink;
  $("pair-qr").hidden = !copyLink;
  if (copyLink) drawPairingQR($("pair-qr"), copyLink);
}

async function loadInfo() {
  const next = await json("/api/info");
  const network = $("network");
  const address = network.value;
  network.replaceChildren();
  for (const item of next.addresses) network.add(new Option(item, item));
  if (next.addresses.includes(address)) network.value = address;
  info = next;
  $("pair-code").textContent = info.code;
  $("network-field").hidden = info.addresses.length < 2;
  $("pair-help").hidden = !info.addresses.length;
  $("no-address").hidden = !!info.addresses.length;
  updateAddress();
}

function updateSettings(view) {
  $("placement").value = view.placement;
  $("orientation").value = view.orientation;
  $("mirror").checked = view.mirror;
  $("boost").checked = view.boost;
  for (const [id, value] of [["intensity", view.level], ["vividness", view.vividness]]) {
    if (adjusting.has(id)) continue;
    $(id).value = value;
    $(`${id}-value`).textContent = `${value}%`;
  }
  $("placement-tip").textContent = placements[view.placement].tip;
}

function openSetupGuide() {
  const placement = $("placement").value;
  const selected = $("orientation").value;
  const {name, auto, tip} = placements[placement];
  const orientation = selected === "auto" ? auto : selected;
  const layout = orientation === "landscape" ? "Landscape" : "Portrait";
  $("guide-title").textContent = `${name} · ${layout}`;
  $("guide-caption").textContent = selected === "auto"
    ? `Match phone follows your physical orientation. This video shows ${layout.toLowerCase()}. ${tip}`
    : tip;
  $("guide-error").hidden = true;
  guideVideo.src = `/guides/${placement}-${orientation}.mp4`;
  setupGuide.showModal();
  void guideVideo.play().catch(() => {});
}

function render(view) {
  if (state && view.revision < state.revision) return;
  state = view;
  const {mode, status, colors, receivers} = state;
  const syncing = mode === "windows" || mode === "browser";
  if (!actionPending && stream &&
      (mode !== "browser" || state.generation !== captureGeneration)) releaseStream();
  controls.forEach(control => control.disabled = actionPending || !online);
  $("capture").textContent = syncing ? "Stop sync" : "Start screen sync";
  $("test-light").textContent = mode === "demo" ? "End test" : "Test light";
  $("browser-capture").hidden = !info.windows || syncing || !navigator.mediaDevices?.getDisplayMedia;
  $("capture-status").textContent = statuses[status];
  $("capture-status").dataset.state = status;
  $("connection").classList.toggle("online", !!receivers);
  $("connection").textContent = receivers === 1 ? "1 phone connected"
    : receivers > 1 ? `${receivers} phones connected` : "No phone connected";

  const browserHint = "Keep this tab open. Fullscreen your movie for the best color match.";
  const instructions = {
    idle: info.windows ? "Start screen sync, then fullscreen your movie on any connected display."
      : "Start screen sync, choose the movie’s tab or window, then fullscreen the movie.",
    waiting: mode === "browser" ? "Waiting for frames from the shared tab or window."
      : "Focus a fullscreen movie window to resume.",
    live: mode === "browser" ? browserHint : "Sync pauses when you leave fullscreen or switch away.",
    demo: "The paired phone will show this test gradient.",
    unavailable: "Windows could not read the display. Reopen Afterglow or try sharing a tab or window."
  };
  $("capture-help").textContent = instructions[status];
  $("preview-label").textContent = {
    idle: "Example gradient", waiting: "Light paused", live: "Live gradient",
    demo: "Test gradient", unavailable: "Light paused"
  }[status];
  preview.set(mode === "idle" ? example : colors, state);
  if (!settingsPending) updateSettings(state);
}

function releaseStream() {
  const activeStream = stream;
  const stop = stopCapture;
  stream = stopCapture = captureGeneration = null;
  stop?.();
  activeStream?.getTracks().forEach(track => track.stop());
}

function captureFailed(message, openStream) {
  if (stream !== openStream) return;
  if (actionPending) {
    captureFailure = {message, openStream};
    return;
  }
  if (message) showError("capture-error", message);
  void changeMode("idle", false);
}

function startWorker(track, config, onError) {
  return new Promise((resolve, reject) => {
    const worker = new Worker("/capture-worker.js", {type: "module"});
    let copy, ready = false;
    const stop = () => {
      clearTimeout(timeout);
      worker.terminate();
      copy?.stop();
    };
    const fail = message => {
      stop();
      if (ready) onError(message);
      else reject(new Error(message));
    };
    const timeout = setTimeout(() => fail("The capture worker did not start."), 1500);
    worker.onmessage = ({data}) => {
      if (data.error) fail(data.error);
      else if (data.ready) {
        clearTimeout(timeout);
        ready = true;
        resolve(stop);
      }
    };
    worker.onerror = () => fail("The capture worker stopped unexpectedly.");
    worker.onmessageerror = () => fail("The capture worker could not read shared frames.");
    try {
      copy = track.clone();
      if (typeof MediaStreamTrackProcessor === "function") {
        const {readable} = new MediaStreamTrackProcessor({track: copy, maxBufferSize: 1});
        worker.postMessage({...config, frames: readable}, [readable]);
      } else {
        worker.postMessage({...config, track: copy}, [copy]);
        // The worker owns the transferred track.
        copy = null;
      }
    } catch (error) {
      fail(error.message);
    }
  });
}

async function startVideoCapture(selected, track, {width, height, generation}, onError) {
  const video = $("capture-video");
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d", {alpha: false, willReadFrequently: true});
  if (!context) throw new Error("This browser could not open a capture canvas.");
  const pixels = new Uint8Array(width * height * 3);
  const abort = new AbortController();
  const videoFrames = typeof video.requestVideoFrameCallback === "function";
  let callback, backgroundTimer, busy = false, last = -Infinity, lastMediaTime = -1;
  function schedule() {
    callback = videoFrames ? video.requestVideoFrameCallback(tick) : requestAnimationFrame(tick);
  }
  function tick(time, metadata) {
    schedule();
    void sample(time, metadata?.mediaTime ?? video.currentTime);
  }
  async function sample(time, mediaTime) {
    if (abort.signal.aborted || busy || time - last < SAMPLE_INTERVAL ||
        mediaTime === lastMediaTime || track.muted || video.readyState < 2 || !video.videoWidth) return;
    busy = true;
    last = time;
    lastMediaTime = mediaTime;
    try {
      readFrame(context, video, width, height, pixels);
      await sendFrame(pixels, generation, abort.signal);
    } catch (error) {
      if (!abort.signal.aborted) onError(error.message);
    } finally {
      busy = false;
    }
  }
  function stop() {
    abort.abort();
    clearInterval(backgroundTimer);
    if (callback !== undefined) {
      if (videoFrames) video.cancelVideoFrameCallback(callback);
      else cancelAnimationFrame(callback);
    }
    video.pause();
    video.srcObject = null;
  }
  video.srcObject = selected;
  try {
    await video.play();
    schedule();
    backgroundTimer = setInterval(() => {
      if (document.hidden) void sample(performance.now(), video.currentTime);
    }, 125);
    return stop;
  } catch (error) {
    stop();
    throw error;
  }
}

async function startBrowserCapture() {
  if (!navigator.mediaDevices?.getDisplayMedia) {
    throw new Error("This browser does not offer screen sharing here. Try a desktop browser with screen sharing enabled.");
  }
  const selected = await navigator.mediaDevices.getDisplayMedia({
    video: {frameRate: {ideal: 12, max: 15}, displaySurface: "window"},
    audio: false,
    selfBrowserSurface: "exclude"
  });
  stream = selected;
  try {
    const track = selected.getVideoTracks()[0];
    if (!track) throw new Error("The selected share did not include video.");
    const onError = message => captureFailed(message, selected);
    track.addEventListener("ended", () => onError(), {once: true});
    const next = await command({mode: "browser"});
    captureGeneration = next.generation;
    const config = {width: info.width, height: info.height, generation: next.generation};
    try {
      stopCapture = await startWorker(track, config, onError);
    } catch {
      stopCapture = await startVideoCapture(selected, track, config, onError);
    }
    if (track.readyState === "ended") onError();
    return next;
  } catch (error) {
    releaseStream();
    await command({mode: "idle"}).then(render, () => {});
    throw error;
  }
}

async function changeMode(mode, clearError = true) {
  if (actionPending) return;
  actionPending = true;
  controls.forEach(control => control.disabled = true);
  if (clearError) showError("capture-error");
  try {
    releaseStream();
    const view = mode === "browser" ? await startBrowserCapture() : await command({mode});
    render(view);
  } catch (error) {
    if (error.name !== "NotAllowedError" && error.name !== "AbortError") {
      showError("capture-error", error.message);
    }
  } finally {
    actionPending = false;
    if (state) render(state);
    if (captureFailure) {
      const {message, openStream} = captureFailure;
      captureFailure = null;
      captureFailed(message, openStream);
    }
  }
}

function saveSetting(values) {
  settingsPending++;
  settingsQueue = settingsQueue.then(async () => {
    try {
      render(await command(values));
      showError("settings-error");
    } catch (error) {
      showError("settings-error", error.message);
    } finally {
      settingsPending--;
      if (!settingsPending && state) updateSettings(state);
    }
  });
}

function connectDashboard() {
  const connection = new EventSource("/api/events");
  dashboardEvents = connection;
  connection.onmessage = ({data}) => {
    if (dashboardEvents !== connection) return;
    if (!online) showError("connection-error");
    online = true;
    render(JSON.parse(data));
  };
  connection.onopen = () => {
    if (dashboardEvents !== connection || !state) return;
    // Reconnecting can reach a restarted process with a new pairing code.
    state = null;
    controls.forEach(control => control.disabled = true);
    void loadInfo().catch(error => showError("connection-error", error.message));
  };
  connection.onerror = () => {
    if (dashboardEvents !== connection) return;
    online = false;
    controls.forEach(control => control.disabled = true);
    showError("connection-error", "Reconnecting to Afterglow.");
  };
}

$("capture").addEventListener("click", () => {
  const active = ["windows", "browser"].includes(state.mode);
  void changeMode(active ? "idle" : info.windows ? "windows" : "browser");
});
$("browser-capture").addEventListener("click", () => void changeMode("browser"));
$("test-light").addEventListener("click", () => void changeMode(state.mode === "demo" ? "idle" : "demo"));
$("setup-help").addEventListener("click", openSetupGuide);
$("close-guide").addEventListener("click", () => setupGuide.close());
setupGuide.addEventListener("close", () => {
  guideVideo.pause();
  guideVideo.removeAttribute("src");
  guideVideo.load();
});
guideVideo.addEventListener("error", () => {
  if (setupGuide.open) $("guide-error").hidden = false;
});
$("network").addEventListener("change", updateAddress);
$("copy-link").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(copyLink);
    $("copy-link").textContent = "Copied";
    setTimeout(() => $("copy-link").textContent = "Copy link", 1300);
  } catch {
    $("phone-address").value = copyLink;
    $("phone-address").focus();
    $("phone-address").select();
  }
});
$("placement").addEventListener("change", event => {
  const placement = event.target.value;
  const mirror = ["center", "left", "right"].includes(placement);
  $("mirror").checked = mirror;
  $("placement-tip").textContent = placements[placement].tip;
  saveSetting({placement, mirror});
});
$("orientation").addEventListener("change", event => saveSetting({orientation: event.target.value}));
$("mirror").addEventListener("change", event => saveSetting({mirror: event.target.checked}));
$("boost").addEventListener("change", event => saveSetting({boost: event.target.checked}));
for (const [id, key] of [["intensity", "level"], ["vividness", "vividness"]]) {
  $(id).addEventListener("input", event => {
    adjusting.add(id);
    $(`${id}-value`).textContent = `${event.target.value}%`;
  });
  $(id).addEventListener("change", event => {
    adjusting.delete(id);
    saveSetting({[key]: Number(event.target.value)});
  });
}
addEventListener("resize", () => { if (state) render(state); });
addEventListener("pagehide", () => { releaseStream(); dashboardEvents?.close(); });
addEventListener("pageshow", event => { if (event.persisted && info) connectDashboard(); });

preview.set(example, {boost: true});
try {
  await loadInfo();
  connectDashboard();
} catch (error) {
  showError("capture-error", error.message);
}
