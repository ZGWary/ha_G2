r"""Print an ASCII rendering of a PNG so the artwork can be judged as text.

    python _tools\png_ascii2.py _tools\_pf_grid_on.png 40

`#` dark, `*` mid, `+` light, `-` very light, `.` transparent, ` ` white.
Handles 1/2/4/8-bit palette + 8-bit grey/RGB(A), non-interlaced (the
PF_ICONS in hoymiles-g2-power-flow.js are 4-bit palette PNGs).
"""
import os
import struct
import sys
import zlib


def chunks(path):
    data = open(path, "rb").read()
    pos = 8
    while pos < len(data):
        (ln,) = struct.unpack(">I", data[pos:pos + 4])
        typ = data[pos + 4:pos + 8]
        yield typ, data[pos + 8:pos + 8 + ln]
        pos += 12 + ln


def load(path):
    """Return (width, height, rows) where rows[y][x] = (a, r, g, b)."""
    idat = b""
    pal = b""
    trns = b""
    w = h = depth = ct = interlace = 0
    for typ, body in chunks(path):
        if typ == b"IHDR":
            w, h, depth, ct, _cm, _fm, interlace = struct.unpack(">IIBBBBB", body)
        elif typ == b"PLTE":
            pal = body
        elif typ == b"tRNS":
            trns = body
        elif typ == b"IDAT":
            idat += body
    assert interlace == 0, interlace

    chan = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ct]
    bits = chan * depth
    stride = (w * bits + 7) // 8
    raw = zlib.decompress(idat)

    rows = []
    prev = bytearray(stride)
    i = 0
    for _ in range(h):
        f = raw[i]
        i += 1
        line = bytearray(raw[i:i + stride])
        i += stride
        bpp = max(1, bits // 8)
        if f == 1:
            for x in range(bpp, stride):
                line[x] = (line[x] + line[x - bpp]) & 255
        elif f == 2:
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 255
        elif f == 3:
            for x in range(stride):
                a = line[x - bpp] if x >= bpp else 0
                line[x] = (line[x] + ((a + prev[x]) >> 1)) & 255
        elif f == 4:
            for x in range(stride):
                a = line[x - bpp] if x >= bpp else 0
                b = prev[x]
                c = prev[x - bpp] if x >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pr) & 255
        prev = line

        if depth < 8:
            per = 8 // depth
            mask = (1 << depth) - 1
            samples = []
            for byte in line:
                for k in range(per):
                    samples.append((byte >> (8 - depth * (k + 1))) & mask)
            samples = samples[:w * chan]
        else:
            samples = list(line)

        out = []
        for x in range(w):
            if ct == 3:
                idx = samples[x]
                r, g, b = pal[idx * 3:idx * 3 + 3] if pal else (0, 0, 0)
                a = trns[idx] if idx < len(trns) else 255
            else:
                s = x * chan
                if ct == 0:
                    a, r, g, b = 255, samples[s], samples[s], samples[s]
                elif ct == 4:
                    a, r, g, b = samples[s + 1], samples[s], samples[s], samples[s]
                elif ct == 2:
                    a, r, g, b = 255, samples[s], samples[s + 1], samples[s + 2]
                else:
                    a, r, g, b = samples[s + 3], samples[s], samples[s + 1], samples[s + 2]
            out.append((a, r, g, b))
        rows.append(out)
    return w, h, rows


def main(src, width=48):
    w, h, rows = load(src)
    scale = max(1, int(round(w / float(width))))
    nw, nh = w // scale, max(1, h // scale)
    print("%s  %dx%d -> %dx%d" % (os.path.basename(src), w, h, nw, nh))
    for y in range(nh):
        row = rows[min(h - 1, y * scale)]
        out = []
        for x in range(nw):
            a, r, g, b = row[min(w - 1, x * scale)]
            if a < 40:
                out.append(".")
                continue
            lum = (r * 299 + g * 587 + b * 114) // 1000
            if lum > 235:
                out.append(" ")
            elif lum > 190:
                out.append("-")
            elif lum > 140:
                out.append("+")
            elif lum > 90:
                out.append("*")
            else:
                out.append("#")
        print("".join(out).rstrip())


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 48)
