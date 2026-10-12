"""Generate 3 SMIL SVG animations from the converted EPS (pdftocairo SVG)."""
import re, sys, os

SRC, OUT = sys.argv[1], sys.argv[2]
DUR = 10.0
BG = "rgb(21.426392%, 27.575684%, 31.733704%)"
FRAME = "rgb(13.729858%, 12.159729%, 12.548828%)"

# artboard 1 coordinates (page units = pt)
VB = (1.753906, 0.003906, 441.008, 223.656)
DX2, DX3 = 460.785, 919.371          # offsets of artboard 2 / 3 in the page
Y0, Y1 = 8.832031, 174.175781
PH2 = [(10.817, 150.905), (158.885, 282.775), (290.755, 433.705)]
PH3 = [(10.813, 151.939), (159.919, 283.469), (291.439, 433.709)]
LOGO = (55.0, 176.8, 340.0, 46.0)     # x, y, w, h (below the photos)

E = {"out": "0.22 1 0.36 1", "in": "0.55 0 1 0.45", "io": "0.65 0 0.35 1",
     "lin": "0 0 1 1", "hold": "0 0 1 1"}


def page_symbol():
    s = open(SRC, encoding="utf-8").read()
    s = re.sub(r"<\?xml[^>]*\?>", "", s)
    s = re.sub(r"<svg[^>]*>", '<symbol id="page" viewBox="0 0 1364.44 224.33" overflow="visible">', s, count=1)
    s = s.replace("</svg>", "</symbol>")
    return s.strip()


def anim(attr, frames, tag="animate", ttype=None, additive=False):
    """frames: [(t, value, ease_into_this_frame)]; padded to cover 0..DUR."""
    fr = list(frames)
    if fr[0][0] > 0:
        fr.insert(0, (0, fr[0][1], "lin"))
    if fr[-1][0] < DUR:
        fr.append((DUR, fr[-1][1], "lin"))
    kt = ";".join(f"{t / DUR:.4f}" for t, _, _ in fr)
    vals = ";".join(str(v) for _, v, _ in fr)
    ks = ";".join(E[e] for _, _, e in fr[1:])
    extra = f' type="{ttype}"' if ttype else ""
    extra += ' additive="sum"' if additive else ""
    an = "attributeName" if tag == "animate" else "attributeName"
    return (f'<{tag} {an}="{attr}"{extra} dur="{DUR}s" repeatCount="indefinite" '
            f'calcMode="spline" keyTimes="{kt}" values="{vals}" keySplines="{ks}"/>')


def region(x, y, w, h, dx, kb=None):
    """Cut a rectangle out of the page; optional Ken-Burns scale frames."""
    inner = '<use href="#page" xlink:href="#page" width="1364.44" height="224.33"/>'
    if kb:
        cx, cy = x + dx + w / 2, y + h / 2
        inner = (f'<g transform="translate({cx:.3f} {cy:.3f})"><g>'
                 + anim("transform", kb, "animateTransform", "scale")
                 + f'<g transform="translate({-cx:.3f} {-cy:.3f})">{inner}</g></g></g>')
    return (f'<svg x="{x:.3f}" y="{y:.3f}" width="{w:.3f}" height="{h:.3f}" '
            f'viewBox="{x + dx:.3f} {y:.3f} {w:.3f} {h:.3f}" overflow="hidden">{inner}</svg>')


class Doc:
    def __init__(self):
        self.defs, self.body, self.n = [], [], 0

    def uid(self, p):
        self.n += 1
        return f"{p}{self.n}"

    def layer(self, content, box, opacity=None, translate=None, scale=None, clip=None):
        """Wrap content; scale is around the box centre. clip: dict attr->frames on a rect."""
        x, y, w, h = box
        cx, cy = x + w / 2, y + h / 2
        if clip:
            cid = self.uid("c")
            anims = "".join(anim(a, f) for a, f in clip.items())
            self.defs.append(f'<clipPath id="{cid}"><rect x="{x:.3f}" y="{y:.3f}" width="{w:.3f}" '
                             f'height="{h:.3f}">{anims}</rect></clipPath>')
            content = f'<g clip-path="url(#{cid})">{content}</g>'
        if scale:
            content = (f'<g transform="translate({cx:.3f} {cy:.3f})"><g>'
                       + anim("transform", scale, "animateTransform", "scale")
                       + f'<g transform="translate({-cx:.3f} {-cy:.3f})">{content}</g></g></g>')
        if translate:
            content = f'<g>{anim("transform", translate, "animateTransform", "translate")}{content}</g>'
        if opacity:
            content = f'<g opacity="{opacity[0][1]}">{anim("opacity", opacity)}{content}</g>'
        self.body.append(content)

    def svg(self, title):
        x, y, w, h = VB
        return f'''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="{x} {y} {w} {h}" width="{w * 2:.0f}" height="{h * 2:.0f}">
<title>{title}</title>
<defs>
{page_symbol()}
{"".join(self.defs)}
<clipPath id="ab"><rect x="{x}" y="{y}" width="{w}" height="{h}"/></clipPath>
</defs>
<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{BG}"/>
<g clip-path="url(#ab)">
{chr(10).join(self.body)}
</g>
<rect x="{x + 0.162}" y="{y + 0.162}" width="{w - 0.324}" height="{h - 0.324}" fill="none" stroke="{FRAME}" stroke-width="0.324"/>
</svg>'''


def artboard1(d):
    """Artboard 1 stays as is: visible 0-4 s (soft cross-fade at both ends)."""
    x, y, w, h = VB
    d.layer(region(x, y, w, h, 0), VB,
            opacity=[(0, 0, "lin"), (0.35, 1, "out"), (3.65, 1, "hold"), (4.0, 0, "io")])


def pbox(p):
    return (p[0], Y0, p[1] - p[0], Y1 - Y0)


def lbox():
    return LOGO


def logo(d, dx, t_in, t_out, style):
    b = lbox()
    content = region(*b, dx)
    if style == "rise":
        d.layer(content, b,
                opacity=[(t_in, 0, "lin"), (t_in + .5, 1, "out"), (t_out - .35, 1, "hold"), (t_out, 0, "in")],
                translate=[(t_in, "0 10", "lin"), (t_in + .6, "0 0", "out"), (t_out, "0 0", "hold")])
    elif style == "wipe":
        x, y, w, h = b
        d.layer(content, b,
                clip={"width": [(t_in, 0, "lin"), (t_in + .7, w, "io"), (t_out - .35, w, "hold"), (t_out, 0, "in")]},
                opacity=[(t_in, 0, "lin"), (t_in + .01, 1, "lin"), (t_out, 1, "hold"), (t_out + .01, 0, "lin")])
    elif style == "zoom":
        d.layer(content, b,
                opacity=[(t_in, 0, "lin"), (t_in + .45, 1, "out"), (t_out - .3, 1, "hold"), (t_out, 0, "in")],
                scale=[(t_in, "1.25 1.25", "lin"), (t_in + .6, "1 1", "out"), (t_out - .3, "1 1", "hold"),
                       (t_out, "0.9 0.9", "in")])


def kenburns(t_in, t_out, a=1.0, b=1.08):
    return [(t_in, f"{a} {a}", "lin"), (t_out, f"{b} {b}", "lin")]


# ---------------------------------------------------------------- variant 1
def v1():
    """Slide & Stagger: photos rise from below (A2) / glide in from the right (A3)."""
    d = Doc()
    artboard1(d)
    for i, p in enumerate(PH2):
        t = 4.0 + i * 0.14
        b = pbox(p)
        d.layer(region(*b, DX2, kb=kenburns(4.0, 7.0)), b,
                opacity=[(t, 0, "lin"), (t + .35, 1, "out"), (6.55 + i * .07, 1, "hold"), (6.9 + i * .03, 0, "in")],
                translate=[(t, "0 70", "lin"), (t + .45, "0 -4", "out"), (t + .65, "0 0", "io"),
                           (6.55 + i * .07, "0 0", "hold"), (6.95 + i * .03, "-30 0", "in")])
    logo(d, DX2, 4.35, 6.95, "rise")
    for i, p in enumerate(PH3):
        t = 7.0 + i * 0.14
        b = pbox(p)
        d.layer(region(*b, DX3, kb=kenburns(7.0, 10.0, 1.08, 1.0)), b,
                opacity=[(t, 0, "lin"), (t + .35, 1, "out"), (9.55 + i * .05, 1, "hold"), (9.9, 0, "in")],
                translate=[(t, "90 0", "lin"), (t + .45, "-5 0", "out"), (t + .65, "0 0", "io"),
                           (9.55 + i * .05, "0 0", "hold"), (9.95, "0 -20", "in")])
    logo(d, DX3, 7.35, 9.95, "rise")
    return d.svg("Kreativ Holz Design – Slide")


# ---------------------------------------------------------------- variant 2
def v2():
    """Curtain wipe: photos are uncovered by vertical (A2) and horizontal (A3) wipes with parallax zoom."""
    d = Doc()
    artboard1(d)
    for i, p in enumerate(PH2):
        x, y, w, h = b = pbox(p)
        t = 4.0 + i * 0.18
        down = i % 2 == 0          # 1 + 3 open downwards, 2 upwards
        te = 6.5 + i * .08
        if down:
            clip = {"height": [(t, 0, "lin"), (t + .7, h, "io"), (te, h, "hold"), (te + .32, 0, "in")],
                    "y": [(t, y, "lin"), (te, y, "hold"), (te + .32, y + h, "in")]}
        else:
            clip = {"height": [(t, 0, "lin"), (t + .7, h, "io"), (te, h, "hold"), (te + .32, 0, "in")],
                    "y": [(t, y + h, "lin"), (t + .7, y, "io"), (te, y, "hold")]}
        d.layer(region(*b, DX2, kb=[(t, "1.3 1.3", "lin"), (t + .9, "1.06 1.06", "out"), (7.0, "1 1", "lin")]),
                b, clip=clip)
    logo(d, DX2, 4.45, 6.95, "wipe")
    for i, p in enumerate(PH3):
        x, y, w, h = b = pbox(p)
        t = 7.0 + i * 0.18
        te = 9.4 + i * .08
        clip = {"width": [(t, 0, "lin"), (t + .65, w, "io"), (te, w, "hold"), (te + .32, 0, "in")],
                "x": [(t, x, "lin"), (te, x, "hold"), (te + .32, x + w, "in")]}
        d.layer(region(*b, DX3, kb=[(t, "1.3 1.3", "lin"), (t + .9, "1.06 1.06", "out"), (10, "1 1", "lin")]),
                b, clip=clip)
    logo(d, DX3, 7.45, 9.95, "wipe")
    return d.svg("Kreativ Holz Design – Wipe")


# ---------------------------------------------------------------- variant 3
def v3():
    """Flip & Zoom: A2 photos turn in like cards, A3 opens from the centre outwards."""
    d = Doc()
    artboard1(d)
    for i, p in enumerate(PH2):
        b = pbox(p)
        t = 4.0 + i * 0.2
        te = 6.5 + i * .12
        d.layer(region(*b, DX2, kb=kenburns(t, 7.0, 1.0, 1.07)), b,
                opacity=[(t, 0, "lin"), (t + .15, 1, "lin"), (te + .3, 1, "hold"), (te + .4, 0, "lin")],
                scale=[(t, "0.01 0.92", "lin"), (t + .5, "1.04 1", "out"), (t + .7, "1 1", "io"),
                       (te, "1 1", "hold"), (te + .4, "0.01 0.92", "in")])
    logo(d, DX2, 4.5, 6.95, "zoom")
    order = {1: 0.0, 0: 0.22, 2: 0.22}       # centre first, then the sides
    for i, p in enumerate(PH3):
        b = pbox(p)
        t = 7.0 + order[i]
        shift = {0: "-60 0", 1: "0 0", 2: "60 0"}[i]
        if i == 1:
            d.layer(region(*b, DX3, kb=kenburns(7.0, 10.0, 1.0, 1.08)), b,
                    opacity=[(t, 0, "lin"), (t + .4, 1, "out"), (9.6, 1, "hold"), (9.85, 0, "in")],
                    scale=[(t, "1.35 1.35", "lin"), (t + .6, "1 1", "out"), (9.6, "1 1", "hold"),
                           (9.85, "0.85 0.85", "in")])
        else:
            d.layer(region(*b, DX3, kb=kenburns(7.0, 10.0, 1.08, 1.0)), b,
                    opacity=[(t, 0, "lin"), (t + .4, 1, "out"), (9.6, 1, "hold"), (9.85, 0, "in")],
                    translate=[(t, shift, "lin"), (t + .6, "0 0", "out"), (10, "0 0", "hold")],
                    scale=[(t, "0.85 0.85", "lin"), (t + .6, "1 1", "out"), (9.6, "1 1", "hold"),
                           (9.85, "0.85 0.85", "in")])
    logo(d, DX3, 7.5, 9.95, "zoom")
    return d.svg("Kreativ Holz Design – Flip")


os.makedirs(OUT, exist_ok=True)
for name, fn in (("vorschlag-1-slide", v1), ("vorschlag-2-wipe", v2), ("vorschlag-3-flip-zoom", v3)):
    with open(os.path.join(OUT, name + ".svg"), "w", encoding="utf-8") as f:
        f.write(fn())
    print(name, os.path.getsize(os.path.join(OUT, name + ".svg")))
