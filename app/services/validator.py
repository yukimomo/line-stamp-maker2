"""Validate a generated stamp set against LINE Creators Market specs."""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path

# LINE static-sticker specs
STICKER_MAX_W = 370
STICKER_MAX_H = 320
MAIN_W = 240
MAIN_H = 240
TAB_W = 96
TAB_H = 74
MAX_FILE_BYTES = 1_000_000   # 1 MB per file
REQUIRED_COUNT = 8


@dataclass
class ValidationIssue:
    level: str   # "error" | "warning"
    message: str


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not any(i.level == "error" for i in self.issues)

    @property
    def errors(self) -> list[str]:
        return [i.message for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[str]:
        return [i.message for i in self.issues if i.level == "warning"]


ALLOWED_COUNTS = (8, 16, 24, 32, 40)


def validate_stamp_set(
    output_dir: Path,
    items: list[dict] | None = None,
    required_count: int = REQUIRED_COUNT,
) -> ValidationReport:
    """
    Validate a generated stamp set.

    Args:
        output_dir:     directory containing stickers/, main.png, tab.png
        items:          optional item dicts for content checks
        required_count: expected sticker count (8/16/24/32/40)

    Checks:
      Image quality: PNG format, dimensions, file size, transparency, count
      Meta images:   main.png and tab.png existence and size
      Content:       duplicate captions/photos, similar-design overuse
    """
    from PIL import Image

    report = ValidationReport()
    stickers_dir = output_dir / "stickers"

    # ── stamp count ──────────────────────────────────────────────────────────
    sticker_files = sorted(stickers_dir.glob("stamp_*.png")) if stickers_dir.exists() else []
    if len(sticker_files) < required_count:
        report.issues.append(ValidationIssue(
            "error",
            f"スタンプが {len(sticker_files)} 個です（{required_count} 個必要）",
        ))
    if required_count not in ALLOWED_COUNTS:
        report.issues.append(ValidationIssue(
            "error",
            f"申請枚数 {required_count} は不正です（8/16/24/32/40 のいずれか）",
        ))

    # ── per-sticker checks ───────────────────────────────────────────────────
    for f in sticker_files:
        _check_png(f, STICKER_MAX_W, STICKER_MAX_H, MAX_FILE_BYTES, report, exact=False)

    # ── main.png ─────────────────────────────────────────────────────────────
    main_png = output_dir / "main.png"
    if not main_png.exists():
        report.issues.append(ValidationIssue("error", "main.png が存在しません"))
    else:
        _check_png(main_png, MAIN_W, MAIN_H, MAX_FILE_BYTES, report, exact=True)

    # ── tab.png ──────────────────────────────────────────────────────────────
    tab_png = output_dir / "tab.png"
    if not tab_png.exists():
        report.issues.append(ValidationIssue("error", "tab.png が存在しません"))
    else:
        _check_png(tab_png, TAB_W, TAB_H, MAX_FILE_BYTES, report, exact=True)

    # ── content checks (require items metadata) ──────────────────────────────
    if items:
        _check_content(items, report)

    return report


def _check_content(items: list[dict], report: ValidationReport) -> None:
    """Check for duplicate captions and duplicate photos."""
    captions = [str(i.get("caption", "")).strip() for i in items]
    photos = [str(i.get("photo_path", "")) for i in items]

    # Duplicate captions
    seen_caps: set[str] = set()
    dupe_caps: set[str] = set()
    for c in captions:
        if c and c in seen_caps:
            dupe_caps.add(c)
        seen_caps.add(c)
    if dupe_caps:
        report.issues.append(ValidationIssue(
            "warning",
            f"重複セリフがあります: {', '.join(sorted(dupe_caps))}",
        ))

    # Duplicate photos
    seen_photos: set[str] = set()
    dupe_count = 0
    for p in photos:
        if p and p in seen_photos:
            dupe_count += 1
        seen_photos.add(p)
    if dupe_count:
        report.issues.append(ValidationIssue(
            "warning",
            f"同じ写真が {dupe_count + 1} 枚使われているスロットがあります",
        ))

    # Empty captions
    empty = sum(1 for c in captions if not c)
    if empty:
        report.issues.append(ValidationIssue(
            "warning",
            f"セリフが空のスロットが {empty} 個あります",
        ))

    # Similar-design overuse: one template used for >70% of a large set
    templates = [str(i.get("item_template") or "") for i in items if i.get("item_template")]
    if len(templates) >= 8:
        from collections import Counter
        tmpl, n = Counter(templates).most_common(1)[0]
        if n / len(templates) > 0.7:
            report.issues.append(ValidationIssue(
                "warning",
                f"同じテンプレートが {n} 枚で偏っています（デザインに変化を付けると良いです）",
            ))


def _check_png(
    path: Path,
    max_w: int,
    max_h: int,
    max_bytes: int,
    report: ValidationReport,
    exact: bool,
) -> None:
    from PIL import Image

    name = path.name

    if path.suffix.lower() != ".png":
        report.issues.append(ValidationIssue("error", f"{name}: PNG 形式ではありません"))
        return

    size_bytes = path.stat().st_size
    if size_bytes > max_bytes:
        report.issues.append(ValidationIssue(
            "error",
            f"{name}: ファイルサイズ {size_bytes:,} B（上限 {max_bytes:,} B）",
        ))

    try:
        img = Image.open(path)
        iw, ih = img.size

        if exact:
            if iw != max_w or ih != max_h:
                report.issues.append(ValidationIssue(
                    "error",
                    f"{name}: サイズ {iw}×{ih} px（{max_w}×{max_h} px が必要）",
                ))
        else:
            if iw > max_w or ih > max_h:
                report.issues.append(ValidationIssue(
                    "error",
                    f"{name}: サイズ {iw}×{ih} px（最大 {max_w}×{max_h} px）",
                ))

        if img.mode != "RGBA":
            report.issues.append(ValidationIssue("warning", f"{name}: 透過情報なし（RGBA 推奨）"))
    except Exception as exc:
        report.issues.append(ValidationIssue("error", f"{name}: 画像を開けません（{exc}）"))
