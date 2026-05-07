from __future__ import annotations

import json
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app import main  # noqa: E402
from app.services.demo_seed_service import seed_demo_data  # noqa: E402


def run() -> dict[str, object]:
    return seed_demo_data(
        auth_store=main.auth_store,
        osce_service=main.osce_session_service,
        candidate_store=main.training_skill_candidate_store,
        reviewer_email=main._get_demo_admin_email(),
        admin_email=main._get_demo_admin_email(),
        admin_password=main._get_demo_admin_password(),
    )


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
