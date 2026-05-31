"""
Built-in design presets that raise the visual polish of a whole set.

Each preset bundles background / frame / text colors, a decoration style,
a recommended font, text placement, and a suggested caption category. A preset
produces (overrides, decorations) that flow through the SAME apply_template
path used by preview and generation, so preview == output is preserved.
"""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class PresetConfig:
    label: str
    icon: str
    base_template: str                      # underlying template (usually simple_circle)
    bg_color: tuple[int, int, int]
    bg_gradient: bool
    frame_color: tuple[int, int, int]
    frame_width: int
    text_color: tuple[int, int, int]
    stroke_color: tuple[int, int, int]
    stroke_width: int
    font: str                               # text_styles font family key
    text_pos: str                           # top|center|bottom
    align: str                              # left|center|right
    decoration: str                         # decoration type, or "" for none
    deco_color: tuple[int, int, int]
    caption_category: str                   # suggested caption category label
    main_bg: tuple[int, int, int, int]      # main.png / tab.png background
    text_style: str = "pop"                 # base text preset

    def overrides(self) -> dict:
        return {
            "bg_color": list(self.bg_color),
            "bg_gradient": self.bg_gradient,
            "frame_color": list(self.frame_color),
            "frame_width": self.frame_width,
            "text_color": list(self.text_color),
            "stroke_color": list(self.stroke_color),
            "stroke_width": self.stroke_width,
            "font": self.font,
            "text_pos": self.text_pos,
            "align": self.align,
        }

    def decorations(self) -> list[dict]:
        """Decoration parts placed in the corners (empty if none)."""
        if not self.decoration:
            return []
        c = list(self.deco_color)
        spots = [(0.16, 0.16), (0.84, 0.16), (0.16, 0.82), (0.84, 0.82)]
        parts = []
        for i, (x, y) in enumerate(spots):
            parts.append({
                "type": self.decoration, "x": x, "y": y,
                "size": 22 if i % 2 == 0 else 18,
                "rotation": (i * 17) % 40, "color": c,
            })
        return parts


BUILTIN_PRESETS: dict[str, PresetConfig] = {
    "pastel_pop": PresetConfig(
        label="パステルポップ", icon="🌸", base_template="simple_circle",
        bg_color=(255, 228, 242), bg_gradient=True,
        frame_color=(255, 255, 255), frame_width=16,
        text_color=(120, 60, 110), stroke_color=(255, 255, 255), stroke_width=6,
        font="maru", text_pos="bottom", align="center",
        decoration="heart", deco_color=(255, 130, 175),
        caption_category="日常", main_bg=(255, 210, 235, 255), text_style="pop",
    ),
    "comic_reaction": PresetConfig(
        label="コミックリアクション", icon="💥", base_template="simple_circle",
        bg_color=(255, 245, 200), bg_gradient=True,
        frame_color=(255, 255, 255), frame_width=14,
        text_color=(255, 255, 255), stroke_color=(20, 20, 20), stroke_width=8,
        font="pop", text_pos="bottom", align="center",
        decoration="sparkle", deco_color=(255, 200, 0),
        caption_category="日常", main_bg=(255, 220, 60, 255), text_style="pop",
    ),
    "business_clean": PresetConfig(
        label="ビジネスクリーン", icon="💼", base_template="simple_circle",
        bg_color=(240, 244, 250), bg_gradient=False,
        frame_color=(255, 255, 255), frame_width=12,
        text_color=(255, 255, 255), stroke_color=(30, 60, 110), stroke_width=6,
        font="gothic", text_pos="bottom", align="center",
        decoration="", deco_color=(30, 60, 110),
        caption_category="仕事", main_bg=(30, 60, 110, 255), text_style="pop",
    ),
    "sticker_cute": PresetConfig(
        label="ステッカーキュート", icon="🧁", base_template="simple_circle",
        bg_color=(255, 250, 235), bg_gradient=True,
        frame_color=(255, 255, 255), frame_width=20,
        text_color=(255, 110, 150), stroke_color=(255, 255, 255), stroke_width=7,
        font="maru", text_pos="bottom", align="center",
        decoration="sparkle", deco_color=(255, 170, 200),
        caption_category="日常", main_bg=(255, 240, 220, 255), text_style="pop",
    ),
    "celebration_party": PresetConfig(
        label="お祝いパーティー", icon="🎉", base_template="simple_circle",
        bg_color=(255, 180, 90), bg_gradient=True,
        frame_color=(255, 240, 150), frame_width=16,
        text_color=(255, 255, 255), stroke_color=(200, 90, 0), stroke_width=8,
        font="pop", text_pos="bottom", align="center",
        decoration="star", deco_color=(255, 230, 80),
        caption_category="家族", main_bg=(255, 140, 50, 255), text_style="pop",
    ),
}


def preset_overrides(key: str) -> dict | None:
    cfg = BUILTIN_PRESETS.get(key)
    return cfg.overrides() if cfg else None


def preset_decorations(key: str) -> list[dict]:
    cfg = BUILTIN_PRESETS.get(key)
    return cfg.decorations() if cfg else []


def preset_main_bg(key: str) -> tuple[int, int, int, int] | None:
    cfg = BUILTIN_PRESETS.get(key)
    return cfg.main_bg if cfg else None
