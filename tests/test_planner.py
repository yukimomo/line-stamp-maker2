"""Tests for the AI stamp-set planner (rule-based)."""

from __future__ import annotations
import pytest
from PIL import Image

from app.services.planner import (
    SCENES, MOODS, ALLOWED_COUNTS, PlannerInput, PlannerResult,
    RuleBasedPlanner, generate_plan, check_phrases, recommend_photos,
)


class TestPlanGeneration:
    @pytest.mark.parametrize("scene", list(SCENES.keys()))
    def test_every_scene_produces_plan(self, scene):
        r = generate_plan(PlannerInput(scene=scene, mood="cute", count=8))
        assert isinstance(r, PlannerResult)
        assert r.title and r.description and r.category
        assert r.tags and r.preset and r.theme

    @pytest.mark.parametrize("count", list(ALLOWED_COUNTS))
    def test_phrase_count_matches(self, count):
        r = generate_plan(PlannerInput(scene="family", count=count))
        assert len(r.phrases) == count

    def test_invalid_count_falls_back(self):
        r = generate_plan(PlannerInput(scene="family", count=11))
        assert len(r.phrases) == 8

    def test_mood_changes_preset(self):
        cute = generate_plan(PlannerInput(scene="family", mood="cute"))
        simple = generate_plan(PlannerInput(scene="family", mood="simple"))
        assert cute.preset != simple.preset

    def test_title_contains_mood(self):
        r = generate_plan(PlannerInput(scene="family", mood="cute"))
        assert MOODS["cute"] in r.title

    def test_work_scene_business(self):
        r = generate_plan(PlannerInput(scene="work", mood="simple"))
        assert r.category == "ビジネス"
        assert r.theme == "business_casual"

    def test_to_dict_has_all_keys(self):
        r = generate_plan(PlannerInput(scene="family"))
        d = r.to_dict()
        for k in ("title", "description", "category", "tags", "preset",
                  "phrases", "recommended_photos", "warnings"):
            assert k in d

    def test_planner_interface_subclassable(self):
        class DummyPlanner(RuleBasedPlanner):
            pass
        r = DummyPlanner().plan(PlannerInput(scene="pet"))
        assert r.phrases


class TestPhraseQuality:
    def test_exact_duplicate(self):
        w = check_phrases(["ありがとう", "ありがとう", "OK"])
        assert any("重複" in x for x in w)

    def test_near_duplicate(self):
        w = check_phrases(["了解", "了解です"])
        assert any("近い" in x for x in w)

    def test_too_long(self):
        w = check_phrases(["これはとても長すぎるセリフなので読みにくいです"])
        assert any("長すぎ" in x for x in w)

    def test_clean_no_warnings(self):
        w = check_phrases(["おはよう", "ありがとう", "おやすみ", "がんばって"])
        assert w == []


class TestPhotoRecommendation:
    def _photos(self):
        return [
            {"path": "high.jpg", "score": 0.95, "tags": ["smile", "happy"]},
            {"path": "group.jpg", "score": 0.8, "tags": ["group", "family"]},
            {"path": "plain.jpg", "score": 0.6, "tags": []},
        ]

    def test_returns_one_per_phrase(self):
        rec, main = recommend_photos(["ありがとう", "おつかれ", "おはよう"], self._photos())
        assert len(rec) == 3

    def test_main_is_highest_score(self):
        _, main = recommend_photos(["x"], self._photos())
        assert main == "high.jpg"

    def test_thanks_prefers_smile(self):
        rec, _ = recommend_photos(["ありがとう"], self._photos())
        assert rec[0] == "high.jpg"   # smile-tagged, also highest score

    def test_empty_photos(self):
        rec, main = recommend_photos(["x", "y"], [])
        assert rec == [] and main is None

    def test_cycles_when_fewer_photos(self):
        rec, _ = recommend_photos(["a", "b", "c", "d", "e"], self._photos()[:2])
        assert len(rec) == 5


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@pytest.fixture
def app_with_photos(tmp_path):
    from app import create_app
    selected = tmp_path / "selected"
    selected.mkdir()
    for i in range(8):
        Image.new("RGB", (300, 400), (180, 140 + i * 5, 110)).save(selected / f"p{i}.jpg", "JPEG")
    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "t.db"),
        "OUTPUT_DIR": str(tmp_path / "out"),
        "PHOTO_SELECTOR_MANIFEST": str(tmp_path / "no.json"),
        "PHOTO_SELECTOR_SELECTED_DIR": str(selected),
    })
    app._photos = [str(selected / f"p{i}.jpg") for i in range(8)]
    return app


@pytest.fixture
def client(app_with_photos):
    return app_with_photos.test_client()


class TestPlannerRoutes:
    def test_planner_page(self, client):
        r = client.get("/planner")
        assert r.status_code == 200
        assert "プランナー".encode("utf-8") in r.data

    def test_generate_preview(self, client):
        r = client.post("/planner/generate",
                        data={"scene": "family", "mood": "cute", "count": 8})
        assert r.status_code == 200
        # preview shows the auto title and the phrase grid
        assert "セット案".encode("utf-8") in r.data

    def test_generate_phrase_count(self, client):
        r = client.post("/planner/generate",
                        data={"scene": "work", "mood": "simple", "count": 16})
        html = r.data.decode("utf-8")
        assert html.count('name="caption_') == 16

    def test_one_click_create_generates(self, client, app_with_photos):
        data = {"title": "テスト企画", "description": "せつめい", "theme": "family_pop",
                "preset": "pastel_pop", "count": 8}
        for i in range(1, 9):
            data[f"caption_{i}"] = f"セリフ{i}"
            data[f"photo_{i}"] = app_with_photos._photos[i - 1]
        r = client.post("/planner/create", data=data)
        assert r.status_code == 302   # redirect to detail
        with app_with_photos.app_context():
            from app.db import get_db
            db = get_db()
            s = db.execute("SELECT * FROM stamp_sets ORDER BY id DESC LIMIT 1").fetchone()
            assert s["name"] == "テスト企画"
            assert s["preset_key"] == "pastel_pop"
            assert s["status"] in ("generated", "partial")
            assert s["zip_path"]
            n = db.execute("SELECT COUNT(*) c FROM stamp_items WHERE set_id=?", (s["id"],)).fetchone()["c"]
            assert n == 8

    def test_create_without_photos_redirects_to_planner(self, client):
        data = {"title": "X", "theme": "family_pop", "preset": "pastel_pop", "count": 8}
        # no photo_* fields
        r = client.post("/planner/create", data=data)
        assert r.status_code == 302
        assert "/planner" in r.headers["Location"]

    def test_existing_create_unaffected(self, client, app_with_photos):
        # The classic /stamps create flow still works
        data = {"name": "従来", "theme": "family_pop", "stamp_count": 8}
        for i in range(1, 9):
            data[f"photo_{i}"] = app_with_photos._photos[i - 1]
        r = client.post("/stamps", data=data)
        assert r.status_code == 302
