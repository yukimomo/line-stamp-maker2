"""
Face / subject region detection for stamp framing.

Primary: OpenCV Haar cascade (if cv2 is installed).
Fallback: NumPy skin-tone heuristic (always available).
Final fallback: upper-center default box.

All public functions accept and return values in terms of a PIL image so the
rest of the pipeline never touches cv2 directly.
"""

from __future__ import annotations
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

# ---------------------------------------------------------------------------
# Optional cv2
# ---------------------------------------------------------------------------

try:
    import cv2
    _CASCADE = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    _HAS_CV2 = not _CASCADE.empty()
except Exception:
    _HAS_CV2 = False
    _CASCADE = None


@dataclass
class FaceInfo:
    """Result of subject/face analysis on a photo."""
    boxes: list[tuple[int, int, int, int]] = field(default_factory=list)  # (x,y,w,h)
    image_size: tuple[int, int] = (0, 0)                                  # (w,h)
    method: str = "default"   # "haar" | "skin" | "default"

    @property
    def count(self) -> int:
        return len(self.boxes)

    @property
    def union_box(self) -> tuple[int, int, int, int] | None:
        """Bounding box covering all detected faces."""
        if not self.boxes:
            return None
        x0 = min(b[0] for b in self.boxes)
        y0 = min(b[1] for b in self.boxes)
        x1 = max(b[0] + b[2] for b in self.boxes)
        y1 = max(b[1] + b[3] for b in self.boxes)
        return (x0, y0, x1 - x0, y1 - y0)

    @property
    def primary_box(self) -> tuple[int, int, int, int] | None:
        """Largest face box."""
        if not self.boxes:
            return None
        return max(self.boxes, key=lambda b: b[2] * b[3])

    @property
    def face_fraction(self) -> float:
        """Largest face area as a fraction of the image area (0 if none)."""
        if not self.boxes or self.image_size == (0, 0):
            return 0.0
        pb = self.primary_box
        iw, ih = self.image_size
        return (pb[2] * pb[3]) / float(iw * ih)


def detect_faces(img: Image.Image) -> FaceInfo:
    """Detect faces / subject region in *img*."""
    w, h = img.size
    if _HAS_CV2:
        boxes = _detect_haar(img)
        if boxes:
            return FaceInfo(boxes=boxes, image_size=(w, h), method="haar")

    skin_box = _detect_skin_region(img)
    if skin_box is not None:
        return FaceInfo(boxes=[skin_box], image_size=(w, h), method="skin")

    return FaceInfo(boxes=[], image_size=(w, h), method="default")


# ---------------------------------------------------------------------------
# Haar cascade
# ---------------------------------------------------------------------------

def _detect_haar(img: Image.Image) -> list[tuple[int, int, int, int]]:
    rgb = np.array(img.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    h, w = gray.shape
    min_side = max(30, int(min(w, h) * 0.06))   # ignore tiny false positives

    raw = _CASCADE.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=6, minSize=(min_side, min_side)
    )
    boxes = [(int(x), int(y), int(bw), int(bh)) for (x, y, bw, bh) in raw]

    # Drop boxes far smaller than the largest (likely false positives)
    if boxes:
        max_area = max(b[2] * b[3] for b in boxes)
        boxes = [b for b in boxes if b[2] * b[3] >= max_area * 0.25]
    return boxes


# ---------------------------------------------------------------------------
# Skin-tone heuristic (NumPy, no cv2)
# ---------------------------------------------------------------------------

def _detect_skin_region(img: Image.Image) -> tuple[int, int, int, int] | None:
    """
    Estimate a subject bounding box via skin-tone masking.
    Returns the bounding box of the largest skin blob, or None.
    """
    small = img.convert("RGB")
    w0, h0 = small.size
    scale = 240 / max(w0, h0) if max(w0, h0) > 240 else 1.0
    if scale < 1.0:
        small = small.resize((max(1, int(w0 * scale)), max(1, int(h0 * scale))))
    arr = np.asarray(small).astype(np.int32)
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]

    # Simple RGB skin rule
    mask = (
        (r > 95) & (g > 40) & (b > 20)
        & ((np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b)) > 15)
        & (np.abs(r - g) > 15) & (r > g) & (r > b)
    )
    if mask.sum() < (mask.size * 0.01):
        return None

    ys, xs = np.where(mask)
    # Use percentiles to ignore scattered noise
    x0, x1 = np.percentile(xs, 5), np.percentile(xs, 95)
    y0, y1 = np.percentile(ys, 5), np.percentile(ys, 95)
    inv = 1.0 / scale
    return (
        int(x0 * inv), int(y0 * inv),
        int((x1 - x0) * inv), int((y1 - y0) * inv),
    )
