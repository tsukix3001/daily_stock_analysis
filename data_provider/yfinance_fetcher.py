# -*- coding: utf-8 -*-
"""YfinanceFetcher - 美股数据源

数据来源：Yahoo Finance（通过 yfinance 库）
当前项目仅支持美股 ticker（如 AAPL, MSFT, SPY, ^GSPC）。
"""

import logging
from datetime import datetime
from typing import Optional

import pandas as pd
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from .base import BaseFetcher, DataFetchError, STANDARD_COLUMNS

logger = logging.getLogger(__name__)


class YfinanceFetcher(BaseFetcher):
    """
    Yahoo Finance 数据源实现
    
    优先级：1（默认数据源）
    数据来源：Yahoo Finance
    
    关键策略：
    - 自动转换股票代码格式
    - 处理时区和数据格式差异
    - 失败后指数退避重试
    
    注意事项：
    - A 股数据可能有延迟
    - 某些股票可能无数据
    - 数据精度可能与国内源略有差异
    """
    
    name = "YfinanceFetcher"
    priority = 1
    
    def __init__(self):
        """初始化 YfinanceFetcher"""
        pass
    
    def _normalize_ticker(self, stock_code: str) -> str:
        """规范化 ticker，并强制仅美股。

        规则：
        - 纯数字（如 600519）视为非美股，直接拒绝
        - .SS/.SZ/.SH 等后缀视为非美股，直接拒绝
        - 其他情况直接按原 ticker（大写）使用
        """
        code = (stock_code or "").strip()
        if not code:
            raise DataFetchError("ticker 为空")

        upper = code.upper()
        if upper.isdigit():
            raise DataFetchError(f"当前版本仅支持美股 ticker，收到纯数字代码: {code}")

        if any(suffix in upper for suffix in (".SS", ".SZ", ".SH")):
            raise DataFetchError(f"当前版本仅支持美股 ticker，收到非美股后缀代码: {code}")

        return upper
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        从 Yahoo Finance 获取原始数据
        
        使用 yfinance.download() 获取历史数据
        
        流程：
        1. 转换股票代码格式
        2. 调用 yfinance API
        3. 处理返回数据
        """
        import yfinance as yf
        
        # 规范化 ticker
        yf_code = self._normalize_ticker(stock_code)
        
        logger.debug(f"调用 yfinance.download({yf_code}, {start_date}, {end_date})")
        
        try:
            # 使用 yfinance 下载数据
            df = yf.download(
                tickers=yf_code,
                start=start_date,
                end=end_date,
                progress=False,  # 禁止进度条
                auto_adjust=True,  # 自动调整价格（复权）
            )
            
            if df.empty:
                raise DataFetchError(f"Yahoo Finance 未查询到 {stock_code} 的数据")
            
            return df
            
        except Exception as e:
            if isinstance(e, DataFetchError):
                raise
            raise DataFetchError(f"Yahoo Finance 获取数据失败: {e}") from e
    
    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """
        标准化 Yahoo Finance 数据
        
        yfinance 返回的列名：
        Open, High, Low, Close, Volume（索引是日期）
        
        需要映射到标准列名：
        date, open, high, low, close, volume, amount, pct_chg
        """
        df = df.copy()

        # yfinance 在部分版本/参数组合下会返回 MultiIndex 列（字段, ticker）。
        # 当前实现一次只请求一个 ticker，因此这里将列扁平化为字段名。
        if isinstance(df.columns, pd.MultiIndex):
            try:
                df.columns = df.columns.get_level_values(0)
            except Exception:
                df.columns = [c[0] if isinstance(c, tuple) and c else str(c) for c in df.columns]
        
        # 重置索引，将日期从索引变为列
        df = df.reset_index()
        
        # 列名映射（yfinance 使用首字母大写）
        column_mapping = {
            'Date': 'date',
            'Datetime': 'date',
            'Open': 'open',
            'High': 'high',
            'Low': 'low',
            'Close': 'close',
            'Volume': 'volume',
        }
        
        df = df.rename(columns=column_mapping)
        
        # 计算涨跌幅（因为 yfinance 不直接提供）
        if 'close' in df.columns:
            df['pct_chg'] = df['close'].pct_change() * 100
            df['pct_chg'] = df['pct_chg'].fillna(0).round(2)
        
        # 计算成交额（yfinance 不提供，使用估算值）
        # 成交额 ≈ 成交量 * 平均价格
        if 'volume' in df.columns and 'close' in df.columns:
            df['amount'] = df['volume'] * df['close']
        else:
            df['amount'] = 0
        
        # 添加股票代码列
        df['code'] = stock_code
        
        # 只保留需要的列
        keep_cols = ['code'] + STANDARD_COLUMNS
        existing_cols = [col for col in keep_cols if col in df.columns]
        df = df[existing_cols]
        
        return df


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(level=logging.DEBUG)
    
    fetcher = YfinanceFetcher()
    
    try:
        df = fetcher.get_daily_data('600519')  # 茅台
        print(f"获取成功，共 {len(df)} 条数据")
        print(df.tail())
    except Exception as e:
        print(f"获取失败: {e}")
