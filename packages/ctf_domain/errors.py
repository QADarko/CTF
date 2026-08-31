from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class DomainError(Exception):
    code: str
    message: str
    status_code: int = 400

    def __str__(self) -> str:
        return self.message


def require(condition: bool, code: str, message: str, status_code: int = 400) -> None:
    if not condition:
        raise DomainError(code, message, status_code)
