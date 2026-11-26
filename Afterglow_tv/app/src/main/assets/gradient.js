export const example = [[117, 54, 208], [171, 63, 177], [244, 117, 87],
  [71, 55, 188], [139, 56, 192], [226, 87, 99], [35, 32, 142], [100, 44, 160], [178, 61, 143]];
const darkness = Array.from({length: 9}, () => [0, 0, 0]);

function toLinear(value) {
  return value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4;
}

function toSrgb(value) {
  return value <= .0031308 ? 12.92 * value : 1.055 * value ** (1 / 2.4) - .055;
}

function liftForWall(color) {
  const peak = Math.max(...color) / 255;
  if (peak === 0) return color;
  const ceiling = toLinear(peak);
  const liftedCeiling = toLinear(peak + .70 * Math.sqrt(peak) * (1 - peak));
  const relative = color.map(channel => toLinear(channel / 255) / ceiling);
  const saturation = 1 - Math.min(...color) / (255 * peak);
  const fill = (.05 + .12 * (1 - peak)) * (1 - .85 * saturation);
  return relative.map(channel => 255 * toSrgb(liftedCeiling * (fill + (1 - fill) * channel)));
}

function axisCurve(size) {
  return Array.from({length: size}, (_, index) => {
    const position = 2 * index / Math.max(1, size - 1);
    const t = position <= 1 ? position : position - 1;
    const t2 = t * t, t3 = t2 * t;
    return {first: position <= 1, a: 2 * t3 - 3 * t2 + 1, b: -2 * t3 + 3 * t2,
      c: t3 - 2 * t2 + t, d: t3 - t2};
  });
}

function middleSlope(first, second) {
  return first * second > 0 ? 2 * first * second / (first + second) : 0;
}

function interpolate(curve, left, center, right, rising, falling, middle) {
  const {a, b, c, d, first} = curve;
  return first ? a * left + b * center + c * rising + d * middle
    : a * center + b * right + c * middle + d * falling;
}

export function smoothingTime(current, target) {
  let distance = 0;
  for (let i = 0; i < current.length; i++) distance += (current[i] - target[i]) ** 2;
  const rms = Math.sqrt(distance / current.length);
  const strength = Math.min(1, Math.max(0, (rms - 12) / 55));
  return 185 - strength * 147;
}

export class Gradient {
  constructor(canvas) {
    this.canvas = canvas;
    this.context = canvas.getContext("2d", {alpha: false});
    this.image = this.context.createImageData(canvas.width, canvas.height);
    this.horizontal = axisCurve(canvas.width);
    this.vertical = axisCurve(canvas.height);
    this.rows = new Float32Array(canvas.width * 9);
    this.current = new Float32Array(27);
    this.target = new Float32Array(27);
    this.frame = null;
    this.last = 0;
    this.response = 185;
    this.draw();
  }

  set(colors, {level = 100, mirror = false, orientation = "auto", boost = false} = {}) {
    const landscape = this.canvas.clientWidth >= this.canvas.clientHeight;
    const rotate = orientation !== "auto" && landscape !== (orientation === "landscape");
    let changed = false;
    for (let y = 0; y < 3; y++) {
      for (let x = 0; x < 3; x++) {
        let column = rotate ? y : x;
        const row = rotate ? 2 - x : y;
        if (mirror) column = 2 - column;
        const original = colors[row * 3 + column];
        const color = boost ? liftForWall(original) : original;
        for (let channel = 0; channel < 3; channel++) {
          const index = (y * 3 + x) * 3 + channel;
          const value = Math.fround(color[channel] * level / 100);
          if (value !== this.target[index]) changed = true;
          this.target[index] = value;
        }
      }
    }
    if (!changed) return;
    this.response = smoothingTime(this.current, this.target);
    if (this.frame === null) {
      this.last = performance.now();
      this.frame = requestAnimationFrame(time => this.tick(time));
    }
  }

  black() {
    this.set(darkness);
  }

  tick(time) {
    const elapsed = Math.max(1, Math.min(80, time - this.last));
    this.last = time;
    const blend = 1 - Math.exp(-elapsed / this.response);
    let moving = false;
    for (let i = 0; i < this.current.length; i++) {
      const delta = this.target[i] - this.current[i];
      if (Math.abs(delta) < .65) {
        this.current[i] = this.target[i];
      } else {
        this.current[i] += delta * blend;
        moving = true;
      }
    }
    this.draw();
    this.frame = moving ? requestAnimationFrame(next => this.tick(next)) : null;
  }

  draw() {
    const {width, height} = this.image;
    const stride = width * 3;
    for (let row = 0; row < 3; row++) {
      for (let channel = 0; channel < 3; channel++) {
        const start = row * 9 + channel;
        const left = this.current[start], center = this.current[start + 3], right = this.current[start + 6];
        const rising = center - left, falling = right - center;
        const middle = middleSlope(rising, falling);
        for (let x = 0; x < width; x++) {
          this.rows[row * stride + x * 3 + channel] =
            interpolate(this.horizontal[x], left, center, right, rising, falling, middle);
        }
      }
    }
    // Monotone cubic interpolation keeps sharp changes smooth without overshooting.
    const pixels = this.image.data;
    for (let x = 0; x < width; x++) {
      for (let channel = 0; channel < 3; channel++) {
        const start = x * 3 + channel;
        const top = this.rows[start], center = this.rows[stride + start], bottom = this.rows[2 * stride + start];
        const rising = center - top, falling = bottom - center;
        const middle = middleSlope(rising, falling);
        for (let y = 0; y < height; y++) {
          const pixel = (y * width + x) * 4;
          pixels[pixel + channel] =
            interpolate(this.vertical[y], top, center, bottom, rising, falling, middle);
          pixels[pixel + 3] = 255;
        }
      }
    }
    this.context.putImageData(this.image, 0, 0);
  }
}
