"""Posting-date interfund-transfer simulator.

Interpretation implemented (5 CFR 1601.32 and the TSP "how to change investments"
page):

* Each calendar month, an account gets two unrestricted interfund transfers,
  counted on the **posting date**, not the request date.
* A request before noon ET on a TSP business day posts that day. A request at
  or after noon, or on a non-business day, posts the next TSP business day.
* After two unrestricted transfers have posted in the month, a later request is
  accepted only when it does not increase any fund other than G and does not
  decrease G. Moving to 100% G qualifies. So does a partial move that only
  raises G and reduces the other funds (the pro-rata case). Anything that
  increases F, C, S, or I is rejected.
* Rejected requests do not post and do not count.
* A G-only transfer after the limit is allowed and does not increase the
  unrestricted counter.
* The first two transfers count even if they move into G.
* Civilian and uniformed-services accounts have separate counters.
* A request that does not change the allocation is rejected and does not count.
* Investment elections for new contributions are out of scope; ``set_initial``
  sets a starting mix without using the monthly budget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from tsppredictor.calendar import TSPCalendar

FUNDS: tuple[str, ...] = ("G", "F", "C", "S", "I")


def as_weights(target: str | np.ndarray | dict) -> np.ndarray:
    if isinstance(target, str):
        if target not in FUNDS:
            raise ValueError(f"Unknown fund {target}")
        weights = np.zeros(len(FUNDS), dtype=float)
        weights[FUNDS.index(target)] = 1.0
        return weights
    if isinstance(target, dict):
        weights = np.array([float(target.get(name, 0.0)) for name in FUNDS], dtype=float)
    else:
        weights = np.asarray(target, dtype=float).reshape(-1)
        if weights.size != len(FUNDS):
            raise ValueError("weights must have length 5 (G, F, C, S, I)")
    total = float(weights.sum())
    if total <= 0:
        raise ValueError("weights must sum to a positive number")
    if abs(total - 1.0) > 1e-6:
        weights = weights / total
    return weights


def is_g_only_move(current: np.ndarray, target: np.ndarray) -> bool:
    """True when the move does not raise any non-G fund and does not cut G."""
    if np.allclose(current, target, atol=1e-8):
        return False
    if target[0] < current[0] - 1e-8:
        return False
    if np.any(target[1:] > current[1:] + 1e-8):
        return False
    return True


@dataclass
class TransferResult:
    accepted: bool
    reason: str
    posting_date: object
    month: str
    unrestricted_used: int
    counted_as_unrestricted: bool
    g_only_after_limit: bool
    account: str


@dataclass
class TransferBook:
    calendar: TSPCalendar
    holdings: dict[str, np.ndarray] = field(default_factory=dict)
    unrestricted: dict[str, dict[str, int]] = field(default_factory=dict)
    log: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        for account in ("civilian", "uniformed"):
            self.holdings.setdefault(account, as_weights("G"))
            self.unrestricted.setdefault(account, {})

    def set_initial(self, account: str, target: str | np.ndarray | dict) -> None:
        """Starting allocation. Does not count as an interfund transfer."""
        self._check_account(account)
        self.holdings[account] = as_weights(target)

    def used(self, account: str, month: str) -> int:
        return self.unrestricted[account].get(month, 0)

    def request(
        self,
        account: str,
        when: datetime,
        target: str | np.ndarray | dict,
    ) -> TransferResult:
        self._check_account(account)
        target_w = as_weights(target)
        current = self.holdings[account]
        posted = self.calendar.posting_date(when)
        month = f"{posted.year:04d}-{posted.month:02d}"
        used = self.unrestricted[account].get(month, 0)
        if np.allclose(current, target_w, atol=1e-8):
            result = TransferResult(
                accepted=False,
                reason="no allocation change",
                posting_date=posted,
                month=month,
                unrestricted_used=used,
                counted_as_unrestricted=False,
                g_only_after_limit=False,
                account=account,
            )
            self._record(when, result, target_w)
            return result
        g_only = is_g_only_move(current, target_w)
        if used >= 2 and not g_only:
            result = TransferResult(
                accepted=False,
                reason="monthly limit: after two unrestricted transfers, only moves into the G Fund are allowed",
                posting_date=posted,
                month=month,
                unrestricted_used=used,
                counted_as_unrestricted=False,
                g_only_after_limit=False,
                account=account,
            )
            self._record(when, result, target_w)
            return result
        counted = used < 2
        if counted:
            used += 1
            self.unrestricted[account][month] = used
        self.holdings[account] = target_w.copy()
        result = TransferResult(
            accepted=True,
            reason="posted" if counted else "posted as a G-only transfer after the monthly limit",
            posting_date=posted,
            month=month,
            unrestricted_used=used,
            counted_as_unrestricted=counted,
            g_only_after_limit=not counted,
            account=account,
        )
        self._record(when, result, target_w)
        return result

    def _check_account(self, account: str) -> None:
        if account not in self.holdings:
            raise ValueError("account must be 'civilian' or 'uniformed'")

    def _record(self, when: datetime, result: TransferResult, target: np.ndarray) -> None:
        self.log.append(
            {
                "account": result.account,
                "requested_at": when.isoformat(),
                "posting_date": result.posting_date.isoformat(),
                "month": result.month,
                "accepted": result.accepted,
                "reason": result.reason,
                "unrestricted_used": result.unrestricted_used,
                "target": {name: float(target[i]) for i, name in enumerate(FUNDS)},
            }
        )
