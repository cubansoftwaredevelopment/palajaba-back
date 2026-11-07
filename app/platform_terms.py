import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException

TERMS_REQUIRED_DETAIL = "Debes aceptar los términos y condiciones."


@lru_cache
def current_terms() -> dict:
    path = Path(__file__).with_name("platform_terms_sections.json")
    return json.loads(path.read_text(encoding="utf-8"))


PLATFORM_TERMS_VERSION = current_terms()["version"]


def platform_terms_snapshot(now: datetime) -> dict:
    document = current_terms()
    return {
        "version": document["version"],
        "attached_at": now,
        "sections": document["sections"],
    }


def acceptance_record(accepted: bool, now: datetime) -> dict:
    if not accepted:
        raise HTTPException(status_code=400, detail=TERMS_REQUIRED_DETAIL)
    return {"terms_accepted_at": now, "terms_version": PLATFORM_TERMS_VERSION}


def stored_acceptance(document: dict) -> dict:
    accepted_at = document.get("terms_accepted_at")
    version = document.get("terms_version")
    if not accepted_at or not version:
        raise HTTPException(status_code=400, detail=TERMS_REQUIRED_DETAIL)
    return {"terms_accepted_at": accepted_at, "terms_version": version}
