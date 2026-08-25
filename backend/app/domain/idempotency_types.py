"""Pure contracts for durable governed-command idempotency."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CommandReceiptStatus(StrEnum):
    RESERVED = "RESERVED"
    COMPLETED = "COMPLETED"


class IdempotencyDisposition(StrEnum):
    NEW = "NEW"
    REPLAY = "REPLAY"
    CONFLICT = "CONFLICT"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")


@dataclass(frozen=True, slots=True)
class CommandIdentity:
    command_namespace: str
    command_scope: str
    idempotency_key: str

    def __post_init__(self) -> None:
        _require_text(self.command_namespace, "command_namespace")
        _require_text(self.command_scope, "command_scope")
        _require_text(self.idempotency_key, "idempotency_key")


@dataclass(frozen=True, slots=True)
class CanonicalRequestHash:
    value: str
    hash_algorithm: str
    canonicalization_version: str

    def __post_init__(self) -> None:
        _require_text(self.value, "canonical request hash")
        _require_text(self.hash_algorithm, "hash_algorithm")
        _require_text(self.canonicalization_version, "canonicalization_version")


@dataclass(frozen=True, slots=True)
class CommandResultReference:
    result_type: str
    result_id: str
    result_revision: str

    def __post_init__(self) -> None:
        _require_text(self.result_type, "result_type")
        _require_text(self.result_id, "result_id")
        _require_text(self.result_revision, "result_revision")


@dataclass(frozen=True, slots=True)
class IdempotencyDecision:
    disposition: IdempotencyDisposition
    receipt_id: str
    status: CommandReceiptStatus
    result_reference: CommandResultReference | None = None
