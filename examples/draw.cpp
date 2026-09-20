#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>
#ifdef _WIN32
#include <direct.h>
#else
#include <sys/stat.h>
#endif

static const int W = 480;
static const int H = 280;
static std::string g_mode = "wave";
static double g_freq = 2.0;
static double g_amp = 70.0;
static std::mutex g_mu;
static std::string g_cmd;

static void ensure_dir() {
#ifdef _WIN32
  _mkdir("output");
  _mkdir("output/_display");
#else
  mkdir("output", 0755);
  mkdir("output/_display", 0755);
#endif
}

static void put32(std::vector<uint8_t>& b, int o, uint32_t v) {
  b[o] = uint8_t(v);
  b[o + 1] = uint8_t(v >> 8);
  b[o + 2] = uint8_t(v >> 16);
  b[o + 3] = uint8_t(v >> 24);
}

static void put16(std::vector<uint8_t>& b, int o, uint16_t v) {
  b[o] = uint8_t(v);
  b[o + 1] = uint8_t(v >> 8);
}

static void write_bmp(const std::vector<uint8_t>& rgb) {
  const int row = (W * 3 + 3) & ~3;
  const int img = row * H;
  std::vector<uint8_t> buf(54 + img, 0);
  buf[0] = 'B';
  buf[1] = 'M';
  put32(buf, 2, uint32_t(buf.size()));
  put32(buf, 10, 54);
  put32(buf, 14, 40);
  put32(buf, 18, uint32_t(W));
  put32(buf, 22, uint32_t(H));
  put16(buf, 26, 1);
  put16(buf, 28, 24);
  put32(buf, 34, uint32_t(img));
  for (int y = 0; y < H; ++y) {
    for (int x = 0; x < W; ++x) {
      const int i = (y * W + x) * 3;
      const int o = 54 + (H - 1 - y) * row + x * 3;
      buf[o] = rgb[i + 2];
      buf[o + 1] = rgb[i + 1];
      buf[o + 2] = rgb[i];
    }
  }
  std::ofstream out("output/_display/frame.bmp", std::ios::binary);
  out.write(reinterpret_cast<const char*>(buf.data()), std::streamsize(buf.size()));
}

static void set_px(std::vector<uint8_t>& rgb, int x, int y, int r, int g, int b) {
  if (x < 0 || y < 0 || x >= W || y >= H) return;
  const int i = (y * W + x) * 3;
  rgb[i] = uint8_t(r);
  rgb[i + 1] = uint8_t(g);
  rgb[i + 2] = uint8_t(b);
}

static void draw(double t, const std::string& note) {
  std::string mode;
  double freq, amp;
  {
    std::lock_guard<std::mutex> lock(g_mu);
    mode = g_mode;
    freq = g_freq;
    amp = g_amp;
  }
  std::vector<uint8_t> rgb(size_t(W * H * 3), 0);
  for (int i = 0; i < W * H; ++i) {
    rgb[i * 3] = 16;
    rgb[i * 3 + 1] = 24;
    rgb[i * 3 + 2] = 40;
  }
  const int cx = W / 2;
  const int cy = H / 2;
  if (mode == "bars") {
    for (int i = 0; i < 16; ++i) {
      int h = int(40 + amp * (0.4 + 0.6 * std::fabs(std::sin(t * 0.8 + i * 0.4))));
      int x0 = 30 + i * ((W - 60) / 16);
      for (int y = H - 20 - h; y < H - 20; ++y) {
        for (int x = x0; x < x0 + 18; ++x) set_px(rgb, x, y, 70 + i * 8, 140, 220 - i * 6);
      }
    }
  } else if (mode == "spiral") {
    for (int i = 0; i < 900; ++i) {
      double a = i * 0.12 + t;
      double r = 8 + i * 0.12;
      int x = int(cx + r * std::cos(a));
      int y = int(cy + r * std::sin(a) * 0.72);
      set_px(rgb, x, y, 255, 80 + (i % 120), 90);
    }
  } else {
    int px = -1, py = -1;
    for (int x = 20; x < W - 20; ++x) {
      int y = int(cy - amp * std::sin((x / 40.0) * freq + t));
      if (y < 16) y = 16;
      if (y > H - 16) y = H - 16;
      if (px >= 0) {
        int steps = std::abs(x - px);
        if (std::abs(y - py) > steps) steps = std::abs(y - py);
        if (steps < 1) steps = 1;
        for (int s = 0; s <= steps; ++s) {
          int xx = px + (x - px) * s / steps;
          int yy = py + (y - py) * s / steps;
          for (int dy = -1; dy <= 1; ++dy)
            for (int dx = -1; dx <= 1; ++dx) set_px(rgb, xx + dx, yy + dy, 90, 200, 255);
        }
      }
      px = x;
      py = y;
    }
    int r = 18;
    int x = int(cx + 90 * std::cos(t * 0.7));
    int y = int(cy + 40 * std::sin(t * 0.7));
    for (int yy = y - r; yy <= y + r; ++yy) {
      for (int xx = x - r; xx <= x + r; ++xx) {
        if ((xx - x) * (xx - x) + (yy - y) * (yy - y) <= r * r) set_px(rgb, xx, yy, 255, 120, 90);
      }
    }
  }
  write_bmp(rgb);
  std::cout << "frame " << mode << " freq=" << freq << " amp=" << amp << " " << note << std::endl;
}

static void reader() {
  std::string line;
  while (std::getline(std::cin, line)) {
    std::lock_guard<std::mutex> lock(g_mu);
    g_cmd = line;
  }
}

int main() {
  ensure_dir();
  std::thread th(reader);
  th.detach();
  std::cout << "draw_cpp ready. stdin: wave | bars | spiral | freq=2 | amp=70" << std::endl;
  double t = 0;
  int n = 0;
  while (true) {
    std::string got;
    {
      std::lock_guard<std::mutex> lock(g_mu);
      got.swap(g_cmd);
    }
    if (!got.empty()) {
      std::string low = got;
      for (size_t i = 0; i < low.size(); ++i) if (low[i] >= 'A' && low[i] <= 'Z') low[i] = char(low[i] + 32);
      if (low == "wave" || low == "bars" || low == "spiral") {
        std::lock_guard<std::mutex> lock(g_mu);
        g_mode = low;
      } else {
        std::string key;
        double val = 0;
        std::istringstream ss(got);
        if (std::getline(ss, key, '=') && (ss >> val)) {
          for (size_t i = 0; i < key.size(); ++i) if (key[i] >= 'A' && key[i] <= 'Z') key[i] = char(key[i] + 32);
          std::lock_guard<std::mutex> lock(g_mu);
          if (key.find("freq") != std::string::npos) {
            if (val < 0.2) val = 0.2;
            if (val > 12) val = 12;
            g_freq = val;
          } else if (key.find("amp") != std::string::npos) {
            if (val < 8) val = 8;
            if (val > 120) val = 120;
            g_amp = val;
          }
        }
      }
      std::cout << "got: " << got << std::endl;
      draw(t, "stdin");
    } else if (n == 0 || n % 4 == 0) {
      draw(t, "tick");
    }
    t += 0.25;
    ++n;
    std::this_thread::sleep_for(std::chrono::milliseconds(250));
  }
}
