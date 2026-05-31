"""
Stamp set theme definitions.

Each theme specifies:
  - label / icon / description  for the UI
  - templates: 8-slot rotation of template names
  - captions:  8 default captions (matched 1-to-1 with slots)
  - text_style: default text rendering style
  - main_bg:    RGBA background color for main.png
"""

from __future__ import annotations
import random
from dataclasses import dataclass


@dataclass
class ThemeConfig:
    label: str
    icon: str
    description: str
    templates: list[str]   # exactly 8 (one per slot)
    captions: list[str]    # exactly 8 default captions
    text_style: str
    main_bg: tuple[int, int, int, int]


# ---------------------------------------------------------------------------
# Theme definitions
# ---------------------------------------------------------------------------

THEMES: dict[str, ThemeConfig] = {
    "family_pop": ThemeConfig(
        label="家族・ポップ",
        icon="👨‍👩‍👧",
        description="家族や友人へのポップで明るいスタンプ",
        templates=["pop_star", "heart", "simple_circle", "birthday",
                   "heart", "pop_star", "simple_circle", "seasonal_sakura"],
        captions=["おはよう", "いってきます", "ただいま", "ありがとう",
                  "ごめんね", "おつかれ", "了解！", "おやすみ"],
        text_style="bubble",
        main_bg=(255, 200, 80, 255),
    ),
    "cute_daily": ThemeConfig(
        label="かわいい日常",
        icon="🌸",
        description="毎日使えるかわいいスタンプ",
        templates=["heart", "seasonal_sakura", "simple_circle", "heart",
                   "seasonal_sakura", "pop_star", "simple_circle", "heart"],
        captions=["おはよう♪", "いいね！", "ありがとう♡", "たのしい♪",
                  "うれしい", "かわいい♡", "すき", "おやすみ♡"],
        text_style="bubble",
        main_bg=(255, 190, 215, 255),
    ),
    "business_casual": ThemeConfig(
        label="ビジネス・カジュアル",
        icon="💼",
        description="ビジネスシーンで使えるスマートなスタンプ",
        templates=["cool_badge", "simple_circle", "cool_badge", "simple_circle",
                   "cool_badge", "simple_circle", "cool_badge", "simple_circle"],
        captions=["承知しました", "確認します", "ありがとうございます", "対応します",
                  "少々お待ちください", "完了しました", "よろしくお願いします", "お疲れさまです"],
        text_style="pop",
        main_bg=(30, 70, 150, 255),
    ),
    "baby_kids": ThemeConfig(
        label="ベビー・キッズ",
        icon="👶",
        description="赤ちゃん・子ども向けのキュートなスタンプ",
        templates=["birthday", "heart", "pop_star", "simple_circle",
                   "heart", "birthday", "pop_star", "heart"],
        captions=["バブバブ", "ねんね", "まんま", "だっこ",
                  "いい子♡", "もっと", "いたいの", "ありがとっ"],
        text_style="bubble",
        main_bg=(255, 220, 120, 255),
    ),
    "celebration": ThemeConfig(
        label="お祝い・イベント",
        icon="🎉",
        description="誕生日・お祝いイベント向けスタンプ",
        templates=["birthday", "pop_star", "birthday", "pop_star",
                   "seasonal_sakura", "birthday", "pop_star", "birthday"],
        captions=["おめでとう！", "やった！", "ありがとう♪", "最高！",
                  "うれしい！", "よかった！", "乾杯！", "お祝い！"],
        text_style="pop",
        main_bg=(255, 100, 40, 255),
    ),
    "simple_icon": ThemeConfig(
        label="シンプルアイコン",
        icon="⭕",
        description="すっきりシンプルなアイコン風スタンプ",
        templates=["simple_circle"] * 8,
        captions=["了解", "ありがとう", "OK", "おつかれ",
                  "ごめん", "いいね", "また今度", "おやすみ"],
        text_style="outline_white",
        main_bg=(50, 50, 70, 255),
    ),
}


# ---------------------------------------------------------------------------
# Caption auto-assignment
# ---------------------------------------------------------------------------

# Tag→caption affinity rules (tag substring → preferred caption substrings)
_TAG_CAPTION_AFFINITY: list[tuple[set[str], list[str]]] = [
    ({"smile", "happy", "laugh", "joy", "笑顔"},
     ["ありがとう", "最高", "いいね", "おはよう", "うれしい", "やった", "おめでとう"]),
    ({"sleep", "tired", "yawn", "目閉じ"},
     ["おやすみ", "おつかれ", "ねんね", "お疲れ"]),
    ({"cry", "sad", "tear"},
     ["ごめん", "ごめんね", "いたいの"]),
    ({"run", "walk", "move", "動き"},
     ["いってきます", "ただいま", "了解", "対応します"]),
    ({"group", "family", "multiple", "複数", "家族"},
     ["おつかれ", "ありがとう", "一緒", "よろしく"]),
    ({"eat", "food", "まんま"},
     ["まんま", "いただきます", "おいしい"]),
]


def assign_captions_to_photos(
    photos: list[dict],
    theme_name: str,
    count: int = 8,
) -> list[str]:
    """
    Return *count* captions for the given photos, using theme defaults but
    matching captions to photo analysis tags where available.

    Photos shorter than *count* are cycled. Captions repeat (with a numeric
    suffix once exhausted) so each slot still gets a distinct label.
    """
    cfg = THEMES.get(theme_name, THEMES["simple_icon"])
    base = cfg.captions
    result: list[str] = []
    used: set[str] = set()

    for i in range(count):
        photo = photos[i % len(photos)] if photos else {}
        tags = _extract_tags(photo)
        pool = [c for c in base if c not in used] or list(base)
        cap = _pick_caption(tags, pool, used) or pool[i % len(pool)]
        if cap in used:
            # captions exhausted for this round — disambiguate
            cap = f"{cap}{(i // len(base)) + 1}"
        result.append(cap)
        used.add(cap)

    return result


def _extract_tags(photo: dict) -> set[str]:
    analysis = photo.get("analysis") or {}
    return {t.lower() for t in analysis.get("tags", [])}


def _pick_caption(tags: set[str], pool: list[str], used: set[str]) -> str | None:
    """Find the first caption from pool that matches affinity rules for tags."""
    for tag_set, preferred_substrings in _TAG_CAPTION_AFFINITY:
        if not (tags & tag_set):
            continue
        for cap in pool:
            if cap in used:
                continue
            if any(sub in cap for sub in preferred_substrings):
                return cap
    return None
