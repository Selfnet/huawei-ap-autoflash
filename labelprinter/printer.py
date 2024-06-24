#!/usr/bin/env python
from PIL import Image
import socket
import os
import cairo


REQUIRED_HEIGHT = 128
REQUIRED_FORMAT = cairo.Format.RGB24


def get_filename(fn):
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), fn)


with open(get_filename("header.prn"), "rb") as f:
    header = list(f.read())


def format_image(img):
    img = Image.open(img)
    assert img.width == REQUIRED_HEIGHT
    out = list(header)
    for i in range(4):
        out[0x83 + i] = (img.height >> (i * 8)) & 0xFF

    for y in range(img.height):
        packet = [0x47, 16, 0]
        packet.extend((0,) * 16)

        for x in range(img.width):
            if img.getpixel((img.width - 1 - x, y)) == 0:
                packet[int(x / 8) + 3] |= 1 << (7 - (x & 7))
        out.extend(packet)

    out.append(0x1A)
    return bytes(out)


def getpixel(surf: cairo.ImageSurface, x, y):
    offset = surf.get_stride() * y + x * 4
    return surf.get_data()[offset] != 0


def format_surface(surf: cairo.ImageSurface):
    assert surf.get_format() == REQUIRED_FORMAT
    assert surf.get_height() == REQUIRED_HEIGHT
    out = list(header)

    width_mm = 24
    out[0x81] = width_mm & 0xFF

    for i in range(4):
        out[0x83 + i] = (surf.get_width() >> (i * 8)) & 0xFF

    for y in range(surf.get_width()):
        packet = [0x47, 16, 0]
        packet.extend((0,) * 16)

        for x in range(surf.get_height()):
            if getpixel(surf, y, x) == 0:
                packet[int(x / 8) + 3] |= 1 << (7 - (x & 7))
        out.extend(packet)

    out.append(0x1A)
    return bytes(out)


def print_to_ip(surf: cairo.ImageSurface, ip: str, port=9100):
    out = format_surface(surf)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((ip, port))
    s.send(out)
    s.close()
