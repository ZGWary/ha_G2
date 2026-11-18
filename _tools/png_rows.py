"""Print alpha extents per row / column for a PNG region.

Same hand-rolled decoder as png_alpha_map.py; used to find exactly where the
side connectors of the product photo sit so the schematic can plug into them.
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
    rows = []
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
        rows.append(line)
        prev = line
    return w, h, bpp, rows


def main(path):
    w, h, bpp, rows = load(path)
    print("size %dx%d" % (w, h))

    def alpha(x, y):
        return rows[y][x * bpp + 3]

    print("\n-- opaque extent per row (thr 128) --")
    for y in range(h):
        xs = [x for x in range(w) if alpha(x, y) > 128]
        if xs:
            print("%4d  x %3d..%3d  (w %3d)" % (y, xs[0], xs[-1], xs[-1] - xs[0] + 1))
        else:
            print("%4d  -" % y)

    print("\n-- opaque extent per column (thr 128) --")
    for x in range(w):
        ys = [y for y in range(h) if alpha(x, y) > 128]
        if ys:
            print("%4d  y %3d..%3d" % (x, ys[0], ys[-1]))


if __name__ == "__main__":
    main(sys.argv[1])
