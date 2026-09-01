"""Fail-closed production runtime checks (CTF-SEC-01/02/03)."""

from __future__ import annotations

import os

from .errors import DomainError
from .malware import create_malware_scanner
from .model_registry import ModelRegistry


def is_production() -> bool:
    return os.getenv("APP_ENV", "").strip().lower() in {"production", "prod"}


def production_runtime_flags() -> dict[str, str | bool]:
    env = os.getenv("APP_ENV", "development").strip().lower()
    return {
        "app_env": env,
        "is_production": env in {"production", "prod"},
        "malware_scanner": os.getenv("CTF_MALWARE_SCANNER", "noop").strip().lower(),
        "enforce_model_registry": os.getenv("CTF_ENFORCE_MODEL_REGISTRY", "").strip().lower()
        in {"1", "true", "yes"}
        or env in {"production", "prod"},
        "document_queue": os.getenv("CTF_DOCUMENT_QUEUE", "in-process").strip().lower(),
    }


def assert_production_runtime_safety() -> None:
    if not is_production():
        return
    flags = production_runtime_flags()
    if flags["malware_scanner"] == "noop":
        raise DomainError(
            "MALWARE_SCANNER_REQUIRED",
            "Production uploads require a real malware scanner.",
            503,
        )
    create_malware_scanner()
    registry = ModelRegistry()
    if not registry.enforced or not registry.is_available():
        raise DomainError(
            "MODEL_REGISTRY_UNAVAILABLE",
            "Production model registry is required but unavailable.",
            503,
        )
    if flags["document_queue"] not in {"postgres", "durable"}:
        raise DomainError(
            "DOCUMENT_QUEUE_NOT_DURABLE",
            "Production refuses the in-process document queue. Set CTF_DOCUMENT_QUEUE=postgres.",
            503,
        )
