"""Rotating pool of provider API keys (thread-safe, storage-agnostic).

The discovery client asks the pool for a key, reports what happened, and on
"out of credits" / "invalid key" simply asks for the next one - so a search
keeps running when one key runs dry. Persistence (Supabase, admin panel) plugs
in through the optional `on_change` / `on_usage` callbacks; `refresher` checks
a key's live balance so exhausted keys that were topped up come back.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

USABLE = "active"
# A revived key must afford at least one normal request (25 posts = 5 credits).
MIN_REVIVE_CREDITS = 5


@dataclass
class PoolKey:
    key: str
    id: str = ""
    label: str = ""
    status: str = USABLE          # active | exhausted | invalid | disabled
    credits_remaining: Optional[int] = None
    priority: int = 100
    order: int = 0
    calls: int = field(default=0, compare=False)
    credits_used: int = field(default=0, compare=False)

    @property
    def hint(self) -> str:
        return self.key[-4:] if self.key else ""


class KeyPool:
    def __init__(
        self,
        keys: list[PoolKey],
        *,
        on_change: Callable[[PoolKey, str], None] | None = None,
        on_usage: Callable[[PoolKey, int, Optional[int]], None] | None = None,
        refresher: Callable[[PoolKey], Optional[int]] | None = None,
    ) -> None:
        for i, k in enumerate(keys):
            k.order = i
        self._keys = keys
        self._lock = threading.Lock()
        self._on_change = on_change
        self._on_usage = on_usage
        self._refresher = refresher
        self._revived = False

    @classmethod
    def from_keys(cls, keys: list[str]) -> "KeyPool":
        seen: list[str] = []
        for k in keys:
            k = (k or "").strip()
            if k and k not in seen:
                seen.append(k)
        return cls([PoolKey(key=k, id=f"env-{i}") for i, k in enumerate(seen)])

    def __len__(self) -> int:
        return len(self._keys)

    @property
    def keys(self) -> list[PoolKey]:
        return list(self._keys)

    def usable(self) -> list[PoolKey]:
        with self._lock:
            return sorted((k for k in self._keys if k.status == USABLE), key=lambda k: (k.priority, k.order))

    def acquire(self, exclude: set[str] | None = None) -> PoolKey | None:
        """First usable key (by priority) not tried yet in this request."""
        exclude = exclude or set()
        for k in self.usable():
            if k.key not in exclude:
                return k
        return None

    def _set_status(self, k: PoolKey, status: str, reason: str = "", remaining: Optional[int] = None) -> None:
        with self._lock:
            changed = k.status != status
            k.status = status
            if remaining is not None:
                k.credits_remaining = remaining
        if changed and self._on_change:
            try:
                self._on_change(k, reason)
            except Exception:  # noqa: BLE001 - persistence never breaks a search
                pass

    def exhausted(self, k: PoolKey, reason: str = "out of credits", remaining: Optional[int] = None) -> None:
        """Too few credits for our requests. `remaining` = the provider's real
        balance when it told us (e.g. 3 left but a request needs 5)."""
        self._set_status(k, "exhausted", reason, remaining=0 if remaining is None else remaining)

    def invalid(self, k: PoolKey, reason: str = "rejected by provider") -> None:
        self._set_status(k, "invalid", reason)

    def report(self, k: PoolKey, credits_used: int, credits_remaining: Optional[int]) -> None:
        with self._lock:
            k.calls += 1
            k.credits_used += max(0, int(credits_used or 0))
            if credits_remaining is not None:
                # parallel requests finish out of order: the lowest balance is the newest
                new = int(credits_remaining)
                k.credits_remaining = new if k.credits_remaining is None else min(k.credits_remaining, new)
            remaining = k.credits_remaining
        if self._on_usage:
            try:
                self._on_usage(k, int(credits_used or 0), remaining if credits_remaining is not None else None)
            except Exception:  # noqa: BLE001
                pass
        if credits_remaining is not None and int(credits_remaining) <= 0:
            self.exhausted(k, "balance reached 0")

    def revive(self) -> bool:
        """All keys dry: re-check exhausted keys once (someone may have topped
        one up). Returns True when at least one key is usable again."""
        with self._lock:
            if self._revived or not self._refresher:
                return False
            self._revived = True
            candidates = [k for k in self._keys if k.status == "exhausted"]
        revived = False
        for k in candidates:
            try:
                remaining = self._refresher(k)
            except Exception:  # noqa: BLE001
                remaining = None
            if remaining is not None and remaining >= MIN_REVIVE_CREDITS:
                self._set_status(k, USABLE, "balance restored", remaining=remaining)
                revived = True
        return revived
