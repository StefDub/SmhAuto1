# region imports
from AlgorithmImports import *
import csv, io
from datetime import datetime
# endregion

"""
=============================================================================
Packet2BReseeder — QuantForge V12 | Data Seeding Utility
=============================================================================

WHAT IT DOES:
    Rebuilds a clean baseline of daily OHLCV price history for all tickers
    in the defined universe and saves each one as a CSV file in the
    QuantConnect Object Store. Also writes a manifest CSV summarising
    bar count and last saved date for every ticker.

    This is a full overwrite — existing stored CSVs are replaced.
    It is NOT an append operation.

PARAMETERS:
    STORAGE_PREFIX (str):
        Object store path prefix where individual ticker CSVs are saved.
        Default: "v12/data/daily/"
        Each file saved as: v12/data/daily/<TICKER>.csv

    MANIFEST_KEY (str):
        Object store path for the manifest summary file.
        Default: "v12/data/manifest.csv"
        Columns: ticker, bars, last_date

    SEED_END_DATE (date):
        The cutoff date for seeding. Only bars on or before this date
        are included. Bars after this date are ignored even if returned
        by QC history call.
        Default: 2024-05-15
        Change this if you need to reseed to a different baseline date.

    UNIVERSE (list):
        List of ETF tickers to seed. Currently 40 tickers across
        US equity, sectors, developed markets, emerging markets,
        bonds, commodities, and currencies.
        Add or remove tickers here if the universe changes.

WHEN TO USE:
    1. First-time setup — building the data store from scratch.
    2. After a major universe change — new tickers added that have
       no existing CSV in the object store.
    3. Data corruption or inconsistency — when existing CSVs need
       to be wiped and rebuilt cleanly from a known good baseline.
    4. After a SEED_END_DATE change — when you want to reset the
       baseline to a different historical cutoff date.

    DO NOT use this for routine daily updates — use Packet2BDailyRefresh
    for that. This utility is destructive (overwrites existing files).

OUTPUT:
    - One CSV per ticker at: v12/data/daily/<TICKER>.csv
      Schema: date, open, high, low, close, volume
              RAW price normalization | UTC timestamps | YYYY-MM-DD dates

    - Manifest at: v12/data/manifest.csv
      Schema: ticker, bars, last_date

VERIFIED: May 2026 — Stefan confirmed seeder working correctly.
=============================================================================
"""


class Packet2BReseeder(QCAlgorithm):

    STORAGE_PREFIX = "v12/data/daily/"
    MANIFEST_KEY   = "v12/data/manifest.csv"
    SEED_END_DATE  = datetime(2024, 5, 15).date()

    UNIVERSE = [
        "SPY","QQQ","IWM","DIA","MDY",
        "XLK","XLF","XLE","XLV","XLI","XLU","XLY","XLP",
        "VGK","EWG","EWU","EWJ","EWA","EWQ","EWI",
        "EWY","EWT","EWH","EWS",
        "EEM","FXI","EWZ","EWW","INDA",
        "SHY","IEF","TLT","LQD","HYG",
        "GLD","SLV","USO","DBC",
        "UUP","FXE"
    ]

    def initialize(self):
        self.set_start_date(2024, 5, 1)
        self.set_end_date(2024, 5, 15)
        self.set_cash(100000)
        self.add_equity("SPY", Resolution.DAILY)
        self.log("=== Packet 2B Reseeder: will seed on_end_of_algorithm ===")

    def on_end_of_algorithm(self):
        self.log("=== RESEEDER STARTING ===")
        manifest_rows = []
        seeded_count  = 0
        error_count   = 0

        for ticker in self.UNIVERSE:
            try:
                if ticker not in [x.value for x in self.securities.keys()]:
                    self.add_equity(ticker, Resolution.DAILY)

                symbol = self.securities[ticker].symbol
                history = self.history[TradeBar](symbol, 500, Resolution.DAILY)
                bars = [
                    b for b in list(history)
                    if b.time.date() <= self.SEED_END_DATE
                ]

                if not bars:
                    self.log("ERROR | " + ticker + " | No bars returned")
                    error_count += 1
                    continue

                key = self.STORAGE_PREFIX + ticker + ".csv"
                buf = io.StringIO()
                buf.write("date,open,high,low,close,volume\n")
                for bar in bars:
                    buf.write(
                        bar.time.strftime("%Y-%m-%d") + "," +
                        str(round(bar.open,  6)) + "," +
                        str(round(bar.high,  6)) + "," +
                        str(round(bar.low,   6)) + "," +
                        str(round(bar.close, 6)) + "," +
                        str(int(bar.volume)) + "\n"
                    )
                self.object_store.save(key, buf.getvalue())

                last_date = bars[-1].time.strftime("%Y-%m-%d")
                seeded_count += 1
                self.log(
                    "SEEDED | " + ticker.ljust(6) +
                    " | bars: " + str(len(bars)) +
                    " | last: " + last_date
                )
                manifest_rows.append({
                    "ticker"    : ticker,
                    "bars"      : str(len(bars)),
                    "last_date" : last_date
                })

            except Exception as e:
                self.log("ERROR | " + ticker + " | " + str(e)[:80])
                error_count += 1

        if manifest_rows:
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=["ticker","bars","last_date"])
            w.writeheader()
            w.writerows(manifest_rows)
            self.object_store.save(self.MANIFEST_KEY, buf.getvalue())
            self.log("Manifest written: " + str(len(manifest_rows)) + " tickers")

        self.log("=== RESEEDER DONE | Seeded: " + str(seeded_count) +
                 " | Errors: " + str(error_count) + " ===")