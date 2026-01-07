"""Fofa Hack - 极简搜索工具"""
__version__ = "2.0.0"

from .models.search import SearchConfig, SearchResult, OutputFormat
from .core.unified_client import UnifiedFofaClient, AutoProxyUnifiedFofaClient
from .utils.output import save_results

__all__ = [
    "SearchConfig",
    "SearchResult",
    "OutputFormat",
    "UnifiedFofaClient",
    "AutoProxyUnifiedFofaClient",
    "save_results",
    "search"
]


def search(query: str, count: int = 20, proxy: bool = True) -> list[SearchResult]:
    """简便的搜索函数 - 一键搜索，自动处理封禁

    Args:
        query: 搜索关键词, 如 "app='Apache'"
        count: 返回结果数量, 默认20条
        proxy: 是否启用自动代理收集, 默认True（自动处理封禁）

    Returns:
        搜索结果列表

    示例:
        >>> from fofa_hack import search
        >>> results = search("app='Apache'", count=10)
        >>> for r in results:
        ...     print(r.link)

    注意:
        - 默认启用代理自动收集，应对IP封禁
        - 如果无结果，会等待代理就绪后重试
        - 使用 --no-proxy 或 proxy=False 可禁用代理
    """
    from .core.unified_client import AutoProxyUnifiedFofaClient
    from .core.proxy import ProxyManager
    import time

    config = SearchConfig(
        keyword=query,
        end_count=count,
        time_sleep=2.0 if proxy else 1.0
    )

    # 总是启用代理收集，但search_all会智能使用
    client = AutoProxyUnifiedFofaClient(config, auto_refresh_proxy=True)

    # 第一次尝试（可能before代理就绪）
    results = client.search_all(query)

    # 如果启用代理且无结果，等待代理后重试
    if proxy and not results:
        # 等待最多15秒代理就绪
        start = time.time()
        while not client.proxy_manager.is_ready and (time.time() - start) < 15:
            time.sleep(1)

        if client.proxy_manager.is_ready and client.proxy_manager.count > 0:
            # 重置统计并重试
            client.total = 0
            client.success = 0
            client.failed = 0
            client.ban_count = 0
            results = client.search_all(query)

    return results
