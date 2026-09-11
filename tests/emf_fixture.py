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


def text_emf(text="FE", escapement=900, align=0x18, x=100, y=200, height=-300):
    header = bytearray(108)
    struct.pack_into('<II', header, 0, 1, 108)
    struct.pack_into('<4i', header, 8, 0, 0, 999, 999)
    struct.pack_into('<4i', header, 24, 0, 0, 26458, 26458)
    struct.pack_into('<II', header, 40, 0x464D4520, 0x10000)
    struct.pack_into('<H', header, 56, 2)
    struct.pack_into('<2i', header, 72, 1000, 1000)
    struct.pack_into('<2i', header, 80, 265, 265)
    struct.pack_into('<2i', header, 100, 265000, 265000)

    font_rec = bytearray(368)
    struct.pack_into('<III', font_rec, 0, 82, 368, 1)
    struct.pack_into('<5i', font_rec, 12, height, 0, escapement, escapement, 400)
    face_utf16 = "Arial".encode("utf-16le")
    font_rec[40:40 + len(face_utf16)] = face_utf16

    sel_rec = struct.pack('<III', 37, 12, 1)
    align_rec = struct.pack('<III', 22, 12, align)

    text_utf16 = text.encode("utf-16le")
    n_chars = len(text)
    str_len = len(text_utf16)
    pad_len = (4 - (str_len % 4)) % 4
    rec_size = 76 + str_len + pad_len
    text_rec = bytearray(rec_size)
    struct.pack_into('<II', text_rec, 0, 84, rec_size)
    struct.pack_into('<4i', text_rec, 8, 0, 0, 100, 100)
    struct.pack_into('<I', text_rec, 24, 1)
    struct.pack_into('<2f', text_rec, 28, 1.0, 1.0)
    struct.pack_into('<iiII', text_rec, 36, x, y, n_chars, 76)
    struct.pack_into('<I4iI', text_rec, 52, 0, 0, 0, -1, -1, 0)
    text_rec[76:76 + str_len] = text_utf16

    eof_rec = struct.pack('<IIIII', 14, 20, 0, 0, 20)

    records = [bytes(header), bytes(font_rec), sel_rec, align_rec, bytes(text_rec), eof_rec]
    struct.pack_into('<II', header, 48, sum(map(len, records)), len(records))
    records[0] = bytes(header)
    return b''.join(records)


def bitblt_emf(dwRop=0x005A0049, cbBitsSrc=0):
    """Synthetic EMF with an EMR_BITBLT record with specified ROP and no bitmap bits."""
    header = bytearray(108)
    struct.pack_into('<II', header, 0, 1, 108)
    struct.pack_into('<4i', header, 8, 0, 0, 999, 999)
    struct.pack_into('<4i', header, 24, 0, 0, 26458, 26458)
    struct.pack_into('<II', header, 40, 0x464D4520, 0x10000)
    struct.pack_into('<H', header, 56, 2)
    struct.pack_into('<2i', header, 72, 1000, 1000)
    struct.pack_into('<2i', header, 80, 265, 265)
    struct.pack_into('<2i', header, 100, 265000, 265000)

    # Brush: solid red brush
    brush = struct.pack('<IIIIII', 39, 24, 1, 0, 0x000000FF, 0)
    sel_brush = struct.pack('<III', 37, 12, 1)

    # BITBLT: record 76, nSize=100
    bitblt = bytearray(100)
    struct.pack_into('<II', bitblt, 0, 76, 100)
    struct.pack_into('<4i', bitblt, 8, 0, 0, 100, 100)
    struct.pack_into('<2i', bitblt, 24, 10, 10)
    struct.pack_into('<2i', bitblt, 32, 100, 100)
    struct.pack_into('<I', bitblt, 40, dwRop)
    struct.pack_into('<2i', bitblt, 44, 0, 0)

    eof = struct.pack('<IIIII', 14, 20, 0, 0, 20)
    records = [bytes(header), brush, sel_brush, bytes(bitblt), eof]
    struct.pack_into('<II', header, 48, sum(map(len, records)), len(records))
    records[0] = bytes(header)
    return b''.join(records)


def monopattern_emf(r=0x93, g=0xBC, b=0x93):
    """Synthetic EMF with a 1-bpp monochrome pattern brush filling a polygon."""
    header = bytearray(108)
    struct.pack_into('<II', header, 0, 1, 108)
    struct.pack_into('<4i', header, 8, 0, 0, 999, 999)
    struct.pack_into('<4i', header, 24, 0, 0, 26458, 26458)
    struct.pack_into('<II', header, 40, 0x464D4520, 0x10000)
    struct.pack_into('<H', header, 56, 2)
    struct.pack_into('<2i', header, 72, 1000, 1000)
    struct.pack_into('<2i', header, 80, 265, 265)
    struct.pack_into('<2i', header, 100, 265000, 265000)

    # 1. Solid brush with color (r, g, b) -> ih=1
    color_val = r | (g << 8) | (b << 16)
    brush1 = struct.pack('<IIIIII', 39, 24, 1, 0, color_val, 0)
    sel1 = struct.pack('<III', 37, 12, 1)

    # 2. Record 94: EMR_CREATEDIBPATTERNBRUSHPT -> ih=2
    rec94 = bytearray(116)
    struct.pack_into('<IIII', rec94, 0, 94, 116, 2, 0)
    struct.pack_into('<IIII', rec94, 16, 36, 48, 84, 32)
    struct.pack_into('<IIIHHIIIIII', rec94, 36, 40, 8, 8, 1, 1, 0, 32, 0, 0, 0, 0)
    rec94[76:84] = bytes([0, 0, 0, 0, 0xFF, 0xFF, 0xFF, 0])
    rec94[84:116] = bytes([0x55, 0, 0, 0, 0xAA, 0, 0, 0] * 4)

    sel2 = struct.pack('<III', 37, 12, 2)

    # 3. Polygon16 (rtype 86): bounds, count=4, apts=4
    poly = bytearray(44)
    struct.pack_into('<II', poly, 0, 86, 44)
    struct.pack_into('<4i', poly, 8, 10, 10, 100, 100)
    struct.pack_into('<I', poly, 24, 4)
    struct.pack_into('<8h', poly, 28, 10, 10, 100, 10, 100, 100, 10, 100)

    eof = struct.pack('<IIIII', 14, 20, 0, 0, 20)
    records = [bytes(header), brush1, sel1, bytes(rec94), sel2, bytes(poly), eof]
    struct.pack_into('<II', header, 48, sum(map(len, records)), len(records))
    records[0] = bytes(header)
    return b''.join(records)

