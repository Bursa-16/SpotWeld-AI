"""Explicit transaction owner for governed application operations."""

from __future__ import annotations

from types import TracebackType

from sqlalchemy.orm import Session

from app.repositories.governance_repository import GovernanceRepository
from app.repositories.idempotency_repository import IdempotencyRepository


class GovernedUnitOfWork:
    """Coordinate governed repositories on one caller-supplied session.

    A successful operation must call :meth:`commit` explicitly.  Leaving a
    context without committing, or leaving because of an exception, rolls all
    participating writes back.  The session itself remains caller-owned and is
    not closed here.
    """

    def __init__(self, session: Session):
        self.session = session
        self.governance_repository = GovernanceRepository(session)
        self.idempotency_repository = IdempotencyRepository(session)
        self._entered = False
        self._finalized = False

    def __enter__(self) -> GovernedUnitOfWork:
        if self._entered:
            raise RuntimeError("governed unit of work cannot be re-entered")
        if self.session.in_transaction():
            raise RuntimeError(
                "governed unit of work requires a session without an active transaction"
            )
        self.session.begin()
        self._entered = True
        return self

    def commit(self) -> None:
        """Commit every write participating in this unit of work."""
        self._ensure_open()
        self.session.commit()
        self._finalized = True

    def rollback(self) -> None:
        """Roll back every write participating in this unit of work."""
        self._ensure_open()
        self.session.rollback()
        self._finalized = True

    def ensure_open(self) -> None:
        """Refuse work after this transaction owner has been finalized."""
        self._ensure_open()

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> bool:
        if not self._finalized:
            self.session.rollback()
            self._finalized = True
        self._entered = False
        return False

    def _ensure_open(self) -> None:
        if self._finalized:
            raise RuntimeError("governed unit of work is already finalized")
