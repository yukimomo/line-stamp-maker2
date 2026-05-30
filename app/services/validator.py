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


def validate_stamp_set(output_dir: Path) -> ValidationReport:
    """
    Validate generated stamp set.

    Checks: PNG format, dimensions, file size, transparency,
    stamp count (8), presence of main.png and tab.png.
    """
    from PIL import Image

    report = ValidationReport()
    stickers_dir = output_dir / "stickers"

    # --- stamp count ---
    sticker_files = sorted(stickers_dir.glob("stamp_*.png")) if stickers_dir.exists() else []
    if len(sticker_files) < REQUIRED_COUNT:
        report.issues.append(
            ValidationIssue(
                "error",
                f"スタンプが {len(sticker_files)} 個です（{REQUIRED_COUNT} 個必要）",
            )
        )

    # --- validate each sticker ---
    for f in sticker_files:
        _check_png(f, STICKER_MAX_W, STICKER_MAX_H, MAX_FILE_BYTES, report, exact=False)

    # --- main.png ---
    main_png = output_dir / "main.png"
    if not main_png.exists():
        report.issues.append(ValidationIssue("error", "main.png が存在しません"))
    else:
        _check_png(main_png, MAIN_W, MAIN_H, MAX_FILE_BYTES, report, exact=True)

    # --- tab.png ---
    tab_png = output_dir / "tab.png"
    if not tab_png.exists():
        report.issues.append(ValidationIssue("error", "tab.png が存在しません"))
    else:
        _check_png(tab_png, TAB_W, TAB_H, MAX_FILE_BYTES, report, exact=True)

    return report


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
        report.issues.append(
            ValidationIssue(
                "error",
                f"{name}: ファイルサイズ {size_bytes:,} B（上限 {max_bytes:,} B）",
            )
        )

    try:
        img = Image.open(path)
        iw, ih = img.size

        if exact:
            if iw != max_w or ih != max_h:
                report.issues.append(
                    ValidationIssue(
                        "error",
                        f"{name}: サイズ {iw}×{ih} px（{max_w}×{max_h} px が必要）",
                    )
                )
        else:
            if iw > max_w or ih > max_h:
                report.issues.append(
                    ValidationIssue(
                        "error",
                        f"{name}: サイズ {iw}×{ih} px（最大 {max_w}×{max_h} px）",
                    )
                )

        if img.mode != "RGBA":
            report.issues.append(
                ValidationIssue("warning", f"{name}: 透過情報なし（RGBA 推奨）")
            )
    except Exception as exc:
        report.issues.append(ValidationIssue("error", f"{name}: 画像を開けません（{exc}）"))
