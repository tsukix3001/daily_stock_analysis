# -*- coding: utf-8 -*-
"""
===================================
大盘复盘分析模块（美股）
===================================

职责：
1. 获取美股主要指数数据（S&P 500、纳斯达克、道琼斯等）
2. 搜索市场新闻形成复盘情报
3. 使用大模型生成每日大盘复盘报告
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List

import pandas as pd
import yfinance as yf

from config import get_config
from search_service import SearchService

logger = logging.getLogger(__name__)


@dataclass
class MarketIndex:
    """大盘指数数据"""
    code: str                    # 指数代码
    name: str                    # 指数名称
    current: float = 0.0         # 当前点位
    change: float = 0.0          # 涨跌点数
    change_pct: float = 0.0      # 涨跌幅(%)
    open: float = 0.0            # 开盘点位
    high: float = 0.0            # 最高点位
    low: float = 0.0             # 最低点位
    prev_close: float = 0.0      # 昨收点位
    volume: float = 0.0          # 成交量（手）
    amount: float = 0.0          # 成交额（元）
    amplitude: float = 0.0       # 振幅(%)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'code': self.code,
            'name': self.name,
            'current': self.current,
            'change': self.change,
            'change_pct': self.change_pct,
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'volume': self.volume,
            'amount': self.amount,
            'amplitude': self.amplitude,
        }


@dataclass
class MarketOverview:
    """市场概览数据"""
    date: str                           # 日期
    indices: List[MarketIndex] = field(default_factory=list)  # 主要指数
    up_count: int = 0                   # 上涨家数
    down_count: int = 0                 # 下跌家数
    flat_count: int = 0                 # 平盘家数
    limit_up_count: int = 0             # 涨停家数
    limit_down_count: int = 0           # 跌停家数
    total_amount: float = 0.0           # 两市成交额（亿元）
    north_flow: float = 0.0             # 北向资金净流入（亿元）
    
    # 板块涨幅榜
    top_sectors: List[Dict] = field(default_factory=list)     # 涨幅前5板块
    bottom_sectors: List[Dict] = field(default_factory=list)  # 跌幅前5板块


class MarketAnalyzer:
    """
    大盘复盘分析器
    
    功能：
    1. 获取大盘指数实时行情
    2. 获取市场涨跌统计
    3. 获取板块涨跌榜
    4. 搜索市场新闻
    5. 生成大盘复盘报告
    """
    
    # 美股主要指数（Yahoo Finance symbols）
    MAIN_INDICES = {
        '^GSPC': 'S&P 500',
        '^IXIC': 'NASDAQ',
        '^DJI': 'Dow Jones',
        '^RUT': 'Russell 2000',
        '^VIX': 'VIX',
    }
    
    def __init__(self, search_service: Optional[SearchService] = None, analyzer=None):
        """
        初始化大盘分析器
        
        Args:
            search_service: 搜索服务实例
            analyzer: AI分析器实例（用于调用LLM）
        """
        self.config = get_config()
        self.search_service = search_service
        self.analyzer = analyzer
        
    def get_market_overview(self) -> MarketOverview:
        """
        获取市场概览数据
        
        Returns:
            MarketOverview: 市场概览数据对象
        """
        today = datetime.now().strftime('%Y-%m-%d')
        overview = MarketOverview(date=today)
        
        # 1. 获取主要指数行情
        overview.indices = self._get_main_indices()

        # 其余字段（涨跌家数/板块/资金）在美股场景下不做统计，保留为 0
        
        return overview
    
    def _get_main_indices(self) -> List[MarketIndex]:
        """获取主要指数实时行情"""
        indices = []
        
        try:
            logger.info("[Market] 获取美股主要指数行情...")

            for symbol, name in self.MAIN_INDICES.items():
                try:
                    df = yf.download(
                        tickers=symbol,
                        period="7d",
                        interval="1d",
                        progress=False,
                        auto_adjust=True,
                    )
                    if df is None or df.empty:
                        logger.warning(f"[Market] {symbol} 无数据")
                        continue

                    df = df.dropna()
                    df = df.tail(2)
                    if len(df) < 1:
                        continue

                    latest = df.iloc[-1]
                    prev = df.iloc[-2] if len(df) >= 2 else None

                    current = float(latest.get('Close', 0) or 0)
                    prev_close = float(prev.get('Close', 0) or 0) if prev is not None else 0.0
                    change = current - prev_close if prev_close else 0.0
                    change_pct = (change / prev_close * 100) if prev_close else 0.0

                    index = MarketIndex(
                        code=symbol,
                        name=name,
                        current=current,
                        change=change,
                        change_pct=change_pct,
                        open=float(latest.get('Open', 0) or 0),
                        high=float(latest.get('High', 0) or 0),
                        low=float(latest.get('Low', 0) or 0),
                        prev_close=prev_close,
                        volume=float(latest.get('Volume', 0) or 0),
                        amount=0.0,
                    )
                    if index.prev_close > 0:
                        index.amplitude = (index.high - index.low) / index.prev_close * 100
                    indices.append(index)
                except Exception as e:
                    logger.warning(f"[Market] 获取 {symbol} 失败: {e}")

            logger.info(f"[Market] 获取到 {len(indices)} 个指数行情")
                
        except Exception as e:
            logger.error(f"[Market] 获取指数行情失败: {e}")
        
        return indices
    
    def search_market_news(self) -> List[Dict]:
        """
        搜索市场新闻
        
        Returns:
            新闻列表
        """
        if not self.search_service:
            logger.warning("[大盘] 搜索服务未配置，跳过新闻搜索")
            return []
        
        all_news = []
        today = datetime.now()
        month_str = f"{today.year}年{today.month}月"
        
        # 多维度搜索（美股）
        search_queries = [
            f"美股 大盘 复盘 {month_str}",
            f"S&P 500 今日 行情 分析 {month_str}",
            f"NASDAQ 市场 热点 板块 事件 {month_str}",
        ]
        
        try:
            logger.info("[大盘] 开始搜索市场新闻...")
            
            for query in search_queries:
                # 使用 search_stock_news 方法，传入"大盘"作为股票名
                response = self.search_service.search_stock_news(
                    stock_code="market",
                    stock_name="美股大盘",
                    max_results=3,
                    focus_keywords=query.split()
                )
                if response and response.results:
                    all_news.extend(response.results)
                    logger.info(f"[大盘] 搜索 '{query}' 获取 {len(response.results)} 条结果")
            
            logger.info(f"[大盘] 共获取 {len(all_news)} 条市场新闻")
            
        except Exception as e:
            logger.error(f"[大盘] 搜索市场新闻失败: {e}")
        
        return all_news
    
    def generate_market_review(self, overview: MarketOverview, news: List) -> str:
        """
        使用大模型生成大盘复盘报告
        
        Args:
            overview: 市场概览数据
            news: 市场新闻列表 (SearchResult 对象列表)
            
        Returns:
            大盘复盘报告文本
        """
        if not self.analyzer or not self.analyzer.is_available():
            logger.warning("[大盘] AI分析器未配置或不可用，使用模板生成报告")
            return self._generate_template_review(overview, news)
        
        # 构建 Prompt
        prompt = self._build_review_prompt(overview, news)
        
        try:
            logger.info("[大盘] 调用大模型生成复盘报告...")
            
            generation_config = {
                'temperature': 0.7,
                'max_output_tokens': 2048,
            }
            
            review = self.analyzer._call_openai_api(prompt, generation_config)
            
            if review:
                logger.info(f"[大盘] 复盘报告生成成功，长度: {len(review)} 字符")
                return review
            else:
                logger.warning("[大盘] 大模型返回为空")
                return self._generate_template_review(overview, news)
                
        except Exception as e:
            logger.error(f"[大盘] 大模型生成复盘报告失败: {e}")
            return self._generate_template_review(overview, news)
    
    def _build_review_prompt(self, overview: MarketOverview, news: List) -> str:
        """构建复盘报告 Prompt"""
        # 指数行情信息（简洁格式，不用emoji）
        indices_text = ""
        for idx in overview.indices:
            direction = "↑" if idx.change_pct > 0 else "↓" if idx.change_pct < 0 else "-"
            indices_text += f"- {idx.name}: {idx.current:.2f} ({direction}{abs(idx.change_pct):.2f}%)\n"
        
        # 板块信息
        top_sectors_text = ", ".join([f"{s['name']}({s['change_pct']:+.2f}%)" for s in overview.top_sectors[:3]])
        bottom_sectors_text = ", ".join([f"{s['name']}({s['change_pct']:+.2f}%)" for s in overview.bottom_sectors[:3]])
        
        # 新闻信息 - 支持 SearchResult 对象或字典
        news_text = ""
        for i, n in enumerate(news[:6], 1):
            # 兼容 SearchResult 对象和字典
            if hasattr(n, 'title'):
                title = n.title[:50] if n.title else ''
                snippet = n.snippet[:100] if n.snippet else ''
            else:
                title = n.get('title', '')[:50]
                snippet = n.get('snippet', '')[:100]
            news_text += f"{i}. {title}\n   {snippet}\n"
        
        prompt = f"""你是一位专业的美股市场分析师，请根据以下数据生成一份简洁的大盘复盘报告。

【重要】输出要求：
- 必须输出纯 Markdown 文本格式
- 禁止输出 JSON 格式
- 禁止输出代码块
- emoji 仅在标题处少量使用（每个标题最多1个）

---

# 今日市场数据

## 日期
{overview.date}

## 主要指数
{indices_text}

## 市场概况
（此版本不统计全市场涨跌家数/成交额/资金流，留空即可）

## 板块表现
领涨: {top_sectors_text}
领跌: {bottom_sectors_text}

## 市场新闻
{news_text if news_text else "暂无相关新闻"}

---

# 输出格式模板（请严格按此格式输出）

## 📊 {overview.date} 大盘复盘

### 一、市场总结
（2-3句话概括今日市场整体表现，包括指数涨跌、成交量变化）

### 二、指数点评
（分析 S&P 500、NASDAQ、道琼斯等指数走势特点）

### 三、资金动向
（解读成交额和北向资金流向的含义）

### 四、热点解读
（分析领涨领跌板块背后的逻辑和驱动因素）

### 五、后市展望
（结合当前走势和新闻，给出明日市场预判）

### 六、风险提示
（需要关注的风险点）

---

请直接输出复盘报告内容，不要输出其他说明文字。
"""
        return prompt
    
    def _generate_template_review(self, overview: MarketOverview, news: List) -> str:
        """使用模板生成复盘报告（无大模型时的备选方案）"""
        
        # 判断市场走势（以 S&P 500 为主）
        spx = next((idx for idx in overview.indices if idx.code == '^GSPC'), None)
        if spx:
            if spx.change_pct > 1:
                market_mood = "强势上涨"
            elif spx.change_pct > 0:
                market_mood = "小幅上涨"
            elif spx.change_pct > -1:
                market_mood = "小幅下跌"
            else:
                market_mood = "明显下跌"
        else:
            market_mood = "震荡整理"
        
        # 指数行情（简洁格式）
        indices_text = ""
        for idx in overview.indices[:4]:
            direction = "↑" if idx.change_pct > 0 else "↓" if idx.change_pct < 0 else "-"
            indices_text += f"- **{idx.name}**: {idx.current:.2f} ({direction}{abs(idx.change_pct):.2f}%)\n"
        
        # 板块信息
        top_text = "、".join([s['name'] for s in overview.top_sectors[:3]])
        bottom_text = "、".join([s['name'] for s in overview.bottom_sectors[:3]])
        
        report = f"""## 📊 {overview.date} 美股大盘复盘

### 一、市场总结
今日美股市场整体呈现**{market_mood}**态势。

### 二、主要指数
{indices_text}

### 三、说明
本版本仅提供主要指数概览与新闻要点，不统计全市场涨跌家数/成交额等指标。

### 四、板块表现
- **领涨**: {top_text}
- **领跌**: {bottom_text}

### 五、风险提示
市场有风险，投资需谨慎。以上数据仅供参考，不构成投资建议。

---
*复盘时间: {datetime.now().strftime('%H:%M')}*
"""
        return report
    
    def run_daily_review(self) -> str:
        """
        执行每日大盘复盘流程
        
        Returns:
            复盘报告文本
        """
        logger.info("========== 开始大盘复盘分析 ==========")
        
        # 1. 获取市场概览
        overview = self.get_market_overview()
        
        # 2. 搜索市场新闻
        news = self.search_market_news()
        
        # 3. 生成复盘报告
        report = self.generate_market_review(overview, news)
        
        logger.info("========== 大盘复盘分析完成 ==========")
        
        return report


# 测试入口
if __name__ == "__main__":
    import sys
    sys.path.insert(0, '.')
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s',
    )
    
    analyzer = MarketAnalyzer()
    
    # 测试获取市场概览
    overview = analyzer.get_market_overview()
    print(f"\n=== 市场概览 ===")
    print(f"日期: {overview.date}")
    print(f"指数数量: {len(overview.indices)}")
    for idx in overview.indices:
        print(f"  {idx.name}: {idx.current:.2f} ({idx.change_pct:+.2f}%)")
    print(f"上涨: {overview.up_count} | 下跌: {overview.down_count}")
    print(f"成交额: {overview.total_amount:.0f}亿")
    
    # 测试生成模板报告
    report = analyzer._generate_template_review(overview, [])
    print(f"\n=== 复盘报告 ===")
    print(report)
