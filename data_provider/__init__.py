# -*- coding: utf-8 -*-
"""数据源策略层

当前项目已调整为仅美股，因此默认只启用 Yahoo Finance（yfinance）数据源。
"""

from .base import BaseFetcher, DataFetcherManager
from .yfinance_fetcher import YfinanceFetcher

__all__ = [
    'BaseFetcher',
    'DataFetcherManager',
    'YfinanceFetcher',
]
