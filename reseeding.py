# region imports
from AlgorithmImports import *
import csv, io
from datetime import datetime
# endregion

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