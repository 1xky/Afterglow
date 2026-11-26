package local.afterglow.tv;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;

/** QR Model 2 version 3-L, byte mode, mask 2. An IPv4 pairing URL fits in 53 bytes. */
final class PairingQr {
    private static final int SIZE = 29, DATA = 55, ECC = 15, MASK = 2;
    private PairingQr() {}

    static boolean[][] encode(String text) {
        byte[] message = text.getBytes(StandardCharsets.UTF_8);
        if (message.length > 53) throw new IllegalArgumentException("Pairing URL too long");
        int[] codewords = new int[DATA + ECC];
        int offset = append(codewords, 0, 4, 4);
        offset = append(codewords, offset, message.length, 8);
        for (byte value : message) offset = append(codewords, offset, value & 255, 8);
        offset = append(codewords, offset, 0, 4);
        for (int i = offset / 8, pad = 0xec; i < DATA; i++, pad ^= 0xec ^ 0x11) codewords[i] = pad;
        addCorrection(codewords);

        int[][] grid = new int[SIZE][SIZE];
        for (int[] row : grid) Arrays.fill(row, -1);
        for (int i = 0; i < SIZE; i++) grid[6][i] = grid[i][6] = 1 - i % 2;
        finder(grid, 3, 3);
        finder(grid, SIZE - 4, 3);
        finder(grid, 3, SIZE - 4);
        for (int y = -2; y <= 2; y++) {
            for (int x = -2; x <= 2; x++) {
                grid[22 + y][22 + x] = Math.max(Math.abs(x), Math.abs(y)) == 1 ? 0 : 1;
            }
        }
        format(grid);
        int index = 0;
        boolean up = true;
        for (int right = SIZE - 1; right >= 1; right -= 2) {
            if (right == 6) right--;
            for (int row = 0; row < SIZE; row++) {
                int y = up ? SIZE - 1 - row : row;
                for (int x = right; x >= right - 1; x--) {
                    if (grid[y][x] != -1) continue;
                    int value = index < codewords.length * 8
                            ? bit(codewords[index / 8], 7 - index % 8) : 0;
                    grid[y][x] = value ^ (x % 3 == 0 ? 1 : 0);
                    index++;
                }
            }
            up = !up;
        }
        boolean[][] modules = new boolean[SIZE][SIZE];
        for (int y = 0; y < SIZE; y++) {
            for (int x = 0; x < SIZE; x++) modules[y][x] = grid[y][x] == 1;
        }
        return modules;
    }

    private static int append(int[] data, int position, int value, int bits) {
        for (int i = bits - 1; i >= 0; i--, position++) {
            data[position / 8] |= bit(value, i) << (7 - position % 8);
        }
        return position;
    }

    private static int bit(int value, int index) { return value >>> index & 1; }

    private static void format(int[][] grid) {
        int value = 8 | MASK, remainder = value;
        for (int i = 0; i < 10; i++) remainder = (remainder << 1) ^ ((remainder >> 9) * 0x537);
        int bits = ((value << 10) | remainder) ^ 0x5412;
        for (int i = 0; i < 6; i++) grid[i][8] = bit(bits, i);
        grid[7][8] = bit(bits, 6);
        grid[8][8] = bit(bits, 7);
        grid[8][7] = bit(bits, 8);
        for (int i = 9; i < 15; i++) grid[8][14 - i] = bit(bits, i);
        for (int i = 0; i < 8; i++) grid[8][SIZE - 1 - i] = bit(bits, i);
        for (int i = 8; i < 15; i++) grid[SIZE - 15 + i][8] = bit(bits, i);
        grid[SIZE - 8][8] = 1;
    }

    private static void finder(int[][] grid, int cx, int cy) {
        for (int dy = -4; dy <= 4; dy++) {
            for (int dx = -4; dx <= 4; dx++) {
                int x = cx + dx, y = cy + dy;
                if (x < 0 || y < 0 || x >= SIZE || y >= SIZE) continue;
                int distance = Math.max(Math.abs(dx), Math.abs(dy));
                grid[y][x] = distance == 2 || distance == 4 ? 0 : 1;
            }
        }
    }

    private static int multiply(int a, int b) {
        int product = 0;
        for (; b != 0; b >>>= 1) {
            if ((b & 1) != 0) product ^= a;
            a <<= 1;
            if ((a & 256) != 0) a ^= 0x11d;
        }
        return product;
    }

    private static void addCorrection(int[] codewords) {
        int[] divisor = new int[ECC];
        divisor[ECC - 1] = 1;
        int root = 1;
        for (int i = 0; i < ECC; i++, root = multiply(root, 2)) {
            for (int j = 0; j < ECC; j++) {
                divisor[j] = multiply(divisor[j], root) ^ (j + 1 < ECC ? divisor[j + 1] : 0);
            }
        }
        for (int i = 0; i < DATA; i++) {
            int factor = codewords[i] ^ codewords[DATA];
            System.arraycopy(codewords, DATA + 1, codewords, DATA, ECC - 1);
            codewords[codewords.length - 1] = 0;
            for (int j = 0; j < ECC; j++) codewords[DATA + j] ^= multiply(divisor[j], factor);
        }
    }
}
