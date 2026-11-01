"""The server's Higgins Luddish words every line exactly as the app's does (content/luddish.json is generated from the
app's Luddish and carries the parity corpus; frontend tests/luddishShared.test.ts keeps that file current)."""
import json
from pathlib import Path

import pytest

from services.higgins.luddish import luddish_text

PARITY = json.loads((Path(__file__).resolve().parents[1] / "content" / "luddish.json").read_text(encoding="utf-8"))["parity"]


@pytest.mark.parametrize("case", PARITY, ids=[c["text"][:40] for c in PARITY])
def test_same_words_as_the_app(case):
    assert luddish_text(case["text"], case["strong"]) == case["out"]
