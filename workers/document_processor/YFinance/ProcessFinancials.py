import asyncio
import uuid
import yfinance as yf
import pandas as pd
from typing import Dict, Optional, Any
from datetime import datetime, date, timedelta


class ProcessFinancials:
    """Process current performance gains from the time of filing to now."""

    def __init__(self, content: Dict[str, Any]):
        self.content = content
        self.current_date = date.today()
        self._yf_cache: Dict[str, pd.DataFrame] = {}    # ticker -> DataFrame
        self._current_price_cache: Dict[str, float] = {} # ticker -> float
        self._spy_cache: Dict[tuple, float] = {}          # (start, end) -> float

    # ── Public ────────────────────────────────────────────────────────────────

    async def process_row(self) -> Optional[list[Dict[str, Any]]]:
        """Process all valid transactions and return a list of dicts for PostgreSQL insertion."""
        results = []

        for tx in self.content.get("transactions", []):
            if not self._is_valid_transaction(tx):
                continue

            performance_data = await self._calculate_performance(tx)
            if not performance_data:
                continue

            amount_min, amount_max = self._parse_amount_range(tx.get("amount_range"))

            row = {
                "id":                        uuid.uuid4(),
                "doc_id":                    self.content["filing_id"],
                "filer_name":                self.content["name"],
                "ticker":                    tx["ticker"],
                "asset_type":                tx["asset_type"],
                "transaction_type":          tx["transaction_type"],
                "trade_date":                self._parse_date(tx["transaction_date"]),
                "amount_range":              tx.get("amount_range"),
                "amount_min":                None,
                "amount_max":                self._get_amount_max(tx.get("amount_range")),
                "estimated_cost":            self._calculate_estimated_cost(amount_min, amount_max),
                "quantity":                  self._get_quantity(tx),
                "purchase_price":            performance_data.get("purchase_price"),
                "current_price":             performance_data.get("current_price"),
                "price_change_pct":          performance_data.get("price_change_pct"),
                "benchmark_return_pct":      performance_data.get("benchmark_return_pct"),
                "alpha_vs_benchmark":        performance_data.get("alpha_vs_benchmark"),
                "max_drawdown_pct":          performance_data.get("max_drawdown_pct"),
                "days_to_peak":              performance_data.get("days_to_peak"),
                "is_initial_entry":          self._is_initial_entry(tx),
                "percent_of_total_holdings": None,
                "created_at":                datetime.now(),
                "updated_at":                datetime.now(),
            }
            results.append(row)

        return results if results else None

    # ── Validation ────────────────────────────────────────────────────────────

    def _is_valid_transaction(self, tx: Dict[str, Any]) -> bool:
        if not tx.get("ticker"):
            return False
        if not tx.get("transaction_date"):
            return False
        if tx.get("asset_type") not in ["ST", "OP", "OT"]:
            return False
        if tx.get("transaction_type") not in ["P", "S", "E"]:
            return False
        return True

    # ── Parsing ───────────────────────────────────────────────────────────────

    def _parse_date(self, date_str: str) -> Optional[date]:
        if not date_str:
            return None
        for fmt in ["%m-%d-%Y", "%m/%d/%Y", "%Y-%m-%d"]:
            try:
                return datetime.strptime(date_str.strip(), fmt).date()
            except ValueError:
                continue
        return None

    def _get_amount_max(self, amount_range: str) -> Optional[float]:
        if not amount_range:
            return None
        try:
            if isinstance(amount_range, (int, float)):
                return float(amount_range)
            cleaned = str(amount_range).replace('$', '').replace(',', '').strip()
            return float(cleaned)
        except (ValueError, TypeError):
            return None

    def _parse_amount_range(self, amount_range: str) -> tuple[Optional[float], Optional[float]]:
        if not amount_range:
            return None, None
        try:
            if isinstance(amount_range, (int, float)):
                return None, float(amount_range)
            cleaned = str(amount_range).replace('$', '').replace(',', '').strip()
            return None, float(cleaned)
        except (ValueError, TypeError):
            return None, None

    def _calculate_estimated_cost(
        self,
        amount_min: Optional[float],
        amount_max: Optional[float],
    ) -> Optional[float]:
        if amount_min is not None and amount_max is not None:
            return (amount_min + amount_max) / 2
        return None

    def _get_quantity(self, tx: Dict[str, Any]) -> Optional[float]:
        metadata = tx.get("metadata") or {}
        shares = metadata.get("shares")
        if shares is not None:
            return float(shares)

        amount_min, amount_max = self._parse_amount_range(tx.get("amount_range"))
        if amount_min and amount_max:
            cached_price = self._current_price_cache.get(tx["ticker"])
            if cached_price:
                return (amount_min + amount_max) / (2 * cached_price)
        return None

    # ── yfinance fetch helpers (blocking → thread pool) ───────────────────────

    def _fetch_ticker_history(self, ticker: str, start_date: date) -> pd.DataFrame:
        """Synchronous yfinance fetch — called via asyncio.to_thread."""
        stock = yf.Ticker(ticker)
        hist = stock.history(start=start_date, end=self.current_date)
        if not hist.empty:
            hist.index = hist.index.tz_localize(None)
        return hist

    def _fetch_spy_history(self, start_date: date, end_date: date) -> pd.DataFrame:
        """Synchronous SPY fetch — called via asyncio.to_thread."""
        spy = yf.Ticker("SPY")
        hist = spy.history(start=start_date, end=end_date)
        if not hist.empty:
            hist.index = hist.index.tz_localize(None)
        return hist

    # ── Performance ───────────────────────────────────────────────────────────

    async def _calculate_performance(self, tx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Calculate performance metrics using yfinance data."""
        ticker = tx["ticker"]
        trade_date = self._parse_date(tx["transaction_date"])

        if not trade_date:
            return None

        try:
            if ticker not in self._yf_cache:
                start_date = trade_date - timedelta(days=180)

                # yfinance is synchronous — offload to thread pool so the
                # event loop is not blocked while waiting on the HTTP call
                hist = await asyncio.to_thread(
                    self._fetch_ticker_history, ticker, start_date
                )

                if hist.empty:
                    return None

                self._yf_cache[ticker] = hist
                self._current_price_cache[ticker] = hist['Close'].iloc[-1]

            hist = self._yf_cache[ticker]
            current_price = self._current_price_cache[ticker]

            trade_date_str = trade_date.strftime('%Y-%m-%d')
            if trade_date_str in hist.index:
                purchase_price = hist.loc[trade_date_str, 'Close']
            else:
                future_dates = hist.index[hist.index >= trade_date_str]
                if len(future_dates) > 0:
                    purchase_price = hist.loc[future_dates[0], 'Close']
                else:
                    return None

            price_change_pct = ((current_price - purchase_price) / purchase_price) * 100
            benchmark_return_pct = await self._get_benchmark_return(trade_date, self.current_date)
            alpha_vs_benchmark = price_change_pct - (benchmark_return_pct or 0)

            post_purchase = hist.loc[hist.index >= trade_date_str]

            if not post_purchase.empty:
                rolling_max = post_purchase['Close'].expanding().max()
                drawdown = (post_purchase['Close'] - rolling_max) / rolling_max * 100
                max_drawdown_pct = drawdown.min()
                peak_price = post_purchase['Close'].max()
                peak_date = post_purchase[post_purchase['Close'] == peak_price].index[0]
                days_to_peak = (peak_date - pd.Timestamp(trade_date_str)).days
            else:
                max_drawdown_pct = None
                days_to_peak = None

            return {
                "purchase_price":       round(float(purchase_price), 4),
                "current_price":        round(float(current_price), 4),
                "price_change_pct":     round(float(price_change_pct), 2),
                "benchmark_return_pct": round(benchmark_return_pct, 2) if benchmark_return_pct is not None else None,
                "alpha_vs_benchmark":   round(alpha_vs_benchmark, 2) if alpha_vs_benchmark is not None else None,
                "max_drawdown_pct":     round(float(max_drawdown_pct), 2) if max_drawdown_pct is not None else None,
                "days_to_peak":         days_to_peak,
            }

        except Exception as e:
            print(f"[ERROR] Performance calculation failed for {ticker}: {e}")
            return None

    async def _get_benchmark_return(self, start_date: date, end_date: date) -> Optional[float]:
        """Calculate S&P 500 (SPY) return between two dates, with caching."""
        cache_key = (start_date, end_date)
        if cache_key in self._spy_cache:
            return self._spy_cache[cache_key]

        try:
            hist = await asyncio.to_thread(
                self._fetch_spy_history, start_date, end_date
            )


            if len(hist) > 0:
                result = ((hist['Close'].iloc[-1] - hist['Close'].iloc[0]) / hist['Close'].iloc[0]) * 100
                self._spy_cache[cache_key] = result
                return result

            return None

        except Exception:
            return None

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _is_initial_entry(self, tx: Dict[str, Any]) -> Optional[bool]:
        return None  # Requires historical filing context