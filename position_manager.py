"""
position_manager.py — Position Lifecycle Manager
==================================================
Handles:
  - Phase -1: Week-1 confirmation (25% position)
  - Phase 0:  Full position, waiting for 5% target, trailing from +3%
  - Phase 1:  After 5% hit, 50% remaining, breakeven stop
  - Phase 2:  After mid target, 25% remaining, breakeven stop

Each position produces one or more TradeEvent records on exit.
"""

from dataclasses import dataclass, field
from typing import Optional, List
import pandas as pd
import config as cfg


@dataclass
class TradeEvent:
    """A single exit event (one position may produce multiple)."""
    tid: int
    symbol: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    pnl_pct: float
    position_pct: float        # % of full position this tranche represents
    weighted_pnl: float        # pnl_pct * position_pct / 100
    hold_days: int
    exit_reason: str
    optimal_target: float = 0.0
    confluence_score: float = 0.0


@dataclass
class Position:
    """Active position state."""
    tid: int
    key: str
    symbol: str
    entry_date: pd.Timestamp
    entry_price: float
    window_end: pd.Timestamp
    window_days: int
    confluence_score: float
    phase: int = -1            # -1=confirming, 0=full, 1=post-5%, 2=post-mid
    alloc: float = 25.0        # current allocation %
    stop_price: float = 0.0
    peak_pnl: float = 0.0     # highest MFE seen

    @property
    def optimal_target(self) -> float:
        return cfg.OPTIMAL_TARGETS.get(self.symbol, cfg.DEFAULT_OPTIMAL_TARGET)

    @property
    def mid_target(self) -> float:
        return cfg.FIRST_TARGET_PCT + (self.optimal_target - cfg.FIRST_TARGET_PCT) / 2

    @property
    def price_5pct(self) -> float:
        return self.entry_price * (1 + cfg.FIRST_TARGET_PCT / 100)

    @property
    def price_mid(self) -> float:
        return self.entry_price * (1 + self.mid_target / 100)

    @property
    def price_optimal(self) -> float:
        return self.entry_price * (1 + self.optimal_target / 100)


def _make_event(pos: Position, exit_date: str, exit_price: float,
                pnl_pct: float, pos_pct: float, reason: str) -> TradeEvent:
    return TradeEvent(
        tid=pos.tid, symbol=pos.symbol,
        entry_date=pos.entry_date.strftime('%Y-%m-%d'),
        exit_date=exit_date,
        entry_price=round(pos.entry_price, 4),
        exit_price=round(exit_price, 4),
        pnl_pct=round(pnl_pct, 2),
        position_pct=pos_pct,
        weighted_pnl=round(pnl_pct * pos_pct / 100, 2),
        hold_days=(pd.Timestamp(exit_date) - pos.entry_date).days,
        exit_reason=reason,
        optimal_target=pos.optimal_target,
        confluence_score=pos.confluence_score,
    )


def process_daily(pos: Position, today: pd.Timestamp,
                  high: float, low: float, close: float
                  ) -> tuple:
    """
    Process one daily bar for a position.

    Returns
    -------
    (events: list of TradeEvent, closed: bool)
    """
    events = []
    date_str = today.strftime('%Y-%m-%d')
    entry = pos.entry_price
    days_held = (today - pos.entry_date).days
    curr_pnl = (close - entry) / entry * 100
    high_pnl = (high - entry) / entry * 100

    # ── PHASE -1: Confirmation Week ──────────────────────
    if pos.phase == -1:
        # Check if 5% hit during confirmation (lucky early win)
        if high >= pos.price_5pct:
            events.append(_make_event(pos, date_str, pos.price_5pct,
                                       cfg.FIRST_TARGET_PCT, 25, 'TARGET_5PCT_EARLY'))
            return events, True

        if days_held >= cfg.CONFIRMATION_DAYS:
            if close > entry:
                # Confirmed — scale to full position
                pos.phase = 0
                pos.alloc = cfg.FULL_ALLOCATION_PCT
                pos.peak_pnl = max(pos.peak_pnl, high_pnl)
                return events, False
            else:
                # Rejected — exit 25%
                events.append(_make_event(pos, date_str, close,
                                           curr_pnl, 25, 'WEEK1_REJECT'))
                return events, True

        if today >= pos.window_end:
            events.append(_make_event(pos, date_str, close,
                                       curr_pnl, 25, 'WINDOW_EXPIRED'))
            return events, True

        return events, False

    # ── PHASE 0: Full Position ───────────────────────────
    if pos.phase == 0:
        pos.peak_pnl = max(pos.peak_pnl, high_pnl)

        # Stop loss (if enabled)
        if cfg.USE_STOP_LOSS:
            sp = entry * (1 + cfg.STOP_LOSS_PCT / 100)
            if low <= sp:
                events.append(_make_event(pos, date_str, sp,
                                           cfg.STOP_LOSS_PCT, pos.alloc, 'STOP_LOSS'))
                return events, True

        # Trailing stop from +3%
        if cfg.USE_TRAILING_STOP and pos.peak_pnl >= cfg.TRAILING_ACTIVATION_PCT:
            trail_pnl = pos.peak_pnl * cfg.TRAILING_RETENTION_PCT
            trail_price = entry * (1 + trail_pnl / 100)
            if low <= trail_price and high_pnl < cfg.FIRST_TARGET_PCT:
                events.append(_make_event(pos, date_str, trail_price,
                                           trail_pnl, pos.alloc, 'TRAILING_STOP'))
                return events, True

        # First target: 5%
        if high >= pos.price_5pct:
            events.append(_make_event(pos, date_str, pos.price_5pct,
                                       cfg.FIRST_TARGET_PCT, cfg.FIRST_EXIT_PCT,
                                       'TARGET_5PCT'))
            pos.phase = 1
            pos.alloc = cfg.FIRST_EXIT_PCT  # 50% remaining
            pos.stop_price = entry  # Breakeven

            # Check mid target same day
            if pos.optimal_target > cfg.FIRST_TARGET_PCT and high >= pos.price_mid:
                events.append(_make_event(pos, date_str, pos.price_mid,
                                           pos.mid_target, cfg.MID_EXIT_PCT,
                                           'TARGET_MID'))
                pos.phase = 2
                pos.alloc = cfg.FINAL_EXIT_PCT

                # Check optimal target same day
                if high >= pos.price_optimal:
                    events.append(_make_event(pos, date_str, pos.price_optimal,
                                               pos.optimal_target, cfg.FINAL_EXIT_PCT,
                                               'TARGET_OPTIMAL'))
                    return events, True

            return events, False

        # Window expired
        if today >= pos.window_end:
            events.append(_make_event(pos, date_str, close,
                                       curr_pnl, pos.alloc, 'WINDOW_EXPIRED'))
            return events, True

        return events, False

    # ── PHASE 1: Post-5% (50% remaining) ────────────────
    if pos.phase == 1:
        if cfg.BREAKEVEN_STOP_AFTER_TARGET and low <= pos.stop_price:
            events.append(_make_event(pos, date_str, entry,
                                       0.0, pos.alloc, 'BREAKEVEN_STOP'))
            return events, True

        if pos.optimal_target > cfg.FIRST_TARGET_PCT and high >= pos.price_mid:
            events.append(_make_event(pos, date_str, pos.price_mid,
                                       pos.mid_target, cfg.MID_EXIT_PCT,
                                       'TARGET_MID'))
            pos.phase = 2
            pos.alloc = cfg.FINAL_EXIT_PCT

            if high >= pos.price_optimal:
                events.append(_make_event(pos, date_str, pos.price_optimal,
                                           pos.optimal_target, cfg.FINAL_EXIT_PCT,
                                           'TARGET_OPTIMAL'))
                return events, True

            return events, False

        if today >= pos.window_end:
            events.append(_make_event(pos, date_str, close,
                                       curr_pnl, pos.alloc, 'WINDOW_EXPIRED'))
            return events, True

        return events, False

    # ── PHASE 2: Post-mid (25% remaining) ────────────────
    if pos.phase == 2:
        if cfg.BREAKEVEN_STOP_AFTER_TARGET and low <= pos.stop_price:
            events.append(_make_event(pos, date_str, entry,
                                       0.0, pos.alloc, 'BREAKEVEN_STOP'))
            return events, True

        if high >= pos.price_optimal:
            events.append(_make_event(pos, date_str, pos.price_optimal,
                                       pos.optimal_target, cfg.FINAL_EXIT_PCT,
                                       'TARGET_OPTIMAL'))
            return events, True

        if today >= pos.window_end:
            events.append(_make_event(pos, date_str, close,
                                       curr_pnl, pos.alloc, 'WINDOW_EXPIRED'))
            return events, True

        return events, False

    return events, False
