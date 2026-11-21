"""Put an app screenshot in a Mac window with rounded corners, traffic lights and a soft shadow, for the site.
python frame.py <in.png> <out.webp or .png>   (1800 x 1161, as the site's tiles expect)"""
import sys
from PIL import Image, ImageDraw, ImageFilter

src, out = sys.argv[1:3]
W, H, M = 1800, 1161, 34
app = Image.open(src).convert("RGB")
w = W - 2 * M
h = round(app.height * w / app.width)
app = app.resize((w, h), Image.LANCZOS)
top = (H - h) // 2
canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
ImageDraw.Draw(shadow).rounded_rectangle((M, top + 10, M + w, top + h + 10), 22, fill=(40, 30, 20, 70))
canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)))
mask = Image.new("L", (w, h), 0)
ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), 20, fill=255)
win = app.convert("RGBA")
d = ImageDraw.Draw(win)
for i, c in enumerate(((255, 95, 87), (254, 188, 46), (40, 200, 64))):     # traffic lights
    x, y, r = 36 + i * 30, 36, 9
    d.ellipse((x - r, y - r, x + r, y + r), fill=c)
win.putalpha(mask)
canvas.alpha_composite(win, (M, top))
ImageDraw.Draw(canvas).rounded_rectangle((M, top, M + w - 1, top + h - 1), 20, outline=(0, 0, 0, 30), width=1)
if out.endswith(".webp"):
    canvas.save(out, "WEBP", quality=88, method=6)
else:
    canvas.save(out, optimize=True)
