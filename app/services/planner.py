"""
AI-ish stamp-set planner (rule/template based).

Turns a use-case (scene / target / mood / count) into a complete PlannerResult:
set title, description, category, tags, recommended preset, phrases,
recommended photos, and quality warnings.

Designed for future LLM swap: `Planner` is the interface; `RuleBasedPlanner`
is the current implementation. An OpenAI/Claude/Ollama planner can implement
the same `plan()` signature and return the same PlannerResult.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any

# ---------------------------------------------------------------------------
# Choice vocabularies (for the UI)
# ---------------------------------------------------------------------------

SCENES: dict[str, str] = {
    "family":   "家族",
    "work":     "仕事",
    "couple":   "カップル",
    "friends":  "友達",
    "kids":     "子育て",
    "pet":      "ペット",
    "celebration": "お祝い",
    "keigo":    "敬語",
}

TARGETS: dict[str, str] = {
    "anyone":  "だれでも",
    "kids":    "子供",
    "adult":   "大人",
    "family":  "家族",
    "coworker": "同僚",
    "friend":  "友達",
}

MOODS: dict[str, str] = {
    "cute":    "かわいい",
    "pop":     "ポップ",
    "simple":  "シンプル",
    "calm":    "落ち着いた",
    "genki":   "元気",
    "yuru":    "ゆるい",
}

ALLOWED_COUNTS = (8, 16, 24, 32, 40)

# Mood → recommended design preset (built-in preset keys)
_MOOD_PRESET: dict[str, str] = {
    "cute":   "pastel_pop",
    "pop":    "comic_reaction",
    "simple": "business_clean",
    "calm":   "business_clean",
    "genki":  "celebration_party",
    "yuru":   "sticker_cute",
}


@dataclass
class _SceneConfig:
    label: str
    title_core: str
    description: str
    category: str
    tags: list[str]
    preset: str           # fallback preset if mood gives none
    theme: str            # existing stamp_themes key (for create handoff)
    phrases: list[str]


_SCENES_CFG: dict[str, _SceneConfig] = {
    "family": _SceneConfig(
        "家族", "家族スタンプ", "家族の連絡や日常会話で使いやすいスタンプセットです。",
        "家族・こども", ["家族", "日常", "かわいい"], "pastel_pop", "family_pop",
        ["おはよう", "いってきます", "ただいま", "おつかれ", "ありがとう", "ごめんね",
         "了解！", "おやすみ", "だいすき", "まかせて", "いまどこ？", "もうすぐ着くよ",
         "ごはんできたよ", "おかえり", "気をつけてね", "また連絡するね",
         "おめでとう", "うれしい", "たのしい", "がんばって"]),
    "work": _SceneConfig(
        "仕事", "お仕事スタンプ", "ビジネスの連絡で使いやすい、丁寧なスタンプセットです。",
        "ビジネス", ["ビジネス", "仕事", "敬語"], "business_clean", "business_casual",
        ["承知しました", "確認します", "お願いします", "完了しました", "対応します",
         "ありがとうございます", "少々お待ちください", "お疲れさまです", "了解です",
         "確認中です", "返信が遅れました", "助かりました", "よろしくお願いします",
         "承りました", "対応中です", "問題ありません", "ご連絡ありがとうございます",
         "確認いたします", "失礼します", "お世話になります"]),
    "couple": _SceneConfig(
        "カップル", "カップルスタンプ", "ふたりの毎日がもっと楽しくなるスタンプセットです。",
        "気持ち・感情", ["カップル", "恋愛", "かわいい"], "pastel_pop", "cute_daily",
        ["だいすき", "会いたい", "おやすみ", "おはよう", "いまなにしてる？", "ありがとう",
         "ごめんね", "また明日", "うれしい", "たのしみ", "気をつけてね", "おつかれさま",
         "むぎゅ", "えへへ", "りょうかい", "まってるね", "デートしよ", "幸せ",
         "ぎゅー", "love"]),
    "friends": _SceneConfig(
        "友達", "友達スタンプ", "友達とのLINEで気軽に使えるスタンプセットです。",
        "日常", ["友達", "日常", "ゆるい"], "comic_reaction", "cute_daily",
        ["おはよ", "やっほー", "りょ", "まじで！？", "わかる", "それな", "いいね！",
         "おつー", "また今度", "ありがと", "ごめん", "おやすみ", "あそぼ", "うける",
         "おめでとう", "がんば", "なるほど", "OK", "たのしかった", "またね"]),
    "kids": _SceneConfig(
        "子育て", "子育てスタンプ", "子育て中の連絡やうちの子の記録に使えるスタンプです。",
        "家族・こども", ["子育て", "赤ちゃん", "成長記録"], "sticker_cute", "baby_kids",
        ["おはよう", "ねんねした", "ミルクのんだ", "おむつかえた", "げんきだよ", "あそぼ",
         "ただいま", "いってきます", "ありがとう", "ごめんね", "たすかった", "おつかれ",
         "びょういん行ってくる", "おむかえよろしく", "もうすぐ寝そう", "ぐずってる",
         "笑った！", "はじめての一歩", "おやすみ", "だいすき"]),
    "pet": _SceneConfig(
        "ペット", "うちの子スタンプ", "かわいいペットの写真で作る、ほっこりスタンプです。",
        "動物", ["ペット", "動物", "かわいい"], "pastel_pop", "cute_daily",
        ["おはわん", "ごはんちょうだい", "なでて", "あそぼ", "おさんぽ行こ", "ねむい",
         "ただいま", "おかえり", "ありがとう", "ごめんね", "うれしい", "まってた",
         "おやすみ", "だいすき", "おすわり", "まてできるよ", "おなかすいた", "げんき",
         "かまって", "また明日"]),
    "celebration": _SceneConfig(
        "お祝い", "お祝いスタンプ", "誕生日やお祝いごとを盛り上げるスタンプセットです。",
        "イベント・季節", ["お祝い", "誕生日", "イベント"], "celebration_party", "celebration",
        ["おめでとう！", "ハッピーバースデー", "やったね！", "乾杯！", "最高！", "ありがとう",
         "うれしい！", "おめでとうございます", "よかったね", "祝！", "パーティー", "サプライズ",
         "ありがとう♪", "感謝", "幸せ", "楽しもう", "おつかれさま", "がんばったね",
         "すごい！", "万歳！"]),
    "keigo": _SceneConfig(
        "敬語", "敬語スタンプ", "目上の方にも使える、丁寧な敬語スタンプセットです。",
        "ビジネス", ["敬語", "丁寧", "ビジネス"], "business_clean", "business_casual",
        ["承知いたしました", "かしこまりました", "ありがとうございます", "よろしくお願いいたします",
         "恐れ入ります", "失礼いたします", "お世話になっております", "確認いたします",
         "申し訳ございません", "助かります", "了解いたしました", "お疲れさまでございます",
         "承ります", "ご連絡いたします", "対応いたします", "お待ちしております",
         "ご確認ください", "問題ございません", "感謝いたします", "お願い申し上げます"]),
}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

@dataclass
class PlannerInput:
    scene: str = "family"
    target: str = "anyone"
    mood: str = "cute"
    count: int = 8


@dataclass
class PlannerResult:
    title: str
    description: str
    category: str
    tags: list[str]
    preset: str
    theme: str
    phrases: list[str]
    recommended_photos: list[str]            # parallel to phrases (may be empty)
    main_photo: str | None = None            # best photo for main.png
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Planner interface + rule-based implementation
# ---------------------------------------------------------------------------

class Planner:
    """Interface. Future: OpenAIPlanner / ClaudePlanner / OllamaPlanner."""

    def plan(self, inp: PlannerInput, photos: list[dict] | None = None) -> PlannerResult:
        raise NotImplementedError


class RuleBasedPlanner(Planner):
    def plan(self, inp: PlannerInput, photos: list[dict] | None = None) -> PlannerResult:
        cfg = _SCENES_CFG.get(inp.scene, _SCENES_CFG["family"])
        count = inp.count if inp.count in ALLOWED_COUNTS else 8
        mood_label = MOODS.get(inp.mood, "かわいい")
        preset = _MOOD_PRESET.get(inp.mood, cfg.preset)

        title = f"{mood_label}{cfg.title_core}"
        tags = list(dict.fromkeys(cfg.tags + [mood_label]))

        phrases = _make_phrases(cfg.phrases, count)
        warnings = check_phrases(phrases)

        recommended, main_photo = recommend_photos(phrases, photos or [])

        return PlannerResult(
            title=title,
            description=cfg.description,
            category=cfg.category,
            tags=tags,
            preset=preset,
            theme=cfg.theme,
            phrases=phrases,
            recommended_photos=recommended,
            main_photo=main_photo,
            warnings=warnings,
        )


def generate_plan(inp: PlannerInput, photos: list[dict] | None = None,
                  planner: Planner | None = None) -> PlannerResult:
    """Convenience entry point (defaults to the rule-based planner)."""
    return (planner or RuleBasedPlanner()).plan(inp, photos)


# ---------------------------------------------------------------------------
# Phrase generation
# ---------------------------------------------------------------------------

def _make_phrases(pool: list[str], count: int) -> list[str]:
    """Return *count* phrases from *pool*, cycling with a suffix once exhausted."""
    out: list[str] = []
    for i in range(count):
        if i < len(pool):
            out.append(pool[i])
        else:
            # Exhausted unique pool: reuse with a round number suffix
            base = pool[i % len(pool)]
            out.append(f"{base}{i // len(pool) + 1}")
    return out


# ---------------------------------------------------------------------------
# Phrase quality check
# ---------------------------------------------------------------------------

MAX_PHRASE_LEN = 12          # characters; longer is hard to read on a sticker
_SIMILAR_SUFFIXES = ("です", "ます", "！", "。", "、", "♪", "ね", "よ", "わん")


def _normalize(phrase: str) -> str:
    p = phrase.strip()
    changed = True
    while changed:
        changed = False
        for suf in _SIMILAR_SUFFIXES:
            if len(p) > 2 and p.endswith(suf):
                p = p[: -len(suf)]
                changed = True
    return p


def check_phrases(phrases: list[str]) -> list[str]:
    """Return warnings: duplicates, near-duplicates, too long, hard to read."""
    warnings: list[str] = []

    # Exact duplicates
    seen: dict[str, int] = {}
    for i, p in enumerate(phrases):
        key = p.strip()
        if key in seen:
            warnings.append(f"{i + 1}番目「{p}」が重複しています")
        seen[key] = i

    # Near-duplicates (same normalized stem)
    norm_map: dict[str, list[str]] = {}
    for p in phrases:
        norm_map.setdefault(_normalize(p), []).append(p)
    for stem, group in norm_map.items():
        uniq = list(dict.fromkeys(group))
        if len(uniq) > 1:
            warnings.append("意味の近いセリフがあります: " + " / ".join(uniq))

    # Too long / hard to read
    for i, p in enumerate(phrases):
        if len(p.strip()) > MAX_PHRASE_LEN:
            warnings.append(f"{i + 1}番目「{p}」は長すぎます（{MAX_PHRASE_LEN}文字以内推奨）")

    return warnings


# ---------------------------------------------------------------------------
# Photo recommendation (uses existing analysis: tags / score)
# ---------------------------------------------------------------------------

_THANKS_WORDS = ("ありがと", "感謝", "うれし", "おめでと", "だいすき", "love", "幸せ")
_GROUP_WORDS = ("おつかれ", "おつー", "がんば", "乾杯", "パーティー")


def _photo_score(p: dict) -> float:
    return float(p.get("score") or 0)


def _has_tag(p: dict, words: set[str]) -> bool:
    tags = {str(t).lower() for t in (p.get("tags") or [])}
    return bool(tags & words)


def recommend_photos(phrases: list[str], photos: list[dict]) -> tuple[list[str], str | None]:
    """
    Assign a recommended photo to each phrase and pick a main.png candidate.

    Heuristics (best-effort with available metadata):
      - thanks/감사-type phrase  → prefer a smile/happy-tagged photo
      - group-type phrase        → prefer a group/family-tagged photo
      - otherwise                → highest remaining quality score
      - main_photo               → highest quality score overall
    """
    if not photos:
        return [], None

    ranked = sorted(photos, key=_photo_score, reverse=True)
    main_photo = ranked[0]["path"]

    smile_pool = [p for p in ranked if _has_tag(p, {"smile", "happy", "laugh", "joy", "笑顔"})]
    group_pool = [p for p in ranked if _has_tag(p, {"group", "family", "people", "multiple", "家族"})]

    used: set[str] = set()
    assigned: list[str] = []

    def _take(pool: list[dict]) -> str | None:
        for p in pool:
            if p["path"] not in used:
                used.add(p["path"])
                return p["path"]
        return None

    for phrase in phrases:
        pick = None
        if any(w in phrase for w in _THANKS_WORDS):
            pick = _take(smile_pool)
        elif any(w in phrase for w in _GROUP_WORDS):
            pick = _take(group_pool)
        if pick is None:
            pick = _take(ranked)
        if pick is None:                      # fewer photos than phrases → cycle
            pick = ranked[len(assigned) % len(ranked)]["path"]
        assigned.append(pick)

    return assigned, main_photo
