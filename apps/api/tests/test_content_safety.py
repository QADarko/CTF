from __future__ import annotations

import io
import zipfile

import pytest

from packages.ctf_domain.content_safety import ContentSafetyInspector
from packages.ctf_domain.errors import DomainError
from packages.ctf_domain.malware import create_malware_scanner


def test_production_noop_scanner_refused(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CTF_MALWARE_SCANNER", "noop")
    with pytest.raises(DomainError) as caught:
        create_malware_scanner("noop")
    assert caught.value.code == "MALWARE_SCANNER_REQUIRED"


def test_pdf_active_content_rejected():
    with pytest.raises(DomainError) as caught:
        ContentSafetyInspector().inspect("brief.pdf", b"%PDF-1.7\n/JavaScript (app.alert)")
    assert caught.value.code == "UNSAFE_DOCUMENT"


def test_external_ooxml_relationship_rejected():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "word/_rels/document.xml.rels",
            '<Relationships><Relationship Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/oleObject" Target="https://evil.example" TargetMode="External"/></Relationships>',
        )
    with pytest.raises(DomainError) as caught:
        ContentSafetyInspector().inspect("doc.docx", buffer.getvalue())
    assert caught.value.code == "UNSAFE_DOCUMENT"


def test_scanner_unavailable_fails_closed(monkeypatch):
    monkeypatch.setenv("CTF_MALWARE_SCANNER", "clamav")
    monkeypatch.setenv("CLAMAV_HOST", "127.0.0.1")
    monkeypatch.setenv("CLAMAV_PORT", "1")
    scanner = create_malware_scanner("clamav")
    with pytest.raises(DomainError) as caught:
        scanner.scan(b"hello")
    assert caught.value.code == "MALWARE_SCANNER_UNAVAILABLE"


def test_office_archive_bomb_rejected():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for index in range(5001):
            archive.writestr(f"pad/{index}.txt", "x")
    with pytest.raises(DomainError) as caught:
        ContentSafetyInspector().inspect("bomb.docx", buffer.getvalue())
    assert caught.value.code == "UNSAFE_DOCUMENT"
