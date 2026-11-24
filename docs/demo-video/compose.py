"""Cut one take into the marketing video.
python compose.py <en|zh> <take dir> <assets dir> <out.mp4> [--frames a,b,c] [--still t out.png]

Camera: keyframes (time, centre x, centre y, zoom) in the app's CSS pixels, eased in between.
Captions: one pill per beat, faded and lifted in. Cursor and click rings are drawn here (headless
Chromium draws none). The end card fades in over the app and holds."""
import json, math, os, subprocess, sys
from PIL import Image, ImageDraw, ImageFilter

lang, take, assets, out = sys.argv[1:5]
opts = sys.argv[5:]
W, H, FPS = 1920, 1200, 30
T = json.load(open(take + "/take.json"))
DPR, CW, CH = T["dpr"], T["w"], T["h"]
M = T["marks"]
frames = T["frames"]
BG = (251, 249, 246)


def ease(k):
    k = min(1, max(0, k))
    return k * k * (3 - 2 * k) if k < 1 else 1.0


def ease_out(k):
    k = min(1, max(0, k))
    return 1 - (1 - k) ** 3


# ------------------------------------------------------------------ the story, in source time
FULL = (640, 400, 1.0)
SEARCH = (452, 236, 1.72)
DRAFTV = (706, 250, 1.12)        # the list on the left, the draft or the sent mail on the right, its lines whole
TERMV = (600, 290, 1.3)
zh = lang == "zh"
t0 = M["start"] + 0.05                      # the cut starts here
cam = [  # (source time, view); between two keys the camera eases from one to the next
    (t0, FULL), (M["term"] - 0.05, FULL), (M["term"] + 0.6, TERMV),
    (M["reveal"] - 0.05, TERMV), (M["reveal"] + 0.7, FULL),
    (M["draftopen"] - 0.1, FULL), (M["draftopen"] + 0.7, DRAFTV),
    (M["term2"] - 0.05, DRAFTV), (M["term2"] + 0.6, TERMV),
    (M["reveal2"] - 0.05, TERMV), (M["reveal2"] + 0.7, FULL),
    (M["sentopen"] - 0.1, FULL), (M["sentopen"] + 0.7, DRAFTV),
    (M["inbox"] - 0.6, DRAFTV), (M["inbox"] + 0.1, FULL),
    (M["type1"] - 0.1, FULL), (M["type1"] + 0.5, SEARCH),
    (M["typed1"] + 0.4, SEARCH), (M["hit"] + 0.5, FULL),
]
t_end_src = M["hit"] + 1.7                  # the app part ends; the end card follows
caps = [  # (caption index, from, to, top or bottom) in source time
    (0, M["term"] + 0.2, M["termdone"] - 0.15, "b"),
    (1, M["termdone"] - 0.05, M["drafts"] + 0.2, "b"),
    (2, M["drafts"] + 0.35, M["term2"] - 0.1, "b"),
    (3, M["term2"] + 0.2, M["reveal2"] + 0.3, "b"),
    (4, M["reveal2"] + 0.45, M["inbox"] - 0.3, "b"),
    (5, M["type1"] - 0.05, M["hit"] + 1.5, "b"),
]
# speed: parts with nothing new on screen run a little faster (source seconds per output second).
# Two of them are fitted to the music (music.m4a, 120 BPM, bars of 2 s from 0.05 s): the drop at bar 6 comes
# as the agent says the draft is saved, and the big hit (bar 16, at 38 s once make.sh repeats bars 6-9) comes with the end card.
DROP, HIT = 10.05, 37.99
END_FADE, END_HOLD = 0.6, 3.1


def fitted():
    def plan(r_type, r_gap):
        return [(t0, r_type), (M["termdone"], 1.0), (M["reveal"] + 0.2, 1.25), (M["draftopen"] - 0.2, 1.0),
                (M["reveal2"] + 0.2, 1.25), (M["sentopen"] - 0.2, 1.0), (M["sentopen"] + 1.0, 1.3),
                (M["inbox"] - 0.3, r_gap), (M["type1"] - 0.3, 1.0)]
    r_type = min(1.25, max(0.8, (M["termdone"] - t0) / DROP))
    lo, hi = 1.0, 4.0           # the quiet walk back to the inbox takes up the rest
    for _ in range(40):
        mid = (lo + hi) / 2
        end = out_len(plan(r_type, mid))
        lo, hi = (mid, hi) if end + END_FADE > HIT else (lo, mid)
    return plan(r_type, (lo + hi) / 2)


def out_len(sp):
    marks = sp + [(t_end_src, 1.0)]
    return sum((b - a) / r for (a, r), (b, _) in zip(marks, marks[1:]) if b > a)


speed = fitted()


def src_time_map():
    """Output time -> source time, following the speed list."""
    pts = [(0.0, t0)]
    o, s = 0.0, t0
    marks = speed + [(t_end_src, 1.0)]
    for (a, rate), (b, _) in zip(marks, marks[1:]):
        if b <= a:
            continue
        o += (b - a) / rate
        pts.append((o, b))
    return pts


TMAP = src_time_map()
APP_LEN = TMAP[-1][0]
TOTAL = APP_LEN + END_FADE + END_HOLD


def to_src(o):
    for (o1, s1), (o2, s2) in zip(TMAP, TMAP[1:]):
        if o <= o2:
            return s1 + (s2 - s1) * (o - o1) / max(1e-9, o2 - o1)
    return TMAP[-1][1] + (o - TMAP[-1][0])


def view_at(t):
    if t <= cam[0][0]:
        return cam[0][1]
    for (a, va), (b, vb) in zip(cam, cam[1:]):
        if t <= b:
            k = ease((t - a) / max(1e-9, b - a))
            za, zb = math.log(va[2]), math.log(vb[2])
            return (va[0] + (vb[0] - va[0]) * k, va[1] + (vb[1] - va[1]) * k, math.exp(za + (zb - za) * k))
    return cam[-1][1]


def crop_box(v):
    cx, cy, z = v
    w, h = CW / z, CH / z
    x = min(max(cx - w / 2, 0), CW - w)
    y = min(max(cy - h / 2, 0), CH - h)
    return x, y, w, h


fr_t = [f[0] for f in frames]
_cache = {}


def frame_at(t):
    import bisect
    i = max(0, bisect.bisect_right(fr_t, t) - 1)
    name = frames[i][1]
    if name not in _cache:
        _cache.clear()
        _cache[name] = Image.open(f"{take}/frames/{name}").convert("RGB")
    return _cache[name]


mouse = T["mouse"]
mt = [m[0] for m in mouse]


def mouse_at(t):
    import bisect
    i = bisect.bisect_right(mt, t) - 1
    if i < 0:
        return mouse[0][1], mouse[0][2]
    if i + 1 < len(mouse) and mouse[i + 1][0] - mouse[i][0] < 0.1:
        a, b = mouse[i], mouse[i + 1]
        k = (t - a[0]) / max(1e-9, b[0] - a[0])
        return a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k
    return mouse[i][1], mouse[i][2]


CURSOR = Image.open(assets + "/cursor.png")
# the arrow's tip in cursor.png: the svg sits at (100,200) on the page, shot with 40 px of margin
_cb = CURSOR.getbbox()
TIP = (40 + 160 * 2 / 20 * 0 + 16, 40 + 16)   # svg viewBox starts at -2: the tip is 2/20*160 = 16 px in
CUR_H = 22  # the arrow's height in CSS pixels (as on a Mac at this size)
CAPS = [Image.open(f"{assets}/cap{i}.png") for i in range(len(caps))]
END = {k: Image.open(f"{assets}/{k}.png") for k in ("icon", "name", "tag", "sub")}


_bg = None


def end_bg():
    global _bg
    if _bg is None:
        _bg = make_bg()
    return _bg


def end_card(k):
    """The end card at k seconds after its pieces start to come in."""
    im = end_bg().copy()
    _end_parts(im, k)
    return im


def make_bg():
    im = Image.new("RGBA", (W, H), BG + (255,))
    # the hero's warm glow
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    g.ellipse((W * 0.18, -H * 0.15, W * 0.82, H * 0.75), fill=(181, 131, 90, 46))
    g.ellipse((W * 0.52, H * 0.35, W * 0.98, H * 0.95), fill=(47, 118, 113, 26))
    glow = glow.filter(ImageFilter.GaussianBlur(170))
    im.alpha_composite(glow)
    return im


def _end_parts(im, k):
    icon = END["icon"].resize((int(END["icon"].width * 0.86), int(END["icon"].height * 0.86)), Image.LANCZOS)
    parts = [(icon, 250, 0.0), (END["name"], 600, 0.12), (END["tag"], 760, 0.24), (END["sub"], 860, 0.36)]
    for img, y, delay in parts:
        a = ease_out((k - delay) / 0.7)
        if a <= 0:
            continue
        dy = int((1 - a) * 26)
        lay = img.copy()
        if a < 1:
            lay.putalpha(lay.getchannel("A").point(lambda v: int(v * a)))
        im.alpha_composite(lay, ((W - img.width) // 2, y + dy))


def ring(r, alpha):
    s = 4
    size = int(r * 2 + 8)
    big = Image.new("RGBA", (size * s, size * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    c = size * s / 2
    d.ellipse((c - r * s, c - r * s, c + r * s, c + r * s), fill=(47, 118, 113, int(60 * alpha)),
              outline=(47, 118, 113, int(200 * alpha)), width=int(2.2 * s))
    return big.resize((size, size), Image.LANCZOS)


def app_frame(o):
    t = to_src(o)
    v = view_at(t)
    x, y, w, h = crop_box(v)
    src = frame_at(t)
    im = src.resize((W, H), Image.LANCZOS, box=(x * DPR, y * DPR, (x + w) * DPR, (y + h) * DPR)).convert("RGBA")
    sc = W / w                                  # output px per CSS px
    # clicks: a soft ring
    for ct, cx, cy in T["clicks"]:
        if ct < M["start"]:          # the set-up click before the take
            continue
        k = (t - ct) / 0.45
        if 0 <= k <= 1:
            r = (8 + 16 * ease_out(k)) * sc / 1.5
            rg = ring(r, 1 - k)
            im.alpha_composite(rg, (int((cx - x) * sc - rg.width / 2), int((cy - y) * sc - rg.height / 2)))
    # cursor
    mx, my = mouse_at(t)
    ch = CUR_H * sc
    f = ch / 240
    cur = CURSOR.resize((max(1, int(CURSOR.width * f)), max(1, int(CURSOR.height * f))), Image.LANCZOS)
    px, py = (mx - x) * sc - TIP[0] * f, (my - y) * sc - TIP[1] * f
    if -200 < px < W and -200 < py < H:
        im.alpha_composite(cur, (int(px), int(py)))
    # caption
    for i, a, b, pos in caps:
        if a - 0.01 <= t <= b + 0.3:
            fin = ease_out((t - a) / 0.35)
            fout = 1 - ease((t - b) / 0.25) if t > b else 1
            al = max(0, min(fin, fout))
            if al <= 0:
                continue
            cap = CAPS[i]
            lay = cap if al >= 1 else cap.copy()
            if al < 1:
                lay.putalpha(cap.getchannel("A").point(lambda q: int(q * al)))
            dy = int((1 - fin) * 18)
            top = 64 - 40 + dy if pos == "t" else H - 64 - cap.height + 40 + dy
            im.alpha_composite(lay, ((W - cap.width) // 2, top))
    return im


def render(o):
    if o < APP_LEN:
        return app_frame(o).convert("RGB")
    k = o - APP_LEN
    if k < END_FADE:   # the app steps back and fades into the card's background
        app = app_frame(APP_LEN - 1e-3)
        s = 1 - 0.05 * ease(k / END_FADE)
        a2 = app.resize((int(W * s), int(H * s)), Image.LANCZOS)
        base = end_bg().copy()
        base.alpha_composite(a2, ((W - a2.width) // 2, (H - a2.height) // 2))
        return Image.blend(base, end_bg(), ease(k / END_FADE)).convert("RGB")
    return end_card(k - END_FADE).convert("RGB")


if "--marks" in opts:   # when each mark comes in the cut (output seconds), to line the music up
    def to_out(t):
        for (o1, s1), (o2, s2) in zip(TMAP, TMAP[1:]):
            if t <= s2:
                return o1 + (o2 - o1) * (t - s1) / max(1e-9, s2 - s1)
        return TMAP[-1][0]
    print(" ".join(f"{k}={to_out(v):.2f}" for k, v in sorted(M.items(), key=lambda kv: kv[1])), f"end_card={APP_LEN + END_FADE:.2f}", f"total={TOTAL:.2f}")
    sys.exit(0)

if "--moving" in opts:   # output-time spans where the camera moves (or the end card fades): the GIF thins these
    spans, on = [], None
    o = 0.0
    while o < TOTAL:
        a, b = view_at(to_src(o)), view_at(to_src(o + 1 / FPS))
        mv = o < APP_LEN and (abs(a[0] - b[0]) + abs(a[1] - b[1]) > 0.05 or abs(a[2] - b[2]) > 0.0005) or APP_LEN <= o < APP_LEN + END_FADE + 0.8
        if mv and on is None:
            on = o
        if not mv and on is not None:
            spans.append((round(on, 2), round(o + 1 / FPS, 2))); on = None
        o += 1 / FPS
    if on is not None:
        spans.append((round(on, 2), round(TOTAL, 2)))
    print("+".join(f"between(t,{a},{b})" for a, b in spans))
    sys.exit(0)

if "--still" in opts:
    i = opts.index("--still")
    for spec in opts[i + 1].split(","):
        o = float(spec)
        render(o).save(f"{out}-{spec}.png")
    print("app", round(APP_LEN, 2), "total", round(TOTAL, 2))
    sys.exit(0)

n = int(round(TOTAL * FPS))
print("app", round(APP_LEN, 2), "total", round(TOTAL, 2), "frames", n, flush=True)
ff = subprocess.Popen([os.environ.get("FF", "ffmpeg"), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                       "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "8", "-pix_fmt", "yuv444p",
                       "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", out], stdin=subprocess.PIPE)
for j in range(n):
    ff.stdin.write(render(j / FPS).tobytes())
    if j % 150 == 0:
        print(j, flush=True)
ff.stdin.close()
ff.wait()
print("done", out)
