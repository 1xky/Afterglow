import {Gradient} from "./gradient.js";

const $ = id => document.getElementById(id);
const gradient = new Gradient($("light"));
const controls = $("light-controls");
const screen = $("light-screen");
const codeInput = $("code");
const fullscreen = $("full");
const sleepNote = $("sleep-note");
const showButton = $("show-controls");
const lightVideo = $("light-video");
const settingsPanel = $("phone-settings");
const settingsToggle = $("phone-settings-toggle");
const localSettings = {};
const localKey = "afterglow-phone-settings";
let events;
let wakeLock;
let wakeRequest = false;
let playback;
let controlsTimer;
let watchdog;
let latest;

if (/^#[a-z0-9]{8}$/i.test(location.hash)) {
  codeInput.value = location.hash.slice(1);
  history.replaceState(null, "", location.pathname);
}
fullscreen.hidden = !document.fullscreenEnabled || !screen.requestFullscreen;

function showControls() {
  clearTimeout(controlsTimer);
  controls.hidden = false;
  if (!settingsPanel.hidden) return;
  controlsTimer = setTimeout(() => {
    if (controls.contains(document.activeElement)) showButton.focus();
    controls.hidden = true;
    sleepNote.hidden = true;
  }, 3600);
}

function resize() {
  if (!latest) return;
  const view = {...latest, ...localSettings};
  gradient.set(latest.palettes?.[view.placement] ?? latest.colors, view);
}

function showSettings(open) {
  settingsPanel.hidden = !open;
  settingsToggle.setAttribute("aria-expanded", String(open));
  if (!open && settingsPanel.contains(document.activeElement)) settingsToggle.focus();
  showControls();
}

function initialiseSettings() {
  let saved = {};
  try {
    saved = JSON.parse(localStorage.getItem(localKey)) ?? {};
  } catch {
    // Receiver choices still work when browser storage is unavailable.
  }
  for (const name of ["placement", "orientation", "mirror"]) {
    const field = $(`phone-${name}`);
    const value = name === "mirror" ? {true: "on", false: "off"}[saved[name]] : saved[name];
    if (value && Array.from(field.options).some(option => option.value === value)) {
      field.value = value;
      localSettings[name] = name === "mirror" ? value === "on" : value;
    }
    field.addEventListener("change", () => {
      if (field.value) localSettings[name] = name === "mirror" ? field.value === "on" : field.value;
      else delete localSettings[name];
      try {
        localStorage.setItem(localKey, JSON.stringify(localSettings));
      } catch {
        // Keep applying the in-memory choices for this session.
      }
      resize();
    });
  }
}

function resetWatchdog() {
  clearTimeout(watchdog);
  watchdog = setTimeout(() => {
    latest = null;
    gradient.black();
    showStatus("Reconnecting.");
    showControls();
  }, 4900);
}

function showStatus(message) {
  $("light-status").textContent = message;
}

async function keepAwake() {
  if (screen.hidden || document.hidden || wakeLock || wakeRequest || playback) return;
  if (navigator.wakeLock) {
    wakeRequest = true;
    try {
      const lock = await navigator.wakeLock.request("screen");
      if (screen.hidden || document.hidden) {
        await lock.release();
        return;
      }
      wakeLock = lock;
      lock.addEventListener("release", () => {
        if (wakeLock === lock) wakeLock = null;
      }, {once: true});
      return;
    } catch {
      // The phone can deny a wake lock in low power mode.
    } finally {
      wakeRequest = false;
    }
  }
  if (gradient.canvas.captureStream && "srcObject" in lightVideo) {
    // On local HTTP, use the actual visible gradient as silent inline video.
    // Browsers that keep the screen on during playback can do so for this light.
    try {
      const localStream = gradient.canvas.captureStream(30);
      playback = localStream;
      lightVideo.hidden = false;
      lightVideo.srcObject = localStream;
      gradient.draw();
      await lightVideo.play();
      if (playback === localStream) screen.classList.add("video-playing");
      return;
    } catch {
      stopPlayback();
      if (screen.hidden) return;
    }
  }
  sleepNote.hidden = false;
}

function stopPlayback() {
  playback?.getTracks().forEach(track => track.stop());
  playback = null;
  lightVideo.pause();
  lightVideo.srcObject = null;
  lightVideo.hidden = true;
  screen.classList.remove("video-playing");
}

function disconnect(message = "") {
  events?.close();
  events = null;
  latest = null;
  clearTimeout(watchdog);
  clearTimeout(controlsTimer);
  settingsPanel.hidden = true;
  settingsToggle.setAttribute("aria-expanded", "false");
  if (document.fullscreenElement === screen) void document.exitFullscreen().catch(() => {});
  void wakeLock?.release().catch(() => {});
  wakeLock = null;
  stopPlayback();
  gradient.black();
  screen.hidden = true;
  $("pair-screen").hidden = false;
  $("pair-error").textContent = message;
  $("pair-error").hidden = !message;
}

function goFullscreen() {
  if (!fullscreen.hidden && !document.fullscreenElement) {
    void screen.requestFullscreen().catch(() => {});
  }
}

$("pair-form").addEventListener("submit", event => {
  event.preventDefault();
  const code = codeInput.value.trim().toLowerCase();
  if (!/^[a-z0-9]{8}$/.test(code)) {
    disconnect("Enter the eight characters shown on your laptop.");
    return;
  }
  $("pair-screen").hidden = true;
  screen.hidden = false;
  showStatus("Connecting…");
  showControls();
  goFullscreen();
  void keepAwake();
  const connection = new EventSource(`/api/light?key=${encodeURIComponent(code)}`);
  events = connection;
  let paired = false;
  connection.onmessage = ({data}) => {
    if (events !== connection) return;
    paired = true;
    latest = JSON.parse(data);
    resize();
    showStatus({idle: "Ready", waiting: "Light paused", live: "Movie sync",
      demo: "Test light", unavailable: "Capture unavailable"}[latest.status]);
    resetWatchdog();
  };
  connection.addEventListener("heartbeat", () => {
    if (events === connection) resetWatchdog();
  });
  connection.onerror = () => {
    if (events !== connection) return;
    if (connection.readyState === EventSource.CLOSED) {
      disconnect(paired ? "Connection closed. Check the laptop and pair again."
        : "Could not pair. Check the code and make sure Afterglow is running.");
      return;
    }
    latest = null;
    gradient.black();
    showStatus("Reconnecting…");
    showControls();
  };
});

fullscreen.addEventListener("click", () => { goFullscreen(); void keepAwake(); });
document.addEventListener("fullscreenchange", () => {
  fullscreen.hidden = !!document.fullscreenElement || !document.fullscreenEnabled;
  resize();
});
$("leave").addEventListener("click", () => disconnect());
settingsToggle.addEventListener("click", () => showSettings(settingsPanel.hidden));
showButton.addEventListener("click", () => {
  showSettings(false);
  void keepAwake();
});
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) void keepAwake();
});
addEventListener("resize", resize);
addEventListener("pagehide", () => disconnect());
initialiseSettings();
