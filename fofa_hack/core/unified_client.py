"""
统一Fofa客户端 - 自动模式切换
支持API/Web自动切换，IP封禁检测，代理轮换
"""
import time
import random
import httpx
from typing import List, Optional, Dict, Any
from enum import Enum

from ..models.search import SearchConfig, SearchResult, FofaResponse
from ..utils.logger import get_logger
from .anonymous import AnonymousFofaClient
from .api_client import ApiFofaClient
from .proxy import ProxyManager

logger = get_logger(__name__)


class AccessMode(str, Enum):
    """访问模式"""
    API = "api"      # API方式（RSA签名）
    WEB = "web"      # 网页方式（匿名）
    AUTO = "auto"    # 自动选择


class UnifiedFofaClient:
    """
    统一Fofa客户端 - 核心功能

    自动模式切换流程：
    1. API尝试 → 失败/空结果 → 自动切WEB
    2. WEB失败 → 重试+换代理
    3. 封禁检测 → 自动换代理/切换模式
    """

    def __init__(self, config: SearchConfig, proxies: Optional[List[str]] = None, auto_refresh_proxy: bool = False):
        self.config = config
        self.mode = AccessMode.AUTO
        self.proxy_manager = ProxyManager()

        # 添加初始代理
        if proxies:
            for p in proxies:
                self.proxy_manager.add_proxy(p)

        # 自动启动代理收集（极速模式）
        if auto_refresh_proxy:
            self.proxy_manager.auto_refresh(count=5)

        self._api_client: Optional[ApiFofaClient] = None
        self._web_client: Optional[AnonymousFofaClient] = None

        self.total = 0
        self.success = 0
        self.failed = 0
        self.ban_count = 0

    @property
    def api_client(self) -> ApiFofaClient:
        """懒加载API客户端 - 检查proxy变更"""
        current_proxy = self.proxy_manager.get_proxy()

        # 如果已存在但配置不匹配，重新创建
        if self._api_client is not None and self._api_client.config.proxy != current_proxy:
            self._api_client = None

        if self._api_client is None:
            config = self.config.model_copy(update={"proxy": current_proxy})
            self._api_client = ApiFofaClient(config)
        return self._api_client

    @property
    def web_client(self) -> AnonymousFofaClient:
        """懒加载WEB客户端 - 检查proxy变更"""
        current_proxy = self.proxy_manager.get_proxy()

        # 如果已存在但配置不匹配，重新创建
        if self._web_client is not None and self._web_client.config.proxy != current_proxy:
            self._web_client = None

        if self._web_client is None:
            config = self.config.model_copy(update={"proxy": current_proxy})
            self._web_client = AnonymousFofaClient(config)
        return self._web_client

    def _is_ban_response(self, data: Dict[str, Any]) -> bool:
        """检测封禁/验证码 - 更严格"""
        if not data:
            return False
        # IP被封禁
        if data.get('code') == -3000:
            return True
        # 验证码要求（2025年新机制）
        if data.get('code') == 850100:
            return True
        msg = str(data.get('message', '')).lower()
        return any(x in msg for x in ['ip访问异常', '爬虫', '禁止访问', '访问异常', '验证码'])

    def _is_ban_html(self, html: str) -> bool:
        """检测WEB端封禁/验证码"""
        if not html:
            return True  # 空内容视为封禁
        # 检测验证码页面
        if 'captcha' in html.lower() or '/captcha' in html:
            return True
        # 检测3000错误
        return any(x in html for x in ['[-3000]', 'IP访问异常', '爬虫', '禁止访问', '访问异常'])

    def _switch_proxy(self, failed_proxy: Optional[str] = None, immediate: bool = False):
        """切换代理 - 简单直接切换"""
        if failed_proxy:
            self.proxy_manager.mark_failed(failed_proxy)

        new_proxy = self.proxy_manager.get_next_proxy(failed_proxy) if failed_proxy else self.proxy_manager.get_proxy()

        if new_proxy:
            logger.info(f"🔄 切换代理: {new_proxy}")
            self.config.proxy = new_proxy
            self._api_client = None
            self._web_client = None
            return True
        else:
            logger.warning("⚠️ 无更多可用代理")
            return False

    def _retry_delay(self, attempt: int) -> float:
        """指数退避延迟 - 更快"""
        delay = self.config.time_sleep * (1.5 ** attempt)
        jitter = random.uniform(0, 0.2) * delay
        return delay + jitter

    def search(self, query: str, page: int = 1, max_retries: int = 3) -> Optional[FofaResponse]:
        """
        执行单页搜索 - 核心原则：
        1. 确保至少尝试一次WEB模式（即使API完全失败）
        2. 自动代理切换，直到成功或无代理
        3. 永不进入无限循环
        """
        original_mode = self.mode
        logs = []

        def log(msg):
            logs.append(msg)
            logger.info(msg)

        # 尝试链：API(可能) → WEB(必须) → 重试
        # 第一阶段：尝试API（如果可用）
        if self.mode in [AccessMode.API, AccessMode.AUTO]:
            log("📡 第一阶段：尝试API模式...")
            try:
                self.total += 1

                # 如果有代理，先确保客户端用的是当前代理
                current_proxy = self.proxy_manager.get_proxy()
                if current_proxy != self.config.proxy:
                    self.config.proxy = current_proxy
                    self._api_client = None

                response = self.api_client.search(query, page)

                if response:
                    # 检查封禁（response不为None表示有响应，但需要检查内容）
                    if self._is_ban_response(response.model_dump()):
                        self.ban_count += 1
                        log(f"⚠️ API封禁，切换代理 ({self.config.proxy})")
                        self._proxy_failed()
                    else:
                        # 检查结果
                        if response.data:
                            assets = response.data.get('assets', [])
                            if assets:
                                self.success += 1
                                self.proxy_manager.mark_success(self.config.proxy)
                                log(f"✅ API成功，{len(assets)}条结果")
                                return response
                            else:
                                log("⚠️ API返回空结果")
                        else:
                            log("⚠️ API返回无数据")
                else:
                    # response 为 None，说明API完全失败（可能被封禁或网络错误）
                    log("❌ API返回None，默认封禁，切换代理")
                    self.ban_count += 1
                    self._proxy_failed()

            except Exception as e:
                log(f"❌ API异常: {e}")
                if "timeout" in str(e).lower() or "connection" in str(e).lower():
                    self._proxy_failed()

        # 第二阶段：切换到WEB模式（必须尝试）
        if AccessMode.AUTO == self.mode or self.mode == AccessMode.WEB:
            self.mode = AccessMode.WEB
            log("📡 第二阶段：切换到WEB模式...")

            # 确保有代理
            for retry in range(8):
                current_proxy = self.proxy_manager.get_proxy()
                if current_proxy:
                    self.config.proxy = current_proxy
                    self._web_client = None
                    break
                log(f"⏳ 等待代理收集中... ({retry+1}/8)")
                time.sleep(1)

            # 如果没代理但允许直连
            if not self.config.proxy:
                if self.proxy_manager.allow_direct:
                    log("⚠️ 无代理，尝试直连...")
                else:
                    log("❌ 无代理可用")
                    return None

            try:
                self.total += 1
                html = self.web_client._make_request(self.web_client._build_url(query, page))

                if not html:
                    log("❌ WEB请求无响应")
                    self._proxy_failed()
                elif self._is_ban_html(html):
                    self.ban_count += 1
                    log("🚨 WEB被封禁")
                    self._proxy_failed()
                else:
                    # 正常解析
                    data = self.web_client._parse_json_response(html)
                    if data:
                        assets = self.web_client._extract_assets_from_data(data)
                        results = [self.web_client._parse_asset_to_result(a) for a in assets]

                        if results:
                            self.success += 1
                            self.proxy_manager.mark_success(self.config.proxy)
                            total = data.get('data', {}).get('total', len(results))
                            log(f"✅ WEB成功，{len(results)}条结果")
                            return FofaResponse(
                                code=200,
                                message="success",
                                data={"assets": [r.model_dump() for r in results], "total": total, "page": page}
                            )
                        log("⚠️ WEB解析无结果")
                    else:
                        log("❌ WEB解析失败")

            except Exception as e:
                log(f"❌ WEB异常: {e}")
                self._proxy_failed()

        # 第三阶段：失败后可选的重试机制
        # 如果仍有代理，尝试快速重试（仅限1次）
        if max_retries > 1:
            current_proxy = self.proxy_manager.get_proxy()
            if current_proxy and current_proxy != self.config.proxy:
                log(f"🔄 最终尝试：重新使用代理 {current_proxy}")
                self.config.proxy = current_proxy
                self._api_client = None
                self._web_client = None
                self.mode = AccessMode.WEB  # 保证用WEB

                try:
                    self.total += 1
                    html = self.web_client._make_request(self.web_client._build_url(query, page))
                    if html and not self._is_ban_html(html):
                        data = self.web_client._parse_json_response(html)
                        if data:
                            assets = self.web_client._extract_assets_from_data(data)
                            results = [self.web_client._parse_asset_to_result(a) for a in assets]
                            if results:
                                self.success += 1
                                self.proxy_manager.mark_success(self.config.proxy)
                                return FofaResponse(
                                    code=200,
                                    message="success",
                                    data={"assets": [r.model_dump() for r in results], "total": len(results), "page": page}
                                )
                except:
                    pass

        log(f"❌ 搜索失败 (所有尝试耗尽)")
        log(f"📊 统计: 成功{self.success} 失败{self.failed} 封禁{self.ban_count} 总尝试{self.total}")

        if len(logs) > 10:
            log("🔍 详细日志见以上输出")

        return None

    def _proxy_failed(self):
        """标记当前代理失败并切换"""
        if hasattr(self, 'config') and hasattr(self.config, 'proxy') and self.config.proxy:
            self.proxy_manager.mark_failed(self.config.proxy)
        self.failed += 1

        # 尝试切换
        new_proxy = self.proxy_manager.get_next_proxy(self.config.proxy if hasattr(self, 'config') else None)
        if new_proxy:
            logger.info(f"🔄 切换到新代理: {new_proxy}")
            self.config.proxy = new_proxy
            self._api_client = None
            self._web_client = None
        else:
            logger.warning("⚠️ 无更多可用代理")

    def search_all(self, query: str, max_pages: int = 10, max_consecutive_failures: int = 3) -> List[SearchResult]:
        """搜索所有页面 - 增强错误处理和代理耗尽检测"""
        all_results = []
        page = 1
        consecutive_failures = 0

        while len(all_results) < self.config.end_count and page <= max_pages:
            logger.info(f"搜索第 {page} 页... (已获取 {len(all_results)} 条)")

            response = self.search(query, page, max_retries=3)

            if not response:
                consecutive_failures += 1
                logger.warning(f"第 {page} 页搜索失败，连续失败次数: {consecutive_failures}")

                # 检查代理池状态 - 如果已耗尽，提前终止
                if self.proxy_manager.get_proxy() is None and not self.proxy_manager.allow_direct:
                    logger.error(f"🚨 代理池已耗尽且不允许直连，终止搜索")
                    break

                # 达到连续失败阈值，提前终止
                if consecutive_failures >= max_consecutive_failures:
                    logger.error(f"🚨 达到最大连续失败次数 ({max_consecutive_failures})，终止搜索")
                    break

                page += 1
                continue

            # 成功获取结果，重置连续失败计数
            consecutive_failures = 0

            # 转换结果
            from ..models.search import SearchResult

            # 从response获取assets数据
            if hasattr(response, 'data') and response.data:
                assets = response.data.get('assets', [])
            else:
                assets = []

            search_results = [
                SearchResult(
                    link=r.get("link", ""),
                    host=r.get("host", ""),
                    port=int(r.get("port", 0)) if r.get("port") else 0,
                    title=r.get("title", ""),
                    ip=r.get("ip", "") or "",
                    city=r.get("city", "") or "",
                    asn=str(r.get("asn", "")),
                    organization=r.get("organization", "") or "",
                    server=r.get("server", "") or "",
                    mtime=r.get("mtime", "") or ""
                )
                for r in assets
            ]

            all_results.extend(search_results)
            logger.info(f"本页获取 {len(search_results)} 条，总计 {len(all_results)} 条")

            # 检查是否已达到目标数量
            if len(all_results) >= self.config.end_count:
                all_results = all_results[:self.config.end_count]
                break

            # 检查是否还有更多结果
            if hasattr(response, 'data') and response.data and response.data.get('total'):
                total = response.data.get('total', 0)
                if total > 0 and len(all_results) >= total:
                    break

            page += 1
            if page <= max_pages and self.config.time_sleep > 0:
                time.sleep(self.config.time_sleep)

        # 最终统计
        if all_results:
            logger.info(f"✅ 搜索完成，共获取 {len(all_results)} 条结果")
        else:
            logger.warning(f"⚠️ 搜索完成，未获取结果")
        logger.info(f"📊 统计: 成功{self.success} 失败{self.failed} 封禁{self.ban_count} 总尝试{self.total}")

        return all_results

    def get_stats(self) -> Dict[str, Any]:
        """获取统计"""
        success_rate = (self.success / self.total * 100) if self.total > 0 else 0
        return {
            "total": self.total,
            "success": self.success,
            "failed": self.failed,
            "rate": f"{success_rate:.1f}%",
            "bans": self.ban_count,
            "mode": self.mode.value,
            "proxy": self.config.proxy,
            "proxies": len(self.proxy_manager.proxies)
        }


class AutoProxyUnifiedFofaClient(UnifiedFofaClient):
    """自动代理客户端 - 支持代理池自动收集"""

    def __init__(self, config: SearchConfig, auto_refresh_proxy: bool = True, proxies: Optional[List[str]] = None):
        # 调用父类时传递 auto_refresh_proxy 参数
        super().__init__(config, proxies=proxies, auto_refresh_proxy=auto_refresh_proxy)

        if auto_refresh_proxy:
            logger.info("🚀 启动代理自动刷新...")

    def get_stats(self) -> Dict[str, Any]:
        """增强统计"""
        stats = super().get_stats()
        stats["pool_ready"] = self.proxy_manager.is_ready
        stats["pool_count"] = self.proxy_manager.count
        return stats