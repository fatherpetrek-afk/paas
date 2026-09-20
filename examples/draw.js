const fs = require("fs");
const readline = require("readline");
const path = require("path");

const W = 480;
const H = 280;
const outDir = path.join("output", "_display");
fs.mkdirSync(outDir, { recursive: true });

let mode = "wave";
let freq = 2;
let amp = 70;

function put32(buf, o, v) {
  buf.writeUInt32LE(v >>> 0, o);
}
function put16(buf, o, v) {
  buf.writeUInt16LE(v, o);
}

function writeBmp(rgb) {
  const row = (W * 3 + 3) & ~3;
  const img = row * H;
  const buf = Buffer.alloc(54 + img);
  buf.write("BM", 0);
  put32(buf, 2, buf.length);
  put32(buf, 10, 54);
  put32(buf, 14, 40);
  put32(buf, 18, W);
  put32(buf, 22, H);
  put16(buf, 26, 1);
  put16(buf, 28, 24);
  put32(buf, 34, img);
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      const i = (y * W + x) * 3;
      const o = 54 + (H - 1 - y) * row + x * 3;
      buf[o] = rgb[i + 2];
      buf[o + 1] = rgb[i + 1];
      buf[o + 2] = rgb[i];
    }
  }
  fs.writeFileSync(path.join(outDir, "frame.bmp"), buf);
}

function setPx(rgb, x, y, r, g, b) {
  if (x < 0 || y < 0 || x >= W || y >= H) return;
  const i = (y * W + x) * 3;
  rgb[i] = r;
  rgb[i + 1] = g;
  rgb[i + 2] = b;
}

function draw(t, note) {
  const rgb = Buffer.alloc(W * H * 3);
  for (let i = 0; i < W * H; i++) {
    rgb[i * 3] = 16;
    rgb[i * 3 + 1] = 24;
    rgb[i * 3 + 2] = 40;
  }
  const cx = (W / 2) | 0;
  const cy = (H / 2) | 0;
  if (mode === "bars") {
    for (let i = 0; i < 16; i++) {
      const h = (40 + amp * (0.4 + 0.6 * Math.abs(Math.sin(t * 0.8 + i * 0.4)))) | 0;
      const x0 = 30 + i * (((W - 60) / 16) | 0);
      for (let y = H - 20 - h; y < H - 20; y++) {
        for (let x = x0; x < x0 + 18; x++) setPx(rgb, x, y, 70 + i * 8, 140, 220 - i * 6);
      }
    }
  } else if (mode === "spiral") {
    for (let i = 0; i < 900; i++) {
      const a = i * 0.12 + t;
      const r = 8 + i * 0.12;
      const x = (cx + r * Math.cos(a)) | 0;
      const y = (cy + r * Math.sin(a) * 0.72) | 0;
      setPx(rgb, x, y, 255, 80 + (i % 120), 90);
    }
  } else {
    let px = -1;
    let py = -1;
    for (let x = 20; x < W - 20; x++) {
      let y = (cy - amp * Math.sin((x / 40) * freq + t)) | 0;
      if (y < 16) y = 16;
      if (y > H - 16) y = H - 16;
      if (px >= 0) {
        let steps = Math.max(Math.abs(x - px), Math.abs(y - py), 1);
        for (let s = 0; s <= steps; s++) {
          const xx = px + (((x - px) * s) / steps) | 0;
          const yy = py + (((y - py) * s) / steps) | 0;
          for (let dy = -1; dy <= 1; dy++) {
            for (let dx = -1; dx <= 1; dx++) setPx(rgb, xx + dx, yy + dy, 90, 200, 255);
          }
        }
      }
      px = x;
      py = y;
    }
    const r = 18;
    const x = (cx + 90 * Math.cos(t * 0.7)) | 0;
    const y = (cy + 40 * Math.sin(t * 0.7)) | 0;
    for (let yy = y - r; yy <= y + r; yy++) {
      for (let xx = x - r; xx <= x + r; xx++) {
        if ((xx - x) * (xx - x) + (yy - y) * (yy - y) <= r * r) setPx(rgb, xx, yy, 255, 120, 90);
      }
    }
  }
  writeBmp(rgb);
  console.log(`frame ${mode} freq=${freq.toFixed(2)} amp=${amp.toFixed(1)} ${note}`);
}

const pending = [];
const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
rl.on("line", (line) => pending.push(String(line || "").trim()));

console.log("draw_js ready. stdin: wave | bars | spiral | freq=2 | amp=70");
let t = 0;
let n = 0;
setInterval(() => {
  n += 1;
  const got = pending.shift() || "";
  if (got) {
    const low = got.toLowerCase();
    if (low === "wave" || low === "bars" || low === "spiral") mode = low;
    else if (got.includes("=")) {
      const parts = got.split("=");
      const key = (parts[0] || "").trim().toLowerCase();
      const val = Number(parts[1]);
      if (Number.isFinite(val) && key === "freq") freq = Math.max(0.2, Math.min(12, val));
      if (Number.isFinite(val) && key === "amp") amp = Math.max(8, Math.min(120, val));
    }
    console.log(`got: ${got}`);
    draw(t, "stdin");
  } else if (n === 1 || n % 4 === 0) {
    draw(t, "tick");
  }
  t += 0.25;
}, 250);
