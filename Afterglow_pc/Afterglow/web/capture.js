export const SAMPLE_INTERVAL = 80;

export function readFrame(context, source, width, height, pixels) {
  context.drawImage(source, 0, 0, width, height);
  const rgba = context.getImageData(0, 0, width, height).data;
  for (let i = 0, j = 0; i < rgba.length; i += 4, j += 3) {
    pixels[j] = rgba[i];
    pixels[j + 1] = rgba[i + 1];
    pixels[j + 2] = rgba[i + 2];
  }
}

export async function sendFrame(pixels, generation, signal) {
  const response = await fetch("/api/frame", {
    method: "POST",
    headers: {"Content-Type": "application/octet-stream", "X-Afterglow": "desktop",
      "X-Generation": String(generation)},
    body: pixels,
    signal
  });
  if (!response.ok) throw new Error("The Afterglow server stopped receiving frames.");
}
