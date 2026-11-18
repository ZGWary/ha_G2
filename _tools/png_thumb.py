"""Write a small nearest-neighbour thumbnail of a PNG (no Pillow available).

Used to eyeball artwork cheaply: a full-size product photo costs far more to
look at than a 100 px wide version, and the silhouette is all that is needed
to place the connectors.  Writes RGBA, filter type 0.
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


def write(path, w, h, pix):
    def chunk(typ, body):
        return (struct.pack(">I", len(body)) + typ + body
                + struct.pack(">I", zlib.crc32(typ + body) & 0xFFFFFFFF))

    out = b"\x89PNG\r\n\x1a\n"
    out += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
    raw = b"".join(b"\x00" + bytes(pix[y * w * 4:(y + 1) * w * 4]) for y in range(h))
    out += chunk(b"IDAT", zlib.compress(raw, 9))
    out += chunk(b"IEND", b"")
    open(path, "wb").write(out)


def main(src, dst, target_w=110):
    w, h, bpp, rows = load(src)
    scale = max(1, w // target_w)
    nw, nh = w // scale, h // scale
    pix = bytearray(nw * nh * 4)
    for y in range(nh):
        src_row = rows[y * scale]
        for x in range(nw):
            s = x * scale * bpp
            a = src_row[s + 3] if bpp == 4 else 255
            o = (y * nw + x) * 4
            # Flatten onto white so the shape is visible without alpha aware viewers.
            if bpp == 4:
                r, g, b = src_row[s], src_row[s + 1], src_row[s + 2]
            else:
                r = g = b = src_row[s]
            f = a / 255.0
            pix[o] = int(r * f + 255 * (1 - f))
            pix[o + 1] = int(g * f + 255 * (1 - f))
            pix[o + 2] = int(b * f + 255 * (1 - f))
            pix[o + 3] = 255
    write(dst, nw, nh, pix)
    print("wrote %s  %dx%d (scale 1/%d)" % (dst, nw, nh, scale))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2],
         int(sys.argv[3]) if len(sys.argv) > 3 else 110)
