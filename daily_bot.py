"""
daily_bot.py — Daily Signal Generator & Position Tracker
==========================================================
Run once per trading day. Outputs:
  - Entry signals for new positions
  - Exit signals for open positions
  - Updated position tracking file
  - Entry date calendar for upcoming windows

Usage:
    python daily_bot.py --data-dir ./data --date 2026-02-16
    python daily_bot.py --data-dir ./data                    # defaults to today
"""

import os
import json
import argparse
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Set, List

import config as cfg
from data_loader import load_instruments, get_symbol
from scanner import scan_opportunities
from position_manager import Position, process_daily


POSITIONS_FILE = 'open_positions.json'
CALENDAR_FILE = 'entry_calendar.csv'


def load_positions(path: str) -> Dict[str, dict]:
    """Load saved positions from JSON."""
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def save_positions(positions: Dict[str, dict], path: str):
    """Save positions to JSON."""
    serializable = {}
    for key, pos in positions.items():
        p = dict(pos)
        for k, v in p.items():
            if isinstance(v, pd.Timestamp):
                p[k] = v.isoformat()
        serializable[key] = p
    with open(path, 'w') as f:
        json.dump(serializable, f, indent=2, default=str)


def run_daily(data_dir: str, run_date: str = None, output_dir: str = './daily_output'):
    """Run daily scan and position management."""
    os.makedirs(output_dir, exist_ok=True)

    if run_date:
        today = pd.Timestamp(run_date)
    else:
        today = pd.Timestamp(datetime.now().strftime('%Y-%m-%d'))

    print(f"Daily Bot — {today.date()}")
    print("=" * 60)

    # Load data
    instruments, inst_indexed = load_instruments(data_dir, cfg.MIN_HISTORY_BARS)

    # Load existing positions
    pos_file = os.path.join(output_dir, POSITIONS_FILE)
    saved_positions = load_positions(pos_file)

    # Reconstruct Position objects
    open_pos: Dict[str, Position] = {}
    positioned_syms: Set[str] = set()

    for key, pdata in saved_positions.items():
        pos = Position(
            tid=pdata['tid'],
            key=key,
            symbol=pdata['symbol'],
            entry_date=pd.Timestamp(pdata['entry_date']),
            entry_price=pdata['entry_price'],
            window_end=pd.Timestamp(pdata['window_end']),
            window_days=pdata.get('window_days', 0),
            confluence_score=pdata.get('confluence_score', 0),
            phase=pdata['phase'],
            alloc=pdata['alloc'],
            stop_price=pdata.get('stop_price', 0),
            peak_pnl=pdata.get('peak_pnl', 0),
        )
        open_pos[key] = pos
        positioned_syms.add(pos.symbol)

    # ── PROCESS EXITS ──
    print(f"\nOpen positions: {len(open_pos)}")
    exit_signals = []
    to_close = []

    for key, pos in open_pos.items():
        idf = inst_indexed.get(key)
        if idf is None or today not in idf.index:
            continue
        bar = idf.loc[today]
        events, closed = process_daily(pos, today, bar['High'], bar['Low'], bar['Close'])
        for e in events:
            exit_signals.append(vars(e))
            print(f"  EXIT: {e.symbol} {e.exit_reason} | "
                  f"PnL: {e.pnl_pct:+.2f}% on {e.position_pct}% | "
                  f"Weighted: {e.weighted_pnl:+.2f}%")
        if closed:
            to_close.append(key)

    for key in to_close:
        positioned_syms.discard(open_pos[key].symbol)
        del open_pos[key]

    # ── SCAN FOR NEW ENTRIES ──
    opp_queue = scan_opportunities(instruments, inst_indexed, today)
    entry_signals = []
    tid_max = max((p.tid for p in open_pos.values()), default=0)
    if saved_positions:
        tid_max = max(tid_max, max(p['tid'] for p in saved_positions.values()))

    slots = cfg.MAX_POSITIONS - len(open_pos)
    for opp in opp_queue:
        if slots <= 0:
            break
        sym = opp['symbol']
        key = opp['key']
        if sym in positioned_syms:
            continue
        if today < opp['window_start'] or today > opp['window_end']:
            continue
        idf = inst_indexed.get(key)
        if idf is None or today not in idf.index:
            continue

        entry_price = idf.loc[today, 'Close']
        tid_max += 1

        initial_phase = -1 if cfg.USE_WEEK1_CONFIRMATION else 0
        initial_alloc = cfg.INITIAL_ALLOCATION_PCT if cfg.USE_WEEK1_CONFIRMATION \
            else cfg.FULL_ALLOCATION_PCT

        pos = Position(
            tid=tid_max, key=key, symbol=sym,
            entry_date=today, entry_price=entry_price,
            window_end=opp['window_end'],
            window_days=opp['window_days'],
            confluence_score=opp['score'],
            phase=initial_phase,
            alloc=initial_alloc,
        )
        open_pos[key] = pos
        positioned_syms.add(sym)
        slots -= 1

        opt = cfg.OPTIMAL_TARGETS.get(sym, cfg.DEFAULT_OPTIMAL_TARGET)
        entry_signals.append({
            'symbol': sym,
            'entry_date': today.strftime('%Y-%m-%d'),
            'entry_price': round(entry_price, 4),
            'target_5pct': round(entry_price * 1.05, 4),
            'target_optimal': round(entry_price * (1 + opt / 100), 4),
            'optimal_pct': opt,
            'window_end': opp['window_end'].strftime('%Y-%m-%d'),
            'window_days': opp['window_days'],
            'score': round(opp['score'], 2),
            'initial_alloc': initial_alloc,
            'phase': 'CONFIRMING' if cfg.USE_WEEK1_CONFIRMATION else 'FULL',
        })
        print(f"  ENTRY: {sym} @ {entry_price:.2f} | "
              f"Target: {entry_price*1.05:.2f} / {entry_price*(1+opt/100):.2f} | "
              f"Window: {opp['window_days']}d | Score: {opp['score']:.1f}")

    # ── GENERATE ENTRY CALENDAR ──
    calendar = []
    for opp in opp_queue:
        opt = cfg.OPTIMAL_TARGETS.get(opp['symbol'], cfg.DEFAULT_OPTIMAL_TARGET)
        calendar.append({
            'symbol': opp['symbol'],
            'window_start': opp['window_start'].strftime('%Y-%m-%d'),
            'window_end': opp['window_end'].strftime('%Y-%m-%d'),
            'window_days': opp['window_days'],
            'score': round(opp['score'], 2),
            'optimal_target': opt,
            'status': 'ACTIVE' if opp['symbol'] in positioned_syms else 'PENDING',
        })

    # ── SAVE OUTPUTS ──
    # Positions
    save_data = {}
    for key, pos in open_pos.items():
        save_data[key] = {
            'tid': pos.tid, 'symbol': pos.symbol,
            'entry_date': pos.entry_date.isoformat(),
            'entry_price': pos.entry_price,
            'window_end': pos.window_end.isoformat(),
            'window_days': pos.window_days,
            'confluence_score': pos.confluence_score,
            'phase': pos.phase, 'alloc': pos.alloc,
            'stop_price': pos.stop_price,
            'peak_pnl': pos.peak_pnl,
        }
    save_positions(save_data, pos_file)

    # Entry signals
    if entry_signals:
        pd.DataFrame(entry_signals).to_csv(
            os.path.join(output_dir, f'entries_{today.strftime("%Y%m%d")}.csv'), index=False)

    # Exit signals
    if exit_signals:
        pd.DataFrame(exit_signals).to_csv(
            os.path.join(output_dir, f'exits_{today.strftime("%Y%m%d")}.csv'), index=False)

    # Calendar
    if calendar:
        pd.DataFrame(calendar).to_csv(
            os.path.join(output_dir, CALENDAR_FILE), index=False)

    # Summary
    summary = {
        'date': today.strftime('%Y-%m-%d'),
        'open_positions': len(open_pos),
        'new_entries': len(entry_signals),
        'exits_today': len(exit_signals),
        'pending_opportunities': len([c for c in calendar if c['status'] == 'PENDING']),
        'positions': {pos.symbol: {
            'phase': pos.phase, 'alloc': pos.alloc,
            'entry': pos.entry_price,
            'days_held': (today - pos.entry_date).days,
        } for pos in open_pos.values()},
    }
    with open(os.path.join(output_dir, f'summary_{today.strftime("%Y%m%d")}.json'), 'w') as f:
        json.dump(summary, f, indent=2)

    print(f"\n{'─'*60}")
    print(f"Summary: {len(open_pos)} positions | "
          f"{len(entry_signals)} entries | {len(exit_signals)} exits")
    print(f"Files → {output_dir}/")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Daily Cycle Bot')
    parser.add_argument('--data-dir', default='./data')
    parser.add_argument('--date', default=None, help='Run date (YYYY-MM-DD)')
    parser.add_argument('--output-dir', default='./daily_output')
    args = parser.parse_args()
    run_daily(args.data_dir, args.date, args.output_dir)
