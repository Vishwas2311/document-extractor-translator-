"""Apply and validate translation review decisions against bilingual artifacts."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

from app.core.exceptions import ConflictError, InvalidDocumentError
from app.schemas.translation_review import TranslationCorrection, TranslationReviewCreate


TRANSLATION_REVIEW_SCHEMA_VERSION = "translation-review-1.0"
REVIEWED_BILINGUAL_PATH = "exports/reviewed-bilingual-document.json"


def bilingual_result_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def apply_translation_corrections(
    bilingual: dict[str, Any],
    corrections: list[TranslationCorrection],
) -> dict[str, Any]:
    """Return a deep-copied bilingual document with reviewer corrections applied."""
    reviewed = deepcopy(bilingual)
    blocks = {
        str(block.get("block_id")): block
        for block in reviewed.get("blocks", [])
        if isinstance(block, dict) and block.get("block_id")
    }
    cells: dict[str, dict[str, Any]] = {}
    for table in reviewed.get("tables", []):
        if not isinstance(table, dict):
            continue
        for cell in table.get("cells", []):
            if isinstance(cell, dict) and cell.get("cell_id"):
                cells[str(cell["cell_id"])] = cell

    for correction in corrections:
        if correction.target_kind == "block":
            target = blocks.get(correction.target_id)
            if target is None:
                raise InvalidDocumentError(
                    f"Unknown translation block id: {correction.target_id}"
                )
            target["translated_text"] = correction.corrected_translated_text
            target["review_required"] = False
            warnings = list(target.get("warnings") or [])
            warnings.append(f"Reviewer correction: {correction.reason}")
            target["warnings"] = warnings
        else:
            target = cells.get(correction.target_id)
            if target is None:
                raise InvalidDocumentError(
                    f"Unknown translation cell id: {correction.target_id}"
                )
            target["translated_content"] = correction.corrected_translated_text
            target["review_required"] = False
            warnings = list(target.get("warnings") or [])
            warnings.append(f"Reviewer correction: {correction.reason}")
            target["warnings"] = warnings
    reviewed["review_schema_version"] = TRANSLATION_REVIEW_SCHEMA_VERSION
    return reviewed


def unresolved_review_targets(bilingual: dict[str, Any]) -> set[tuple[str, str]]:
    unresolved: set[tuple[str, str]] = set()
    for block in bilingual.get("blocks", []):
        if isinstance(block, dict) and block.get("review_required"):
            unresolved.add(("block", str(block.get("block_id"))))
    for table in bilingual.get("tables", []):
        if not isinstance(table, dict):
            continue
        for cell in table.get("cells", []):
            if isinstance(cell, dict) and cell.get("review_required"):
                unresolved.add(("cell", str(cell.get("cell_id"))))
    return unresolved


def validate_translation_approval(
    bilingual: dict[str, Any],
    review: TranslationReviewCreate,
) -> None:
    if review.decision != "approved":
        return
    reviewed = apply_translation_corrections(bilingual, review.corrections)
    remaining = unresolved_review_targets(reviewed)
    if remaining:
        raise ConflictError(
            "Every review-required translation target needs a correction before approval."
        )
