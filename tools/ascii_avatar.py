#!/usr/bin/env python3
"""Convert a portrait PNG to neofetch-style ASCII art (reproducible pipeline)."""
from __future__ import annotations

import argparse
import sys
from collections import deque
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("Install Pillow: pip install pillow", file=sys.stderr)
    raise

CHARS = "@%#*+=-:. "
COLS = 45
ROWS = 23
# char cell ~7.9px wide, 15px tall in SVG
CROP_ASPECT = (COLS * 7.9) / (ROWS * 15)


def lum(r: int, g: int, b: int) -> float:
    return 0.299 * r + 0.587 * g + 0.114 * b


def corner_mean_lum(img: Image.Image, frac: float = 0.12) -> float:
    w, h = img.size
    cw, ch = max(1, int(w * frac)), max(1, int(h * frac))
    corners = [
        img.crop((0, 0, cw, ch)),
        img.crop((w - cw, 0, w, ch)),
        img.crop((0, h - ch, cw, h)),
        img.crop((w - cw, h - ch, w, h)),
    ]
    total = 0.0
    n = 0
    for c in corners:
        for r, g, b in c.convert("RGB").getdata():
            total += lum(r, g, b)
            n += 1
    return total / max(n, 1)


def build_fg_mask(img: Image.Image, dark_background: bool) -> list[list[bool]]:
    w, h = img.size
    rgb = img.convert("RGB")
    fg: list[list[bool]] = [[False] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            r, g, b = rgb.getpixel((x, y))
            L = lum(r, g, b)
            blue = (b - r) > 12
            lit = L > 90
            sky = blue and lit
            bright = L > 235
            if dark_background:
                # Dark hoodie background: drop very dark pixels, keep white fur (no bright punch-out)
                bg = sky or L < 42
            else:
                bg = sky or bright
            fg[y][x] = not bg
    return fg


def largest_component(fg: list[list[bool]]) -> list[list[bool]]:
    h, w = len(fg), len(fg[0])
    seen = [[False] * w for _ in range(h)]
    best: list[tuple[int, int]] = []

    for sy in range(h):
        for sx in range(w):
            if not fg[sy][sx] or seen[sy][sx]:
                continue
            q: deque[tuple[int, int]] = deque([(sx, sy)])
            seen[sy][sx] = True
            comp: list[tuple[int, int]] = []
            while q:
                x, y = q.popleft()
                comp.append((x, y))
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and fg[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = True
                        q.append((nx, ny))
            if len(comp) > len(best):
                best = comp

    out = [[False] * w for _ in range(h)]
    for x, y in best:
        out[y][x] = True
    return out


def bbox(fg: list[list[bool]]) -> tuple[int, int, int, int]:
    h, w = len(fg), len(fg[0])
    min_x, min_y, max_x, max_y = w, h, -1, -1
    for y in range(h):
        for x in range(w):
            if fg[y][x]:
                min_x = min(min_x, x)
                max_x = max(max_x, x)
                min_y = min(min_y, y)
                max_y = max(max_y, y)
    if max_x < 0:
        return 0, 0, w - 1, h - 1
    return min_x, min_y, max_x, max_y


def crop_to_aspect(img: Image.Image, fg: list[list[bool]], aspect: float) -> Image.Image:
    min_x, min_y, max_x, max_y = bbox(fg)
    bw, bh = max_x - min_x + 1, max_y - min_y + 1
    cx, cy = (min_x + max_x) / 2, (min_y + max_y) / 2
    # expand box to target aspect while staying in image
    w, h = img.size
    if bw / max(bh, 1) > aspect:
        nh = bw / aspect
        nw = bw
    else:
        nw = bh * aspect
        nh = bh
    x0 = int(max(0, min(cx - nw / 2, w - nw)))
    y0 = int(max(0, min(cy - nh / 2, h - nh)))
    x1 = int(min(w, x0 + nw))
    y1 = int(min(h, y0 + nh))
    return img.crop((x0, y0, x1, y1))


def to_ascii(img: Image.Image, cols: int, rows: int) -> list[str]:
    small = img.resize((cols, rows), Image.Resampling.LANCZOS)
    gray = small.convert("L")
    lines: list[str] = []
    for y in range(rows):
        row = []
        for x in range(cols):
            g = gray.getpixel((x, y))
            v = (g / 255) ** 0.45
            idx = int(v * (len(CHARS) - 1) + 0.5)
            row.append(CHARS[idx])
        lines.append("".join(row).rstrip())
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return [ln.rstrip() for ln in lines]


def generate(path: Path, cols: int = COLS, rows: int = ROWS) -> str:
    img = Image.open(path).convert("RGB")
    dark_bg = corner_mean_lum(img) < 60
    fg = build_fg_mask(img, dark_bg)
    fg = largest_component(fg)
    cropped = crop_to_aspect(img, fg, CROP_ASPECT)
    # re-mask on crop
    fg2 = build_fg_mask(cropped, dark_bg)
    fg2 = largest_component(fg2)
    min_x, min_y, max_x, max_y = bbox(fg2)
    subject = cropped.crop((min_x, min_y, max_x + 1, max_y + 1))
    lines = to_ascii(subject, cols, rows)
    # pad lines to `rows` height centered in char grid if needed
    while len(lines) < rows:
        lines.append("")
    if len(lines) > rows:
        lines = lines[:rows]
    art = "\n".join(lines)
    assert max(len(l) for l in art.split("\n")) <= 46
    return art


def main() -> None:
    p = argparse.ArgumentParser(description="Portrait → ASCII for GitHub profile SVG")
    p.add_argument("image", type=Path, help="Source PNG/JPEG")
    p.add_argument("--cols", type=int, default=COLS)
    p.add_argument("--rows", type=int, default=ROWS)
    p.add_argument("-o", "--output", type=Path, help="Write ART snippet to file")
    args = p.parse_args()
    art = generate(args.image, args.cols, args.rows)
    snippet = 'ART = r"""' + art + '"""\n'
    if args.output:
        args.output.write_text(snippet, encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(snippet)


if __name__ == "__main__":
    main()
