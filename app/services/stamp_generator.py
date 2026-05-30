"""
Generate LINE stamp images from photos using the character-ification pipeline.

Flow per item:
  photo → CharacterProcessor.process() → resize to spec → save PNG
  intermediate (styled) image is also saved for step preview.
"""

from __future__ import annotations
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image

from .character_processor import CharacterProcessor, STYLES, EXPRESSIONS
from .text_styles import TEXT_STYLES

# LINE Creators Market spec
STICKER_MAX_W = 370
STICKER_MAX_H = 320
MAIN_W = 240
MAIN_H = 240
TAB_W = 96
TAB_H = 74
MAX_FILE_BYTES = 1_000_000

# Photo content area (before the stamp frame is added)
_CONTENT_MAX_W = 260
_CONTENT_MAX_H = 200


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class StampItemSpec:
    position: int
    photo_path: str
    caption: str = ""
    style: str = "line_stamp"
    text_style: str = "bubble"
    expression: str = "none"


@dataclass
class GenerationResult:
    position: int
    success: bool
    sticker_path: Optional[str] = None
    preview_path: Optional[str] = None    # styled image (before frame+text)
    error: Optional[str] = None
    error_stage: Optional[str] = None


@dataclass
class GenerationSummary:
    set_output_dir: str
    zip_path: Optional[str]
    results: list[GenerationResult] = field(default_factory=list)

    @property
    def success_count(self) -> int:
        return sum(1 for r in self.results if r.success)

    @property
    def failed_positions(self) -> list[int]:
        return [r.position for r in self.results if not r.success]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_stamp_set(
    items: list[StampItemSpec],
    output_dir: Path,
) -> GenerationSummary:
    """
    Generate a complete LINE stamp set (8 stickers + main + tab + ZIP).

    Each item may have its own style / text_style / expression,
    but typically the set uses one style throughout.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    stickers_dir = output_dir / "stickers"
    stickers_dir.mkdir(exist_ok=True)
    previews_dir = output_dir / "previews"
    previews_dir.mkdir(exist_ok=True)

    results: list[GenerationResult] = []
    main_saved = False

    for item in items:
        result = _process_one(item, stickers_dir, previews_dir)
        if result.success and not main_saved:
            _save_main_tab(Path(result.sticker_path), output_dir)
            main_saved = True
        results.append(result)

    zip_path: Optional[Path] = None
    if any(r.success for r in results):
        zip_path = _build_zip(output_dir, stickers_dir, results)

    return GenerationSummary(
        set_output_dir=str(output_dir),
        zip_path=str(zip_path) if zip_path else None,
        results=results,
    )


# ---------------------------------------------------------------------------
# Per-item processing
# ---------------------------------------------------------------------------

def _process_one(
    item: StampItemSpec,
    stickers_dir: Path,
    previews_dir: Path,
) -> GenerationResult:
    stage = "load"
    try:
        photo = _load_image(Path(item.photo_path))

        stage = "resize"
        photo.thumbnail((_CONTENT_MAX_W, _CONTENT_MAX_H), Image.Resampling.LANCZOS)

        stage = "character"
        processor = CharacterProcessor(style=item.style, expression=item.expression)
        steps = processor.process(photo, item.caption, item.text_style)

        stage = "save_preview"
        preview_path = previews_dir / f"preview_{item.position:02d}.jpg"
        steps.styled.convert("RGB").save(preview_path, "JPEG", quality=80)

        stage = "save_sticker"
        stamp = steps.stamp.copy()
        stamp.thumbnail((STICKER_MAX_W, STICKER_MAX_H), Image.Resampling.LANCZOS)
        sticker_path = stickers_dir / f"stamp_{item.position:02d}.png"
        stamp.save(sticker_path, "PNG")

        return GenerationResult(
            position=item.position,
            success=True,
            sticker_path=str(sticker_path),
            preview_path=str(preview_path),
        )

    except Exception as exc:
        return GenerationResult(
            position=item.position,
            success=False,
            error=str(exc),
            error_stage=stage,
        )


def _load_image(path: Path) -> Image.Image:
    if path.suffix.lower() in (".heic", ".heif"):
        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()
        except ImportError as exc:
            raise RuntimeError("HEIC には pillow-heif が必要: pip install pillow-heif") from exc
    return Image.open(path)


def _save_main_tab(sticker_src: Path, output_dir: Path) -> None:
    """Create main.png (240×240) and tab.png (96×74) from the first sticker."""
    try:
        img = Image.open(sticker_src).convert("RGBA")
        for fname, w, h in [("main.png", MAIN_W, MAIN_H), ("tab.png", TAB_W, TAB_H)]:
            fitted = img.copy()
            fitted.thumbnail((w, h), Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            canvas.paste(fitted,
                         ((w - fitted.width) // 2, (h - fitted.height) // 2),
                         fitted)
            canvas.save(output_dir / fname, "PNG")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# ZIP builder
# ---------------------------------------------------------------------------

def _build_zip(
    output_dir: Path,
    stickers_dir: Path,
    results: list[GenerationResult],
) -> Path:
    zip_path = output_dir / "upload.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for r in results:
            if r.success and r.sticker_path:
                p = Path(r.sticker_path)
                if p.exists():
                    zf.write(p, p.name)
        for fname in ("main.png", "tab.png"):
            p = output_dir / fname
            if p.exists():
                zf.write(p, fname)
    return zip_path
