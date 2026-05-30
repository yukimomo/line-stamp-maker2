"""Generate LINE stamp images from photos.

Uses line-stamp-maker's ImageProcessor when available (high quality:
MediaPipe segmentation + custom fonts).  Falls back to a pure-Pillow
implementation so the app works even without the optional dependencies.
"""

from __future__ import annotations
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image

# ---------------------------------------------------------------------------
# Optional: import line-stamp-maker from its sibling directory
# ---------------------------------------------------------------------------
_LSM_ROOT = Path(__file__).resolve().parents[3] / "line-stamp-maker"
if _LSM_ROOT.exists() and str(_LSM_ROOT) not in sys.path:
    sys.path.insert(0, str(_LSM_ROOT))

try:
    from line_stamp_maker.image_processor import ImageProcessor  # type: ignore
    from line_stamp_maker.config import ProcessingConfig, ImageConfig, TextConfig  # type: ignore
    _HAS_LSM = True
except ImportError:
    _HAS_LSM = False

# ---------------------------------------------------------------------------
# LINE Creators Market spec constants
# ---------------------------------------------------------------------------
STICKER_MAX_W = 370
STICKER_MAX_H = 320
MAIN_W = 240
MAIN_H = 240
TAB_W = 96
TAB_H = 74
MAX_STICKER_BYTES = 1_000_000


@dataclass
class StampItemSpec:
    position: int          # 1-8
    photo_path: str
    caption: str = ""


@dataclass
class GenerationResult:
    position: int
    success: bool
    sticker_path: Optional[str] = None
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


def generate_stamp_set(
    items: list[StampItemSpec],
    output_dir: Path,
    font_preset: str = "kiwi",
    use_segmentation: bool = True,
) -> GenerationSummary:
    """
    Generate a complete LINE stamp set (8 stickers + main + tab + ZIP).

    Args:
        items: List of StampItemSpec (8 items expected)
        output_dir: Directory to write output files into
        font_preset: Font preset for line-stamp-maker
        use_segmentation: Whether to use MediaPipe person segmentation
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    stickers_dir = output_dir / "stickers"
    stickers_dir.mkdir(exist_ok=True)

    if _HAS_LSM:
        try:
            results = _generate_with_lsm(items, output_dir, stickers_dir, font_preset, use_segmentation)
        except Exception as exc:
            # MediaPipe / LSM initialization can crash on some platforms; fall back gracefully.
            results = _generate_fallback(items, output_dir, stickers_dir)
    else:
        results = _generate_fallback(items, output_dir, stickers_dir)

    zip_path: Optional[Path] = None
    if any(r.success for r in results):
        zip_path = _build_zip(output_dir, stickers_dir, results)

    return GenerationSummary(
        set_output_dir=str(output_dir),
        zip_path=str(zip_path) if zip_path else None,
        results=results,
    )


# ---------------------------------------------------------------------------
# High-quality path: line-stamp-maker ImageProcessor
# ---------------------------------------------------------------------------

def _generate_with_lsm(
    items: list[StampItemSpec],
    output_dir: Path,
    stickers_dir: Path,
    font_preset: str,
    use_segmentation: bool,
) -> list[GenerationResult]:
    image_config = ImageConfig(
        sticker_max_width=STICKER_MAX_W,
        sticker_max_height=STICKER_MAX_H,
        main_width=MAIN_W,
        main_height=MAIN_H,
        tab_width=TAB_W,
        tab_height=TAB_H,
    )
    text_config = TextConfig(
        font_preset=font_preset,
        font_size=36,
        caption_style="bubble",
        caption_outline_px=8,
    )
    config = ProcessingConfig(
        image_config=image_config,
        text_config=text_config,
        photos_dir=output_dir,
        mapping_file=output_dir / "_mapping.csv",
        output_dir=output_dir,
        use_segmentation=use_segmentation,
        create_zip=False,
    )
    processor = ImageProcessor(config)

    results: list[GenerationResult] = []
    main_saved = False
    tab_saved = False

    for item in items:
        photo_path = Path(item.photo_path)
        pos_str = f"stamp_{item.position:02d}"
        debug_errors: dict = {}

        sticker, main_img, tab_img = processor.process_image(photo_path, item.caption, debug_errors)

        if sticker is None:
            err = debug_errors.get("error", {})
            results.append(
                GenerationResult(
                    position=item.position,
                    success=False,
                    error=err.get("message", "Unknown error"),
                    error_stage=err.get("stage"),
                )
            )
            continue

        sticker_path = stickers_dir / f"{pos_str}.png"
        sticker.save(sticker_path, "PNG")

        if not main_saved and main_img is not None:
            main_img.save(output_dir / "main.png", "PNG")
            main_saved = True
        if not tab_saved and tab_img is not None:
            tab_img.save(output_dir / "tab.png", "PNG")
            tab_saved = True

        results.append(
            GenerationResult(position=item.position, success=True, sticker_path=str(sticker_path))
        )

    return results


# ---------------------------------------------------------------------------
# Fallback path: pure Pillow (no segmentation)
# ---------------------------------------------------------------------------

def _generate_fallback(
    items: list[StampItemSpec],
    output_dir: Path,
    stickers_dir: Path,
) -> list[GenerationResult]:
    results: list[GenerationResult] = []
    main_saved = False
    tab_saved = False

    for item in items:
        photo_path = Path(item.photo_path)
        pos_str = f"stamp_{item.position:02d}"
        try:
            img = _load_image_pil(photo_path).convert("RGBA")
            img.thumbnail((STICKER_MAX_W, STICKER_MAX_H), Image.Resampling.LANCZOS)

            if item.caption:
                img = _add_caption_pil(img, item.caption)

            sticker_path = stickers_dir / f"{pos_str}.png"
            img.save(sticker_path, "PNG")

            if not main_saved:
                _save_fitted(img, output_dir / "main.png", MAIN_W, MAIN_H)
                main_saved = True
            if not tab_saved:
                _save_fitted(img, output_dir / "tab.png", TAB_W, TAB_H)
                tab_saved = True

            results.append(
                GenerationResult(position=item.position, success=True, sticker_path=str(sticker_path))
            )
        except Exception as exc:
            results.append(
                GenerationResult(position=item.position, success=False, error=str(exc))
            )

    return results


def _load_image_pil(path: Path) -> Image.Image:
    if path.suffix.lower() in (".heic", ".heif"):
        try:
            from pillow_heif import register_heif_opener  # type: ignore
            register_heif_opener()
        except ImportError as exc:
            raise RuntimeError(
                "HEIC ファイルには pillow-heif が必要です: pip install pillow-heif"
            ) from exc
    return Image.open(path)


def _save_fitted(img: Image.Image, path: Path, w: int, h: int) -> None:
    fitted = img.copy()
    fitted.thumbnail((w, h), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    x = (w - fitted.width) // 2
    y = (h - fitted.height) // 2
    canvas.paste(fitted, (x, y), fitted)
    canvas.save(path, "PNG")


def _add_caption_pil(img: Image.Image, caption: str) -> Image.Image:
    """Add caption text with stroke at bottom of image (Pillow-only fallback)."""
    from PIL import ImageDraw, ImageFont

    draw = ImageDraw.Draw(img)
    w, h = img.size
    font_size = max(20, min(w, h) // 8)

    font: ImageFont.ImageFont | ImageFont.FreeTypeFont
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except OSError:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), caption, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (w - tw) // 2
    ty = h - th - 20

    # Stroke
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            if dx or dy:
                draw.text((tx + dx, ty + dy), caption, font=font, fill=(0, 0, 0, 255))
    draw.text((tx, ty), caption, font=font, fill=(255, 255, 255, 255))

    return img


# ---------------------------------------------------------------------------
# ZIP builder
# ---------------------------------------------------------------------------

def _build_zip(
    output_dir: Path,
    stickers_dir: Path,
    results: list[GenerationResult],
) -> Path:
    """Build upload.zip in LINE Creators Market format."""
    zip_path = output_dir / "upload.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for result in results:
            if result.success and result.sticker_path:
                p = Path(result.sticker_path)
                if p.exists():
                    zf.write(p, p.name)

        for fname in ("main.png", "tab.png"):
            p = output_dir / fname
            if p.exists():
                zf.write(p, fname)

    return zip_path
