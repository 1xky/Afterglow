package local.afterglow.tv;

import java.nio.ByteBuffer;

/** Afterglow's small RGB grid and placement palettes. */
final class Palette {
    static final int WIDTH = 36, HEIGHT = 22;
    static final int FRAME_BYTES = WIDTH * HEIGHT * 3;
    static final String[] PLACEMENTS = {"center", "left", "right", "below", "flat"};
    static final int[][][] BLACK = new int[5][9][3];
    private static final double[][] COLUMNS = {{.17, .50, .83}, {.12, .24, .38}, {.62, .76, .88}};
    private static final double[][] ROWS = {{.18, .50, .82}, {.59, .76, .90}, {.56, .73, .88}};
    private static final int[] COLUMN_LAYOUT = {0, 1, 2, 0, 0};
    private static final int[] ROW_LAYOUT = {0, 0, 0, 1, 2};
    private static final double[] LINEAR = new double[256];

    static {
        for (int i = 0; i < 256; i++) {
            double c = i / 255.0;
            LINEAR[i] = c <= .04045 ? c / 12.92 : Math.pow((c + .055) / 1.055, 2.4);
        }
    }

    private Palette() {}

    static void sample(ByteBuffer rgba, int width, int height, int stride, int pixelStride,
                       byte[] rgb) {
        int origin = rgba.position();
        for (int y = 0; y < HEIGHT; y++) {
            int top = y * height / HEIGHT;
            int bottom = Math.max(top + 1, (y + 1) * height / HEIGHT);
            for (int x = 0; x < WIDTH; x++) {
                int left = x * width / WIDTH;
                int right = Math.max(left + 1, (x + 1) * width / WIDTH);
                int r = 0, g = 0, b = 0;
                for (int row = top; row < bottom; row++) {
                    for (int column = left; column < right; column++) {
                        int i = origin + row * stride + column * pixelStride;
                        r += rgba.get(i) & 255;
                        g += rgba.get(i + 1) & 255;
                        b += rgba.get(i + 2) & 255;
                    }
                }
                int count = (bottom - top) * (right - left);
                int p = (y * WIDTH + x) * 3;
                rgb[p] = (byte) ((r + count / 2) / count);
                rgb[p + 1] = (byte) ((g + count / 2) / count);
                rgb[p + 2] = (byte) ((b + count / 2) / count);
            }
        }
    }

    static int[][][] extract(byte[] rgb, int vividness) {
        int[] peaks = new int[WIDTH * HEIGHT];
        double[][] samples = new double[4][peaks.length];
        double strength = vividness / 100.0;
        for (int i = 0; i < peaks.length; i++) {
            int r = rgb[3 * i] & 255, g = rgb[3 * i + 1] & 255, b = rgb[3 * i + 2] & 255;
            int peak = Math.max(r, Math.max(g, b));
            int chroma = peak - Math.min(r, Math.min(g, b));
            double saturation = (double) chroma / Math.max(peak, 48);
            double weight = 1 + 7 * strength * saturation * saturation * Math.min(1, chroma / 96.0);
            peaks[i] = peak;
            samples[0][i] = LINEAR[r] * weight;
            samples[1][i] = LINEAR[g] * weight;
            samples[2][i] = LINEAR[b] * weight;
            samples[3][i] = weight;
        }
        int[] vertical = bars(peaks, true, 2, WIDTH - 2);
        int[] horizontal = bars(peaks, false, vertical[0], vertical[1]);
        int left = horizontal[0], right = horizontal[1], top = vertical[0], bottom = vertical[1];
        int rw = right - left, rh = bottom - top;
        double rx = Math.max(3, rw * .23), ry = Math.max(2, rh * .28);
        int[][][] palettes = new int[PLACEMENTS.length][9][3];
        for (int p = 0; p < PLACEMENTS.length; p++) {
            for (int i = 0; i < 9; i++) {
                double cx = left + COLUMNS[COLUMN_LAYOUT[p]][i % 3] * (rw - 1);
                double cy = top + ROWS[ROW_LAYOUT[p]][i / 3] * (rh - 1);
                double[] sums = new double[4];
                for (int y = Math.max(top, (int) (cy - ry)); y < Math.min(bottom, (int) (cy + ry) + 1); y++) {
                    double wy = Math.max(0, 1 - Math.abs(y - cy) / ry);
                    for (int x = Math.max(left, (int) (cx - rx)); x < Math.min(right, (int) (cx + rx) + 1); x++) {
                        double weight = wy * Math.max(0, 1 - Math.abs(x - cx) / rx);
                        for (int c = 0; c < 4; c++) sums[c] += samples[c][y * WIDTH + x] * weight;
                    }
                }
                int[] color = palettes[p][i];
                for (int c = 0; c < 3; c++) {
                    double v = sums[c] / sums[3];
                    color[c] = (int) Math.round(255 * (v <= .0031308 ? 12.92 * v :
                            1.055 * Math.pow(v, 1 / 2.4) - .055));
                }
                int peak = Math.max(color[0], Math.max(color[1], color[2]));
                int minimum = Math.min(color[0], Math.min(color[1], color[2]));
                double gain = 1 + .35 * strength * (peak - minimum) / Math.max(peak, 48);
                for (int c = 0; c < 3; c++) color[c] = Math.max(0, (int) Math.round(peak - (peak - color[c]) * gain));
            }
        }
        return palettes;
    }

    private static int[] bars(int[] peaks, boolean horizontal, int start, int end) {
        int length = horizontal ? HEIGHT : WIDTH;
        int span = end - start;
        int tolerance = span / (horizontal ? 4 : 8);
        int limit = length / 4;
        int near = 0, far = 0;
        while (near <= limit && bright(peaks, horizontal, near, start, end, 26) <= tolerance) near++;
        while (far <= limit) {
            int line = length - 1 - far;
            int count = bright(peaks, horizontal, line, start, end, 26);
            int edge = span / 5;
            if (count > tolerance && !(horizontal && count * 2 <= span &&
                    bright(peaks, true, line, start, start + edge, 26) +
                    bright(peaks, true, line, end - edge, end, 26) <= 1)) break;
            far++;
        }
        if (Math.min(near, far) == 0 || Math.max(near, far) > limit || Math.abs(near - far) > 2 ||
                bright(peaks, horizontal, near, start, end, 39) * 4 < span ||
                bright(peaks, horizontal, length - 1 - far, start, end, 39) * 4 < span) {
            return new int[] {0, length};
        }
        return new int[] {near, length - far};
    }

    private static int bright(int[] peaks, boolean horizontal, int line, int start, int end, int limit) {
        int count = 0;
        for (int i = start; i < end; i++) {
            if (peaks[horizontal ? line * WIDTH + i : i * WIDTH + line] > limit) count++;
        }
        return count;
    }

    static int[][][] demo(int vividness) {
        byte[] rgb = new byte[FRAME_BYTES];
        for (int y = 0; y < HEIGHT; y++) {
            for (int x = 0; x < WIDTH; x++) {
                int i = (y * WIDTH + x) * 3;
                rgb[i] = (byte) (70 + 160 * x / WIDTH - 35 * y / HEIGHT);
                rgb[i + 1] = (byte) (36 + 75 * x / WIDTH - 22 * y / HEIGHT);
                rgb[i + 2] = (byte) (225 - 125 * x / WIDTH - 35 * y / HEIGHT);
            }
        }
        return extract(rgb, vividness);
    }
}
