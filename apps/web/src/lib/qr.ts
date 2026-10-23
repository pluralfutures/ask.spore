// A QR code encoder (ISO/IEC 18004), byte mode only, for the TOTP enrolment page
// (P1c-08): the otpauth:// URI becomes an image the admin scans with their phone. Written
// here rather than added as a dependency (CLAUDE.md asks for no new runtime dependency);
// it follows the standard's procedure step by step: data codewords, Reed-Solomon error
// correction, block interleaving, function patterns, the eight masks scored by the
// standard's penalty rules, then format and version information. Nothing leaves the
// browser.

export type Ecc = "L" | "M" | "Q" | "H";

// Per error-correction level: the format bits, then per version 1..40 the error
// correction codewords per block and the number of blocks.
const ECC_FORMAT: Record<Ecc, number> = { L: 1, M: 0, Q: 3, H: 2 };
const ECC_ORDER: Record<Ecc, number> = { L: 0, M: 1, Q: 2, H: 3 };
// prettier-ignore
const EC_CODEWORDS_PER_BLOCK: number[][] = [
  [-1, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30, 22, 24, 28, 30, 28, 28, 28, 28, 30, 30, 26, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
  [-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26, 26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28],
  [-1, 13, 22, 18, 26, 18, 24, 18, 22, 20, 24, 28, 26, 24, 20, 30, 24, 28, 28, 26, 30, 28, 30, 30, 30, 30, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
  [-1, 17, 28, 22, 16, 22, 28, 26, 26, 24, 28, 24, 28, 22, 24, 24, 30, 28, 28, 26, 28, 30, 24, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
];
// prettier-ignore
const EC_BLOCKS: number[][] = [
  [-1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4, 6, 6, 6, 6, 7, 8, 8, 9, 9, 10, 12, 12, 12, 13, 14, 15, 16, 17, 18, 19, 19, 20, 21, 22, 24, 25],
  [-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16, 17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49],
  [-1, 1, 1, 2, 2, 4, 4, 6, 6, 8, 8, 8, 10, 12, 16, 12, 17, 16, 18, 21, 20, 23, 23, 25, 27, 29, 34, 34, 35, 38, 40, 43, 45, 48, 51, 53, 56, 59, 62, 65, 68],
  [-1, 1, 1, 2, 4, 4, 4, 5, 6, 8, 8, 11, 11, 16, 16, 18, 16, 19, 21, 25, 25, 25, 34, 30, 32, 35, 37, 40, 42, 45, 48, 51, 54, 57, 60, 63, 66, 70, 74, 77, 81],
];

/** Modules of the code, ``true`` for dark, indexed ``[row][column]``. */
export type QrMatrix = boolean[][];

// Indexing helpers: every index below is in range by construction, and these give the
// fallback ``noUncheckedIndexedAccess`` asks for.
const at = (list: readonly number[], i: number): number => list[i] ?? 0;
const isDark = (m: QrMatrix, x: number, y: number): boolean => m[y]?.[x] ?? false;
const lookup = (rows: number[][], ecc: Ecc, version: number): number =>
  at(rows[ECC_ORDER[ecc]] ?? [], version);

function rawModules(version: number): number {
  let result = (16 * version + 128) * version + 64;
  if (version >= 2) {
    const align = Math.floor(version / 7) + 2;
    result -= (25 * align - 10) * align - 55;
    if (version >= 7) result -= 36;
  }
  return result;
}

function dataCodewords(version: number, ecc: Ecc): number {
  return (
    Math.floor(rawModules(version) / 8) -
    lookup(EC_CODEWORDS_PER_BLOCK, ecc, version) * lookup(EC_BLOCKS, ecc, version)
  );
}

// --- Reed-Solomon over GF(2^8), polynomial 0x11D ----------------------------------

function multiply(x: number, y: number): number {
  let z = 0;
  for (let i = 7; i >= 0; i--) {
    z = (z << 1) ^ ((z >>> 7) * 0x11d);
    z ^= ((y >>> i) & 1) * x;
  }
  return z & 0xff;
}

function divisor(degree: number): number[] {
  const result = new Array<number>(degree).fill(0);
  result[degree - 1] = 1;
  let root = 1;
  for (let i = 0; i < degree; i++) {
    for (let j = 0; j < degree; j++) {
      result[j] = multiply(at(result, j), root) ^ (j + 1 < degree ? at(result, j + 1) : 0);
    }
    root = multiply(root, 0x02);
  }
  return result;
}

function remainder(data: number[], div: number[]): number[] {
  const result = new Array<number>(div.length).fill(0);
  for (const b of data) {
    const factor = b ^ (result.shift() ?? 0);
    result.push(0);
    div.forEach((coef, i) => {
      result[i] = at(result, i) ^ multiply(coef, factor);
    });
  }
  return result;
}

// --- codewords ---------------------------------------------------------------------

function encodeData(bytes: Uint8Array, version: number, ecc: Ecc): number[] {
  const capacity = dataCodewords(version, ecc) * 8;
  const bits: number[] = [];
  const append = (value: number, length: number) => {
    for (let i = length - 1; i >= 0; i--) bits.push((value >>> i) & 1);
  };
  append(0b0100, 4); // byte mode
  append(bytes.length, version <= 9 ? 8 : 16);
  bytes.forEach((b) => append(b, 8));
  append(0, Math.min(4, capacity - bits.length)); // terminator
  append(0, (8 - (bits.length % 8)) % 8);
  for (let pad = 0xec; bits.length < capacity; pad ^= 0xec ^ 0x11) append(pad, 8);
  const words: number[] = [];
  for (let i = 0; i < bits.length; i += 8) {
    words.push(bits.slice(i, i + 8).reduce((acc, bit) => (acc << 1) | bit, 0));
  }
  return words;
}

function withErrorCorrection(data: number[], version: number, ecc: Ecc): number[] {
  const blockCount = lookup(EC_BLOCKS, ecc, version);
  const ecLength = lookup(EC_CODEWORDS_PER_BLOCK, ecc, version);
  const raw = Math.floor(rawModules(version) / 8);
  const shortBlocks = blockCount - (raw % blockCount);
  const shortLength = Math.floor(raw / blockCount);
  const div = divisor(ecLength);
  const blocks: number[][] = [];
  for (let i = 0, k = 0; i < blockCount; i++) {
    const take = shortLength - ecLength + (i < shortBlocks ? 0 : 1);
    const chunk = data.slice(k, k + take);
    k += take;
    const ec = remainder(chunk, div);
    if (i < shortBlocks) chunk.push(0); // placeholder, skipped when interleaving
    blocks.push([...chunk, ...ec]);
  }
  const result: number[] = [];
  for (let i = 0; i <= shortLength; i++) {
    blocks.forEach((block, j) => {
      if (i !== shortLength - ecLength || j >= shortBlocks) result.push(at(block, i));
    });
  }
  return result;
}

// --- the matrix --------------------------------------------------------------------

function alignmentPositions(version: number): number[] {
  if (version === 1) return [];
  const count = Math.floor(version / 7) + 2;
  const step = Math.floor((version * 8 + count * 3 + 5) / (count * 4 - 4)) * 2;
  const result = [6];
  for (let pos = version * 4 + 10; result.length < count; pos -= step) result.splice(1, 0, pos);
  return result;
}

const MASKS: ((x: number, y: number) => boolean)[] = [
  (x, y) => (x + y) % 2 === 0,
  (_x, y) => y % 2 === 0,
  (x) => x % 3 === 0,
  (x, y) => (x + y) % 3 === 0,
  (x, y) => (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0,
  (x, y) => ((x * y) % 2) + ((x * y) % 3) === 0,
  (x, y) => (((x * y) % 2) + ((x * y) % 3)) % 2 === 0,
  (x, y) => (((x + y) % 2) + ((x * y) % 3)) % 2 === 0,
];

class Grid {
  readonly size: number;
  readonly modules: boolean[][];
  private readonly reserved: boolean[][];

  constructor(readonly version: number) {
    this.size = version * 4 + 17;
    const blank = () =>
      Array.from({ length: this.size }, () => new Array<boolean>(this.size).fill(false));
    this.modules = blank();
    this.reserved = blank();
  }

  private put(x: number, y: number, value: boolean) {
    const row = this.modules[y];
    if (row) row[x] = value;
  }

  private free(x: number, y: number): boolean {
    return !(this.reserved[y]?.[x] ?? true);
  }

  set(x: number, y: number, value: boolean) {
    this.put(x, y, value);
    const row = this.reserved[y];
    if (row) row[x] = true;
  }

  functionPatterns() {
    const n = this.size;
    for (let i = 0; i < n; i++) {
      this.set(6, i, i % 2 === 0);
      this.set(i, 6, i % 2 === 0);
    }
    const finders: [number, number][] = [
      [3, 3],
      [n - 4, 3],
      [3, n - 4],
    ];
    for (const [cx, cy] of finders) {
      for (let dy = -4; dy <= 4; dy++) {
        for (let dx = -4; dx <= 4; dx++) {
          const d = Math.max(Math.abs(dx), Math.abs(dy));
          const x = cx + dx;
          const y = cy + dy;
          if (x >= 0 && x < n && y >= 0 && y < n) this.set(x, y, d !== 2 && d !== 4);
        }
      }
    }
    const align = alignmentPositions(this.version);
    const last = align.length - 1;
    align.forEach((ay, i) =>
      align.forEach((ax, j) => {
        if ((i === 0 && j === 0) || (i === 0 && j === last) || (i === last && j === 0)) return;
        for (let dy = -2; dy <= 2; dy++) {
          for (let dx = -2; dx <= 2; dx++) {
            this.set(ax + dx, ay + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
          }
        }
      }),
    );
    this.format(0, "M"); // reserves the format areas; drawn for real after masking
    this.versionInfo();
  }

  format(mask: number, ecc: Ecc) {
    const data = (ECC_FORMAT[ecc] << 3) | mask;
    let rem = data;
    for (let i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
    const bits = ((data << 10) | rem) ^ 0x5412;
    const bit = (i: number) => ((bits >>> i) & 1) === 1;
    const n = this.size;
    for (let i = 0; i <= 5; i++) this.set(8, i, bit(i));
    this.set(8, 7, bit(6));
    this.set(8, 8, bit(7));
    this.set(7, 8, bit(8));
    for (let i = 9; i < 15; i++) this.set(14 - i, 8, bit(i));
    for (let i = 0; i < 8; i++) this.set(n - 1 - i, 8, bit(i));
    for (let i = 8; i < 15; i++) this.set(8, n - 15 + i, bit(i));
    this.set(8, n - 8, true); // the dark module
  }

  versionInfo() {
    if (this.version < 7) return;
    let rem = this.version;
    for (let i = 0; i < 12; i++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1f25);
    const bits = (this.version << 12) | rem;
    for (let i = 0; i < 18; i++) {
      const value = ((bits >>> i) & 1) === 1;
      const a = this.size - 11 + (i % 3);
      const b = Math.floor(i / 3);
      this.set(a, b, value);
      this.set(b, a, value);
    }
  }

  codewords(words: number[]) {
    const n = this.size;
    let i = 0;
    for (let right = n - 1; right >= 1; right -= 2) {
      if (right === 6) right = 5;
      for (let vert = 0; vert < n; vert++) {
        for (let j = 0; j < 2; j++) {
          const x = right - j;
          const upward = ((right + 1) & 2) === 0;
          const y = upward ? n - 1 - vert : vert;
          if (this.free(x, y) && i < words.length * 8) {
            this.put(x, y, ((at(words, i >>> 3) >>> (7 - (i & 7))) & 1) === 1);
            i++;
          }
        }
      }
    }
  }

  applyMask(mask: number) {
    const rule = MASKS[mask] ?? MASKS[0];
    for (let y = 0; y < this.size; y++) {
      for (let x = 0; x < this.size; x++) {
        if (this.free(x, y) && rule?.(x, y)) this.put(x, y, !isDark(this.modules, x, y));
      }
    }
  }
}

// The standard's penalty score (N1 = 3, N2 = 3, N3 = 40, N4 = 10).
export function penalty(m: QrMatrix): number {
  const n = m.length;
  let score = 0;
  const FINDER = [true, false, true, true, true, false, true];
  const lines = (get: (i: number, j: number) => boolean) => {
    for (let i = 0; i < n; i++) {
      let run = 1;
      for (let j = 1; j <= n; j++) {
        if (j < n && get(i, j) === get(i, j - 1)) {
          run++;
          continue;
        }
        if (run >= 5) score += 3 + (run - 5);
        run = 1;
      }
      // Finder-like 1:1:3:1:1 with four light modules on either side.
      for (let j = 0; j + 7 <= n; j++) {
        if (!FINDER.every((value, k) => get(i, j + k) === value)) continue;
        const lightBefore = [1, 2, 3, 4].every((k) => j - k < 0 || !get(i, j - k));
        const lightAfter = [0, 1, 2, 3].every((k) => j + 7 + k >= n || !get(i, j + 7 + k));
        if (lightBefore) score += 40;
        if (lightAfter) score += 40;
      }
    }
  };
  lines((i, j) => isDark(m, j, i));
  lines((i, j) => isDark(m, i, j));
  for (let y = 0; y + 1 < n; y++) {
    for (let x = 0; x + 1 < n; x++) {
      const c = isDark(m, x, y);
      if (c === isDark(m, x + 1, y) && c === isDark(m, x, y + 1) && c === isDark(m, x + 1, y + 1)) {
        score += 3;
      }
    }
  }
  const darkCount = m.reduce((acc, row) => acc + row.filter(Boolean).length, 0);
  const total = n * n;
  const k = Math.ceil(Math.abs(darkCount * 20 - total * 10) / total) - 1;
  score += Math.max(0, k) * 10;
  return score;
}

/** The QR code for ``text`` (UTF-8, byte mode): the smallest version that holds it at
 * ``ecc``, with the mask of lowest penalty unless ``mask`` is given. */
export function encodeQr(text: string, ecc: Ecc = "M", mask?: number): QrMatrix {
  const bytes = new TextEncoder().encode(text);
  let version = 1;
  for (; version <= 40; version++) {
    const header = 4 + (version <= 9 ? 8 : 16);
    if (header + bytes.length * 8 <= dataCodewords(version, ecc) * 8) break;
  }
  if (version > 40) throw new Error("text too long for a QR code");
  const words = withErrorCorrection(encodeData(bytes, version, ecc), version, ecc);
  const build = (m: number): QrMatrix => {
    const grid = new Grid(version);
    grid.functionPatterns();
    grid.codewords(words);
    grid.applyMask(m);
    grid.format(m, ecc);
    return grid.modules;
  };
  if (mask !== undefined) return build(mask);
  let best = build(0);
  let bestScore = penalty(best);
  for (let m = 1; m < 8; m++) {
    const candidate = build(m);
    const score = penalty(candidate);
    if (score < bestScore) {
      best = candidate;
      bestScore = score;
    }
  }
  return best;
}

/** One SVG path drawing every dark module, with a four-module quiet zone. */
export function qrPath(matrix: QrMatrix, quiet = 4): { d: string; size: number } {
  const parts: string[] = [];
  matrix.forEach((row, y) =>
    row.forEach((value, x) => {
      if (value) parts.push(`M${x + quiet},${y + quiet}h1v1h-1z`);
    }),
  );
  return { d: parts.join(""), size: matrix.length + quiet * 2 };
}
