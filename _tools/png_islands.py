"""Bounding boxes of the opaque regions of a PNG (flood fill on alpha).

The provided product photo is a marketing cut-out: the unit itself plus a few
detached callout shapes.  Rather than guessing where the body is, this labels
every connected opaque island and prints its box and area, so the schematic can
aim its connectors at the real edges.
"""
import sys

from png_thumb import load


def main(path):
    w, h, bpp, rows = load(path)

    def opaque(x, y):
        return (rows[y][x * bpp + 3] if bpp == 4 else 255) > 128

    seen = [[False] * w for _ in range(h)]
    comps = []
    for y0 in range(h):
        for x0 in range(w):
            if seen[y0][x0] or not opaque(x0, y0):
                continue
            stack = [(x0, y0)]
            seen[y0][x0] = True
            n = 0
            minx = maxx = x0
            miny = maxy = y0
            while stack:
                x, y = stack.pop()
                n += 1
                if x < minx:
                    minx = x
                if x > maxx:
                    maxx = x
                if y < miny:
                    miny = y
                if y > maxy:
                    maxy = y
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and not seen[ny][nx] \
                            and opaque(nx, ny):
                        seen[ny][nx] = True
                        stack.append((nx, ny))
            comps.append((n, minx, miny, maxx, maxy))

    comps.sort(reverse=True)
    print("%dx%d  %d opaque islands" % (w, h, len(comps)))
    for n, minx, miny, maxx, maxy in comps:
        if n < 120:
            continue
        print("  area %6d  x %3d..%3d  y %3d..%3d  (w %3d h %3d)  centre %d,%d"
              % (n, minx, maxx, miny, maxy, maxx - minx + 1, maxy - miny + 1,
                 (minx + maxx) // 2, (miny + maxy) // 2))


if __name__ == "__main__":
    main(sys.argv[1])
