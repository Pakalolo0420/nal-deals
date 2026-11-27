#!/usr/bin/env python3
"""NAL floor plan renderer (v2, Nov 26 2026: door hand, double_doors, angled openings, room sizes).

Usage:  python3 floorplan_renderer.py spec.json out.png
Needs:  rsvg-convert (librsvg) and the brand fonts. Fonts are fetched from
        github.com/google/fonts into ~/.fonts on first run.

SPEC FORMAT (plan units = any consistent unit, roughly feet; y grows DOWN)
{
  "title": "1 Bed · 1 Bath",            # Playfair heading
  "sub":   "About 790 sq ft",           # DM Sans subline (round Sq Ft to nearest 10)
  "open":  [[[x,y],...], ...],          # open living polygons (living/kitchen/dining/hall), any shape incl. angles
  "rooms": [{"poly":[[x,y],...] | "rect":[x0,y0,x1,y1], "kind":"room|wet|outdoor"}],
           # room = bedrooms/dens (off-white), wet = baths/closets/utility (linen), outdoor = balcony/patio (green, dashed)
  "walls": [[x0,y0,x1,y1], ...],        # extra interior wall lines (6px)
  "fixtures": [{"type": T, "rect":[x0,y0,x1,y1], "wall":"n|e|s|w"}],
           # T: counter, island, fridge, sink, range, tub, shower, toilet, vanity, wh (water heater), wd (washer/dryer), rod
           # "wall" = which side is against the wall (toilet tank, vanity basin offset)
  "doors":  [{"hinge":[x,y], "len":L, "wall":"h|v", "swing":1|-1, "hand":"left|right", "bg":"room|wet"}],
           # h = door in a horizontal wall; leaf swings toward +y (swing 1) or -y. v = vertical wall, toward +x / -x.
           # hand left (default) = opening runs +x (h) / +y (v) from the hinge; right = opening runs -x / -y (hinge on the far jamb)
  "double_doors":[{"wall":"h|v", "at":c, "from":a, "to":b, "swing":1|-1, "bg":"room"}],
           # paired doors (French/balcony): two half-width leaves hinged on each jamb, swinging apart in mirror image
  "bifolds":[{"wall":"h|v", "at":c, "from":a, "to":b, "side":1|-1, "bg":"wet|room"}],
  "sliders":[{"wall":"h|v", "at":c, "from":a, "to":b}],
  "windows":[{"wall":"h|v", "at":c, "from":a, "to":b}],
  "openings_a":[{"type":"window|slider", "line":[x1,y1,x2,y2]}],   # window or sliding door on an ANGLED wall segment
  "entry":  {"at":[x,y], "dir":"s|n|e|w"},   # brass arrow pointing INTO the unit, placed outside the wall
  "labels": [[x, y, "Text", size], ...],     # size 15-34; use "\n" for 2 lines; "Cl." for small closets
  "sizes":  [[x, y, "~18' × 11'"], ...],     # approximate room size under a label (small grey text); put y ~70 plan units below the label
  "notes":  [{"text":"Line one\nline two", "to":[x,y], "side":"left|right", "y":planY}],
  "margin": [left, right]                    # optional extra plan-unit margin for notes (default auto)
}
Rules baked in: no community name/logo anywhere, footer "Layout for illustration; approximate", NAL mark.
"""
import json, math, os, subprocess, sys, urllib.request

NAVY = "#1B2A4A"; CHAR = "#2D2D2D"; CREAM = "#F5F0E8"; LINEN = "#E8DFD0"; BRASS = "#C4993A"
ROOM = "#FBF7F0"; WET = "#E8DFD0"; OUT = "#D9E0DB"
W = H = 1080
FONTS = {
    "PlayfairDisplay.ttf": "ofl/playfairdisplay/PlayfairDisplay%5Bwght%5D.ttf",
    "DMSans.ttf": "ofl/dmsans/DMSans%5Bopsz,wght%5D.ttf",
    "Caveat.ttf": "ofl/caveat/Caveat%5Bwght%5D.ttf",
}

def ensure_fonts():
    d = os.path.expanduser("~/.fonts"); os.makedirs(d, exist_ok=True)
    new = False
    for name, path in FONTS.items():
        p = os.path.join(d, name)
        if not os.path.exists(p):
            urllib.request.urlretrieve("https://raw.githubusercontent.com/google/fonts/main/" + path, p); new = True
    if new:
        subprocess.run(["fc-cache", "-f"], capture_output=True)

def esc(s): return str(s).replace("&", "&amp;").replace("<", "&lt;")

def bbox(spec):
    xs, ys = [], []
    for poly in spec.get("open", []):
        for x, y in poly: xs.append(x); ys.append(y)
    for r in spec.get("rooms", []):
        pts = r["poly"] if "poly" in r else [(r["rect"][0], r["rect"][1]), (r["rect"][2], r["rect"][3])]
        for x, y in pts: xs.append(x); ys.append(y)
    return min(xs), min(ys), max(xs), max(ys)

def render_svg(spec):
    x0, y0, x1, y1 = bbox(spec)
    notes = spec.get("notes", [])
    ml, mr = spec.get("margin", [None, None]) if spec.get("margin") else (None, None)
    span = max(x1 - x0, y1 - y0)
    if ml is None: ml = span * 0.26 if any(n.get("side") == "left" for n in notes) else span * 0.03
    if mr is None: mr = span * 0.26 if any(n.get("side") == "right" for n in notes) else span * 0.03
    ex0, ey0, ex1, ey1 = x0 - ml, y0 - span * 0.03, x1 + mr, y1 + span * 0.08
    ax0, ay0, ax1, ay1 = 70, 245, 1010, 915
    s = min((ax1 - ax0) / (ex1 - ex0), (ay1 - ay0) / (ey1 - ey0))
    ox = ax0 + ((ax1 - ax0) - (ex1 - ex0) * s) / 2 - ex0 * s
    oy = ay0 + ((ay1 - ay0) - (ey1 - ey0) * s) / 2 - ey0 * s
    P = lambda x, y: (ox + x * s, oy + y * s)
    o = []
    bgc = {"room": ROOM, "wet": WET, "outdoor": OUT}

    def poly_svg(pts, fill, dash=False, sw=9):
        d = " ".join("%.1f,%.1f" % P(x, y) for x, y in pts)
        da = ' stroke-dasharray="14 10"' if dash else ""
        o.append(f'<polygon points="{d}" fill="{fill}" stroke="{NAVY}" stroke-width="{sw}" stroke-linejoin="miter"{da}/>')
    def rect(r, fill="none", rx=0, sw=3):
        a, b = P(r[0], r[1]); c, d = P(r[2], r[3])
        o.append(f'<rect x="{min(a,c):.1f}" y="{min(b,d):.1f}" width="{abs(c-a):.1f}" height="{abs(d-b):.1f}" rx="{rx}" fill="{fill}" stroke="{NAVY}" stroke-width="{sw}"/>')
    def line(xa, ya, xb, yb, col=NAVY, sw=3, dash=None):
        a, b = P(xa, ya); c, d = P(xb, yb)
        da = f' stroke-dasharray="{dash}"' if dash else ""
        o.append(f'<line x1="{a:.1f}" y1="{b:.1f}" x2="{c:.1f}" y2="{d:.1f}" stroke="{col}" stroke-width="{sw}"{da}/>')
    def seg(wall, at, a, b):
        return (a, at, b, at) if wall == "h" else (at, a, at, b)

    # 1 shapes
    for poly in spec.get("open", []):
        poly_svg(poly, ROOM)
    for r in spec.get("rooms", []):
        pts = r["poly"] if "poly" in r else [(r["rect"][0], r["rect"][1]), (r["rect"][2], r["rect"][1]), (r["rect"][2], r["rect"][3]), (r["rect"][0], r["rect"][3])]
        poly_svg(pts, bgc.get(r.get("kind", "room"), ROOM), dash=r.get("kind") == "outdoor")
    for w_ in spec.get("walls", []):
        line(*w_, sw=6)

    # 2 fixtures
    for f in spec.get("fixtures", []):
        t, r = f["type"], f["rect"]; wall = f.get("wall", "s")
        cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2; wdt, hgt = abs(r[2] - r[0]), abs(r[3] - r[1])
        if t in ("counter", "island"):
            rect(r, LINEN)
        elif t == "fridge":
            rect(r, ROOM)
        elif t == "sink":
            rect(r, rx=5)
        elif t == "range":
            rect(r, ROOM)
            for fx in (0.3, 0.7):
                for fy in (0.3, 0.7):
                    a, b = P(r[0] + wdt * fx, r[1] + hgt * fy)
                    o.append(f'<circle cx="{a:.1f}" cy="{b:.1f}" r="{min(wdt,hgt)*0.15*s:.1f}" fill="none" stroke="{NAVY}" stroke-width="2"/>')
        elif t in ("tub", "shower"):
            rect(r, ROOM, rx=8)
            if t == "tub":
                pad = min(wdt, hgt) * 0.14
                rect((r[0] + pad, r[1] + pad, r[2] - pad, r[3] - pad), rx=14, sw=2)
            else:
                line(r[0], r[1], r[2], r[3], sw=1.5); line(r[0], r[3], r[2], r[1], sw=1.5)
        elif t == "toilet":
            # tank against `wall`, bowl toward the room
            if wall in ("n", "s"):
                ty = r[1] if wall == "n" else r[3] - hgt * 0.28
                rect((r[0], ty, r[2], ty + hgt * 0.28), ROOM, sw=2)
                by = r[1] + hgt * 0.62 if wall == "n" else r[1] + hgt * 0.38
                a, b = P(cx, by); o.append(f'<ellipse cx="{a:.1f}" cy="{b:.1f}" rx="{wdt*0.38*s:.1f}" ry="{hgt*0.34*s:.1f}" fill="{ROOM}" stroke="{NAVY}" stroke-width="2"/>')
            else:
                tx = r[0] if wall == "w" else r[2] - wdt * 0.28
                rect((tx, r[1], tx + wdt * 0.28, r[3]), ROOM, sw=2)
                bx = r[0] + wdt * 0.62 if wall == "w" else r[0] + wdt * 0.38
                a, b = P(bx, cy); o.append(f'<ellipse cx="{a:.1f}" cy="{b:.1f}" rx="{wdt*0.34*s:.1f}" ry="{hgt*0.38*s:.1f}" fill="{ROOM}" stroke="{NAVY}" stroke-width="2"/>')
        elif t == "vanity":
            rect(r, ROOM)
            a, b = P(cx, cy); o.append(f'<ellipse cx="{a:.1f}" cy="{b:.1f}" rx="{min(wdt,hgt*1.6)*0.3*s:.1f}" ry="{min(hgt,wdt*1.6)*0.28*s:.1f}" fill="none" stroke="{NAVY}" stroke-width="2"/>')
        elif t == "wh":
            a, b = P(cx, cy); o.append(f'<circle cx="{a:.1f}" cy="{b:.1f}" r="{min(wdt,hgt)*0.45*s:.1f}" fill="{ROOM}" stroke="{NAVY}" stroke-width="3"/>')
        elif t == "wd":
            rect(r, ROOM)
            for k in (0, 1):
                if wdt >= hgt:
                    c = (r[0] + wdt * (0.25 + 0.5 * k), cy); rr = min(wdt / 2, hgt) * 0.3
                else:
                    c = (cx, r[1] + hgt * (0.25 + 0.5 * k)); rr = min(wdt, hgt / 2) * 0.3
                a, b = P(*c); o.append(f'<circle cx="{a:.1f}" cy="{b:.1f}" r="{rr*s:.1f}" fill="none" stroke="{NAVY}" stroke-width="2"/>')
        elif t == "rod":
            line(r[0], r[1], r[2], r[3], sw=2, dash="3 4")

    # 3 openings
    def gap(wall, at, a, b, col):
        line(*seg(wall, at, a, b), col=col, sw=12)
    for w_ in spec.get("windows", []):
        gap(w_["wall"], w_["at"], w_["from"], w_["to"], ROOM)
        for off in (-4, 0, 4):
            xa, ya, xb, yb = seg(w_["wall"], w_["at"], w_["from"], w_["to"])
            a, b = P(xa, ya); c, d = P(xb, yb)
            if w_["wall"] == "h": b += off; d += off
            else: a += off; c += off
            o.append(f'<line x1="{a:.1f}" y1="{b:.1f}" x2="{c:.1f}" y2="{d:.1f}" stroke="{NAVY}" stroke-width="1.6"/>')
    for sl in spec.get("sliders", []):
        gap(sl["wall"], sl["at"], sl["from"], sl["to"], ROOM)
        a_, b_ = sl["from"], sl["to"]; mid = (a_ + b_) / 2; ov = (b_ - a_) * 0.07; dd = 0.25
        for (p, q, off) in ((a_, mid + ov, -dd), (mid - ov, b_, dd)):
            line(*seg(sl["wall"], sl["at"] + off, p, q), sw=3.5)
    for bf in spec.get("bifolds", []):
        gap(bf["wall"], bf["at"], bf["from"], bf["to"], bgc.get(bf.get("bg", "wet"), WET))
        xa, ya, xb, yb = seg(bf["wall"], bf["at"], bf["from"], bf["to"])
        a, b = P(xa, ya); c, d = P(xb, yb); k = bf.get("side", 1) * abs((bf["to"] - bf["from"])) * 0.25 * s
        if bf["wall"] == "v": o.append(f'<polyline points="{a:.1f},{b:.1f} {a+k:.1f},{(b+d)/2:.1f} {c:.1f},{d:.1f}" fill="none" stroke="{NAVY}" stroke-width="2"/>')
        else: o.append(f'<polyline points="{a:.1f},{b:.1f} {(a+c)/2:.1f},{b+k:.1f} {c:.1f},{d:.1f}" fill="none" stroke="{NAVY}" stroke-width="2"/>')
    def door(hx, hy, L, wall, sw_, hand, col):
        # hand "left" (default): door opening runs +x/+y from the hinge; "right": runs -x/-y (hinge on the other jamb)
        d_ = -1 if hand == "right" else 1
        if wall == "h":
            gap("h", hy, min(hx, hx + d_ * L), max(hx, hx + d_ * L), col)
            a, b = P(hx, hy); c, _ = P(hx + d_ * L, hy); ex, ey = P(hx, hy + sw_ * L); sweep = 1 if sw_ * d_ > 0 else 0; start = (c, b)
        else:
            gap("v", hx, min(hy, hy + d_ * L), max(hy, hy + d_ * L), col)
            a, b = P(hx, hy); _, d = P(hx, hy + d_ * L); ex, ey = P(hx + sw_ * L, hy); sweep = 0 if sw_ * d_ > 0 else 1; start = (a, d)
        o.append(f'<line x1="{a:.1f}" y1="{b:.1f}" x2="{ex:.1f}" y2="{ey:.1f}" stroke="{NAVY}" stroke-width="3"/>')
        o.append(f'<path d="M{start[0]:.1f},{start[1]:.1f} A{L*s:.1f},{L*s:.1f} 0 0 {sweep} {ex:.1f},{ey:.1f}" fill="none" stroke="{NAVY}" stroke-width="2" stroke-dasharray="6 5"/>')
    for dr in spec.get("doors", []):
        hx, hy = dr["hinge"]
        door(hx, hy, dr["len"], dr["wall"], dr.get("swing", 1), dr.get("hand", "left"), bgc.get(dr.get("bg", "room"), ROOM))
    for dd in spec.get("double_doors", []):
        # paired doors: hinges on both jambs, leaves swing apart (mirror images), each half the opening
        a_, b_ = sorted((dd["from"], dd["to"])); half = (b_ - a_) / 2; sw_ = dd.get("swing", 1)
        col = bgc.get(dd.get("bg", "room"), ROOM)
        if dd["wall"] == "h":
            door(a_, dd["at"], half, "h", sw_, "left", col); door(b_, dd["at"], half, "h", sw_, "right", col)
        else:
            door(dd["at"], a_, half, "v", sw_, "left", col); door(dd["at"], b_, half, "v", sw_, "right", col)

    # 3b angled openings (example extension): windows/sliders on any straight wall segment
    for op in spec.get("openings_a", []):
        x1, y1, x2, y2 = op["line"]; L_ = math.hypot(x2 - x1, y2 - y1); ux, uy = (x2 - x1) / L_, (y2 - y1) / L_; nx, ny = -uy, ux
        a, b = P(x1, y1); c, d = P(x2, y2)
        o.append(f'<line x1="{a:.1f}" y1="{b:.1f}" x2="{c:.1f}" y2="{d:.1f}" stroke="{ROOM}" stroke-width="12"/>')
        if op.get("type") == "window":
            for off in (-4, 0, 4):
                o.append(f'<line x1="{a+nx*off:.1f}" y1="{b+ny*off:.1f}" x2="{c+nx*off:.1f}" y2="{d+ny*off:.1f}" stroke="{NAVY}" stroke-width="1.6"/>')
        else:
            mid = L_ / 2; ov = L_ * 0.07
            for (p_, q_, off) in ((0, mid + ov, -3), (mid - ov, L_, 3)):
                sa, sb = P(x1 + ux * p_, y1 + uy * p_); ea, eb = P(x1 + ux * q_, y1 + uy * q_)
                o.append(f'<line x1="{sa+nx*off:.1f}" y1="{sb+ny*off:.1f}" x2="{ea+nx*off:.1f}" y2="{eb+ny*off:.1f}" stroke="{NAVY}" stroke-width="3.5"/>')

    # 4 entry
    en = spec.get("entry")
    if en:
        x, y = P(*en["at"]); dr = en.get("dir", "n")
        v = {"n": (0, -1), "s": (0, 1), "e": (1, 0), "w": (-1, 0)}[dr]  # direction the arrow points (into the unit)
        bx, by = x - v[0] * 34, y - v[1] * 34; tx, ty = x - v[0] * 12, y - v[1] * 12
        px, py = -v[1], v[0]
        o.append(f'<polygon points="{bx+px*16:.1f},{by+py*16:.1f} {bx-px*16:.1f},{by-py*16:.1f} {tx:.1f},{ty:.1f}" fill="{BRASS}"/>')
        lx, ly = x - v[0] * 62, y - v[1] * 62 + (8 if dr in ("e", "w") else 0)
        o.append(f'<text x="{lx:.1f}" y="{ly:.1f}" font-family="DM Sans" font-weight="600" font-size="20" letter-spacing="3" fill="{CHAR}" text-anchor="middle">ENTRY</text>')

    # 5 labels
    for x, y, t, size in spec.get("labels", []):
        px, py = P(x, y); lines = str(t).split("\n")
        for i, ln in enumerate(lines):
            yy = py + size * 0.35 + (i - (len(lines) - 1) / 2) * size * 1.2
            o.append(f'<text x="{px:.1f}" y="{yy:.1f}" font-family="DM Sans" font-weight="700" font-size="{size}" letter-spacing="{size*0.08:.1f}" fill="{CHAR}" text-anchor="middle">{esc(ln.upper())}</text>')

    # 5b approximate room sizes (example extension)
    for x, y, tx in spec.get("sizes", []):
        px, py = P(x, y)
        o.append(f'<text x="{px:.1f}" y="{py:.1f}" font-family="DM Sans" font-weight="500" font-size="17" fill="{CHAR}" fill-opacity="0.75" text-anchor="middle">{esc(tx)}</text>')

    # 6 notes (Caveat + brass arrows) in the side margins
    lx_, _ = P(x0, 0); rx_, _ = P(x1, 0)
    for n in notes:
        side = n.get("side", "right"); lines = n["text"].split("\n")
        tx = lx_ - 22 if side == "left" else rx_ + 26; anchor = "end" if side == "left" else "start"
        ty = P(0, n.get("y", n["to"][1]))[1]
        for i, ln in enumerate(lines):
            o.append(f'<text x="{tx:.1f}" y="{ty + i*38:.1f}" font-family="Caveat" font-weight="700" font-size="40" fill="{BRASS}" text-anchor="{anchor}">{esc(ln)}</text>')
        ex, ey = P(*n["to"]); sx = tx + (10 if anchor == "start" else -10); sy = ty + (len(lines) - 1) * 38 + 16
        mx, my = (sx + ex) / 2, (sy + ey) / 2 + (30 if ey > sy else -30)
        o.append(f'<path d="M{sx:.1f},{sy:.1f} Q{mx:.1f},{my:.1f} {ex:.1f},{ey:.1f}" fill="none" stroke="{BRASS}" stroke-width="3.5" stroke-linecap="round"/>')
        ang = math.atan2(ey - my, ex - mx)
        for da in (2.6, -2.6):
            o.append(f'<line x1="{ex:.1f}" y1="{ey:.1f}" x2="{ex+18*math.cos(ang+da):.1f}" y2="{ey+18*math.sin(ang+da):.1f}" stroke="{BRASS}" stroke-width="3.5" stroke-linecap="round"/>')

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
<rect width="{W}" height="{H}" fill="{CREAM}"/>
<rect x="0" y="0" width="{W}" height="14" fill="{BRASS}"/>
<text x="90" y="118" font-family="Playfair Display" font-weight="700" font-size="76" fill="{NAVY}">{esc(spec["title"])}</text>
<text x="92" y="182" font-family="DM Sans" font-weight="500" font-size="38" fill="{CHAR}">{esc(spec["sub"])}</text>
{"".join(o)}
<rect x="0" y="960" width="{W}" height="120" fill="{NAVY}"/>
<text x="90" y="1029" font-family="DM Sans" font-weight="500" font-size="27" fill="{CREAM}">Layout for illustration; approximate</text>
<circle cx="944" cy="1020" r="34" fill="none" stroke="{BRASS}" stroke-width="4"/>
<text x="944" y="1029" font-family="Playfair Display" font-weight="700" font-size="22" letter-spacing="1.5" fill="{CREAM}" text-anchor="middle">NAL</text>
</svg>'''

def render(spec, out_png):
    ensure_fonts()
    svg_path = out_png.rsplit(".", 1)[0] + ".svg"
    open(svg_path, "w").write(render_svg(spec))
    subprocess.run(["rsvg-convert", "-w", "1080", svg_path, "-o", out_png], check=True)
    return out_png

if __name__ == "__main__":
    spec = json.load(open(sys.argv[1]))
    print(render(spec, sys.argv[2]))
