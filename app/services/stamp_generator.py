"""
Generate LINE stamp images from photos using the character-ification pipeline.

Flow per item:
  photo → CharacterProcessor.process() → resize to spec → save PNG
  Themed main.png / tab.png are generated after all stickers are done.
"""

from __future__ import annotations
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw

from .character_processor import CharacterProcessor, Adjustments
from .quality_check import analyze_quality
from .text_styles import TEXT_STYLES, load_font, auto_font_size, _draw_outlined_text

# LINE Creators Market spec
STICKER_MAX_W = 370
STICKER_MAX_H = 320
MAIN_W = 240
MAIN_H = 240
TAB_W = 96
TAB_H = 74
MAX_FILE_BYTES = 1_000_000

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
    style: str = "simple_circle"   # template name
    text_style: str = "bubble"
    expression: str = "none"       # reserved
    # Manual adjustments
    zoom: float = 1.0
    offset_x: float = 0.0
    offset_y: float = 0.0
    brightness: float = 0.0
    # Free-design overrides (text + frame) and decoration parts
    overrides: dict | None = None
    decorations: list | None = None


@dataclass
class GenerationResult:
    position: int
    success: bool
    sticker_path: Optional[str] = None
    preview_path: Optional[str] = None
    error: Optional[str] = None
    error_stage: Optional[str] = None
    warnings: list[str] = field(default_factory=list)


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
    theme_name: str = "simple_icon",
    set_name: str = "",
) -> GenerationSummary:
    """
    Generate a complete LINE stamp set (8 stickers + main + tab + ZIP).

    Args:
        items:      8 StampItemSpec, each with its own template/caption.
        output_dir: Output directory.
        theme_name: Theme key from stamp_themes.THEMES (used for main/tab).
        set_name:   Displayed on main.png.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "stickers").mkdir(exist_ok=True)
    (output_dir / "previews").mkdir(exist_ok=True)

    results: list[GenerationResult] = []
    for item in items:
        results.append(_process_one(item, output_dir / "stickers", output_dir / "previews"))

    # Themed main / tab
    successful_stickers = [
        Path(r.sticker_path) for r in results if r.success and r.sticker_path
    ]
    _generate_themed_main_tab(successful_stickers, theme_name, set_name, output_dir)

    zip_path: Optional[Path] = None
    if successful_stickers:
        zip_path = _build_zip(output_dir, output_dir / "stickers", results)

    return GenerationSummary(
        set_output_dir=str(output_dir),
        zip_path=str(zip_path) if zip_path else None,
        results=results,
    )


# ---------------------------------------------------------------------------
# Single-item regenerate + finalize (for editing individual stamps)
# ---------------------------------------------------------------------------

def regenerate_item(item: StampItemSpec, output_dir: Path) -> GenerationResult:
    """Regenerate one stamp (sticker + preview) in an existing set output dir."""
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "stickers").mkdir(exist_ok=True)
    (output_dir / "previews").mkdir(exist_ok=True)
    return _process_one(item, output_dir / "stickers", output_dir / "previews")


def finalize_set(
    output_dir: Path,
    theme_name: str = "simple_icon",
    set_name: str = "",
) -> Optional[str]:
    """
    Rebuild main.png / tab.png and upload.zip from whatever stickers currently
    exist in output_dir. Call after single-item regeneration. Returns zip path.
    """
    stickers_dir = output_dir / "stickers"
    sticker_paths = sorted(stickers_dir.glob("stamp_*.png")) if stickers_dir.exists() else []
    if not sticker_paths:
        return None
    _generate_themed_main_tab(sticker_paths, theme_name, set_name, output_dir)
    results = [GenerationResult(position=i + 1, success=True, sticker_path=str(p))
               for i, p in enumerate(sticker_paths)]
    return str(_build_zip(output_dir, stickers_dir, results))


def render_preview(item: StampItemSpec) -> Image.Image:
    """
    Render a single stamp in-memory (no disk write) for live preview.
    Returns an RGBA image fitted to the sticker spec.
    """
    photo = _load_image(Path(item.photo_path))
    big = photo.copy()
    big.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
    adj = Adjustments(zoom=item.zoom, offset_x=item.offset_x,
                      offset_y=item.offset_y, brightness=item.brightness)
    processor = CharacterProcessor(style=item.style, expression=item.expression)
    steps = processor.process(big, item.caption, item.text_style, adjustments=adj,
                              overrides=item.overrides, decorations=item.decorations)
    stamp = steps.stamp.copy()
    stamp.thumbnail((STICKER_MAX_W, STICKER_MAX_H), Image.Resampling.LANCZOS)
    return stamp


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
        # Keep enough resolution for face detection; downscale very large photos
        big = photo.copy()
        big.thumbnail((1200, 1200), Image.Resampling.LANCZOS)

        stage = "character"
        adj = Adjustments(
            zoom=item.zoom, offset_x=item.offset_x,
            offset_y=item.offset_y, brightness=item.brightness,
        )
        processor = CharacterProcessor(style=item.style, expression=item.expression)
        steps = processor.process(big, item.caption, item.text_style, adjustments=adj,
                              overrides=item.overrides, decorations=item.decorations)

        stage = "quality"
        warnings = analyze_quality(big, steps.face_info, item.caption, item.text_style)

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
            warnings=warnings,
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


# ---------------------------------------------------------------------------
# Themed main.png / tab.png
# ---------------------------------------------------------------------------

def _generate_themed_main_tab(
    sticker_paths: list[Path],
    theme_name: str,
    set_name: str,
    output_dir: Path,
) -> None:
    """
    main.png (240×240): theme-colored background + up to 3 sticker thumbnails + set name.
    tab.png  (96×74):   first sticker as a clean circular icon, no text.
    """
    if not sticker_paths:
        return

    try:
        from .stamp_themes import THEMES
        cfg = THEMES.get(theme_name)
        bg_color = cfg.main_bg if cfg else (60, 60, 90, 255)
    except Exception:
        bg_color = (60, 60, 90, 255)

    # ── main.png ────────────────────────────────────────────────────────────
    main = Image.new("RGBA", (MAIN_W, MAIN_H), bg_color)
    shown = sticker_paths[:3]

    if len(shown) == 1:
        _paste_thumb(main, shown[0], 150, (MAIN_W // 2, 100))
    elif len(shown) == 2:
        for i, p in enumerate(shown):
            _paste_thumb(main, p, 100, (60 + i * 120, 100))
    else:
        _paste_thumb(main, shown[0], 100, (60, 80))
        _paste_thumb(main, shown[1], 100, (180, 80))
        _paste_thumb(main, shown[2], 90,  (120, 170))

    # Set name text at bottom
    if set_name:
        font_size = auto_font_size(set_name, 220, base_size=22, min_size=10)
        font = load_font(font_size)
        draw = ImageDraw.Draw(main)
        bbox = draw.textbbox((0, 0), set_name, font=font)
        tw = bbox[2] - bbox[0]
        tx = (MAIN_W - tw) // 2
        ty = MAIN_H - (bbox[3] - bbox[1]) - 8
        _draw_outlined_text(draw, (tx, ty), set_name, font,
                            fill=(255, 255, 255, 255),
                            stroke_fill=(0, 0, 0, 180),
                            stroke_width=2)

    main.save(output_dir / "main.png", "PNG")

    # ── tab.png ─────────────────────────────────────────────────────────────
    tab = Image.new("RGBA", (TAB_W, TAB_H), (0, 0, 0, 0))
    _paste_thumb(tab, sticker_paths[0], min(TAB_W, TAB_H) - 4, (TAB_W // 2, TAB_H // 2))
    tab.save(output_dir / "tab.png", "PNG")


def _paste_thumb(canvas: Image.Image, src: Path, size: int, center: tuple[int, int]) -> None:
    """Load *src*, thumbnail to *size*, paste centered at *center* on *canvas*."""
    try:
        img = Image.open(src).convert("RGBA")
        img.thumbnail((size, size), Image.Resampling.LANCZOS)
        x = center[0] - img.width // 2
        y = center[1] - img.height // 2
        canvas.paste(img, (x, y), img)
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
