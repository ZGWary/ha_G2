"""Crop and flatten a region of a PNG to a small preview.

Companion to png_thumb.py; ``crop`` keeps the token cost of inspecting the
product photo down while making its composition obvious.
"""
import sys

from png_thumb import load, write


def main(src, dst, x0, y0, x1, y1, scale=1):
    w, h, bpp, rows = load(src)
    x1 = min(x1, w)
    y1 = min(y1, h)
    cw = (x1 - x0) // scale
    ch = (y1 - y0) // scale
    pix = bytearray(cw * ch * 4)
    for y in range(ch):
        src_row = rows[y0 + y * scale]
        for x in range(cw):
            s = (x0 + x * scale) * bpp
            a = src_row[s + 3] if bpp == 4 else 255
            if bpp == 4:
                r, g, b = src_row[s], src_row[s + 1], src_row[s + 2]
            else:
                r = g = b = src_row[s]
            f = a / 255.0
            # Tint the transparent area so the cut-out edge is easy to see.
            bg = (255, 240, 200)
            o = (y * cw + x) * 4
            pix[o] = int(r * f + bg[0] * (1 - f))
            pix[o + 1] = int(g * f + bg[1] * (1 - f))
            pix[o + 2] = int(b * f + bg[2] * (1 - f))
            pix[o + 3] = 255
    write(dst, cw, ch, pix)
    print("wrote %s  %dx%d  from x %d..%d y %d..%d" % (dst, cw, ch, x0, x1, y0, y1))


if __name__ == "__main__":
    a = sys.argv
    main(a[1], a[2], int(a[3]), int(a[4]), int(a[5]), int(a[6]),
         int(a[7]) if len(a) > 7 else 1)
