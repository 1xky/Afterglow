import assert from "node:assert/strict";
import {createHash} from "node:crypto";
import {readFileSync} from "node:fs";
import {setImmediate as settled} from "node:timers/promises";
import test from "node:test";
import {Gradient, smoothingTime} from "../web/gradient.js";
import {pairingMatrix} from "../web/pairing-qr.js";

const solid = (r, g, b) => Array.from({length: 9}, () => [r, g, b]);
const black = solid(0, 0, 0);

class Element extends EventTarget {
  constructor(id) {
    super();
    this.id = id;
    this.value = "";
    this.hidden = false;
    this.dataset = {};
    this.attributes = {};
    this.classList = {add() {}, remove() {}, toggle() {}};
    this.options = [];
    this.width = this.height = 9;
    this.clientWidth = 120;
    this.clientHeight = 80;
    this.videoWidth = 640;
    this.readyState = 2;
    this.currentTime = 1;
    this.plays = 0;
    this.context = {
      createImageData: (width, height) => ({width, height, data: new Uint8ClampedArray(width * height * 4)}),
      putImageData: image => { this.image = image; },
      fillRect: (...rectangle) => { this.lastRectangle = rectangle; },
      drawImage() {},
      getImageData: (_, __, width, height) => ({data: Uint8ClampedArray.from(
        {length: width * height * 4}, (_, index) => [150, 50, 12, 255][index % 4])})
    };
  }

  getContext() { return this.context; }
  setAttribute(name, value) { this.attributes[name] = value; }
  contains(element) { return element === this; }
  add(option) { this.options.push(option); this.value ||= option.value; }
  replaceChildren() { this.options = []; this.value = ""; }
  focus() {}
  select() {}
  async play() { this.plays++; }
  pause() {}
  load() {}
  removeAttribute() {}
}

function animation() {
  let id = 0;
  const frames = new Map();
  globalThis.requestAnimationFrame = callback => { frames.set(++id, callback); return id; };
  globalThis.cancelAnimationFrame = id => frames.delete(id);
  return {
    step(time) {
      const pending = [...frames.values()];
      frames.clear();
      pending.forEach(callback => callback(time));
    },
    finish() {
      const now = performance.now();
      for (let i = 1; i <= 180 && frames.size; i++) this.step(now + i * 16);
      assert.equal(frames.size, 0);
    }
  };
}

test("QR modules match a reference Version 3-L encoder for a full pairing URL", () => {
  const matrix = pairingMatrix("http://192.168.100.255:65535/light#23456789");
  assert.equal(matrix.length, 29);
  assert.ok(matrix.every(row => row.length === 29 && row.every(value => value === 0 || value === 1)));
  const digest = createHash("sha256").update(matrix.map(row => [...row].join("")).join("")).digest("hex");
  assert.equal(digest, "361dbe1f2636402fd6a5c62462d142cfc95750818df179b707e1791e13945504");
  assert.throws(() => pairingMatrix("x".repeat(54)), RangeError);
});

test("gradient converges, mirrors and rotates the grid, and dampens small changes", () => {
  const frames = animation();
  const canvas = new Element("light");
  const gradient = new Gradient(canvas);
  const colors = black.map((_, i) => [i * 30, 20, 0]);
  gradient.set(colors, {mirror: true, level: 50});
  frames.finish();
  assert.equal(canvas.image.data[0], 30);
  assert.equal(canvas.image.data[4 * 8], 0);
  assert.equal(canvas.image.data[4 * (4 * 9 + 4)], 60);
  gradient.set(colors, {orientation: "portrait"});
  frames.finish();
  assert.equal(canvas.image.data[0], 180);
  assert.equal(canvas.image.data[4 * 8], 0);
  gradient.black();
  frames.finish();
  assert.equal(canvas.image.data[0], 0);
  assert.ok(smoothingTime(gradient.current, new Float32Array(27).fill(180)) <
    smoothingTime(gradient.current, new Float32Array(27).fill(4)));
  gradient.set(black.map((_, index) => [index % 3 === 1 ? 210 : 20, 0, 0]));
  frames.finish();
  const row = Array.from({length: 9}, (_, x) => canvas.image.data[4 * x]);
  assert.ok(row[0] < row[1] && row[1] < row[2] && row[2] < row[3] && row[3] < row[4]);
  assert.deepEqual(row, row.toReversed());
});

function browser(page, {worker = false, videoFrames = true} = {}) {
  const html = readFileSync(new URL(`../web/${page}.html`, import.meta.url), "utf8");
  const nodes = Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)]
    .map(([, id]) => [id, new Element(id)]));
  for (const [, id] of html.matchAll(/<[^>]*id="([^"]+)"[^>]*\bhidden\b[^>]*>/g)) nodes[id].hidden = true;
  for (const [, id, options] of html.matchAll(/<select id="([^"]+)"[^>]*>([\s\S]*?)<\/select>/g)) {
    nodes[id].options = [...options.matchAll(/<option value="([^"]*)"/g)].map(([, value]) => ({value}));
  }
  const frames = animation();
  const listeners = new EventTarget();
  globalThis.addEventListener = listeners.addEventListener.bind(listeners);
  globalThis.document = Object.assign(new EventTarget(), {
    getElementById: id => nodes[id],
    createElement: tag => new Element(tag),
    fullscreenEnabled: false,
    hidden: false
  });
  Object.defineProperty(globalThis, "navigator", {configurable: true, value: {}});
  globalThis.Option = class { constructor(text, value) { Object.assign(this, {text, value}); } };
  globalThis.location = {hash: "#23456789", pathname: "/light"};
  globalThis.history = {replaceState() {}};
  const storage = new Map();
  globalThis.localStorage = {getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value)};
  const sources = [];
  globalThis.EventSource = class extends EventTarget {
    static OPEN = 1;
    static CLOSED = 2;
    readyState = 1;
    constructor(url) { super(); this.url = url; sources.push(this); }
    message(value) { this.onmessage({data: JSON.stringify(value)}); }
    close() { this.readyState = 2; }
  };

  const workers = [];
  globalThis.Worker = class {
    constructor(url) { this.url = url; workers.push(this); }
    postMessage() {
      queueMicrotask(() => this.onmessage({data: worker ? {ready: true} : {error: "Processor unavailable"}}));
    }
    terminate() { this.stopped = true; }
  };
  const track = Object.assign(new EventTarget(), {
    readyState: "live",
    muted: false,
    clone: () => ({stop() {}}),
    stop() { this.readyState = "ended"; }
  });
  const stream = {getVideoTracks: () => [track], getTracks: () => [track]};
  navigator.mediaDevices = {getDisplayMedia: async () => stream};
  const video = nodes["capture-video"];
  let nextVideoFrame;
  if (video && videoFrames) {
    video.requestVideoFrameCallback = callback => { nextVideoFrame = callback; return 1; };
    video.cancelVideoFrameCallback = () => { nextVideoFrame = null; };
  }
  return {nodes, frames, sources, workers, storage, track, video, listeners,
    videoFrame: (time, mediaTime) => nextVideoFrame(time, {mediaTime})};
}

const defaults = {mode: "idle", status: "idle", colors: black, placement: "center",
  orientation: "auto", mirror: true, boost: false, level: 100, vividness: 55,
  revision: 0, generation: 0, receivers: 0};

function fire(node, event) {
  node.dispatchEvent(new Event(event, {cancelable: true}));
}

for (const strategy of ["worker", "video frames", "animation frames"]) {
  test(`dashboard handles SSE, settings, pairing addresses and capture via ${strategy}`, async () => {
    const env = browser("index", {worker: strategy === "worker", videoFrames: strategy !== "animation frames"});
    const {nodes, sources, workers, video} = env;
    let state = {...defaults};
    const captured = [];
    const commands = [];
    globalThis.fetch = async (url, options) => {
      if (url === "/api/info") return {ok: true, json: async () => ({
        windows: false, addresses: ["10.0.0.2", "192.168.0.6"], code: "23456789", port: 8765, width: 2, height: 1
      })};
      if (url === "/api/command") {
        const command = JSON.parse(options.body);
        commands.push(command);
        state = {...state, ...command, revision: state.revision + 1};
        if (command.mode) {
          state.generation++;
          state.status = command.mode === "browser" ? "waiting" : command.mode;
        }
        return {ok: true, json: async () => state};
      }
      assert.equal(url, "/api/frame"); // The dashboard must never poll /api/status.
      captured.push({pixels: [...options.body], headers: options.headers});
      return {ok: true};
    };
    const cleanUp = () => env.listeners.dispatchEvent(new Event("pagehide"));
    try {
      await import(`../web/desktop.js?${strategy.replaceAll(" ", "-")}`);
      const [source] = sources;
      assert.equal(source.url, "/api/events");
      source.onopen();
      source.message(state);
      assert.equal(nodes.connection.textContent, "No phone connected");
      state = {...state, receivers: 2, revision: 1};
      source.message(state);
      assert.equal(nodes.connection.textContent, "2 phones connected");
      assert.equal(nodes["pair-qr"].hidden, false);
      nodes.network.value = "192.168.0.6";
      fire(nodes.network, "change");
      assert.equal(nodes["phone-address"].value, "http://192.168.0.6:8765/light");
      nodes.vividness.value = "79";
      fire(nodes.vividness, "input");
      fire(nodes.vividness, "change");
      await settled();
      assert.deepEqual(commands.at(-1), {vividness: 79});
      fire(nodes.capture, "click");
      await settled();
      assert.equal(state.mode, "browser");
      assert.equal(nodes.capture.textContent, "Stop sync");
      assert.equal(workers[0].url, "/capture-worker.js");
      if (strategy === "worker") {
        assert.equal(video.plays, 0);
      } else {
        assert.equal(workers[0].stopped, true);
        assert.equal(video.plays, 1);
        if (strategy === "video frames") env.videoFrame(100, 0.1);
        else env.frames.step(100);
        await settled();
        assert.deepEqual(captured[0].pixels, [150, 50, 12, 150, 50, 12]);
        assert.equal(captured[0].headers["X-Afterglow"], "desktop");
        assert.equal(captured[0].headers["X-Generation"], "1");
      }
      fire(nodes.capture, "click");
      await settled();
      assert.equal(env.track.readyState, "ended");
      assert.equal(state.mode, "idle");
    } finally {
      cleanUp();
    }
  });
}

test("capture worker samples VideoFrames, posts RGB with the generation, and closes the frames", async () => {
  let closed = 0;
  const rgb = [];
  globalThis.OffscreenCanvas = Element;
  globalThis.fetch = async (_, options) => {
    rgb.push({pixels: [...options.body], generation: options.headers["X-Generation"]});
    return {ok: true};
  };
  const messages = [];
  globalThis.self = {postMessage: message => messages.push(message)};
  await import("../web/capture-worker.js");
  const frames = new ReadableStream({start(controller) {
    controller.enqueue({close() { closed++; }});
    controller.close();
  }});
  await self.onmessage({data: {width: 1, height: 1, generation: 7, frames}});
  assert.equal(messages[0].ready, true);
  assert.equal(closed, 1);
  assert.deepEqual(rgb, [{pixels: [150, 50, 12], generation: "7"}]);
});

test("phone retains its own placement, orientation and mirroring independently of the desktop", async () => {
  const {nodes, frames, sources, storage} = browser("light");
  const saved = {placement: "left", orientation: "portrait", mirror: false};
  storage.set("afterglow-phone-settings", JSON.stringify(saved));
  await import("../web/light.js");
  assert.equal(nodes.code.value, "23456789");
  assert.equal(nodes["phone-placement"].value, "left");
  assert.equal(nodes["phone-orientation"].value, "portrait");
  assert.equal(nodes["phone-mirror"].value, "off");
  fire(nodes["pair-form"], "submit");
  const [source] = sources;
  try {
    assert.equal(source.url, "/api/light?key=23456789");
    const left = black.map((_, i) => [120 + 10 * i, 0, 0]);
    const right = solid(0, 0, 180);
    source.message({...defaults, status: "live", placement: "right",
      mirror: true, colors: right, palettes: {left, right}});
    frames.finish();
    assert.equal(nodes.light.image.data[0], 180);
    assert.equal(nodes["light-status"].textContent, "Movie sync");
    fire(nodes["phone-settings-toggle"], "click");
    assert.equal(nodes["phone-settings-toggle"].attributes["aria-expanded"], "true");
    nodes["phone-orientation"].value = "landscape";
    fire(nodes["phone-orientation"], "change");
    nodes["phone-mirror"].value = "on";
    fire(nodes["phone-mirror"], "change");
    frames.finish();
    assert.equal(nodes.light.image.data[0], 140);
    nodes["phone-placement"].value = "";
    fire(nodes["phone-placement"], "change");
    frames.finish();
    assert.equal(nodes.light.image.data[2], 180);
    assert.deepEqual(JSON.parse(storage.get("afterglow-phone-settings")), {orientation: "landscape", mirror: true});
    source.dispatchEvent(new Event("heartbeat"));
  } finally {
    fire(nodes.leave, "click");
  }
  assert.equal(source.readyState, EventSource.CLOSED);
});
