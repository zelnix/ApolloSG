"""Copy the ApolloSG User Guide to the app after editing it.

The guide is written once, in backend/services/higgins/user_guide.json (what Higgins reads).
The app's User Guide screen bundles an exact copy so it works offline:
    cd backend && python scripts/sync_user_guide.py
"""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "backend/services/higgins/user_guide.json"
COPY = ROOT / "frontend/src/guide/userGuide.json"

json.loads(SOURCE.read_text(encoding="utf-8"))  # refuse to copy a broken file
COPY.parent.mkdir(parents=True, exist_ok=True)
shutil.copyfile(SOURCE, COPY)
print(f"User Guide copied to {COPY.relative_to(ROOT)}")
