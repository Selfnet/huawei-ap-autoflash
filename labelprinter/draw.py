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
    imgsurf = cairo.ImageSurface(cairo.Format.RGB24, 580, 128)
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

    layout = PangoCairo.create_layout(ctx)
    font = Pango.FontDescription("Terminus 30")
    layout.set_font_description(font)
    layout.set_text(f"SSID: {ssid}\nPW:   {password}")
    ctx.set_source_rgb(0, 0, 0)
    ctx.move_to(120, 20)
    PangoCairo.show_layout(ctx, layout)

    return imgsurf


if __name__ == "__main__":
    imgsurf = render_wifi_label("stuttgart-EX", "Faem3heiweetae6e")
    imgsurf.write_to_png("out.png")
