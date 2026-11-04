#!/usr/bin/env python3
"""Build the animated README hero, assets/s3mirror-readme-hero.svg.

The banner follows the soakes/cv README hero, like the netspeedy/s3ctl and zquota ones: the
bucket-and-arrow mark, a two-line headline, a short body and a meta row on the left, and a
generated scene on the right. The scene is a mirror run: a source and a destination bucket
drawn in dots, joined by parallel worker lanes, with objects in flight at different speeds,
one multipart upload among them, and a ping wherever an object lands.

Edit the copy, layout or timing here and run `make readme-hero` rather than editing the
generated SVG. netspeedy/homebrew-s3mirror shows the same banner, built from a copy of this
script in its .github/scripts, so copy changes there too. The headline is positioned from
measured advances (see ADVANCE); if you change its words, measure them again with
measure_headline.py. Inter and JetBrains Mono (SIL Open Font License 1.1) are fetched from
Google Fonts, subset to the characters the finished SVG renders, and embedded, so the hero
renders the same on every platform. Needs network access.
"""

from __future__ import annotations

import base64
import math
import random
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "assets" / "s3mirror-readme-hero.svg"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

# The website's palette (website/style.css) and the favicon's cyan-violet-orange bucket,
# with the same inks as the s3ctl hero so the netspeedy banners read as one family.
BG = "#060B13"
INK = "#F1F5FA"
INK_2 = "#B5C0CD"
INK_3 = "#808D9E"
CYAN = "#4BD8FF"
CYAN_2 = "#A8ECFF"
CYAN_3 = "#18A8FF"
VIOLET = "#9B73FF"
VIOLET_2 = "#CDB9FF"
ORANGE = "#FF9F43"
AMBER = "#F5B841"

# Fonts: css class -> (Google Fonts family spec, embedded family name).
FAMILIES = {
    "sans": ("Inter:opsz,wght@14..32,400..800", "Hero Sans"),
    "mono": ("JetBrains Mono:wght@400..700", "Hero Mono"),
}
FONT_CSS = (
    ".sans{font-family:'Hero Sans',-apple-system,'Segoe UI','Helvetica Neue',Arial,"
    "sans-serif;font-optical-sizing:auto;}"
    ".mono{font-family:'Hero Mono','SF Mono',Menlo,Consolas,monospace;}"
)
TWINKLE_CSS = (
    ".tw{animation:tw 5.2s ease-in-out infinite;transform-box:fill-box;"
    "transform-origin:center}"
    ".tw1{animation-duration:6.4s}.tw2{animation-duration:4.6s}.tw3{animation-duration:7.3s}"
    "@keyframes tw{0%,100%{opacity:.85}50%{opacity:.15}}"
)

# Starfield: seeded, so rebuilding gives the same sky. No star sits behind the copy.
STAR_SEED = 11
STARS = 110
TWINKLING = 16
COPY_BOX = (36, 30, 520, 340)

# Headline advances in px, measured by measure_headline.py on Inter 800 at 44px (opsz 32,
# letter-spacing -1.3). The swash and the gradients are placed from these.
ADVANCE = {
    "No ": 63.17,
    "vendor": 138.49,
    "No vendor lock-in.": 352.64,
    "Copy what changed.": 402.40,
}


# Fonts


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def collect_chars(svg: str) -> dict[str, set[str]]:
    """Characters rendered by each font class, inherited through groups."""
    chars: dict[str, set[str]] = {name: set() for name in FAMILIES}

    def family_of(element: ET.Element, inherited: str | None) -> str | None:
        for cls in (element.get("class") or "").split():
            if cls in FAMILIES:
                return cls
        return inherited

    def walk(element: ET.Element, inherited: str | None, in_text: bool) -> None:
        tag = element.tag.split("}")[-1]
        family = family_of(element, inherited)
        if tag in ("style", "title", "desc", "script"):
            return
        is_text = in_text or tag in ("text", "tspan", "textPath")
        if is_text and tag in ("text", "tspan", "textPath") and element.text:
            if family is None:
                raise SystemExit(f"text without a font class: {element.text!r}")
            chars[family].update(element.text)
        for child in element:
            walk(child, family, is_text)
            if is_text and child.tail and child.tail.strip():
                chars[family or "sans"].update(child.tail)

    walk(ET.fromstring(svg), None, False)
    return chars


def font_faces(svg: str) -> str:
    """One @font-face per family, subset to exactly the characters the SVG renders."""
    chars = collect_chars(svg)
    faces = []
    for cls, (spec, local) in FAMILIES.items():
        used = chars[cls]
        if not used:
            continue
        text = "".join(sorted((used - set("\n\t\r")) | {" "}))
        query = urllib.parse.urlencode(
            {"family": spec, "text": text, "display": "block"}
        )
        css = fetch(f"https://fonts.googleapis.com/css2?{query}").decode()
        seen = set()
        # Google serves one variable file covering every weight; embed each file once.
        for weight, url in re.findall(
            r"font-weight:\s*([\d ]+);.*?src:\s*url\(([^)]+)\)", css, re.S
        ):
            if url in seen:
                continue
            seen.add(url)
            data = base64.b64encode(fetch(url)).decode()
            faces.append(
                f"@font-face{{font-family:'{local}';font-weight:{weight.strip()};"
                f"font-style:normal;src:url(data:font/woff2;base64,{data}) "
                "format('woff2');}"
            )
    return "".join(faces)


# Small helpers


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def num(value: float) -> str:
    """One decimal place, without a trailing .0."""
    text = f"{value:.1f}"
    return text[:-2] if text.endswith(".0") else text


def mono_width(chars: int, size: float, spacing: float = 0.0) -> float:
    """JetBrains Mono advances exactly 0.6 em; letter-spacing applies per glyph."""
    return chars * (size * 0.6 + spacing)


def gradient(kind: str, attrs: str, stops: list[tuple[str, str, str]]) -> list[str]:
    lines = [f"    <{kind} {attrs}>"]
    for offset, colour, opacity in stops:
        alpha = f' stop-opacity="{opacity}"' if opacity else ""
        lines.append(f'      <stop offset="{offset}" stop-color="{colour}"{alpha} />')
    return [*lines, f"    </{kind}>"]


def dot_paths(
    points: list[tuple[float, float, int]],
    styles: dict[int, tuple[float, float]],
    colour: str,
) -> str:
    """Dots grouped by band, each band one path of round-capped stubs."""
    paths = []
    for band, (opacity, width) in styles.items():
        pts = sorted(
            ((x, y) for x, y, b in points if b == band),
            key=lambda p: (round(p[1]), p[0]),
        )
        if not pts:
            continue
        moves = []
        px = py = 0.0
        for x, y in pts:
            # "h.01", not "h0": some renderers drop zero-length subpaths.
            moves.append(f"m{num(x - px)} {num(y - py)}h.01")
            px, py = x + 0.01, y
        paths.append(
            f'<path d="M0 0{"".join(moves)}" fill="none" stroke="{colour}" '
            f'stroke-opacity="{opacity}" stroke-width="{width}" stroke-linecap="round" />'
        )
    return "".join(paths)


def chip_width(label: str, size: float = 10.5, spacing: float = 1.2) -> float:
    return mono_width(len(label), size, spacing) - spacing + 16


def chip(x: float, y: float, label: str, colour: str) -> str:
    """A mono label in a small outlined box; (x, y) is the box's top-left corner."""
    width = chip_width(label)
    return (
        f'<g><rect x="{num(x)}" y="{num(y)}" width="{num(width)}" height="20" rx="4" '
        f'fill="#0A0F18" fill-opacity="0.9" stroke="{colour}" stroke-opacity="0.4" />'
        f'<text class="mono" x="{num(x + width / 2)}" y="{num(y + 13.8)}" '
        f'text-anchor="middle" font-size="10.5" letter-spacing="1.2" fill="{colour}">'
        f"{esc(label)}</text></g>"
    )


def cubic_points(p0, p1, p2, p3, steps: int = 80) -> list[tuple[float, float]]:
    pts = []
    for i in range(steps + 1):
        t = i / steps
        mt = 1 - t
        x = mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
        y = mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
        pts.append((x, y))
    return pts


def path_length(points: list[tuple[float, float]]) -> float:
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


# Shared card


def starfield(
    free: list[tuple[float, float, float, float]],
) -> tuple[list[str], list[str]]:
    """Background gradient and nebula defs, plus the body: base, glows and seeded stars."""
    rng = random.Random(STAR_SEED)
    stars = []
    tries = 0
    while len(stars) < STARS and tries < STARS * 50:
        tries += 1
        x, y = rng.uniform(8, 1192), rng.uniform(8, 392)
        if any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in free):
            continue
        radius = rng.choice([0.55, 0.6, 0.7, 0.8, 0.9, 1.0, 1.15])
        stars.append((x, y, radius, rng.uniform(0.18, 0.6)))
    twinkling = [
        f'<circle class="tw tw{i % 4}" cx="{num(x)}" cy="{num(y)}" r="{num(r + 0.25)}" '
        f'fill="#DDF2FF" opacity="{o + 0.25:.2f}" '
        f'style="animation-delay:-{rng.uniform(0, 6):.1f}s" />'
        for i, (x, y, r, o) in enumerate(stars[:TWINKLING])
    ]
    plain = "".join(
        f'<circle cx="{num(x)}" cy="{num(y)}" r="{num(r)}" opacity="{o:.2f}" />'
        for x, y, r, o in stars[TWINKLING:]
    )
    defs = [
        '    <linearGradient id="spaceBg" x1="0" y1="0" x2="0.35" y2="1">',
        '      <stop offset="0" stop-color="#081020" />',
        f'      <stop offset="0.55" stop-color="{BG}" />',
        '      <stop offset="1" stop-color="#0B1424" />',
        "    </linearGradient>",
        *gradient(
            "radialGradient",
            'id="nebViolet" cx="0.5" cy="0.5" r="0.5"',
            [("0", VIOLET, "0.3"), ("1", VIOLET, "0")],
        ),
        *gradient(
            "radialGradient",
            'id="nebIndigo" cx="0.5" cy="0.5" r="0.5"',
            [("0", "#3B4BB8", "0.3"), ("1", "#3B4BB8", "0")],
        ),
    ]
    body = [
        '    <rect width="1200" height="400" fill="url(#spaceBg)" />',
        '    <ellipse cx="190" cy="-30" rx="520" ry="260" fill="url(#nebIndigo)" />',
        '    <ellipse cx="900" cy="430" rx="560" ry="300" fill="url(#nebViolet)" '
        'opacity="0.5" />',
        f'    <g fill="#CFE6FF">{plain}</g>',
        f'    <g>{"".join(twinkling)}</g>',
    ]
    return defs, body


def mark_symbols() -> list[str]:
    """The bucket and arrow from website/favicon.svg, without its tile."""
    return [
        *gradient(
            "linearGradient",
            'id="markStroke" x1="10" y1="12" x2="54" y2="54" gradientUnits="userSpaceOnUse"',
            [("0", "#29C7FF", ""), ("0.5", VIOLET, ""), ("1", ORANGE, "")],
        ),
        '    <symbol id="mark" viewBox="0 0 64 64">',
        '      <path d="M14 18c0-4 8-7 18-7s18 3 18 7-8 7-18 7-18-3-18-7Z" fill="none" '
        'stroke="url(#markStroke)" stroke-width="4" />',
        '      <path d="M14 18v20c0 4 8 7 18 7s18-3 18-7V18" fill="none" '
        'stroke="url(#markStroke)" stroke-width="4" stroke-linecap="round" />',
        '      <path d="M22 32h19m0 0-6-6m6 6-6 6" fill="none" stroke="#F5F8FC" '
        'stroke-width="4" stroke-linecap="round" stroke-linejoin="round" />',
        "    </symbol>",
    ]


def lockup() -> list[str]:
    return [
        '  <rect x="48.5" y="38.5" width="33" height="33" rx="8" fill="#0B1018" '
        'stroke="#3B4A5F" stroke-width="1.2" />',
        '  <use href="#mark" x="49" y="39" width="32" height="32" />',
        f'  <text class="sans" x="94" y="52.5" font-size="15" font-weight="600" '
        f'fill="{INK}">s3mirror</text>',
        f'  <text class="sans" x="94" y="69.5" font-size="12" fill="{INK_3}">'
        "netspeedy · S3 bucket mirroring</text>",
    ]


def headline(
    prefix: str, word: str, suffix: str, second: str
) -> tuple[list[str], list[str]]:
    """Two lines at 44px: line one with a highlighted word and an amber swash under it."""
    x = 46.0
    first = prefix + word + suffix
    start = x + ADVANCE[prefix]
    end = start + ADVANCE[word.rstrip(",.")]
    defs = [
        *gradient(
            "linearGradient",
            f'id="titleWhite" gradientUnits="userSpaceOnUse" x1="{num(x)}" y1="0" '
            f'x2="{num(x + ADVANCE[first])}" y2="0"',
            [("0", "#FFFFFF", ""), ("1", "#DCE6FF", "")],
        ),
        *gradient(
            "linearGradient",
            f'id="hl" gradientUnits="userSpaceOnUse" x1="{num(start)}" y1="0" '
            f'x2="{num(end)}" y2="0"',
            [("0", CYAN_2, ""), ("0.5", "#F4F7FA", ""), ("1", AMBER, "")],
        ),
        *gradient(
            "linearGradient",
            f'id="titleBrand" gradientUnits="userSpaceOnUse" x1="{num(x)}" y1="0" '
            f'x2="{num(x + ADVANCE[second])}" y2="0"',
            [("0", CYAN, ""), ("0.55", VIOLET_2, ""), ("1", ORANGE, "")],
        ),
        *gradient(
            "linearGradient",
            'id="uline" x1="0" y1="0" x2="1" y2="0"',
            [("0", AMBER, "0.35"), ("0.5", AMBER, ""), ("1", AMBER, "0.5")],
        ),
    ]
    span = end - start
    els = [
        f'  <text class="sans" x="{num(x)}" y="160" font-size="44" font-weight="800" '
        'letter-spacing="-1.3" xml:space="preserve">'
        f'<tspan fill="url(#titleWhite)">{esc(prefix)}</tspan>'
        f'<tspan fill="url(#hl)">{esc(word)}</tspan>'
        f'<tspan fill="url(#titleWhite)">{esc(suffix)}</tspan></text>',
        f'  <path d="M{num(start + 2)} 172.5q{num(span * 0.5)} -6.5 {num(span - 6)} -1.5" '
        'fill="none" stroke="url(#uline)" stroke-width="2.6" stroke-linecap="round" />',
        f'  <text class="sans" x="{num(x)}" y="212" font-size="44" font-weight="800" '
        f'letter-spacing="-1.3" fill="url(#titleBrand)">{esc(second)}</text>',
    ]
    return defs, els


def body(lines: list[list[tuple[str, bool]]]) -> list[str]:
    out = [
        f'  <text class="sans" font-size="15.5" fill="{INK_2}" xml:space="preserve">'
    ]
    for i, segments in enumerate(lines):
        spans = "".join(
            (
                f'<tspan class="mono" font-size="14" fill="{CYAN_2}">{esc(text)}</tspan>'
                if mono
                else esc(text)
            )
            for text, mono in segments
        )
        out.append(f'    <tspan x="48" y="{254 + 23 * i}">{spans}</tspan>')
    out.append("  </text>")
    return out


def meta_row(labels: list[str]) -> str:
    x = 48.0
    parts = []
    for i, label in enumerate(labels):
        if i:
            parts.append(
                f'<circle cx="{num(x + 9)}" cy="318.3" r="2.1" fill="{AMBER}" />'
            )
            x += 19
        parts.append(f'<text x="{num(x)}" y="322">{esc(label)}</text>')
        x += mono_width(len(label), 11.5, 1.5)
    return (
        f'  <g class="mono" font-size="11.5" letter-spacing="1.5" fill="{INK_3}">'
        f'{"".join(parts)}</g>'
    )


# Scene: lanes


class Bucket:
    """A tapered bucket seen from slightly above, drawn in dots like the s3ctl monolith."""

    def __init__(self, key, cx, colour, dot_colour, tint):
        self.key, self.cx = key, cx
        self.colour, self.dot_colour, self.tint = colour, dot_colour, tint
        self.top, self.rx0, self.rx1, self.depth, self.ry = (
            138.0,
            74.0,
            56.0,
            150.0,
            0.22,
        )
        self.bottom = self.top + self.depth

    def radius(self, t: float) -> float:
        return self.rx0 + (self.rx1 - self.rx0) * t / self.depth

    def surface(self, t: float, theta: float) -> tuple[float, float]:
        r = self.radius(t)
        return self.cx + r * math.sin(theta), self.top + t + r * self.ry * math.cos(
            theta
        )

    def silhouette(self) -> str:
        cx, top, bottom = self.cx, self.top, self.bottom
        rx0, rx1, ry = self.rx0, self.rx1, self.ry
        return (
            f"M{num(cx - rx0)} {num(top)}"
            f"A{num(rx0)} {num(rx0 * ry)} 0 0 1 {num(cx + rx0)} {num(top)}"
            f"L{num(cx + rx1)} {num(bottom)}"
            f"A{num(rx1)} {num(rx1 * ry)} 0 0 1 {num(cx - rx1)} {num(bottom)}Z"
        )

    def dots(self) -> str:
        points = []
        t = 8.5
        ring = 0
        while t <= self.depth:
            r = self.radius(t)
            count = int(2 * math.pi * r / 9.0)
            for q in range(count):
                theta = 2 * math.pi * (q + (ring & 1) * 0.5) / count
                c = math.cos(theta)
                if c <= 0.03:
                    continue
                x, y = self.surface(t, theta)
                band = 0 if c < 0.3 else 1 if c < 0.55 else 2 if c < 0.8 else 3
                points.append((x, y, band))
            t += 8.5
            ring += 1
        styles = {0: (0.2, 1.1), 1: (0.36, 1.3), 2: (0.52, 1.45), 3: (0.7, 1.55)}
        return dot_paths(points, styles, self.dot_colour)

    def objects(self, spots: list[tuple[float, float]]) -> str:
        """Objects resting in the bucket, as small outlined tiles."""
        return "".join(
            f'<rect x="{num(self.cx + ox - 5.5)}" y="{num(self.top + oy - 5.5)}" '
            f'width="11" height="11" rx="2.5" fill="{self.colour}" fill-opacity="0.16" '
            f'stroke="{self.colour}" stroke-opacity="0.55" />'
            for ox, oy in spots
        )

    def render(self, spots: list[tuple[float, float]]) -> str:
        sil = self.silhouette()
        return "".join(
            [
                f'<path d="{sil}" fill="url(#body_{self.key})" />',
                f'<path d="{sil}" fill="none" stroke="{self.colour}" stroke-opacity="0.35" '
                'stroke-width="1.2" />',
                f'<g clip-path="url(#clip_{self.key})">{self.dots()}'
                f"{self.objects(spots)}</g>",
                f'<ellipse cx="{num(self.cx)}" cy="{num(self.top)}" rx="{num(self.rx0)}" '
                f'ry="{num(self.rx0 * self.ry)}" fill="url(#mouth)" stroke="{self.colour}" '
                'stroke-width="2.4" />',
            ]
        )

    def defs(self) -> list[str]:
        return [
            *gradient(
                "linearGradient",
                f'id="body_{self.key}" x1="0" y1="0" x2="1" y2="0"',
                [("0", "#081322", ""), ("0.5", self.tint, ""), ("1", "#081322", "")],
            ),
            f'    <clipPath id="clip_{self.key}"><path d="{self.silhouette()}" /></clipPath>',
        ]


def scene_lanes() -> (
    tuple[list[str], str, str, list[tuple[float, float, float, float]]]
):
    """Source and destination buckets joined by parallel worker lanes, objects in flight.

    The lanes start and end inside the buckets, which are drawn over them, so objects slip
    out of the source and into the destination. Each lane runs at its own speed; one carries
    a multipart upload in three parts. Every object is drawn at a resting point along its
    lane for reduced motion, and pings where it enters the destination.
    """
    src = Bucket("src", 676.0, CYAN, "#CFEFFF", "#0C2236")
    dst = Bucket("dst", 1099.0, ORANGE, "#FFE2C2", "#2A1B10")
    lanes = 7
    mid = 222.0
    keyframes = []
    routes = []
    packets = []
    pings = []
    for k in range(lanes):
        y = 176 + k * 15.5
        p0 = (src.cx + 24, y)
        p3 = (dst.cx - 24, y)
        bundle = mid + (y - mid) * 0.38
        p1 = (812.0, bundle)
        p2 = (963.0, bundle)
        length = path_length(cubic_points(p0, p1, p2, p3))
        d = (
            f"M{num(p0[0])} {num(p0[1])}C{num(p1[0])} {num(p1[1])} {num(p2[0])} "
            f"{num(p2[1])} {num(p3[0])} {num(p3[1])}"
        )
        routes.append(
            f'<path d="{d}" fill="none" stroke="{VIOLET_2}" stroke-opacity="0.32" '
            'stroke-width="1.2" />'
        )
        multipart = k == 2
        colour = AMBER if multipart else (VIOLET_2 if k == 4 else CYAN)
        dur = 2.1 + (k * 0.37) % 1.3
        if multipart:
            dash, seg = f"6 3 6 3 6 {num(length + 24)}", 24
        else:
            dash, seg = f"10 {num(length + 10)}", 10
        keyframes.append(
            f"@keyframes ln{k}{{from{{stroke-dashoffset:{seg}}}"
            f"to{{stroke-dashoffset:{num(-length)}}}}}"
        )
        rest = -length * (0.2 + (k * 0.37 + 0.15) % 0.6)
        delay = -((k * 0.83) % dur)
        packets.append(
            f'<path d="{d}" fill="none" stroke="{colour}" stroke-width="6" '
            f'stroke-dasharray="{dash}" stroke-dashoffset="{num(rest)}" '
            f'style="animation:ln{k} {dur:.2f}s linear infinite;'
            f'animation-delay:{delay:.2f}s" />'
        )
        # The ping fires as the head of the object reaches the destination's wall. The
        # head travels length + seg over one cycle, and the lane's last stretch is flat.
        wall = dst.cx - dst.radius(y - dst.top)
        reach = (length - (p3[0] - wall)) / (length + seg)
        pings.append(
            f'<circle class="ping" cx="{num(wall + 2)}" cy="{num(y)}" r="2.6" '
            f'fill="none" stroke="{colour}" stroke-width="1.1" '
            f'style="animation-duration:{dur:.2f}s;'
            f'animation-delay:{delay + dur * reach:.2f}s" />'
        )
    css = "".join(keyframes) + (
        ".ping{transform-box:fill-box;transform-origin:center;opacity:0;"
        "animation:ping 2s ease-out infinite}"
        "@keyframes ping{0%{opacity:.9;transform:scale(1)}25%{opacity:0;"
        "transform:scale(4)}100%{opacity:0;transform:scale(4)}}"
    )
    labels = "".join(
        f'<text class="mono" x="{num(b.cx)}" y="340" text-anchor="middle" '
        f'font-size="10.5" letter-spacing="2" fill="{b.colour}">{name}</text>'
        for b, name in ((src, "SOURCE"), (dst, "DESTINATION"))
    )
    centre = (src.cx + dst.cx) / 2
    chips = chip(
        centre - chip_width("20 WORKERS") / 2, 168, "20 WORKERS", VIOLET_2
    ) + chip(centre - chip_width("MULTIPART") / 2, 258, "MULTIPART", AMBER)
    defs = [
        *gradient(
            "radialGradient",
            'id="mouth" cx="0.5" cy="0.62" r="0.6"',
            [("0", "#02060C", ""), ("0.7", "#061020", ""), ("1", "#0B2033", "")],
        ),
        *src.defs(),
        *dst.defs(),
        *gradient(
            "radialGradient",
            'id="aura" cx="0.5" cy="0.5" r="0.5"',
            [("0", VIOLET, "0.22"), ("0.6", VIOLET, "0.06"), ("1", VIOLET, "0")],
        ),
    ]
    scene = "".join(
        [
            f'<ellipse cx="{num(centre)}" cy="210" rx="330" ry="200" fill="url(#aura)" />',
            "".join(routes),
            "".join(packets),
            src.render([(-30, 52), (14, 74), (-18, 104), (30, 118)]),
            dst.render([(18, 56), (-14, 92), (26, 116)]),
            "".join(pings),
            chips,
            labels,
        ]
    )
    return defs, css, scene, [(600, 40, 1180, 360)]


# Copy

CARD = {
    "title": "s3mirror - no vendor lock-in, copy what changed",
    "desc": (
        "A cyan source bucket and an orange destination bucket drawn in dots, joined by "
        "seven parallel worker lanes carrying objects at different speeds, one of them a "
        "multipart upload, with a ping wherever an object lands."
    ),
    "headline": ("No ", "vendor", " lock-in.", "Copy what changed."),
    "body": [
        [("Buckets and objects between S3-compatible endpoints,", False)],
        [
            ("one config, clear logs. ", False),
            ("--no-delete", True),
            (" keeps it copy-only.", False),
        ],
    ],
    "meta": ["DISCOVER", "DIFF", "COPY", "PRUNE"],
    "scene": scene_lanes,
}


def build_svg(spec: dict = CARD) -> str:
    scene_defs, scene_css, scene, free = spec["scene"]()
    star_defs, star_body = starfield([COPY_BOX, *free])
    head_defs, head_els = headline(*spec["headline"])
    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 400" width="960" '
        'height="320" role="img" aria-labelledby="title desc">',
        f'  <title id="title">{esc(spec["title"])}</title>',
        f'  <desc id="desc">{esc(spec["desc"])}</desc>',
        "",
        "  <defs>",
        "    <style>",
        "      /* Inter and JetBrains Mono, SIL Open Font License 1.1, subset to the "
        "glyphs used here. */",
        "      __FONT_FACES__",
        f"      {FONT_CSS}",
        f"      {TWINKLE_CSS}",
        f"      {scene_css}",
        "      @media (prefers-reduced-motion: reduce){",
        "        *{animation:none !important}",
        "      }",
        "    </style>",
        *star_defs,
        *mark_symbols(),
        *head_defs,
        *scene_defs,
        '    <clipPath id="frame"><rect x="1" y="1" width="1198" height="398" rx="20" />'
        "</clipPath>",
        "  </defs>",
        "",
        '  <g clip-path="url(#frame)">',
        *star_body,
        f"    {scene}",
        "  </g>",
        '  <rect x="0.75" y="0.75" width="1198.5" height="398.5" rx="20" fill="none" '
        'stroke="#1A2638" stroke-width="1.5" />',
        "",
        "  <!-- Left: brand and headline -->",
        *lockup(),
        "",
        *head_els,
        *body(spec["body"]),
        meta_row(spec["meta"]),
        "</svg>",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    svg = build_svg()
    svg = svg.replace("__FONT_FACES__", font_faces(svg))
    if "http://" in svg.replace("http://www.w3.org/2000/svg", "") or "https://" in svg:
        raise SystemExit("external reference found in the hero SVG")
    ET.fromstring(svg)  # well-formed, or this raises
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(svg, encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)} ({len(svg.encode()) / 1024:.1f} KiB)")


if __name__ == "__main__":
    main()
