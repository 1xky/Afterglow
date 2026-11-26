// QR Model 2, version 3-L. Its 53-byte payload fits all IPv4 Afterglow URLs.
const SIZE = 29;
const DATA_CODEWORDS = 55;
const ECC_CODEWORDS = 15;
const MASKS = [
  (x, y) => (x + y) % 2 === 0,
  (x, y) => y % 2 === 0,
  x => x % 3 === 0,
  (x, y) => (x + y) % 3 === 0,
  (x, y) => (Math.floor(y / 2) + Math.floor(x / 3)) % 2 === 0,
  (x, y) => x * y % 2 + x * y % 3 === 0,
  (x, y) => (x * y % 2 + x * y % 3) % 2 === 0,
  (x, y) => ((x + y) % 2 + x * y % 3) % 2 === 0
];

function multiply(a, b) {
  let product = 0;
  for (; b; b >>>= 1) {
    if (b & 1) product ^= a;
    a <<= 1;
    if (a & 256) a ^= 0x11d;
  }
  return product;
}

function correction(data) {
  const divisor = new Uint8Array(ECC_CODEWORDS);
  divisor[divisor.length - 1] = 1;
  let root = 1;
  for (let i = 0; i < divisor.length; i++) {
    for (let j = 0; j < divisor.length; j++) {
      divisor[j] = multiply(divisor[j], root) ^ (divisor[j + 1] ?? 0);
    }
    root = multiply(root, 2);
  }
  const remainder = new Uint8Array(ECC_CODEWORDS);
  for (const byte of data) {
    const factor = byte ^ remainder[0];
    remainder.copyWithin(0, 1);
    remainder[remainder.length - 1] = 0;
    for (let i = 0; i < remainder.length; i++) remainder[i] ^= multiply(divisor[i], factor);
  }
  return remainder;
}

function encode(text) {
  const bytes = new TextEncoder().encode(text);
  if (bytes.length > 53) throw new RangeError("Pairing URL is too long for the QR code.");
  const data = new Uint8Array(DATA_CODEWORDS);
  let index = 0;
  function append(value, count) {
    for (let i = count - 1; i >= 0; i--) {
      data[index >> 3] |= ((value >>> i) & 1) << (7 - (index++ & 7));
    }
  }
  append(4, 4); // Byte mode
  append(bytes.length, 8);
  for (const byte of bytes) append(byte, 8);
  append(0, 4); // Terminator, including byte alignment for this profile
  for (let i = index / 8, pad = 0xec; i < data.length; i++, pad ^= 0xec ^ 0x11) data[i] = pad;
  return Uint8Array.from([...data, ...correction(data)]);
}

function matrix(code, mask) {
  const modules = Array.from({length: SIZE}, () => new Int8Array(SIZE).fill(-1));
  const set = (x, y, dark) => { modules[y][x] = Number(dark); };

  for (let i = 0; i < SIZE; i++) {
    set(6, i, i % 2 === 0);
    set(i, 6, i % 2 === 0);
  }
  for (const [cx, cy] of [[3, 3], [SIZE - 4, 3], [3, SIZE - 4]]) {
    for (let dy = -4; dy <= 4; dy++) {
      for (let dx = -4; dx <= 4; dx++) {
        const x = cx + dx, y = cy + dy;
        if (x < 0 || y < 0 || x >= SIZE || y >= SIZE) continue;
        const distance = Math.max(Math.abs(dx), Math.abs(dy));
        set(x, y, distance !== 2 && distance !== 4);
      }
    }
  }
  for (let dy = -2; dy <= 2; dy++) {
    for (let dx = -2; dx <= 2; dx++) {
      set(22 + dx, 22 + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
    }
  }

  const format = 8 | mask; // Low error correction level and mask index
  let remainder = format;
  for (let i = 0; i < 10; i++) remainder = (remainder << 1) ^ ((remainder >> 9) * 0x537);
  const bits = ((format << 10) | remainder) ^ 0x5412;
  const bit = index => (bits >>> index) & 1;
  for (let i = 0; i < 6; i++) set(8, i, bit(i));
  set(8, 7, bit(6));
  set(8, 8, bit(7));
  set(7, 8, bit(8));
  for (let i = 9; i < 15; i++) set(14 - i, 8, bit(i));
  for (let i = 0; i < 8; i++) set(SIZE - 1 - i, 8, bit(i));
  for (let i = 8; i < 15; i++) set(8, SIZE - 15 + i, bit(i));
  set(8, SIZE - 8, true);

  let index = 0;
  let upwards = true;
  for (let right = SIZE - 1; right >= 1; right -= 2) {
    if (right === 6) right--;
    for (let row = 0; row < SIZE; row++) {
      const y = upwards ? SIZE - 1 - row : row;
      for (const x of [right, right - 1]) {
        if (modules[y][x] !== -1) continue;
        const value = (code[index >> 3] ?? 0) >>> (7 - (index++ & 7)) & 1;
        set(x, y, value ^ MASKS[mask](x, y));
      }
    }
    upwards = !upwards;
  }
  return modules;
}

function penalty(modules) {
  let score = 0, dark = 0;
  function line(values) {
    let last = -1, run = 0, window = 0;
    for (const [index, value] of values.entries()) {
      run = value === last ? run + 1 : 1;
      last = value;
      if (run >= 5) score += run === 5 ? 3 : 1;
      window = ((window << 1) | value) & 0x7ff;
      if (index >= 10 && (window === 0x05d || window === 0x5d0)) score += 40;
    }
  }
  for (let y = 0; y < SIZE; y++) {
    line(modules[y]);
    line(modules.map(row => row[y]));
    for (let x = 0; x < SIZE; x++) {
      const color = modules[y][x];
      dark += color;
      if (x && y && color === modules[y][x - 1] && color === modules[y - 1][x]
          && color === modules[y - 1][x - 1]) score += 3;
    }
  }
  return score + 10 * Math.floor(Math.abs(dark / (SIZE * SIZE) - .5) * 20);
}

export function pairingMatrix(url) {
  const code = encode(url);
  let best, lowest = Infinity;
  for (let mask = 0; mask < MASKS.length; mask++) {
    const candidate = matrix(code, mask);
    const score = penalty(candidate);
    if (score < lowest) {
      lowest = score;
      best = candidate;
    }
  }
  return best;
}

export function drawPairingQR(canvas, url) {
  const modules = pairingMatrix(url);
  const quietZone = 4;
  const scale = 5;
  canvas.width = canvas.height = (modules.length + 2 * quietZone) * scale;
  const context = canvas.getContext("2d", {alpha: false});
  context.fillStyle = "#fff";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.fillStyle = "#000";
  modules.forEach((row, y) => row.forEach((dark, x) => {
    if (dark) context.fillRect((x + quietZone) * scale, (y + quietZone) * scale, scale, scale);
  }));
}
