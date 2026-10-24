"""Fleet UI consumers use feature contracts instead of reaching private owners."""

from pathlib import Path
import json
import re


WEB = Path(__file__).resolve().parents[3] / "applications" / "fleet" / "web"


def test_console_does_not_reach_into_roster_trip_state():
    source = (WEB / "console.js").read_text(encoding="utf8")
    assert not re.search(r"\broster\.trip\b", source), "trip form lifetime belongs to roster"


def test_roster_styles_belong_to_the_console_feature_and_are_served():
    from test_site_map_api import _client

    registry = json.loads((WEB / "assets.json").read_text(encoding="utf8"))
    assert registry["assets"].get("roster.css") == {"path": "roster.css", "media_type": "text/css"}
    response = _client().get("/console/assets/roster.css")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    assert 'href="/console/assets/roster.css"' in (WEB / "index.html").read_text(encoding="utf8")
    common = (WEB / "shared" / "styles.css").read_text(encoding="utf8")
    assert not re.search(r"\.(?:roster(?:-block)?|robot-summary(?:-[\w-]+)?|card-trip)\b"
                         r"|#robot-(?:choice|workspace)\b|\.robot(?=[\s.:\[{])", common)
