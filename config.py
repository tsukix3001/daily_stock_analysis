# -*- coding: utf-8 -*-
"""daily_stock_analysis 配置管理

本项目已调整为：仅分析美股（US tickers），AI 使用 Grok（xAI）API。

职责：
1. 使用单例模式管理全局配置
2. 从 .env 文件加载敏感配置
3. 提供类型安全的配置访问接口
"""

import os
from pathlib import Path
from typing import List, Optional
from dotenv import load_dotenv
from dataclasses import dataclass, field


def _parse_symbol_list(raw: str) -> List[str]:
    """Parse user-provided symbols from env.

    Accepts comma-separated and/or whitespace-separated formats to be forgiving.
    Examples:
      "AAPL,MSFT,TSLA" -> ["AAPL","MSFT","TSLA"]
      "AAPL MSFT TSLA" -> ["AAPL","MSFT","TSLA"]
      "RKLB. TSLA" -> ["RKLB.","TSLA"]
    """
    if not raw:
        return []

    # Normalize common separators
    normalized = raw.replace('\n', ',').replace('\t', ',').replace(';', ',')

    parts: List[str] = []
    for chunk in normalized.split(','):
        chunk = chunk.strip()
        if not chunk:
            continue
        # Also split by whitespace inside a chunk
        parts.extend([p for p in chunk.split() if p])

    cleaned: List[str] = []
    for sym in parts:
        s = (sym or '').strip()
        if not s:
            continue
        # 容错：去掉用户误带的尾部标点（不影响 BRK.B 这种合法 ticker）
        s = s.rstrip('.,')
        s = s.upper()
        cleaned.append(s)

    return cleaned


def _is_placeholder_value(value: str) -> bool:
    """Return True if the value looks like an example/placeholder from .env.example."""
    if value is None:
        return True
    v = str(value).strip()
    if not v:
        return True
    lower = v.lower()
    # Common placeholder patterns used in this repo's .env.example
    if lower.startswith("your_"):
        return True
    if lower in {
        "your_xai_key_here",
        "your_tavily_key_here",
        "your_serpapi_key_here",
        "your_key_here",
    }:
        return True
    return False


def _parse_key_list(raw: str) -> List[str]:
    """Parse comma-separated key list and drop placeholders."""
    if not raw:
        return []
    keys = [k.strip() for k in raw.split(',') if k.strip()]
    return [k for k in keys if not _is_placeholder_value(k)]


@dataclass
class Config:
    """
    系统配置类 - 单例模式
    
    设计说明：
    - 使用 dataclass 简化配置属性定义
    - 所有配置项从环境变量读取，支持默认值
    - 类方法 get_instance() 实现单例访问
    """
    
    # === 市场配置 ===
    market: str = "US"  # 仅支持 US

    # === 自选股配置（US tickers）===
    stock_list: List[str] = field(default_factory=list)

    # === AI 分析配置（xAI / OpenAI 兼容）===
    # 支持 xAI Grok（OpenAI 兼容接口）以及其他 OpenAI 兼容服务。
    llm_api_key: Optional[str] = None
    llm_base_url: str = "https://api.x.ai/v1"  # xAI 默认（可用 OPENAI_BASE_URL / XAI_BASE_URL 覆盖）
    llm_model: str = "grok-2-latest"          # 可用 OPENAI_MODEL / XAI_MODEL 覆盖

    # 请求/重试配置（防止 429 限流）
    llm_request_delay: float = 1.0  # 请求间隔（秒）
    llm_max_retries: int = 5
    llm_retry_delay: float = 3.0
    
    # === 搜索引擎配置（支持多 Key 负载均衡）===
    tavily_api_keys: List[str] = field(default_factory=list)  # Tavily API Keys
    serpapi_keys: List[str] = field(default_factory=list)  # SerpAPI Keys
    
    # === 通知配置（可同时配置多个，全部推送）===
    
    # 企业微信 Webhook
    wechat_webhook_url: Optional[str] = None
    
    # 飞书 Webhook
    feishu_webhook_url: Optional[str] = None
    
    # Telegram 配置（需要同时配置 Bot Token 和 Chat ID）
    telegram_bot_token: Optional[str] = None  # Bot Token（@BotFather 获取）
    telegram_chat_id: Optional[str] = None  # Chat ID
    
    # 邮件配置（只需邮箱和授权码，SMTP 自动识别）
    email_sender: Optional[str] = None  # 发件人邮箱
    email_password: Optional[str] = None  # 邮箱密码/授权码
    email_receivers: List[str] = field(default_factory=list)  # 收件人列表（留空则发给自己）
    
    # === 数据库配置 ===
    database_path: str = "./data/stock_analysis.db"
    
    # === 日志配置 ===
    log_dir: str = "./logs"  # 日志文件目录
    log_level: str = "INFO"  # 日志级别
    
    # === 系统配置 ===
    max_workers: int = 3  # 低并发防封禁
    debug: bool = False
    
    # === 定时任务配置 ===
    schedule_enabled: bool = False            # 是否启用定时任务
    schedule_time: str = "18:00"              # 每日推送时间（HH:MM 格式）
    market_review_enabled: bool = True        # 是否启用大盘复盘
    
    # === 流控配置（防封禁关键参数）===
    # Akshare 请求间隔范围（秒）
    akshare_sleep_min: float = 2.0
    akshare_sleep_max: float = 5.0
    
    # 重试配置
    max_retries: int = 3
    retry_base_delay: float = 1.0
    retry_max_delay: float = 30.0
    
    # 单例实例存储
    _instance: Optional['Config'] = None
    
    @classmethod
    def get_instance(cls) -> 'Config':
        """
        获取配置单例实例
        
        单例模式确保：
        1. 全局只有一个配置实例
        2. 配置只从环境变量加载一次
        3. 所有模块共享相同配置
        """
        if cls._instance is None:
            cls._instance = cls._load_from_env()
        return cls._instance
    
    @classmethod
    def _load_from_env(cls) -> 'Config':
        """
        从 .env 文件加载配置
        
        加载优先级：
        1. 系统环境变量
        2. .env 文件
        3. 代码中的默认值
        """
        # 加载项目根目录下的 .env 文件
        env_path = Path(__file__).parent / '.env'
        load_dotenv(dotenv_path=env_path)
        
        # 解析自选股列表（逗号分隔）
        stock_list_str = os.getenv('STOCK_LIST', '')
        stock_list = _parse_symbol_list(stock_list_str)
        
        # 如果没有配置，使用默认的示例股票（US tickers）
        if not stock_list:
            stock_list = ['AAPL', 'MSFT', 'SPY']

        # LLM 配置：优先 XAI_API_KEY，其次 OPENAI_API_KEY
        llm_api_key = (
            os.getenv('XAI_API_KEY')
            or os.getenv('OPENAI_API_KEY')
        )
        llm_base_url = (
            os.getenv('XAI_BASE_URL')
            or os.getenv('OPENAI_BASE_URL')
            or 'https://api.x.ai/v1'
        )
        llm_model = (
            os.getenv('XAI_MODEL')
            or os.getenv('OPENAI_MODEL')
            or 'grok-2-latest'
        )
        
        # 解析搜索引擎 API Keys（支持多个 key，逗号分隔；自动忽略 your_* 占位符）
        tavily_api_keys = _parse_key_list(os.getenv('TAVILY_API_KEYS', ''))
        serpapi_keys = _parse_key_list(os.getenv('SERPAPI_API_KEYS', ''))
        
        return cls(
            stock_list=stock_list,
            market=os.getenv('MARKET', 'US').upper(),
            llm_api_key=llm_api_key,
            llm_base_url=llm_base_url,
            llm_model=llm_model,
            llm_request_delay=float(os.getenv('LLM_REQUEST_DELAY', '1.0')),
            llm_max_retries=int(os.getenv('LLM_MAX_RETRIES', '5')),
            llm_retry_delay=float(os.getenv('LLM_RETRY_DELAY', '3.0')),
            tavily_api_keys=tavily_api_keys,
            serpapi_keys=serpapi_keys,
            wechat_webhook_url=os.getenv('WECHAT_WEBHOOK_URL'),
            feishu_webhook_url=os.getenv('FEISHU_WEBHOOK_URL'),
            telegram_bot_token=os.getenv('TELEGRAM_BOT_TOKEN'),
            telegram_chat_id=os.getenv('TELEGRAM_CHAT_ID'),
            email_sender=os.getenv('EMAIL_SENDER'),
            email_password=os.getenv('EMAIL_PASSWORD'),
            email_receivers=[r.strip() for r in os.getenv('EMAIL_RECEIVERS', '').split(',') if r.strip()],
            database_path=os.getenv('DATABASE_PATH', './data/stock_analysis.db'),
            log_dir=os.getenv('LOG_DIR', './logs'),
            log_level=os.getenv('LOG_LEVEL', 'INFO'),
            max_workers=int(os.getenv('MAX_WORKERS', '3')),
            debug=os.getenv('DEBUG', 'false').lower() == 'true',
            schedule_enabled=os.getenv('SCHEDULE_ENABLED', 'false').lower() == 'true',
            schedule_time=os.getenv('SCHEDULE_TIME', '18:00'),
            market_review_enabled=os.getenv('MARKET_REVIEW_ENABLED', 'true').lower() == 'true',
        )
    
    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（主要用于测试）"""
        cls._instance = None
    
    def validate(self) -> List[str]:
        """
        验证配置完整性
        
        Returns:
            缺失或无效配置项的警告列表
        """
        warnings = []

        if self.market != 'US':
            warnings.append("警告：当前版本仅支持美股 (MARKET=US)，已忽略其他市场配置")
        
        if not self.stock_list:
            warnings.append("警告：未配置自选股列表 (STOCK_LIST)")

        # 美股 ticker 基本校验：纯数字代码通常是 A 股
        non_us_like = [t for t in self.stock_list if t.strip().isdigit()]
        if non_us_like:
            warnings.append(
                "警告：检测到可能不是美股 ticker 的代码（纯数字）: " + ", ".join(non_us_like)
            )

        if not self.llm_api_key:
            warnings.append("警告：未配置 Grok/xAI API Key（XAI_API_KEY 或 OPENAI_API_KEY），AI 分析功能将不可用")
        
        if not self.tavily_api_keys and not self.serpapi_keys:
            warnings.append("提示：未配置搜索引擎 API Key (Tavily/SerpAPI)，新闻搜索功能将不可用")
        
        # 检查通知配置
        has_notification = (
            self.wechat_webhook_url or 
            self.feishu_webhook_url or
            (self.telegram_bot_token and self.telegram_chat_id) or
            (self.email_sender and self.email_password)
        )
        if not has_notification:
            warnings.append("提示：未配置通知渠道，将不发送推送通知")
        
        return warnings
    
    def get_db_url(self) -> str:
        """
        获取 SQLAlchemy 数据库连接 URL
        
        自动创建数据库目录（如果不存在）
        """
        db_path = Path(self.database_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{db_path.absolute()}"


# === 便捷的配置访问函数 ===
def get_config() -> Config:
    """获取全局配置实例的快捷方式"""
    return Config.get_instance()


if __name__ == "__main__":
    # 测试配置加载
    config = get_config()
    print("=== 配置加载测试 ===")
    print(f"自选股列表: {config.stock_list}")
    print(f"数据库路径: {config.database_path}")
    print(f"最大并发数: {config.max_workers}")
    print(f"调试模式: {config.debug}")
    
    # 验证配置
    warnings = config.validate()
    if warnings:
        print("\n配置验证结果:")
        for w in warnings:
            print(f"  - {w}")
