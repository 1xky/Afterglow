import {readFrame, SAMPLE_INTERVAL, sendFrame} from "./capture.js";

self.onmessage = async ({data}) => {
  const {width, height, generation, track} = data;
  let reader;
  try {
    const frames = data.frames || new MediaStreamTrackProcessor({track, maxBufferSize: 1}).readable;
    reader = frames.getReader();
    const canvas = new OffscreenCanvas(width, height);
    const context = canvas.getContext("2d", {alpha: false, willReadFrequently: true});
    if (!context) throw new Error("Canvas capture is unavailable in this worker.");
    const pixels = new Uint8Array(width * height * 3);
    let last = -Infinity;
    self.postMessage({ready: true});
    while (true) {
      const {value: frame, done} = await reader.read();
      if (done) break;
      try {
        const now = performance.now();
        if (track?.muted || now - last < SAMPLE_INTERVAL) continue;
        last = now;
        readFrame(context, frame, width, height, pixels);
      } finally {
        frame.close();
      }
      await sendFrame(pixels, generation);
    }
    self.postMessage({error: "The browser stopped sending shared frames."});
  } catch (error) {
    self.postMessage({error: error.message || "This browser could not read the shared video."});
  } finally {
    if (reader) {
      await reader.cancel().catch(() => {});
      reader.releaseLock();
    }
    track?.stop();
  }
};
