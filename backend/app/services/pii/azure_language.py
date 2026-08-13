"""Azure AI Language multilingual PII detector (fail-closed).

Targets Azure AI Language's PII recognition, which covers many languages beyond
what regex can (Arabic, Simplified/Traditional Chinese, Hindi, etc.). This adapter
is the production path for ``PII_DETECTION_MODE=multilingual``.

Fail-closed contract: if the service is not configured, unreachable, or returns an
error, detection raises ``PolicyBlockedError`` so the caller must abort before any
content reaches the generative provider. It never returns "no PII" on failure.

The Azure SDK is imported lazily so the rest of the app runs without the optional
dependency installed. A ``recognizer`` callable can be injected for testing and to
keep the SDK-specific mapping isolated.
"""

from __future__ import annotations

import bisect
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING

from app.core.exceptions import PolicyBlockedError
from app.services.pii.base import PiiSpan

if TYPE_CHECKING:
    # Only for type-checking - the real azure-ai-textanalytics/azure-identity
    # SDKs are imported lazily at runtime (see _default_recognizer/_credential)
    # so the rest of the app runs without the optional dependency installed.
    from azure.core.credentials import AzureKeyCredential
    from azure.core.credentials_async import AsyncTokenCredential

Recognizer = Callable[[list[dict[str, str]]], Awaitable[list[list[PiiSpan]]]]


def utf16_code_unit_offsets(text: str) -> list[int]:
    """``offsets[i]`` is the UTF-16 code-unit position of Python (code-point)
    index ``i``; ``offsets[len(text)]`` is the text's total UTF-16 length.

    Azure AI Language reports entity offsets/lengths as UTF-16 code units,
    not Python string indices - identical for any text without astral-plane
    characters (the two only diverge once a character needs a UTF-16
    surrogate pair, i.e. ``ord(ch) > 0xFFFF``), but silently wrong for text
    containing rare emoji or CJK extension characters otherwise.
    """
    offsets = [0] * (len(text) + 1)
    position = 0
    for index, character in enumerate(text):
        offsets[index] = position
        position += 2 if ord(character) > 0xFFFF else 1
    offsets[len(text)] = position
    return offsets


def utf16_offset_to_python_index(offsets: list[int], utf16_offset: int) -> int:
    """Convert a UTF-16 code-unit offset (from ``utf16_code_unit_offsets``)
    back into the Python string index at that position."""
    return bisect.bisect_left(offsets, utf16_offset)


class AzureLanguagePiiDetector:
    name = "multilingual"

    def __init__(
        self,
        *,
        endpoint: str | None,
        api_key: str | None = None,
        azure_auth_mode: str = "api_key",
        recognizer: Recognizer | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._api_key = api_key
        self._azure_auth_mode = azure_auth_mode
        self._recognizer = recognizer

    async def detect_batch(
        self, texts: Sequence[str], *, language: str | None = None
    ) -> list[list[PiiSpan]]:
        if not texts:
            return []
        if not self._endpoint:
            raise PolicyBlockedError(
                "Multilingual PII detection is selected but the Azure AI Language "
                "endpoint is not configured. Failing closed.",
                details={"service": "azure_language"},
            )
        recognizer = self._recognizer or self._default_recognizer
        documents = [
            {"id": str(index), "text": text, "language": (language or "en")}
            for index, text in enumerate(texts)
        ]
        try:
            results = await recognizer(documents)
        except PolicyBlockedError:
            raise
        except Exception as exc:  # noqa: BLE001 - any failure must fail closed
            raise PolicyBlockedError(
                "Multilingual PII detection failed. Failing closed before any "
                "content is sent to the generative provider.",
                details={"service": "azure_language"},
            ) from exc
        if len(results) != len(texts):
            raise PolicyBlockedError(
                "Multilingual PII detection returned an incomplete result. Failing closed.",
                details={"service": "azure_language"},
            )
        return results

    async def _default_recognizer(
        self, documents: list[dict[str, str]]
    ) -> list[list[PiiSpan]]:
        try:
            from azure.ai.textanalytics.aio import TextAnalyticsClient
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise PolicyBlockedError(
                "The Azure AI Language SDK is not installed in this build.",
                details={"service": "azure_language"},
            ) from exc

        # detect_batch already guarantees self._endpoint is set before any
        # recognizer runs, but that guard lives in a different method than
        # this one - re-asserting it here narrows the type for mypy and
        # keeps the fail-closed contract self-contained if this method is
        # ever called directly.
        endpoint = self._endpoint
        if not endpoint:
            raise PolicyBlockedError(
                "Multilingual PII detection is selected but the Azure AI Language "
                "endpoint is not configured. Failing closed.",
                details={"service": "azure_language"},
            )
        credential = self._credential()
        # Azure returns entity offsets/lengths as UTF-16 code units - convert
        # to Python string indices (see utf16_code_unit_offsets) so downstream
        # slicing of the same Python `text` string (security_gateway.py) lands
        # on the correct characters even when astral-plane characters (rare
        # emoji, some CJK extensions) precede an entity.
        text_by_index = [document["text"] for document in documents]
        # Call recognize_pii_entities on `client` directly rather than on
        # `async with ... as client`'s bound name - the SDK's own __aenter__
        # is typed to return the base class (missing recognize_pii_entities
        # in its stub), even though it returns `self` at runtime. Using the
        # original reference sidesteps that stub imprecision.
        client = TextAnalyticsClient(endpoint, credential)
        async with client:
            response = await client.recognize_pii_entities(documents)
            spans_by_doc: list[list[PiiSpan]] = []
            for doc_index, document in enumerate(response):
                if getattr(document, "is_error", False):
                    raise PolicyBlockedError(
                        "Azure AI Language reported an error for a document. Failing closed.",
                        details={"service": "azure_language"},
                    )
                offsets = utf16_code_unit_offsets(text_by_index[doc_index])
                spans_by_doc.append(
                    [
                        PiiSpan(
                            start=utf16_offset_to_python_index(offsets, entity.offset),
                            end=utf16_offset_to_python_index(
                                offsets, entity.offset + entity.length
                            ),
                            category=str(entity.category),
                        )
                        for entity in document.entities
                    ]
                )
            return spans_by_doc

    def _credential(self) -> AzureKeyCredential | AsyncTokenCredential:
        if self._azure_auth_mode == "managed_identity":
            from azure.identity.aio import DefaultAzureCredential

            return DefaultAzureCredential()
        from azure.core.credentials import AzureKeyCredential

        if not self._api_key:
            raise PolicyBlockedError(
                "Azure AI Language API key is not configured. Failing closed.",
                details={"service": "azure_language"},
            )
        return AzureKeyCredential(self._api_key)
