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
    "group_badge":     "グループ（複数人・横長）",
    "action_pop":      "アクション（効果線・躍動感）",
    "bright_frame":    "ブライト（暗め写真向け・明るい枠）",
    "soft_pastel":     "ソフトパステル（やわらか・家族向け）",
}

# Per-template framing hints for face-centered cropping.
#   target_face_frac: desired face height as fraction of crop side (bigger=closer)
#   zoom:             default zoom multiplier
ZOOM_PRESETS: dict[str, dict[str, float]] = {
    "simple_circle":   {"target_face_frac": 0.45, "zoom": 1.0},
    "pop_star":        {"target_face_frac": 0.50, "zoom": 1.0},
    "heart":           {"target_face_frac": 0.48, "zoom": 1.0},
    "speech_bubble":   {"target_face_frac": 0.38, "zoom": 1.0},   # leave room for bubble
    "birthday":        {"target_face_frac": 0.44, "zoom": 1.0},
    "seasonal_sakura": {"target_face_frac": 0.44, "zoom": 1.0},
    "cool_badge":      {"target_face_frac": 0.46, "zoom": 1.0},
    "group_badge":     {"target_face_frac": 0.30, "zoom": 0.85},   # wide, fit everyone
    "action_pop":      {"target_face_frac": 0.50, "zoom": 1.05},
    "bright_frame":    {"target_face_frac": 0.46, "zoom": 1.0},
    "soft_pastel":     {"target_face_frac": 0.44, "zoom": 1.0},
}


def zoom_preset(template: str) -> dict[str, float]:
    return ZOOM_PRESETS.get(template, ZOOM_PRESETS["simple_circle"])


# Frame overrides for the current render, consumed by _paste_circle.
# Set/cleared by apply_template so all 11 templates honor them without
# changing their individual signatures (keeps preview == output).
_FRAME_OVERRIDE: dict | None = None


def apply_template(
    circle_img: Image.Image,
    template: str,
    caption: str = "",
    text_style: str = "pop",
    seed: int | None = None,
    overrides: dict | None = None,
    decorations: list[dict] | None = None,
) -> Image.Image:
    """
    Render a complete LINE stamp image from a circular photo + template.

    Args:
        circle_img:  RGBA circular photo (output of circle_crop).
        template:    Key from TEMPLATES dict.
        caption:     Text to write on the stamp.
        text_style:  Key from TEXT_STYLES.
        seed:        RNG seed for reproducible decoration placement.
        overrides:   Optional design overrides (text + frame fields).
        decorations: Optional list of decoration parts to draw on top.

    The SAME function is used by both live preview and final generation, so
    customized output always matches the preview.
    """
    global _FRAME_OVERRIDE
    if seed is not None:
        random.seed(seed)
        np.random.seed(seed)

    fn = _DISPATCH.get(template, _tmpl_simple_circle)
    has_text_override = bool(overrides) and any(
        k in overrides for k in ("text_color", "stroke_color", "stroke_width", "shadow",
                                  "shadow_color", "font", "font_size", "text_pos",
                                  "text_y", "align")
    )

    _FRAME_OVERRIDE = overrides or None
    try:
        # If text is customized, render the template WITHOUT its built-in caption
        # and draw the caption centrally so overrides apply on every template.
        tmpl_caption = "" if has_text_override else caption
        result = fn(circle_img, tmpl_caption, text_style)
    finally:
        _FRAME_OVERRIDE = None

    # Decorations layer (on top of frame/background, below/over text as added)
    if decorations:
        result = _draw_decorations(result, decorations)

    # Central caption when customized
    if has_text_override and caption:
        result = add_caption(result, caption, style=text_style, overrides=overrides)

    if result.width > 370 or result.height > 320:
        result.thumbnail((370, 320), Image.Resampling.LANCZOS)
    return result


def auto_select_template(
    photo_metadata: dict | None = None,
    face_count: int | None = None,
    is_dark: bool | None = None,
) -> str:
    """
    Heuristic template selection from analysis metadata + optional signals.

    Args:
        photo_metadata: photo dict with "analysis" {tags, caption, risks}.
        face_count:     number of detected faces (from face_detect), if known.
        is_dark:        whether the photo is dark (from risks or measurement).

    Priority:
        dark photo        → bright_frame
        multiple people   → group_badge
        movement/action   → action_pop
        birthday/お祝い    → birthday
        桜/spring          → seasonal_sakura
        smile/happy/cute  → pop_star / heart
        calm/quiet        → simple_circle / cool_badge / soft_pastel
    """
    analysis = (photo_metadata or {}).get("analysis") or {}
    tags = {t.lower() for t in analysis.get("tags", [])}
    caption = (analysis.get("caption") or "").lower()
    risks = analysis.get("risks") or {}

    def _match(words: set[str]) -> bool:
        return bool(tags & words) or any(w in caption for w in words)

    # ── dark / backlit ──
    dark = is_dark if is_dark is not None else bool(risks.get("dark"))
    if dark:
        return "bright_frame"

    # ── multiple people ──
    multi = (face_count is not None and face_count >= 2) or _match(
        {"group", "family", "friends", "multiple", "people", "crowd", "家族", "集合"}
    )
    if multi:
        return "group_badge"

    # ── movement / action ──
    if _match({"movement", "running", "jump", "action", "sport", "play", "dance",
               "走", "ジャンプ", "動き"}):
        return "action_pop"

    # ── events ──
    if _match({"birthday", "cake", "party", "celebrate", "誕生", "お祝い"}):
        return "birthday"
    if _match({"sakura", "cherry", "blossom", "spring", "桜", "春"}):
        return "seasonal_sakura"

    # ── mood ──
    if _match({"smile", "happy", "cute", "love", "heart", "fun", "笑顔", "楽し"}):
        return random.choice(["pop_star", "heart"])
    if _match({"baby", "child", "kid", "soft", "gentle", "赤ちゃん", "子ども", "家族"}):
        return "soft_pastel"
    if _match({"calm", "cool", "serious", "quiet", "落ち着"}):
        return random.choice(["simple_circle", "cool_badge"])

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
    """Add border+shadow to circle and paste at the standard position.

    Honors _FRAME_OVERRIDE (frame_color/frame_width/outer_color/outer_width/
    frame_shadow/shadow_strength) set by apply_template for the current render.
    """
    ov = _FRAME_OVERRIDE or {}
    black_color = (0, 0, 0)
    shadow_alpha = 70
    if "frame_color" in ov and ov["frame_color"] is not None:
        border_color = tuple(int(x) for x in ov["frame_color"])
    if ov.get("frame_width") is not None:
        white_px = max(0, int(ov["frame_width"]))
    if ov.get("outer_width") is not None:
        black_px = max(0, int(ov["outer_width"]))
    if "outer_color" in ov and ov["outer_color"] is not None:
        black_color = tuple(int(x) for x in ov["outer_color"])
    if ov.get("frame_shadow") is not None:
        shadow = bool(ov["frame_shadow"])
    if ov.get("shadow_strength") is not None:
        shadow_alpha = max(0, min(255, int(ov["shadow_strength"])))

    decorated, pad = add_circle_border(
        circle_img,
        white_px=white_px,
        black_px=black_px,
        shadow=shadow,
        shadow_alpha=shadow_alpha,
        border_color=border_color,
        black_color=black_color,
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
# Decoration parts (user-editable overlays)
# ---------------------------------------------------------------------------

# Available decoration types for the UI
DECORATIONS: dict[str, str] = {
    "heart":         "ハート",
    "star":          "星",
    "sparkle":       "キラキラ",
    "speech_bubble": "吹き出し",
    "ribbon":        "リボン",
    "flower":        "花",
}


def _deco_speech_bubble(draw, cx, cy, size, color):
    w = size * 1.6
    h = size
    draw.rounded_rectangle([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2],
                           radius=size * 0.3, fill=color)
    draw.polygon([(cx - size * 0.2, cy + h / 2), (cx + size * 0.2, cy + h / 2),
                  (cx - size * 0.1, cy + h / 2 + size * 0.5)], fill=color)


def _deco_ribbon(draw, cx, cy, size, color):
    s = size
    draw.polygon([(cx, cy), (cx - s, cy - s * 0.6), (cx - s, cy + s * 0.6)], fill=color)
    draw.polygon([(cx, cy), (cx + s, cy - s * 0.6), (cx + s, cy + s * 0.6)], fill=color)
    draw.ellipse([cx - s * 0.28, cy - s * 0.28, cx + s * 0.28, cy + s * 0.28], fill=color)


def _draw_decorations(img: Image.Image, parts: list[dict]) -> Image.Image:
    """
    Draw user decoration parts on top of *img*.

    Each part: {type, x, y (0..1), size (px), rotation (deg), color [r,g,b], visible}.
    Rendered to a small layer then rotated, so rotation works for every shape.
    """
    W, H = img.size
    base = img.convert("RGBA")
    for part in parts:
        if part.get("visible") is False:
            continue
        ptype = part.get("type")
        if ptype not in DECORATIONS:
            continue
        size = float(part.get("size", 28))
        rot = float(part.get("rotation", 0))
        color = tuple(int(c) for c in part.get("color", [255, 90, 120]))[:3]
        rgba = (*color, int(part.get("alpha", 230)))
        cx = float(part.get("x", 0.5)) * W
        cy = float(part.get("y", 0.5)) * H

        box = int(size * 3) + 8
        layer = Image.new("RGBA", (box, box), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        lc = box / 2
        if ptype == "heart":
            _heart(d, lc, lc, size, rgba)
        elif ptype == "star":
            _star(d, lc, lc, size, size * 0.42, rgba, n=5)
        elif ptype == "sparkle":
            _sparkle(d, lc, lc, size, rgba)
        elif ptype == "flower":
            _draw_sakura(d, lc, lc, size, rgba)
        elif ptype == "speech_bubble":
            _deco_speech_bubble(d, lc, lc, size, rgba)
        elif ptype == "ribbon":
            _deco_ribbon(d, lc, lc, size, rgba)

        if rot:
            layer = layer.rotate(rot, resample=Image.BICUBIC, expand=False)
        base.alpha_composite(layer, (int(cx - box / 2), int(cy - box / 2)))
    return base


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


def _tmpl_group_badge(
    circle: Image.Image, caption: str, text_style: str
) -> Image.Image:
    """
    Wide layout for group photos: the circle is shown larger and the badge ring
    is wider, so multiple faces remain legible. Neutral teal background.
    """
    canvas = _canvas()
    bg = _gradient_v((CANVAS_W, CANVAS_H), (70, 170, 175, 200), (40, 120, 140, 215))
    canvas = Image.alpha_composite(canvas, bg)
    draw = ImageDraw.Draw(canvas)

    # Soft outer ring to frame the (larger) group circle
    ring_r = CIRCLE_DIAM // 2 + 20
    cx, cy = CIRCLE_CX, CIRCLE_CY
    draw.ellipse([cx - ring_r, cy - ring_r, cx + ring_r - 1, cy + ring_r - 1],
                 outline=(255, 255, 255, 200), width=5)

    # "人数を活かす" — slightly thinner border so face area is maximized
    _paste_circle(canvas, circle, white_px=10, black_px=3,
                  shadow=True, border_color=(255, 255, 255))
    if caption:
        canvas = add_caption(canvas, caption, style="pop")
    return canvas


def _tmpl_action_pop(
    circle: Image.Image, caption: str, text_style: str
) -> Image.Image:
    """Manga-style concentration lines radiating from the subject + bold text."""
    canvas = _canvas()
    bg = _radial_gradient((CANVAS_W, CANVAS_H), (255, 255, 255, 200), (255, 230, 120, 210))
    canvas = Image.alpha_composite(canvas, bg)
    draw = ImageDraw.Draw(canvas)

    # Concentration lines from center outward
    cx, cy = CIRCLE_CX, CIRCLE_CY
    inner_r = CIRCLE_DIAM // 2 + 6
    outer_r = max(CANVAS_W, CANVAS_H)
    rng = random.Random(7)
    n = 36
    for i in range(n):
        a = 2 * math.pi * i / n + rng.uniform(-0.03, 0.03)
        x1 = cx + inner_r * math.cos(a)
        y1 = cy + inner_r * math.sin(a)
        x2 = cx + outer_r * math.cos(a)
        y2 = cy + outer_r * math.sin(a)
        wdt = rng.choice([2, 3, 4])
        draw.line([(x1, y1), (x2, y2)], fill=(40, 40, 40, 200), width=wdt)

    _paste_circle(canvas, circle, white_px=12, black_px=5, shadow=True)
    if caption:
        canvas = add_caption(canvas, caption, style="pop")
    return canvas


def _tmpl_bright_frame(
    circle: Image.Image, caption: str, text_style: str
) -> Image.Image:
    """
    For dark / backlit photos: bright warm background + extra-thick white border
    so a dim subject still stands out.
    """
    canvas = _canvas()
    bg = _radial_gradient((CANVAS_W, CANVAS_H), (255, 252, 235, 255), (255, 226, 150, 235))
    canvas = Image.alpha_composite(canvas, bg)
    draw = ImageDraw.Draw(canvas)

    # Glow ring behind subject
    glow_r = CIRCLE_DIAM // 2 + 22
    cx, cy = CIRCLE_CX, CIRCLE_CY
    glow = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse(
        [cx - glow_r, cy - glow_r, cx + glow_r - 1, cy + glow_r - 1],
        fill=(255, 255, 220, 180),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(10))
    canvas = Image.alpha_composite(canvas, glow)

    # Extra-thick white border
    _paste_circle(canvas, circle, white_px=20, black_px=3, shadow=True)
    if caption:
        canvas = add_caption(canvas, caption, style="pop")
    return canvas


def _tmpl_soft_pastel(
    circle: Image.Image, caption: str, text_style: str
) -> Image.Image:
    """Gentle pastel background with soft dots — for family / kids photos."""
    canvas = _canvas()
    bg = _gradient_v((CANVAS_W, CANVAS_H), (220, 240, 255, 205), (255, 235, 245, 215))
    canvas = Image.alpha_composite(canvas, bg)
    draw = ImageDraw.Draw(canvas)

    # Soft polka dots
    rng = random.Random(11)
    dot_colors = [(255, 210, 225, 150), (210, 235, 255, 150), (255, 240, 200, 150)]
    for _ in range(18):
        dx = rng.randint(10, CANVAS_W - 10)
        dy = rng.randint(10, CANVAS_H - 10)
        r = rng.randint(6, 14)
        draw.ellipse([dx - r, dy - r, dx + r, dy + r], fill=rng.choice(dot_colors))

    _paste_circle(canvas, circle, white_px=14, black_px=0,
                  shadow=True, border_color=(255, 248, 252))
    if caption:
        canvas = add_caption(canvas, caption, style="bubble")
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
    "group_badge":     _tmpl_group_badge,
    "action_pop":      _tmpl_action_pop,
    "bright_frame":    _tmpl_bright_frame,
    "soft_pastel":     _tmpl_soft_pastel,
}
