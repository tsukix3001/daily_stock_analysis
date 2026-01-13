# -*- coding: utf-8 -*-
"""StooqFetcher - 免费备用数据源（美股日线）

数据来源：Stooq (https://stooq.com)

说明：
- Stooq 提供免费 CSV 下载接口，适合作为 yfinance 的备用数据源。
- 该源一般只覆盖日线（不适合实时/分钟级）。
- 本 fetcher 仅用于“事实层”行情数据；AI 不参与取数。

接口示例：
- https://stooq.com/q/d/l/?s=aapl.us&i=d

返回 CSV 列：Date,Open,High,Low,Close,Volume
"""

import logging
from datetime import datetime
from io import StringIO
from typing import Optional

import pandas as pd
import requests

from .base import BaseFetcher, DataFetchError, STANDARD_COLUMNS

logger = logging.getLogger(__name__)


class StooqFetcher(BaseFetcher):
    """Stooq 数据源实现（免费备用）。"""

    name = "StooqFetcher"
    priority = 2

    def __init__(self, timeout_seconds: int = 20):
        self.timeout_seconds = timeout_seconds

    def _normalize_ticker_to_stooq_symbol(self, stock_code: str) -> str:
        code = (stock_code or "").strip()
        if not code:
            raise DataFetchError("ticker 为空")

        # 容错：仅剔除尾部的 "." 和 ","，不影响 BRK.B 这类合法 ticker。
        code = code.rstrip('.,')

        upper = code.upper()
        if any(ch.isspace() for ch in upper) or ',' in upper:
            raise DataFetchError(f"ticker 格式不正确（疑似包含多个 ticker）: {stock_code!r}")
        if upper.isdigit():
            raise DataFetchError(f"当前版本仅支持美股 ticker，收到纯数字代码: {code}")
        if upper.startswith('^'):
            raise DataFetchError(f"StooqFetcher 暂不支持指数 ticker: {code}")
        if any(suffix in upper for suffix in (".SS", ".SZ", ".SH")):
            raise DataFetchError(f"当前版本仅支持美股 ticker，收到非美股后缀代码: {code}")

        # Stooq 美股一般使用 <symbol>.us（小写）
        base = upper.lower()
        if base.endswith('.us'):
            return base
        return f"{base}.us"

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        symbol = self._normalize_ticker_to_stooq_symbol(stock_code)
        url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/csv,application/octet-stream,*/*",
        }

        try:
            resp = requests.get(url, headers=headers, timeout=self.timeout_seconds)
            resp.raise_for_status()
        except Exception as e:
            raise DataFetchError(f"Stooq 请求失败: {e}") from e

        text = (resp.text or "").strip()
        if not text:
            raise DataFetchError("Stooq 返回内容为空")

        # Stooq 在无数据时可能返回非 CSV 或只有表头
        if "Date,Open,High,Low,Close,Volume" not in text.splitlines()[0]:
            raise DataFetchError("Stooq 返回格式异常（非预期 CSV）")

        df = pd.read_csv(StringIO(text))
        if df is None or df.empty:
            raise DataFetchError("Stooq 未返回任何数据")

        # 过滤日期范围（Stooq 不支持在 URL 上直接带 from/to）
        try:
            df['Date'] = pd.to_datetime(df['Date'])
            start_dt = pd.to_datetime(start_date)
            end_dt = pd.to_datetime(end_date)
            df = df[(df['Date'] >= start_dt) & (df['Date'] <= end_dt)]
        except Exception:
            # 如果日期解析失败，交给 normalize/clean 阶段兜底
            pass

        if df.empty:
            raise DataFetchError(f"Stooq 在区间 {start_date}~{end_date} 无数据")

        return df

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        df = df.copy()

        column_mapping = {
            'Date': 'date',
            'Open': 'open',
            'High': 'high',
            'Low': 'low',
            'Close': 'close',
            'Volume': 'volume',
        }
        df = df.rename(columns=column_mapping)

        # 计算涨跌幅
        if 'close' in df.columns:
            df['pct_chg'] = df['close'].pct_change(fill_method=None) * 100
            df['pct_chg'] = df['pct_chg'].fillna(0).round(2)

        # 估算成交额
        if 'volume' in df.columns and 'close' in df.columns:
            df['amount'] = df['volume'] * df['close']
        else:
            df['amount'] = 0

        df['code'] = stock_code

        keep_cols = ['code'] + STANDARD_COLUMNS
        existing_cols = [col for col in keep_cols if col in df.columns]
        df = df[existing_cols]

        return df
