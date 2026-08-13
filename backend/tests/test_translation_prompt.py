"""Guards against the translation prompt's block_id guidance silently drifting
out of sync with the real ID scheme documents actually get.

Regression: the prompt hardcoded an example ID shape (t####-c####) that matched
only small, un-ranged documents. Large documents (over di_page_range_size pages)
get IDs reassigned by assign_stable_ids() to a different, page-stable scheme
(p####-b####/p####-t####-c####) - the prompt was never updated to match, so the
model was shown a wrong example of its own input IDs for exactly the document
size where this was failing. Found via RCA on 2026-08-13 after a real 164-page
document showed systemic "Translation IDs did not match the input batch" errors.
"""

import re

from app.prompts.translation import TRANSLATION_DEVELOPER_PROMPT, TRANSLATION_PROMPT_VERSION
from app.schemas.page import BoundingRegion, CanonicalDocument, PageMetadata, TableCell, TableResult
from app.services.di_ranges import assign_stable_ids

# Pinned to the version in place before the CJK consistency guidance was added. If this
# fails, the prompt text changed without bumping TRANSLATION_PROMPT_VERSION - the
# translation cache key in processing.py is derived from this version string, so
# skipping the bump would silently keep serving stale cached translations under the
# old prompt forever, and the new guidance would never take effect.
_PRIOR_VERSION = "translation-v3-multilingual-format-aware"

# A rigid, single hardcoded ID-shape example (e.g. "t####-c####") is exactly what
# drifted silently before - the prompt must describe block_id handling generically
# instead of asserting one canonical shape as if it were the only one.
_RIGID_SHAPE_CLAIM_RE = re.compile(r"shaped like", re.IGNORECASE)

# Matches assign_stable_ids()'s real output format for both un-ranged (small
# document) and ranged (large document, page-stable) ID schemes.
_VALID_ID_SHAPE_RE = re.compile(r"^p\d{4}-t\d{4}-c\d{4}$|^t\d{4}-c\d{4}$")

# Any token in the prompt that looks like it's meant to illustrate a table-cell
# block_id shape (contains digits, a 't', and a 'c' segment joined by hyphens).
_EXAMPLE_ID_TOKEN_RE = re.compile(r"\b(?:p\d{4}-)?t\d{4}-c\d{4}\b")


def _normalized(text: str) -> str:
    return " ".join(text.split())


def test_prompt_version_was_bumped_for_the_cjk_consistency_guidance() -> None:
    assert TRANSLATION_PROMPT_VERSION != _PRIOR_VERSION


def test_prompt_includes_script_preservation_and_consistency_guidance() -> None:
    assert "Traditional" in TRANSLATION_DEVELOPER_PROMPT
    assert "Simplified" in TRANSLATION_DEVELOPER_PROMPT
    assert "identically every time" in TRANSLATION_DEVELOPER_PROMPT


def test_prompt_does_not_assert_a_single_rigid_id_shape() -> None:
    assert not _RIGID_SHAPE_CLAIM_RE.search(TRANSLATION_DEVELOPER_PROMPT)


def test_prompt_instructs_verbatim_id_echo() -> None:
    # The actual fix for the ID-mismatch bug: an explicit, scheme-agnostic
    # instruction to copy block_id back exactly, regardless of its shape.
    # Whitespace-normalized since the prompt is a wrapped multi-line string.
    normalized = _normalized(TRANSLATION_DEVELOPER_PROMPT)
    assert "opaque identifier" in normalized
    assert "copy it back exactly as given" in normalized


def test_prompts_example_cell_ids_match_the_current_id_scheme() -> None:
    # Every example ID token the prompt uses to illustrate "this is a table
    # cell" must match a shape assign_stable_ids() can actually produce today -
    # not a stale example from a scheme that no longer exists. Extracts the
    # example tokens from the prompt text itself, rather than hardcoding one
    # expected string, so this doesn't need updating every time the prompt's
    # wording changes - only if the *scheme* changes without updating examples.
    example_tokens = _EXAMPLE_ID_TOKEN_RE.findall(TRANSLATION_DEVELOPER_PROMPT)
    assert example_tokens, "Prompt has no recognizable table-cell ID example at all."
    for token in example_tokens:
        assert _VALID_ID_SHAPE_RE.match(token), (
            f"Prompt's example cell ID {token!r} doesn't match any real ID shape "
            "assign_stable_ids() (or the un-ranged mapper path) actually produces."
        )


def test_assign_stable_ids_real_cell_output_matches_the_scheme_the_prompt_documents() -> None:
    # The other direction: prove the regex the prompt's examples are checked
    # against is actually what the real function outputs today, not a made-up
    # pattern that happens to also be wrong.
    document = CanonicalDocument(
        document_id="doc-prompt-check",
        filename="sample.pdf",
        status="normalizing",
        pages=[PageMetadata(page_number=161, page_count=164, width=8.5, height=11, unit="inch")],
        tables=[
            TableResult(
                table_id="t0001",
                row_count=1,
                column_count=1,
                bounding_regions=[BoundingRegion(page_number=161, polygon=[])],
                cells=[
                    TableCell(cell_id="unassigned", row_index=0, column_index=0, content="x")
                ],
            )
        ],
    )
    stable = assign_stable_ids(document)
    real_cell_id = stable.tables[0].cells[0].cell_id
    assert _VALID_ID_SHAPE_RE.match(real_cell_id), real_cell_id
