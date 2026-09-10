"""Small synthetic EMFs; no user graphics or proprietary Origin data."""
import struct


def pen_emf(width=46, style=0, extended=False):
    header = bytearray(108)
    struct.pack_into('<II', header, 0, 1, 108)
    struct.pack_into('<4i', header, 8, 0, 0, 999, 999)
    struct.pack_into('<4i', header, 24, 0, 0, 26458, 26458)
    struct.pack_into('<II', header, 40, 0x464D4520, 0x10000)
    struct.pack_into('<H', header, 56, 2)
    struct.pack_into('<2i', header, 72, 1000, 1000)
    struct.pack_into('<2i', header, 80, 265, 265)
    struct.pack_into('<2i', header, 100, 265000, 265000)
    if extended:
        pen = struct.pack('<13I', 95, 52, 1, 0, 0, 0, 0,
                          style, width, 0, 0xFF, 0, 0)
    else:
        pen = struct.pack('<IIIIiiI', 38, 28, 1, style, width, 0, 0xFF)
    records = [bytes(header), pen,
               struct.pack('<III', 37, 12, 1),
               struct.pack('<IIii', 27, 16, 100, 100),
               struct.pack('<IIii', 54, 16, 900, 100),
               struct.pack('<III', 40, 12, 1),
               struct.pack('<IIIII', 14, 20, 0, 0, 20)]
    struct.pack_into('<II', header, 48, sum(map(len, records)), len(records))
    records[0] = bytes(header)
    return b''.join(records)
