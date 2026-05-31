"""
LINE Creators Market application metadata: fields, defaults, and
auto-suggestion from theme / captions / photo tags.
"""

from __future__ import annotations
from collections import Counter

# Field keys + Japanese labels (order = form order)
META_FIELDS: dict[str, str] = {
    "title":       "タイトル",
    "description": "説明文",
    "author":      "作者名",
    "copyright":   "コピーライト表記",
    "sales_area":  "販売エリア",
    "language":    "言語",
    "category":    "カテゴリ",
    "tags":        "タグ",
    "price_note":  "価格メモ",
    "review_note": "審査メモ",
}

LINE_CATEGORIES = [
    "キャラクター", "家族・こども", "日常", "あいさつ", "気持ち・感情",
    "ビジネス", "イベント・季節", "動物", "その他",
]


def default_metadata() -> dict:
    return {
        "title": "", "description": "", "author": "", "copyright": "",
        "sales_area": "全エリア", "language": "日本語", "category": "日常",
        "tags": "", "price_note": "120円（50コイン）", "review_note": "",
    }


# Theme → suggestion hints
_THEME_HINTS: dict[str, dict] = {
    "family_pop":      {"title": "まいにち家族スタンプ", "category": "家族・こども",
                        "desc": "家族の日常会話で使いやすい、かわいい写真デコスタンプです。",
                        "tags": ["家族", "日常", "かわいい", "こども"]},
    "cute_daily":      {"title": "ゆるかわ毎日スタンプ", "category": "日常",
                        "desc": "毎日のLINEがもっと楽しくなる、ゆるくてかわいいスタンプです。",
                        "tags": ["かわいい", "日常", "ゆるい", "女子"]},
    "business_casual": {"title": "つかえる敬語スタンプ", "category": "ビジネス",
                        "desc": "ビジネスシーンでサッと使える、丁寧で使いやすいスタンプです。",
                        "tags": ["ビジネス", "敬語", "仕事", "丁寧"]},
    "baby_kids":       {"title": "うちの子スタンプ", "category": "家族・こども",
                        "desc": "赤ちゃん・子どものかわいい瞬間を集めたスタンプです。",
                        "tags": ["赤ちゃん", "こども", "かわいい", "成長記録"]},
    "celebration":     {"title": "お祝いスタンプ", "category": "イベント・季節",
                        "desc": "誕生日やお祝いごとを盛り上げる、にぎやかなスタンプです。",
                        "tags": ["お祝い", "誕生日", "イベント", "おめでとう"]},
    "simple_icon":     {"title": "シンプル丸アイコンスタンプ", "category": "日常",
                        "desc": "すっきり見やすい、シンプルなアイコン風スタンプです。",
                        "tags": ["シンプル", "日常", "アイコン"]},
}


def suggest_metadata(theme: str, captions: list[str], photo_tags: list[str],
                     author: str = "") -> dict:
    """Suggest application metadata from theme + captions + photo tags."""
    hint = _THEME_HINTS.get(theme, _THEME_HINTS["simple_icon"])

    # Tags: theme tags + most common photo tags (deduped, max 8)
    tag_pool: list[str] = list(hint["tags"])
    for t, _ in Counter([t for t in photo_tags if t]).most_common(6):
        if t not in tag_pool:
            tag_pool.append(t)
    tags = tag_pool[:8]

    # Description: theme description + a couple of example captions
    sample = [c for c in captions if c][:3]
    desc = hint["desc"]
    if sample:
        desc += "（例: " + " / ".join(sample) + " など" + str(len(captions)) + "種）"

    note = (
        "・写真は本人/家族の撮影分のみ使用しています。\n"
        "・第三者の著作物、ロゴ、商標は含みません。\n"
        "・公序良俗に反する表現はありません。"
    )

    return {
        "title": hint["title"],
        "description": desc,
        "author": author,
        "copyright": (f"© {author}" if author else ""),
        "sales_area": "全エリア",
        "language": "日本語",
        "category": hint["category"],
        "tags": ", ".join(tags),
        "price_note": "120円（50コイン）",
        "review_note": note,
    }
