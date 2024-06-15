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


def putpixel(surf, x, y, v):
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
        box_size=2,
        border=4,
    )
    qr.add_data(qr_data)
    qr.make(fit=True)

    qrimg = qr.make_image(fill_color="black", back_color="white").get_image()
    return qrimg


def render_text(text, mac, mac_qr):
    recsurf = cairo.RecordingSurface(cairo.Content.COLOR_ALPHA, None)

    ctx = cairo.Context(recsurf)
    ctx.translate(0, 29)
    x_offset = 0

    if mac is not None:
        layout = PangoCairo.create_layout(ctx)
        font = Pango.FontDescription("Terminus 8")
        layout.set_font_description(font)
        layout.set_text(mac)
        ctx.set_source_rgb(0, 0, 0)
        ctx.move_to(max(x_offset - 10, 0), 60)
        PangoCairo.show_layout(ctx, layout)
    if mac_qr is not None:
        x_offset += 60

    opts = cairo.FontOptions()
    opts.set_antialias(cairo.ANTIALIAS_NONE)
    layout = PangoCairo.create_layout(ctx)
    PangoCairo.context_set_font_options(layout.get_context(), opts)
    font = Pango.FontDescription("Cantarell Bold 58")
    layout.set_font_description(font)
    layout.set_text(text)
    ctx.set_source_rgb(0, 0, 0)
    ctx.move_to(x_offset, -20)
    PangoCairo.show_layout(ctx, layout)

    x0, y0, width, height = recsurf.ink_extents()
    imgsurf = cairo.ImageSurface(
        cairo.Format.RGB24, int(x0 + width), max(int(y0 + height), 128)
    )
    ctx = cairo.Context(imgsurf)
    ctx.set_source_rgb(1, 1, 1)
    ctx.paint()
    ctx.set_source_surface(recsurf)
    ctx.paint()

    if mac_qr is not None:
        imgsurf.flush()
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=2,
            border=4,
        )
        qr.add_data(mac_qr)
        qr.make(fit=True)

        qrimg = qr.make_image(fill_color="black", back_color="white").get_image()
        for x in range(qrimg.width):
            for y in range(qrimg.height):
                putpixel(imgsurf, x_offset + x, 30 + y, qrimg.getpixel((x, y)))
        imgsurf.mark_dirty()

    return imgsurf


def render_small_label(text):
    recsurf = cairo.RecordingSurface(cairo.Content.COLOR_ALPHA, None)

    ctx = cairo.Context(recsurf)
    ctx.translate(0, 0)
    opts = cairo.FontOptions()
    opts.set_antialias(cairo.ANTIALIAS_NONE)
    layout = PangoCairo.create_layout(ctx)
    PangoCairo.context_set_font_options(layout.get_context(), opts)
    font = Pango.FontDescription("Cantarell Bold 28")
    layout.set_font_description(font)
    layout.set_text(text)
    ctx.set_source_rgb(0, 0, 0)
    ctx.move_to(0, 0)
    PangoCairo.show_layout(ctx, layout)

    x0, y0, width, height = recsurf.ink_extents()
    imgsurf = cairo.ImageSurface(
        cairo.Format.RGB24, int(x0 + width), max(int(y0 + height), 64)
    )
    ctx = cairo.Context(imgsurf)
    ctx.set_source_rgb(1, 1, 1)
    ctx.paint()
    ctx.set_source_surface(recsurf)
    ctx.paint()

    return imgsurf


if __name__ == "__main__":
    imgsurf = render_text("asdf", "68:f7:28:77:e5:1d".replace(":", ""), True)
    # imgsurf = render_small_label("ross1-117-010-1")
    # imgsurf = render_text("asdf", None,  False)
    imgsurf.write_to_png("out.png")
