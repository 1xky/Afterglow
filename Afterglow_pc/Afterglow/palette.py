"""Build a palette for each phone placement from a small RGB frame."""

from functools import lru_cache

WIDTH, HEIGHT = 36, 22
BLACK = [[0, 0, 0] for _ in range(9)]
DEMO = [[117, 54, 208], [171, 63, 177], [244, 117, 87],
        [71, 55, 188], [139, 56, 192], [226, 87, 99],
        [35, 32, 142], [100, 44, 160], [178, 61, 143]]
PLACEMENTS = {
    "center": ((.17, .5, .83), (.18, .5, .82)),
    "left": ((.12, .24, .38), (.18, .5, .82)),
    "right": ((.62, .76, .88), (.18, .5, .82)),
    "below": ((.17, .5, .83), (.59, .76, .9)),
    "flat": ((.17, .5, .83), (.56, .73, .88)),
}
DEFAULT_VIVIDNESS = 55


def to_linear(value):
    return value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4


def to_rgb(value):
    channel = (12.92 * value if value <= .0031308
               else 1.055 * value ** (1 / 2.4) - .055)
    return round(255 * channel)


LINEAR = [to_linear(value / 255) for value in range(256)]


def matte_bounds(pixels):
    """Find paired dark bars, allowing a few bright subtitle or compression pixels."""
    peaks = [max(pixel) for pixel in pixels]

    def matching_bars(length, stripe, stripe_width, tolerance, subtitles=False):
        def mostly_dark(position, allow_subtitles):
            bright = [peaks[index] > 26 for index in stripe(position)]
            count = sum(bright)
            if count <= tolerance:
                return True
            if allow_subtitles and count * 2 <= stripe_width:
                edge = stripe_width // 5
                return sum(bright[:edge]) + sum(bright[-edge:]) <= 1
            return False

        def run(positions, allow_subtitles=False):
            for index, position in enumerate(positions):
                if not mostly_dark(position, allow_subtitles):
                    return index
            return limit + 1

        limit = length // 4
        near = run(range(limit + 1))
        far = run(range(length - 1, length - limit - 2, -1), subtitles)
        if min(near, far) == 0 or max(near, far) > limit or abs(near - far) > 2:
            return 0, length
        # Require a visible boundary on each side before trimming a dim scene.
        for edge in (near, length - 1 - far):
            if sum(peaks[index] > 39 for index in stripe(edge)) * 4 < stripe_width:
                return 0, length
        return near, length - far

    top, bottom = matching_bars(
        HEIGHT, lambda y: range(y * WIDTH + 2, (y + 1) * WIDTH - 2),
        WIDTH - 4, (WIDTH - 4) // 4, subtitles=True)
    left, right = matching_bars(
        WIDTH, lambda x: range(top * WIDTH + x, bottom * WIDTH + x, WIDTH),
        bottom - top, (bottom - top) // 8)
    return left, top, right, bottom


def _axis_weights(start, end, fraction, span, minimum):
    center = start + fraction * (end - start - 1)
    radius = max(minimum, (end - start) * span)
    return [(position, max(0, 1 - abs(position - center) / radius))
            for position in range(max(start, int(center - radius)),
                                  min(end, int(center + radius) + 1))]


@lru_cache(maxsize=96)
def _kernels(bounds, placements):
    left, top, right, bottom = bounds
    kernels = {}
    for placement in placements:
        columns, rows = PLACEMENTS[placement]
        for y in rows:
            for x in columns:
                if (x, y) not in kernels:
                    xs = _axis_weights(left, right, x, .23, 3)
                    ys = _axis_weights(top, bottom, y, .28, 2)
                    kernels[x, y] = [(row * WIDTH + column, wy * wx)
                                     for row, wy in ys for column, wx in xs if wy * wx]
    return kernels


def _extract(raw, placements, vividness):
    pixels = list(zip(raw[::3], raw[1::3], raw[2::3]))
    bounds = matte_bounds(pixels)
    strength = vividness / 100
    samples = []
    for red, green, blue in pixels:
        peak = max(red, green, blue)
        chroma = peak - min(red, green, blue)
        # Ignore tiny color casts in near-black pixels when choosing vibrant samples.
        saturation = chroma / max(peak, 48)
        weight = 1 + 7 * strength * saturation ** 2 * min(1, chroma / 96)
        samples.append((LINEAR[red] * weight, LINEAR[green] * weight,
                        LINEAR[blue] * weight, weight))

    colors = {}
    for position, kernel in _kernels(bounds, placements).items():
        red = green = blue = total = 0.0
        for index, spatial_weight in kernel:
            r, g, b, weight = samples[index]
            red += r * spatial_weight
            green += g * spatial_weight
            blue += b * spatial_weight
            total += weight * spatial_weight
        channels = [to_rgb(channel / total) for channel in (red, green, blue)]
        peak = max(channels)
        # Expand existing chroma while leaving the brightest channel and greys alone.
        gain = 1 + .35 * strength * (peak - min(channels)) / max(peak, 48)
        colors[position] = [max(0, round(peak - (peak - channel) * gain))
                            for channel in channels]
    return {placement: [colors[x, y] for y in PLACEMENTS[placement][1]
                        for x in PLACEMENTS[placement][0]] for placement in placements}


def extract_colors(raw, placement, vividness=DEFAULT_VIVIDNESS):
    """Extract one row-major 3×3 palette."""
    return _extract(raw, (placement,), vividness)[placement]


def extract_palettes(raw, vividness=DEFAULT_VIVIDNESS):
    """Share frame analysis and overlapping zones across phone placements."""
    return _extract(raw, tuple(PLACEMENTS), vividness)


def demo_frame():
    raw = bytearray()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            fx, fy = x * 2 / (WIDTH - 1), y * 2 / (HEIGHT - 1)
            column, row = min(1, int(fx)), min(1, int(fy))
            a, b = fx - column, fy - row
            index = row * 3 + column
            for channel in range(3):
                top = DEMO[index][channel] * (1 - a) + DEMO[index + 1][channel] * a
                bottom = DEMO[index + 3][channel] * (1 - a) + DEMO[index + 4][channel] * a
                raw.append(round(top * (1 - b) + bottom * b))
    return bytes(raw)
