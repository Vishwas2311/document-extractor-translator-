import json
import os
import shutil
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import aiofiles

from app.core.exceptions import DocumentNotFoundError


class LocalArtifactStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def document_dir(self, document_id: str) -> Path:
        target = (self.root / document_id).resolve()
        if target.parent != self.root:
            raise ValueError("Unsafe document path")
        return target

    def ensure_document_dirs(self, document_id: str) -> Path:
        root = self.document_dir(document_id)
        for name in ("source", "raw", "normalized", "translations", "pages", "exports"):
            (root / name).mkdir(parents=True, exist_ok=True)
        return root

    def source_path(self, document_id: str, extension: str | None = None) -> Path:
        source_dir = self.document_dir(document_id) / "source"
        if extension:
            return source_dir / f"original.{extension.lstrip('.').lower()}"
        matches = list(source_dir.glob("original.*"))
        if not matches:
            raise DocumentNotFoundError("Source document was not found.")
        return matches[0]

    def _artifact_path(self, document_id: str, relative_path: str) -> Path:
        document_root = self.document_dir(document_id)
        target = (document_root / relative_path).resolve()
        if document_root not in target.parents:
            raise ValueError("Unsafe artifact path")
        return target

    async def write_json(self, document_id: str, relative_path: str, payload: dict[str, Any]) -> Path:
        target = self._artifact_path(document_id, relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        async with aiofiles.open(temporary, "w", encoding="utf-8", newline="\n") as handle:
            await handle.write(content)
            await handle.flush()
        os.replace(temporary, target)
        return target

    async def read_json(self, document_id: str, relative_path: str) -> dict[str, Any]:
        target = self._artifact_path(document_id, relative_path)
        if not target.exists():
            raise DocumentNotFoundError("Requested artifact was not found.")
        async with aiofiles.open(target, encoding="utf-8") as handle:
            return cast(dict[str, Any], json.loads(await handle.read()))

    def exists(self, document_id: str, relative_path: str) -> bool:
        return self._artifact_path(document_id, relative_path).exists()

    def artifact_path(self, document_id: str, relative_path: str) -> Path:
        return self._artifact_path(document_id, relative_path)

    async def delete_document(self, document_id: str) -> None:
        target = self.document_dir(document_id)
        if target.exists():
            await __import__("asyncio").to_thread(shutil.rmtree, target)
