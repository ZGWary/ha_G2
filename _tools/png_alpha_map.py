"""Print an ASCII coverage map of a PNG so a cut-out can be measured.

Written because the box only has PowerShell and this is far easier to read in
a terminal than a decoded byte dump.  Not imported by the integration.
"""
import struct
import sys
import zlib


def load(path):
    data = open(path, "rb").read()
    pos = 8
    idat = b""
    w = h = ct = 0
    while pos < len(data):
        ln = struct.unpack(">I", data[pos:pos + 4])[0]
        typ = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            w, h, _bd, ct, _cm, _fm, _il = struct.unpack(">IIBBBBB", chunk)
        elif typ == b"IDAT":
            idat += chunk
        pos += 12 + ln

    raw = zlib.decompress(idat)
    bpp = 4 if ct == 6 else 3
    stride = w * bpp
    out = bytearray()
    prev = bytearray(stride)
    i = 0
    for _ in range(h):
        f = raw[i]
        i += 1
        line = bytearray(raw[i:i + stride])
        i += stride
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
        out += line
        prev = line
    return w, h, bpp, stride, out


def main(path):
    w, h, bpp, stride, pix = load(path)
    print("size %dx%d bpp %d" % (w, h, bpp))

    alpha = (bpp == 4)
    for thr in (8, 64, 200):
        minx, miny, maxx, maxy = w, h, -1, -1
        for y in range(h):
            base = y * stride
            for x in range(w):
                a = pix[base + x * bpp + 3] if alpha else 255
                if a > thr:
                    if x < minx:
                        minx = x
                    if x > maxx:
                        maxx = x
                    if y < miny:
                        miny = y
                    if y > maxy:
                        maxy = y
        if maxx < 0:
            print("thr %3d : empty" % thr)
        else:
            print("thr %3d : bbox x %d..%d y %d..%d  (w %d h %d)"
                  % (thr, minx, maxx, miny, maxy, maxx - minx + 1, maxy - miny + 1))

    print()
    step = max(1, w // 72)
    for y in range(0, h, max(1, h // 42)):
        base = y * stride
        row = ""
        for x in range(0, w, step):
            a = pix[base + x * bpp + 3] if alpha else 255
            row += "#" if a > 200 else ("+" if a > 32 else ".")
        print("%4d %s" % (y, row))


if __name__ == "__main__":
    main(sys.argv[1])
