import printer
import cairo
import gi

gi.require_version("PangoCairo", "1.0")
gi.require_version("Pango", "1.0")
from gi.repository import Pango
from gi.repository import PangoCairo
import qrcode
import os


def get_filename(fn):
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), fn)


def putpixel(surf: cairo.ImageSurface, x, y, v):
    offset = surf.get_stride() * y + x * 4
    v = 255 if v else 0
    d = surf.get_data()
    for i in range(4):
        d[offset + i] = v


def create_wifi_qr(ssid, password):
    qr_data = f"WIFI:S:{ssid};T:WPA;P:{password};;"

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=3,
        border=4,
    )
    qr.add_data(qr_data)
    qr.make(fit=True)

    qrimg = qr.make_image(fill_color="black", back_color="white").get_image()
    return qrimg


def render_wifi_label(ssid, password):
    recsurf = cairo.RecordingSurface(cairo.Content.COLOR_ALPHA, None)
    ctx = cairo.Context(recsurf)
    imgsurf = cairo.ImageSurface(printer.REQUIRED_FORMAT, 620, printer.REQUIRED_HEIGHT)
    ctx = cairo.Context(imgsurf)
    ctx.set_source_rgb(1, 1, 1)
    ctx.paint()
    ctx.set_source_surface(recsurf)
    ctx.paint()

    qrimg = create_wifi_qr(ssid, password)
    imgsurf.flush()
    for x in range(qrimg.width):
        for y in range(qrimg.height):
            putpixel(imgsurf, x, y + 7, qrimg.getpixel((x, y)))
    imgsurf.mark_dirty()

    opts = cairo.FontOptions()
    opts.set_antialias(cairo.ANTIALIAS_NONE)
    layout = PangoCairo.create_layout(ctx)
    PangoCairo.context_set_font_options(layout.get_context(), opts)
    font = Pango.FontDescription("Liberation Mono Bold 28")
    layout.set_font_description(font)
    layout.set_text(f"Name: {ssid}\nPW:   {password}")
    ctx.set_source_rgb(0, 0, 0)
    ctx.move_to(110, 18)
    PangoCairo.show_layout(ctx, layout)

    return imgsurf


def render_login_label(ip, password, bootloader_pw):
    font_size = 27
    recsurf = cairo.RecordingSurface(cairo.Content.COLOR_ALPHA, None)
    ctx = cairo.Context(recsurf)
    width = 180 + int(font_size * max(len(ip), len(bootloader_pw)))
    imgsurf = cairo.ImageSurface(
        printer.REQUIRED_FORMAT,
        width,
        printer.REQUIRED_HEIGHT,
    )
    ctx = cairo.Context(imgsurf)
    ctx.set_source_rgb(1, 1, 1)
    ctx.paint()
    ctx.set_source_surface(recsurf)
    ctx.paint()

    opts = cairo.FontOptions()
    opts.set_antialias(cairo.ANTIALIAS_NONE)
    layout = PangoCairo.create_layout(ctx)
    PangoCairo.context_set_font_options(layout.get_context(), opts)
    font = Pango.FontDescription(f"Liberation Mono Bold {font_size}")
    layout.set_font_description(font)
    layout.set_text(f"  AP IP: {ip}\nroot PW: {password}\n  BL PW: {bootloader_pw}")
    ctx.set_source_rgb(0, 0, 0)
    ctx.move_to(10, 4)
    PangoCairo.show_layout(ctx, layout)

    return imgsurf


if __name__ == "__main__":
    imgsurf = render_wifi_label("stuttgart-EX", "Faem3heiweetae6e")
    imgsurf.write_to_png("out.png")
    imgsurf = render_login_label("192.168.0.1", "eeG1phoo", "dasuboot")
    imgsurf.write_to_png("out2.png")
