import pytest

from app.services.document import DocumentService


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (b"%PDF-1.7", ("pdf", "application/pdf")),
        (b"\x89PNG\r\n\x1a\n", ("png", "image/png")),
        (b"\xff\xd8\xff\xe0", ("jpg", "image/jpeg")),
        (b"II*\x00", ("tiff", "image/tiff")),
        (b"MM\x00*", ("tiff", "image/tiff")),
        (b"BM1234", ("bmp", "image/bmp")),
    ],
)
def test_detects_allowed_file_signatures(header: bytes, expected: tuple[str, str]) -> None:
    assert DocumentService._detect_type(header) == expected


def test_rejects_unknown_file_signature() -> None:
    assert DocumentService._detect_type(b"not-a-document") is None
