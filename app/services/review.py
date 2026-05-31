"""
LINE submission review: aggregate image-spec, quality, content, and
copyright/appropriateness risk advisories into a structured report with
per-stamp fix links.
"""

from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path

from .validator import validate_stamp_set, ALLOWED_COUNTS


@dataclass
class ReviewIssue:
    category: str          # "image" | "quality" | "content" | "risk"
    level: str             # "error" | "warning" | "advisory"
    message: str
    position: int | None = None       # slot to jump to, if applicable
    fix: str | None = None            # "edit" | "photo"


@dataclass
class ReviewReport:
    issues: list[ReviewIssue] = field(default_factory=list)

    def by_category(self, cat: str) -> list[ReviewIssue]:
        return [i for i in self.issues if i.category == cat]

    @property
    def errors(self) -> list[ReviewIssue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def fixable(self) -> list[ReviewIssue]:
        """Issues that point at a specific stamp (have a fix link)."""
        return [i for i in self.issues if i.position is not None]

    @property
    def is_ready(self) -> bool:
        """Ready to submit: no errors and no fixable quality/content problems."""
        return not any(i.level == "error" for i in self.issues) and not any(
            i.category in ("quality", "content") and i.level in ("error", "warning")
            for i in self.issues
        )

    def submit_status(self, has_zip: bool) -> str:
        if any(i.level == "error" for i in self.issues):
            return "needs_fix"
        if any(i.category in ("quality", "content") and i.level == "warning"
               for i in self.issues):
            return "needs_fix"
        return "exported" if has_zip else "ready"


# Risk keyword tables (caption / tag substrings → advisory)
_RISK_RULES: list[tuple[str, set[str]]] = [
    ("有名キャラクター風のデザインは審査でリジェクトされやすいです。オリジナルか確認してください。",
     {"character", "anime", "hero", "mascot", "キャラ", "アニメ", "ヒーロー", "ゆるキャラ"}),
    ("ロゴ・商標が写っていないか確認してください（ブランド名・企業ロゴはNG）。",
     {"logo", "brand", "trademark", "ロゴ", "商標", "ブランド", "企業"}),
    ("個人情報（名札・表札・住所・書類・ナンバープレート）が写っていないか確認してください。",
     {"id", "license", "address", "document", "name tag", "番号", "住所", "名札", "表札", "書類", "ナンバー"}),
    ("不適切表現（飲酒・喫煙・暴力など）が含まれていないか確認してください。",
     {"alcohol", "beer", "cigarette", "smoke", "violence", "酒", "ビール", "たばこ", "タバコ", "暴力"}),
]


def run_review(
    output_dir: Path | None,
    items: list[dict],
    count: int,
    photo_tags_by_pos: dict[int, list[str]] | None = None,
) -> ReviewReport:
    """
    Build a full submission review.

    Args:
        output_dir:        generated output dir (None if not generated yet)
        items:             stamp_items dicts (caption, photo_path, warnings, position)
        count:             expected stamp count
        photo_tags_by_pos: optional {position: [tags]} for richer risk scan
    """
    report = ReviewReport()
    photo_tags_by_pos = photo_tags_by_pos or {}

    # ── image spec (reuse validator) ──
    if output_dir and Path(output_dir).exists():
        vr = validate_stamp_set(Path(output_dir), items=items, required_count=count)
        for e in vr.errors:
            report.issues.append(ReviewIssue("image", "error", e))
        for w in vr.warnings:
            report.issues.append(ReviewIssue("image", "warning", w))
    else:
        report.issues.append(ReviewIssue("image", "error", "まだ生成されていません（先に生成してください）"))

    if count not in ALLOWED_COUNTS:
        report.issues.append(
            ReviewIssue("image", "error", f"スタンプ数 {count} は不正です（8/16/24/32/40）"))

    # ── per-stamp quality (from stored warnings) ──
    for it in items:
        pos = it.get("position")
        raw = it.get("warnings")
        warns = it.get("warning_list")
        if warns is None:
            try:
                warns = json.loads(raw) if raw else []
            except (ValueError, TypeError):
                warns = []
        for w in warns:
            fix = "photo" if ("写真" in w or "見切れ" in w or "小さ" in w or "暗" in w) else "edit"
            report.issues.append(ReviewIssue("quality", "warning", w, position=pos, fix=fix))

    # ── content (duplicate captions / photos) ──
    _content_checks(items, report)

    # ── risk advisories (keyword scan over captions + tags) ──
    _risk_advisories(items, photo_tags_by_pos, report)

    return report


def _content_checks(items: list[dict], report: ReviewReport) -> None:
    cap_pos: dict[str, list[int]] = {}
    photo_pos: dict[str, list[int]] = {}
    for it in items:
        c = str(it.get("caption", "")).strip()
        p = str(it.get("photo_path", ""))
        if c:
            cap_pos.setdefault(c, []).append(it.get("position"))
        if p:
            photo_pos.setdefault(p, []).append(it.get("position"))

    for cap, positions in cap_pos.items():
        if len(positions) > 1:
            report.issues.append(ReviewIssue(
                "content", "warning",
                f"同じセリフ「{cap}」が {len(positions)} 個で重複しています",
                position=positions[0], fix="edit"))

    for _photo, positions in photo_pos.items():
        if len(positions) >= 3:
            report.issues.append(ReviewIssue(
                "content", "warning",
                f"同じ写真が {len(positions)} 回使われています（使い回し過多）",
                position=positions[0], fix="photo"))


def _risk_advisories(items, photo_tags_by_pos, report: ReviewReport) -> None:
    haystack = " ".join(str(it.get("caption", "")) for it in items).lower()
    for tags in photo_tags_by_pos.values():
        haystack += " " + " ".join(str(t).lower() for t in (tags or []))

    for message, keywords in _RISK_RULES:
        if any(k.lower() in haystack for k in keywords):
            report.issues.append(ReviewIssue("risk", "advisory", message))

    # Always-on general reminder (advisory)
    report.issues.append(ReviewIssue(
        "risk", "advisory",
        "写真に第三者・他人の顔や作品が含まれていないか最終確認してください。"))
