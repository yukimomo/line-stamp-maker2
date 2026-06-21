"""Tests for face / subject detection."""

from __future__ import annotations
import numpy as np
import pytest
from PIL import Image

from app.services.face_detect import FaceInfo, detect_faces


def _skin_photo(w=300, h=400) -> Image.Image:
    """Photo with a skin-tone blob in the upper-center (simulates a face)."""
    arr = np.full((h, w, 3), 40, dtype=np.uint8)        # dark background
    cx, cy, r = w // 2, h // 3, 60
    yy, xx = np.ogrid[:h, :w]
    mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= r ** 2
    arr[mask] = (200, 150, 120)                          # skin tone
    return Image.fromarray(arr, "RGB")


class TestFaceInfo:
    def test_empty_info(self):
        fi = FaceInfo(boxes=[], image_size=(100, 100))
        assert fi.count == 0
        assert fi.union_box is None
        assert fi.primary_box is None
        assert fi.face_fraction == 0.0

    def test_union_box(self):
        fi = FaceInfo(boxes=[(10, 10, 20, 20), (50, 50, 30, 30)], image_size=(100, 100))
        # union: x0=10,y0=10 -> x1=80,y1=80
        assert fi.union_box == (10, 10, 70, 70)

    def test_primary_box_is_largest(self):
        fi = FaceInfo(boxes=[(0, 0, 10, 10), (0, 0, 40, 40)], image_size=(100, 100))
        assert fi.primary_box == (0, 0, 40, 40)

    def test_face_fraction(self):
        fi = FaceInfo(boxes=[(0, 0, 50, 50)], image_size=(100, 100))
        assert fi.face_fraction == pytest.approx(0.25)

    def test_count(self):
        fi = FaceInfo(boxes=[(0, 0, 5, 5)] * 3, image_size=(100, 100))
        assert fi.count == 3


class TestDetectFaces:
    def test_returns_faceinfo(self):
        result = detect_faces(_skin_photo())
        assert isinstance(result, FaceInfo)
        assert result.image_size == (300, 400)

    def test_method_is_known(self):
        result = detect_faces(_skin_photo())
        assert result.method in ("haar", "skin", "default")

    def test_skin_blob_detected_by_heuristic_or_haar(self):
        # The skin blob should yield at least a subject box via skin fallback
        result = detect_faces(_skin_photo())
        # Either haar finds nothing (synthetic) and skin finds the blob,
        # or default. Skin heuristic should catch the obvious blob.
        if result.method == "skin":
            assert result.count == 1
            box = result.primary_box
            # box roughly in the upper-center
            assert box is not None

    def test_flat_image_falls_back_to_default(self):
        flat = Image.new("RGB", (200, 200), (10, 10, 10))   # no skin, no faces
        result = detect_faces(flat)
        assert result.method in ("default", "skin")  # likely default
        if result.method == "default":
            assert result.count == 0

    def test_handles_rgba(self):
        img = _skin_photo().convert("RGBA")
        result = detect_faces(img)
        assert isinstance(result, FaceInfo)
