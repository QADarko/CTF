"""Active-content inspection for uploaded documents (CTF-013)."""

from __future__ import annotations

import zipfile
from io import BytesIO

from .errors import DomainError

UNSAFE_PDF_MARKERS = (
    b"/JavaScript",
    b"/JS",
    b"/OpenAction",
    b"/Launch",
    b"/EmbeddedFile",
    b"/RichMedia",
    b"/AA",
)
DANGEROUS_OOXML_PARTS = (
    "vbaProject.bin",
    "oleObject",
    "/embeddings/",
)
DANGEROUS_RELATIONSHIP_TYPES = (
    "oleObject",
    "externalLink",
    "hyperlink",
    "attachedTemplate",
)
MACRO_EXTENSIONS = {".docm", ".xlsm", ".pptm", ".dotm", ".xltm"}


class ContentSafetyInspector:
    def inspect(self, filename: str, content: bytes) -> None:
        lowered = filename.lower()
        suffix = lowered[lowered.rfind(".") :] if "." in lowered else ""
        if suffix in MACRO_EXTENSIONS:
            raise DomainError("UNSAFE_DOCUMENT", "Macro-enabled Office documents are not accepted.", 422)
        if suffix == ".pdf" or content.startswith(b"%PDF"):
            self._inspect_pdf(content)
        if suffix in {".docx", ".xlsx", ".pptx"} or content.startswith(b"PK"):
            self._inspect_ooxml(content, suffix)

    def _inspect_pdf(self, content: bytes) -> None:
        upper = content
        for marker in UNSAFE_PDF_MARKERS:
            if marker in upper:
                raise DomainError(
                    "UNSAFE_DOCUMENT",
                    "PDF active content is not accepted.",
                    422,
                )

    def _inspect_ooxml(self, content: bytes, suffix: str) -> None:
        if suffix not in {".docx", ".xlsx", ".pptx", ""} and not content.startswith(b"PK"):
            return
        try:
            archive = zipfile.ZipFile(BytesIO(content))
        except zipfile.BadZipFile:
            return
        names = [name.replace("\\", "/") for name in archive.namelist()]
        if len(names) > 5_000:
            raise DomainError("UNSAFE_DOCUMENT", "Office archive bomb was rejected.", 422)
        uncompressed = 0
        for info in archive.infolist():
            uncompressed += max(info.file_size, 0)
            if uncompressed > 100 * 1024 * 1024:
                raise DomainError("UNSAFE_DOCUMENT", "Office archive bomb was rejected.", 422)
            lowered = info.filename.lower()
            if any(token in lowered for token in DANGEROUS_OOXML_PARTS):
                raise DomainError("UNSAFE_DOCUMENT", "Embedded OLE or active Office content is not accepted.", 422)
        for name in names:
            if name.endswith((".rels", ".xml")):
                try:
                    payload = archive.read(name).decode("utf-8", errors="ignore").lower()
                except KeyError:
                    continue
                if "encrypt" in payload and "encryption" in payload:
                    raise DomainError("UNSAFE_DOCUMENT", "Encrypted Office content is not accepted.", 422)
                if any(token.lower() in payload for token in DANGEROUS_RELATIONSHIP_TYPES) and "targetmode=\"external\"" in payload:
                    raise DomainError(
                        "UNSAFE_DOCUMENT",
                        "External OOXML relationships are not accepted.",
                        422,
                    )
