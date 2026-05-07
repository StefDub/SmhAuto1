"""
backtest.py — Walk-Forward Backtest Engine
=============================================
Processes EVERY daily bar sequentially.
Checks daily HIGH for profit targets, daily LOW for stops.
Manages the full portfolio of up to 50 positions.

Usage:
    python backtest.py --data-dir ./data --output-dir ./output --start-year 2010
"""

import os
import argparse
import pandas as pd
import numpy as np
from typing import Dict, Set, List
from datetime import timedelta

import config as cfg
from data_loader import load_instruments, get_symbol, build_trading_calendar
from scanner import scan_opportunities
from position_manager import Position, TradeEvent, process_daily


def run_backtest(data_dir: str, start_year: int = 2010) -> tuple:
    """
    Full walk-forward backtest.

    Returns
    -------
    (all_events: list of TradeEvent, instruments: dict)
    """
    instruments, inst_indexed = load_instruments(data_dir, cfg.MIN_HISTORY_BARS)

    # Determine start date
    starts = []
    for key, df in instruments.items():
        if len(df) >= cfg.MIN_HISTORY_BARS:
            starts.append(df['Date'].iloc[cfg.MIN_HISTORY_BARS - 1])
    starts.sort()
    start_dt = max(pd.Timestamp(f'{start_year}-01-01'),
                   starts[min(29, len(starts) - 1)])

    all_dates = set()
    for df in instruments.values():
        all_dates.update(df['Date'].values)
    end_dt = pd.Timestamp(max(all_dates))
    trading_days = build_trading_calendar(instruments, start_dt, end_dt)

    print(f"\nBacktest: {start_dt.date()} → {end_dt.date()} ({len(trading_days)} days)")
    print(f"Strategy: Enhanced Scaled Exit (Week1 Confirm + Trail from +3%)")
    print(f"  Week-1 confirmation: {cfg.USE_WEEK1_CONFIRMATION}")
    print(f"  Trailing stop:       {cfg.USE_TRAILING_STOP} (from +{cfg.TRAILING_ACTIVATION_PCT}%)")
    print(f"  Fixed stop loss:     {cfg.USE_STOP_LOSS}")
    print(f"  Max positions:       {cfg.MAX_POSITIONS}")
    print()

    # State
    open_pos: Dict[str, Position] = {}
    positioned_syms: Set[str] = set()
    opp_queue: List[dict] = []
    last_scan = start_dt - timedelta(days=cfg.SCAN_INTERVAL_DAYS + 1)
    all_events: List[TradeEvent] = []
    tid = 0

    for di, today in enumerate(trading_days):

        # Quarterly scan
        if (today - last_scan).days >= cfg.SCAN_INTERVAL_DAYS:
            opp_queue = scan_opportunities(instruments, inst_indexed, today)
            last_scan = today
            if di % 252 == 0:
                print(f"  {today.date()}: {len(opp_queue)} opps queued, "
                      f"{len(open_pos)} positions open")

        # Process each open position
        to_close = []
        for key, pos in open_pos.items():
            idf = inst_indexed.get(key)
            if idf is None or today not in idf.index:
                continue

            bar = idf.loc[today]
            events, closed = process_daily(
                pos, today, bar['High'], bar['Low'], bar['Close']
            )
            all_events.extend(events)
            if closed:
                to_close.append(key)

        for key in to_close:
            positioned_syms.discard(open_pos[key].symbol)
            del open_pos[key]

        # Fill new positions from queue
        slots = cfg.MAX_POSITIONS - len(open_pos)
        if slots > 0:
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

                tid += 1
                initial_phase = -1 if cfg.USE_WEEK1_CONFIRMATION else 0
                initial_alloc = cfg.INITIAL_ALLOCATION_PCT if cfg.USE_WEEK1_CONFIRMATION \
                    else cfg.FULL_ALLOCATION_PCT

                open_pos[key] = Position(
                    tid=tid, key=key, symbol=sym,
                    entry_date=today,
                    entry_price=idf.loc[today, 'Close'],
                    window_end=opp['window_end'],
                    window_days=opp['window_days'],
                    confluence_score=opp['score'],
                    phase=initial_phase,
                    alloc=initial_alloc,
                )
                positioned_syms.add(sym)
                slots -= 1

    # Close remaining at end
    for key, pos in open_pos.items():
        idf = inst_indexed.get(key)
        if idf is None:
            continue
        avail = idf.index[idf.index <= end_dt]
        if len(avail) == 0:
            continue
        last_close = idf.loc[avail[-1], 'Close']
        pnl = (last_close - pos.entry_price) / pos.entry_price * 100
        all_events.append(TradeEvent(
            tid=pos.tid, symbol=pos.symbol,
            entry_date=pos.entry_date.strftime('%Y-%m-%d'),
            exit_date=end_dt.strftime('%Y-%m-%d'),
            entry_price=round(pos.entry_price, 4),
            exit_price=round(last_close, 4),
            pnl_pct=round(pnl, 2),
            position_pct=pos.alloc,
            weighted_pnl=round(pnl * pos.alloc / 100, 2),
            hold_days=(end_dt - pos.entry_date).days,
            exit_reason='BACKTEST_END',
            optimal_target=pos.optimal_target,
            confluence_score=pos.confluence_score,
        ))

    print(f"\nBacktest complete: {len(all_events)} exit events from {tid} positions")
    return all_events, instruments


def generate_report(events: List[TradeEvent], output_dir: str):
    """Generate comprehensive report and all output files."""
    os.makedirs(output_dir, exist_ok=True)

    # Events DataFrame
    edf = pd.DataFrame([vars(e) for e in events])
    edf.to_csv(os.path.join(output_dir, 'all_exit_events.csv'), index=False)

    # Position-level aggregation
    pos_agg = edf.groupby('tid').agg(
        symbol=('symbol', 'first'),
        entry_date=('entry_date', 'first'),
        last_exit_date=('exit_date', 'last'),
        entry_price=('entry_price', 'first'),
        n_exits=('pnl_pct', 'count'),
        total_weighted_pnl=('weighted_pnl', 'sum'),
        hit_5pct=('exit_reason', lambda x: any('5PCT' in str(v) for v in x)),
        hit_optimal=('exit_reason', lambda x: 'TARGET_OPTIMAL' in x.values),
        rejected=('exit_reason', lambda x: 'WEEK1_REJECT' in x.values),
        optimal_target=('optimal_target', 'first'),
        confluence_score=('confluence_score', 'first'),
    ).reset_index()
    pos_agg.to_csv(os.path.join(output_dir, 'position_summaries.csv'), index=False)

    # Exclude backtest-end positions from stats
    active_events = edf[edf['exit_reason'] != 'BACKTEST_END']
    active_pos = pos_agg[~pos_agg['entry_date'].isin(
        edf[edf['exit_reason'] == 'BACKTEST_END']['entry_date'].unique()
    )]

    n_pos = len(pos_agg)
    total_wpnl = pos_agg['total_weighted_pnl'].sum()
    wins = (pos_agg['total_weighted_pnl'] > 0).sum()
    hit5 = pos_agg['hit_5pct'].sum()
    hit_opt = pos_agg['hit_optimal'].sum()
    rejected = pos_agg['rejected'].sum()

    w_sum = pos_agg[pos_agg['total_weighted_pnl'] > 0]['total_weighted_pnl'].sum()
    l_sum = abs(pos_agg[pos_agg['total_weighted_pnl'] <= 0]['total_weighted_pnl'].sum())
    pf = w_sum / l_sum if l_sum > 0 else float('inf')

    # Report
    rpt = []
    rpt.append("=" * 85)
    rpt.append("ENHANCED CYCLE CONFLUENCE STRATEGY — PERFORMANCE REPORT")
    rpt.append("=" * 85)
    rpt.append(f"\nEntry:  25% at window start → confirm after {cfg.CONFIRMATION_DAYS}d → 100%")
    rpt.append(f"Exit:   50% at +{cfg.FIRST_TARGET_PCT}% | 25% at midpoint | 25% at optimal")
    rpt.append(f"Trail:  From +{cfg.TRAILING_ACTIVATION_PCT}% (retain {cfg.TRAILING_RETENTION_PCT*100:.0f}% of peak)")
    rpt.append(f"Stop:   Breakeven after 5% hit | {'SL=' + str(cfg.STOP_LOSS_PCT) + '%' if cfg.USE_STOP_LOSS else 'No fixed stop'}")

    rpt.append(f"\n{'─'*70}")
    rpt.append("OVERALL PERFORMANCE")
    rpt.append(f"{'─'*70}")
    rpt.append(f"  Total Positions:             {n_pos}")
    rpt.append(f"  Week-1 Rejected:             {rejected} ({rejected/n_pos*100:.0f}%)")
    rpt.append(f"  Confirmed & Traded:          {n_pos - rejected}")
    rpt.append(f"  Winning Positions:           {wins} ({wins/n_pos*100:.1f}%)")
    rpt.append(f"  Hit 5% Target:               {hit5} ({hit5/n_pos*100:.1f}%)")
    rpt.append(f"  Hit Optimal Target:          {hit_opt} ({hit_opt/n_pos*100:.1f}%)")
    rpt.append(f"  Total Weighted PnL:          {total_wpnl:+.1f}%")
    rpt.append(f"  Avg Position PnL:            {pos_agg['total_weighted_pnl'].mean():+.2f}%")
    rpt.append(f"  Profit Factor:               {pf:.2f}")
    rpt.append(f"  Max Single Position Loss:    {pos_agg['total_weighted_pnl'].min():+.1f}%")

    # Exit reason breakdown
    rpt.append(f"\n{'─'*70}")
    rpt.append("EXIT EVENT BREAKDOWN")
    rpt.append(f"{'─'*70}")
    for reason in sorted(active_events['exit_reason'].unique()):
        sub = active_events[active_events['exit_reason'] == reason]
        rpt.append(f"  {reason:25s}: {len(sub):>5} events | "
                   f"Avg PnL: {sub['pnl_pct'].mean():+.2f}% | "
                   f"Weighted: {sub['weighted_pnl'].mean():+.2f}%")

    # Annual performance
    rpt.append(f"\n{'─'*70}")
    rpt.append("ANNUAL PERFORMANCE")
    rpt.append(f"{'─'*70}")
    active_events_copy = active_events.copy()
    active_events_copy['year'] = pd.to_datetime(active_events_copy['exit_date']).dt.year
    annual = active_events_copy.groupby('year')['weighted_pnl'].agg(['sum', 'count'])
    annual.columns = ['total_pnl', 'n_events']

    rpt.append(f"  {'Year':>5} {'Events':>7} {'Total PnL':>10} {'Portfolio':>10}")
    rpt.append(f"  {'─'*40}")
    for year, row in annual.iterrows():
        port = row['total_pnl'] / cfg.MAX_POSITIONS
        rpt.append(f"  {year:>5} {int(row['n_events']):>7} {row['total_pnl']:>+9.1f}% {port:>+9.1f}%")

    neg_years = (annual['total_pnl'] < 0).sum()
    rpt.append(f"\n  Negative years: {neg_years}")
    rpt.append(f"  Avg annual PnL: {annual['total_pnl'].mean():+.1f}%")
    rpt.append(f"  Avg annual portfolio return: {annual['total_pnl'].mean()/cfg.MAX_POSITIONS:+.1f}%")

    # Top 50 symbols
    rpt.append(f"\n{'─'*70}")
    rpt.append("TOP 50 INSTRUMENT RANKING")
    rpt.append(f"{'─'*70}")
    sym_stats = pos_agg.groupby('symbol').agg(
        n=('total_weighted_pnl', 'count'),
        avg=('total_weighted_pnl', 'mean'),
        total=('total_weighted_pnl', 'sum'),
        wr=('total_weighted_pnl', lambda x: (x > 0).sum() / len(x) * 100),
        hit5=('hit_5pct', 'mean'),
        opt_target=('optimal_target', 'first'),
    ).reset_index()
    sym_stats['comp'] = (sym_stats['wr'] * 0.3 + sym_stats['hit5'] * 100 * 0.3 +
                          sym_stats['avg'].clip(-5, 5) * 10 * 0.2 +
                          np.minimum(sym_stats['n'], 15) * 2 * 0.2)
    sym_stats = sym_stats.sort_values('comp', ascending=False).reset_index(drop=True)

    for i, row in sym_stats.head(50).iterrows():
        rpt.append(f"  {i+1:2d}. {row['symbol']:8s} | {int(row['n']):>3} pos | "
                   f"Win: {row['wr']:.0f}% | 5%: {row['hit5']*100:.0f}% | "
                   f"Avg: {row['avg']:+.2f}% | OptTarget: {row['opt_target']:.0f}%")

    report_text = "\n".join(rpt)
    print(report_text)
    with open(os.path.join(output_dir, 'performance_report.txt'), 'w') as f:
        f.write(report_text)

    sym_stats.head(50).round(2).to_csv(
        os.path.join(output_dir, 'top_50_ranking.csv'), index=False)
    annual.round(2).to_csv(
        os.path.join(output_dir, 'annual_performance.csv'))

    print(f"\nAll files → {output_dir}/")
    return report_text


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Cycle Confluence Backtest')
    parser.add_argument('--data-dir', default='./data', help='Path to data directory')
    parser.add_argument('--output-dir', default='./output', help='Output directory')
    parser.add_argument('--start-year', type=int, default=2010)
    args = parser.parse_args()

    output_dir = args.output_dir
    events, instruments = run_backtest(args.data_dir, args.start_year)
    generate_report(events, output_dir)
