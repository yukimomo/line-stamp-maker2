"""
Stamp template implementations.

Each template:
  - Takes a circular RGBA photo + caption string
  - Returns a final RGBA stamp image (fits within 370×320 LINE spec)
  - Uses pure Pillow + NumPy

Canvas layout (shared across templates):
  Width=320, Height=310  →  fits in LINE max 370×320
  Circle center: (160, 130)
  Circle diam: 220 px
  Text zone: y ≈ 255-300
"""

from __future__ import annotations
import math
import random
from typing import Callable

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .circle_crop import add_circle_border
from .text_styles import add_caption, TEXT_STYLES

# ---------------------------------------------------------------------------
# Canvas constants
# ---------------------------------------------------------------------------

CANVAS_W = 320
CANVAS_H = 310
CIRCLE_DIAM = 220          # diameter of the circular photo
CIRCLE_CX = CANVAS_W // 2  # 160
CIRCLE_CY = 128            # vertical center of circle


# ---------------------------------------------------------------------------
# Template registry
# ---------------------------------------------------------------------------

TEMPLATES: dict[str, str] = {
    "simple_circle":   "シンプル丸（白フチ・影）",
    "pop_star":        "ポップスター（星・キラキラ）",
    "heart":           "ハート（かわいい・ピンク）",
    "speech_bubble":   "吹き出し（セリフ枠付き）",
    "birthday":        "バースデー（カラフル・お祝い）",
    "seasonal_sakura": "桜（和風・春モチーフ）",
    "cool_badge":      "バッジ（スタイリッシュ）",
}


def apply_template(
    circle_img: Image.Image,
    template: str,
    caption: str = "",
    text_style: str = "pop",
    seed: int | None = None,
) -> Image.Image:
    """
    Render a complete LINE stamp image from a circular photo + template.

    Args:
        circle_img:  RGBA circular photo (output of circle_crop).
        template:    Key from TEMPLATES dict.
        caption:     Text to write on the stamp.
        text_style:  Key from TEXT_STYLES.
        seed:        RNG seed for reproducible decoration placement.
    """
    if seed is not None:
        random.seed(seed)
        np.random.seed(seed)

    fn = _DISPATCH.get(template, _tmpl_simple_circle)
    result = fn(circle_img, caption, text_style)

    # Guarantee within LINE spec
    if result.width > 370 or result.height > 320:
        result.thumbnail((370, 320), Image.Resampling.LANCZOS)
    return result


def auto_select_template(photo_metadata: dict | None = None) -> str:
    """Heuristic template selection from photo-selector analysis metadata."""
    if not photo_metadata:
        return "simple_circle"

    analysis = photo_metadata.get("analysis") or {}
    tags = {t.lower() for t in analysis.get("tags", [])}
    caption = analysis.get("caption", "").lower()

    def _match(words: set[str]) -> bool:
        """True if any word is in tags OR appears as a substring of caption."""
        return bool(tags & words) or any(w in caption for w in words)

    if _match({"birthday", "cake", "party", "celebrate", "誕生", "お祝い"}):
        return "birthday"

    if _match({"sakura", "cherry", "blossom", "spring", "桜", "春"}):
        return "seasonal_sakura"

    if _match({"smile", "happy", "cute", "love", "heart", "笑顔"}):
        return random.choice(["pop_star", "heart"])

    if _match({"group", "family", "friends", "multiple", "家族"}):
        return "simple_circle"

    return "simple_circle"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _canvas() -> Image.Image:
    return Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))


def _paste_circle(
    canvas: Image.Image,
    circle_img: Image.Image,
    white_px: int = 14,
    black_px: int = 3,
    shadow: bool = True,
    border_color: tuple[int, int, int] = (255, 255, 255),
    cy_override: int | None = None,
) -> None:
    """Add border+shadow to circle and paste at the standard position."""
    decorated, pad = add_circle_border(
        circle_img,
        white_px=white_px,
        black_px=black_px,
        shadow=shadow,
        border_color=border_color,
    )
    cy = cy_override if cy_override is not None else CIRCLE_CY
    dx = CIRCLE_CX - (decorated.width // 2)
    dy = cy - (decorated.height // 2)
    canvas.paste(decorated, (dx, dy), decorated)


def _gradient_v(
    size: tuple[int, int],
    color1: tuple[int, int, int, int],
    color2: tuple[int, int, int, int],
) -> Image.Image:
    """Vertical linear gradient (RGBA)."""
    w, h = size
    t = np.linspace(0, 1, h)[:, None]          # (h,1)
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    for c in range(4):
        arr[:, :, c] = (color1[c] * (1 - t) + color2[c] * t).astype(np.uint8)
    return Image.fromarray(arr)


def _radial_gradient(
    size: tuple[int, int],
    center_color: tuple[int, int, int, int],
    edge_color: tuple[int, int, int, int],
) -> Image.Image:
    """Radial gradient centered in the canvas (RGBA)."""
    w, h = size
    x = np.linspace(-1, 1, w)[None, :]          # (1,w)
    y = np.linspace(-1, 1, h)[:, None]          # (h,1)
    d = np.clip(np.sqrt(x ** 2 + y ** 2), 0, 1)
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    for c in range(4):
        arr[:, :, c] = (
            center_color[c] * (1 - d) + edge_color[c] * d
        ).clip(0, 255).astype(np.uint8)
    return Image.fromarray(arr)


def _star(
    draw: ImageDraw.ImageDraw,
    cx: float, cy: float,
    outer_r: float, inner_r: float,
    color: tuple,
    n: int = 5,
) -> None:
    pts = []
    for i in range(n * 2):
        r = outer_r if i % 2 == 0 else inner_r
        angle = math.pi * i / n - math.pi / 2
        pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    draw.polygon(pts, fill=color)


def _heart(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float, color: tuple) -> None:
    s = size
    draw.ellipse([cx - s, cy - s / 2, cx,     cy + s / 2], fill=color)
    draw.ellipse([cx,     cy - s / 2, cx + s, cy + s / 2], fill=color)
    draw.polygon([(cx - s, cy + s / 4), (cx + s, cy + s / 4), (cx, cy + s * 1.4)],
                 fill=color)


def _sparkle(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, color: tuple) -> None:
    _star(draw, cx, cy, r, r * 0.3, color, n=4)
    _star(draw, cx, cy, r * 0.5, r * 0.15, (255, 255, 255, 180), n=4)


def _sakura_petal(
    draw: ImageDraw.ImageDraw,
    cx: float, cy: float,
    petal_r: float,
    angle: float,
    color: tuple,
) -> None:
    """One cherry-blossom petal (ellipse offset at angle)."""
    dist = petal_r * 0.9
    px = cx + dist * math.cos(angle)
    py = cy + dist * math.sin(angle)
    # Rotate a narrow ellipse (approximate with polygon)
    pts = []
    w2, h2 = petal_r * 0.55, petal_r
    for theta in np.linspace(0, 2 * math.pi, 12):
        lx = w2 * math.cos(theta)
        ly = h2 * math.sin(theta)
        rx = lx * math.cos(angle) - ly * math.sin(angle) + px
        ry = lx * math.sin(angle) + ly * math.cos(angle) + py
        pts.append((rx, ry))
    draw.polygon(pts, fill=color)


def _draw_sakura(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, color: tuple) -> None:
    """Full 5-petal sakura flower."""
    for i in range(5):
        angle = 2 * math.pi * i / 5 - math.pi / 2
        _sakura_petal(draw, cx, cy, r, angle, color)
    draw.ellipse([cx - r * 0.2, cy - r * 0.2, cx + r * 0.2, cy + r * 0.2],
                 fill=(255, 210, 220, 220))


def _confetti_rect(draw: ImageDraw.ImageDraw, x: float, y: float, w: float, h: float,
                   color: tuple, angle: float) -> None:
    """Draw a rotated confetti rectangle."""
    pts = [(-w/2, -h/2), (w/2, -h/2), (w/2, h/2), (-w/2, h/2)]
    rotated = [
        (x + p[0]*math.cos(angle) - p[1]*math.sin(angle),
         y + p[0]*math.sin(angle) + p[1]*math.cos(angle))
        for p in pts
    ]
    draw.polygon(rotated, fill=color)


# ---------------------------------------------------------------------------
# Template implementations
# ---------------------------------------------------------------------------

def _tmpl_simple_circle(
    circle: Image.Image, caption: str, text_style: str
) -> Image.Image:
    """Simple circle: white border, shadow, transparent background."""
    canvas = _canvas()
    _paste_circle(canvas, circle, white_px=14, black_px=3, shadow=True)
    if caption:
        canvas = add_caption(canvas, caption, style=text_style)
    return canvas


def _tmpl_pop_star(
    circle: Image.Image, caption: str, text_style: str
) -> Image.Image:
    """Yellow-orange gradient, large stars, sparkles."""
    canvas = _canvas()

    # Gradient background
    bg = _radial_gradient(
        (CANVAS_W, CANVAS_H),
        (255, 240, 30, 210), (255, 110, 0, 180),
    )
    canvas = Image.alpha_composite(canvas, bg)
    draw = ImageDraw.Draw(canvas)

    # Large stars (behind circle)
    star_positions = [
        (45,  45,  28, 12, (255, 220, 0, 230)),
        (275, 40,  24, 10, (255, 200, 20, 220)),
        (30,  220, 20, 8,  (255, 230, 50, 200)),
        (288, 225, 22, 9,  (255, 210, 0, 220)),
        (155, 18,  16, 6,  (255, 240, 80, 200)),
    ]
    for sx, sy, sr, si, sc in star_positions:
        _star(draw, sx, sy, sr, si, sc, n=5)

    # Sparkles
    for spx, spy in [(70, 90), (248, 85), (55, 175), (270, 170), (160, 255)]:
        _sparkle(draw, spx, spy, 9, (255, 255, 255, 200))

    _paste_circle(canvas, circle, white_px=12, black_px=0, shadow=True)
    if caption:
        canvas = add_caption(canvas, caption, style="pop")
    return canvas


def _tmpl_heart(
    circle: Image.Image, caption: str, text_style: str
) -> Image.Image:
    """Pink gradient, hearts, soft pink border."""
    canvas = _canvas()

    bg = _gradient_v(
        (CANVAS_W, CANVAS_H),
        (255, 200, 220, 180), (255, 160, 200, 200),
    )
    canvas = Image.alpha_composite(canvas, bg)
    draw = ImageDraw.Draw(canvas)

    # Hearts (behind circle)
    heart_params = [
        (40,  50,  20, (255, 80, 130, 210)),
        (278, 48,  18, (255, 100, 150, 200)),
        (25,  200, 14, (255, 120, 160, 190)),
        (290, 205, 16, (255, 90,  140, 200)),
        (155, 20,  12, (255, 150, 180, 180)),
        (60,  250, 10, (255, 100, 140, 170)),
        (255, 255, 10, (255, 110, 150, 180)),
    ]
    for hx, hy, hs, hc in heart_params:
        _heart(draw, hx, hy, hs, hc)

    _paste_circle(canvas, circle, white_px=12, black_px=3,
                  shadow=True, border_color=(255, 220, 230))
    if caption:
        canvas = add_caption(canvas, caption, style=text_style)
    return canvas


def _tmpl_speech_bubble(
    circle: Image.Image, caption: str, text_style: str
) -> Image.Image:
    """Circle at top + large speech bubble below (text inside bubble)."""
    canvas = _canvas()

    # Place circle higher than usual
    _paste_circle(canvas, circle, white_px=12, black_px=3, shadow=True, cy_override=105)

    # Speech bubble covering the lower portion
    bx, by, bw, bh = 30, 195, 260, 80
    tail_cx = CANVAS_W // 2
    bubble_layer = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bubble_layer)

    bd.rounded_rectangle(
        [bx, by, bx + bw, by + bh],
        radius=20,
        fill=(255, 255, 255, 240),
        outline=(30, 30, 30, 255),
        width=4,
    )
    # Tail pointing up to circle
    tail_top = by - 18
    bd.polygon(
        [(tail_cx - 12, by + 1), (tail_cx + 12, by + 1), (tail_cx, tail_top)],
        fill=(255, 255, 255, 240),
    )
    bd.line([(tail_cx - 12, by), (tail_cx, tail_top)], fill=(30, 30, 30, 255), width=4)
    bd.line([(tail_cx + 12, by), (tail_cx, tail_top)], fill=(30, 30, 30, 255), width=4)

    canvas = Image.alpha_composite(canvas, bubble_layer)

    # Text inside bubble
    if caption:
        from .text_styles import load_font, auto_font_size, _draw_outlined_text
        font_size = auto_font_size(caption, bw - 20, base_size=36)
        font = load_font(font_size)
        draw2 = ImageDraw.Draw(canvas)
        tb = draw2.textbbox((0, 0), caption, font=font)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        tx = bx + (bw - tw) // 2
        ty = by + (bh - th) // 2
        _draw_outlined_text(draw2, (tx, ty), caption, font,
                            fill=(20, 20, 20, 255),
                            stroke_fill=(255, 255, 255, 180),
                            stroke_width=2)
    return canvas


def _tmpl_birthday(
    circle: Image.Image, caption: str, text_style: str
) -> Image.Image:
    """Colorful gradient + confetti + balloon decorations."""
    canvas = _canvas()

    bg = _gradient_v(
        (CANVAS_W, CANVAS_H),
        (255, 230, 80, 190), (255, 100, 180, 200),
    )
    canvas = Image.alpha_composite(canvas, bg)
    draw = ImageDraw.Draw(canvas)

    # Confetti (rotated rectangles)
    conf_colors = [
        (255, 60, 60, 220), (60, 200, 60, 220), (60, 60, 255, 220),
        (255, 210, 30, 220), (200, 60, 200, 220), (30, 200, 200, 220),
    ]
    rng = random.Random(42)
    for _ in range(28):
        cx = rng.randint(10, CANVAS_W - 10)
        cy = rng.randint(10, CANVAS_H - 10)
        col = rng.choice(conf_colors)
        w_ = rng.randint(6, 14)
        h_ = rng.randint(4, 8)
        ang = rng.uniform(0, math.pi)
        _confetti_rect(draw, cx, cy, w_, h_, col, ang)

    # Balloon shapes (ellipses)
    balloons = [
        (52, 85, 22, 28, (255, 80, 80, 190)),
        (268, 88, 20, 26, (80, 130, 255, 190)),
        (40, 200, 16, 20, (255, 200, 30, 190)),
    ]
    for bx_, by_, brx, bry, bc in balloons:
        draw.ellipse([bx_ - brx, by_ - bry, bx_ + brx, by_ + bry], fill=bc)
        draw.line([(bx_, by_ + bry), (bx_ + 5, by_ + bry + 20)],
                  fill=(100, 100, 100, 180), width=2)

    _paste_circle(canvas, circle, white_px=12, black_px=4,
                  shadow=True, border_color=(255, 240, 80))
    if caption:
        canvas = add_caption(canvas, caption, style="pop")
    return canvas


def _tmpl_seasonal_sakura(
    circle: Image.Image, caption: str, text_style: str
) -> Image.Image:
    """Light pink background + scattered sakura blossoms."""
    canvas = _canvas()

    bg = _gradient_v(
        (CANVAS_W, CANVAS_H),
        (255, 235, 240, 200), (255, 200, 215, 210),
    )
    canvas = Image.alpha_composite(canvas, bg)
    draw = ImageDraw.Draw(canvas)

    # Sakura flowers
    sakura_params = [
        (45,  50,  22, (255, 183, 197, 210)),
        (272, 45,  20, (255, 175, 185, 210)),
        (28,  210, 16, (255, 190, 200, 200)),
        (286, 208, 18, (255, 180, 192, 200)),
        (155, 18,  14, (255, 185, 198, 190)),
        (70,  265, 12, (255, 178, 190, 185)),
        (248, 262, 12, (255, 182, 195, 185)),
    ]
    for sx, sy, sr, sc in sakura_params:
        _draw_sakura(draw, sx, sy, sr, sc)

    # Petals floating (single petals)
    petal_positions = [(100, 30), (210, 25), (35, 130), (285, 130)]
    for px_, py_ in petal_positions:
        angle = random.uniform(0, 2 * math.pi)
        _sakura_petal(draw, px_, py_, 9, angle, (255, 190, 205, 170))

    _paste_circle(canvas, circle, white_px=12, black_px=3,
                  shadow=True, border_color=(255, 220, 228))
    if caption:
        canvas = add_caption(canvas, caption, style=text_style)
    return canvas


def _tmpl_cool_badge(
    circle: Image.Image, caption: str, text_style: str
) -> Image.Image:
    """Dark gradient, thick colored ring, badge aesthetic."""
    canvas = _canvas()

    bg = _gradient_v(
        (CANVAS_W, CANVAS_H),
        (30, 30, 50, 220), (20, 20, 60, 230),
    )
    canvas = Image.alpha_composite(canvas, bg)
    draw = ImageDraw.Draw(canvas)

    # Outer decorative ring (thick, gold)
    ring_r = CIRCLE_DIAM // 2 + 28
    cx, cy = CIRCLE_CX, CIRCLE_CY
    draw.ellipse(
        [cx - ring_r, cy - ring_r, cx + ring_r - 1, cy + ring_r - 1],
        outline=(220, 180, 40, 255), width=6,
    )
    # Dashed effect: small dots on the ring
    for i in range(24):
        angle = 2 * math.pi * i / 24
        dx = cx + ring_r * math.cos(angle)
        dy = cy + ring_r * math.sin(angle)
        draw.ellipse([dx - 3, dy - 3, dx + 3, dy + 3], fill=(255, 210, 60, 200))

    # Secondary ring (thin, white)
    ring2_r = ring_r + 10
    draw.ellipse(
        [cx - ring2_r, cy - ring2_r, cx + ring2_r - 1, cy + ring2_r - 1],
        outline=(255, 255, 255, 120), width=2,
    )

    _paste_circle(canvas, circle, white_px=10, black_px=4,
                  shadow=False, border_color=(220, 180, 40))

    if caption:
        # White text on dark background
        canvas = add_caption(canvas, caption, style="outline_white")
    return canvas


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_DISPATCH: dict[str, Callable] = {
    "simple_circle":   _tmpl_simple_circle,
    "pop_star":        _tmpl_pop_star,
    "heart":           _tmpl_heart,
    "speech_bubble":   _tmpl_speech_bubble,
    "birthday":        _tmpl_birthday,
    "seasonal_sakura": _tmpl_seasonal_sakura,
    "cool_badge":      _tmpl_cool_badge,
}
