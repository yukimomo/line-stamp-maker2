"""
Per-image quality / framing warnings for the set-preview screen.

Operates on the enhanced source image + face detection results, so warnings
reflect what the user can fix (reframe, swap photo, change template).
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from .face_detect import FaceInfo

# Thresholds
FACE_SMALL_FRAC = 0.045     # largest face < this fraction of image area
EDGE_MARGIN_FRAC = 0.02     # how close to the edge counts as "cut off"
DARK_MEAN = 70              # mean luma below this = too dark
BLUR_VAR = 60.0             # laplacian-like variance below this = soft/blurry
LOWRES_MIN = 400            # min(width,height) below this = low resolution


def analyze_quality(
    img: Image.Image,
    face_info: FaceInfo | None,
    caption: str = "",
    text_style: str = "pop",
) -> list[str]:
    """Return a list of human-readable warning strings (may be empty)."""
    warnings: list[str] = []
    w, h = img.size

    # ── resolution ──
    if min(w, h) < LOWRES_MIN:
        warnings.append("画像が粗いです（解像度が低い）")

    # ── brightness ──
    mean = _mean_luma(img)
    if mean < DARK_MEAN:
        warnings.append("写真が暗すぎます（bright_frame テンプレート推奨）")

    # ── sharpness ──
    if _sharpness(img) < BLUR_VAR:
        warnings.append("ピントが甘い・ブレている可能性があります")

    # ── face-related ──
    if face_info is not None and face_info.count > 0:
        # too small
        if face_info.face_fraction < FACE_SMALL_FRAC:
            warnings.append("顔が小さすぎます（ズームで拡大できます）")

        # cut off at edge
        if _box_touches_edge(face_info.primary_box, w, h):
            warnings.append("顔が見切れています（位置調整してください）")

        # multi-person partly cut
        if face_info.count >= 2 and _box_touches_edge(face_info.union_box, w, h):
            warnings.append(f"複数人（{face_info.count}人）の一部が見切れています")

        # text overlapping a very large face
        if caption and face_info.face_fraction > 0.55 and text_style != "bubble":
            warnings.append("文字が顔に被る可能性があります")
    elif face_info is not None and face_info.method == "default":
        warnings.append("顔を検出できませんでした（中央トリミングを使用）")

    return warnings


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _mean_luma(img: Image.Image) -> float:
    arr = np.asarray(img.convert("RGB")).astype(np.float32)
    luma = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
    return float(luma.mean())


def _sharpness(img: Image.Image) -> float:
    """Variance of a Laplacian-like high-pass — higher = sharper."""
    small = img.convert("L")
    if max(small.size) > 320:
        scale = 320 / max(small.size)
        small = small.resize((max(1, int(small.width * scale)),
                              max(1, int(small.height * scale))))
    a = np.asarray(small).astype(np.float32)
    # 4-neighbour Laplacian
    lap = (
        -4 * a
        + np.roll(a, 1, 0) + np.roll(a, -1, 0)
        + np.roll(a, 1, 1) + np.roll(a, -1, 1)
    )
    return float(lap.var())


def _box_touches_edge(box: tuple[int, int, int, int] | None, w: int, h: int) -> bool:
    if box is None:
        return False
    x, y, bw, bh = box
    m = int(min(w, h) * EDGE_MARGIN_FRAC)
    return x <= m or y <= m or (x + bw) >= (w - m) or (y + bh) >= (h - m)
