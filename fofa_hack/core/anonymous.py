"""
匿名访问Fofa的核心实现
支持多种方式访问：网页接口、API接口（RSA签名）
"""
import asyncio
import base64
import json
import random
import time
from typing import List, Optional, Dict, Any
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

from ..models.search import SearchConfig, SearchResult, FofaResponse
from ..utils.logger import get_logger

logger = get_logger(__name__)


class AnonymousFofaClient:
    """
    匿名Fofa客户端 - 通过网页接口进行搜索，无需认证
    """

    BASE_URL = "https://fofa.info"
    SEARCH_URL = BASE_URL + "/result"

    # 浏览器头部，模拟真实用户
    DEFAULT_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"macOS"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Upgrade-Insecure-Requests": "1",
    }

    def __init__(self, config: SearchConfig):
        self.config = config
        self.client = httpx.Client(
            headers=self.DEFAULT_HEADERS,
            timeout=config.timeout,
            follow_redirects=True,
            http2=True
        )
        if config.proxy:
            self.client.proxies = {"all://": config.proxy}

        # 速率限制
        self.request_count = 0
        self.last_request_time = 0

    def _encode_query(self, query: str) -> str:
        """Base64编码搜索查询"""
        return base64.b64encode(query.encode('utf-8')).decode('utf-8')

    def _build_url(self, query: str, page: int = 1) -> str:
        """构建搜索URL"""
        encoded_query = self._encode_query(query)
        url = f"{self.SEARCH_URL}?qbase64={encoded_query}"
        if page > 1:
            url += f"&page={page}"
        return url

    def _rate_limit(self):
        """速率限制控制"""
        current_time = time.time()
        elapsed = current_time - self.last_request_time

        # 最小请求间隔
        min_interval = self.config.time_sleep
        if elapsed < min_interval:
            sleep_time = min_interval - elapsed
            time.sleep(sleep_time)

        self.last_request_time = time.time()
        self.request_count += 1

    def _parse_json_response(self, text: str) -> Optional[Dict[str, Any]]:
        """
        尝试从响应中提取JSON数据
        Fofa页面会在script标签中包含JSON数据
        """
        try:
            # 方法1: 直接解析JSON（某些情况下返回的是纯JSON）
            try:
                data = json.loads(text)
                if isinstance(data, dict) and "data" in data:
                    return data
            except json.JSONDecodeError:
                pass

            # 方法2: 从HTML中提取JSON数据
            soup = BeautifulSoup(text, 'html.parser')

            # 查找包含数据的script标签
            scripts = soup.find_all('script')
            for script in scripts:
                if script.string and 'window.__INITIAL_STATE__' in script.string:
                    # 提取JSON数据
                    start = script.string.find('{')
                    end = script.string.rfind('}') + 1
                    if start >= 0 and end > start:
                        json_str = script.string[start:end]
                        data = json.loads(json_str)
                        return data

            # 方法3: 查找其他可能的JSON数据位置
            # 检查是否有其他包含数据的脚本
            for script in scripts:
                if script.string:
                    # 查找可能的数据模式
                    if '"assets":' in script.string or '"results":' in script.string:
                        try:
                            # 尝试提取JSON对象
                            content = script.string
                            # 简单的JSON提取，查找最外层的大括号
                            if content.strip().startswith('{'):
                                data = json.loads(content)
                                if isinstance(data, dict):
                                    return data
                        except:
                            pass

            return None
        except Exception as e:
            logger.debug(f"解析JSON失败: {e}")
            return None

    def _extract_assets_from_data(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """从响应数据中提取资产列表"""
        try:
            # 不同的数据结构可能有不同字段
            if "data" in data and isinstance(data["data"], dict):
                inner_data = data["data"]
                if "assets" in inner_data:
                    return inner_data["assets"]
                elif "results" in inner_data:
                    return inner_data["results"]

            # 直接包含assets字段
            if "assets" in data:
                return data["assets"]

            # 直接包含results字段
            if "results" in data:
                return data["results"]

            # 某些情况下数据可能在其他字段中
            for key, value in data.items():
                if isinstance(value, list) and len(value) > 0:
                    if isinstance(value[0], dict) and ("link" in value[0] or "host" in value[0]):
                        return value

            return []
        except Exception as e:
            logger.debug(f"提取资产数据失败: {e}")
            return []

    def _parse_asset_to_result(self, asset: Dict[str, Any]) -> SearchResult:
        """将单条资产数据转换为SearchResult"""
        try:
            # 处理可能的字段差异
            link = asset.get("link", "")
            host = asset.get("host", "")
            port = asset.get("port", 0)
            title = asset.get("title", "")
            ip = asset.get("ip", "")
            city = asset.get("city", "")
            asn = asset.get("asn", "")
            organization = asset.get("organization", "")
            server = asset.get("server", "")
            mtime = asset.get("mtime", "")

            # 如果link为空但host存在，尝试构建link
            if not link and host:
                link = host
                if port and str(port) not in link:
                    link = f"{host}:{port}"

            return SearchResult(
                link=link,
                host=host,
                port=int(port) if port else 0,
                title=title,
                ip=ip,
                city=city,
                asn=str(asn),
                organization=organization,
                server=server,
                mtime=mtime
            )
        except Exception as e:
            logger.warning(f"转换资产数据失败: {asset}, 错误: {e}")
            return SearchResult()

    def _make_request(self, url: str) -> Optional[str]:
        """执行HTTP请求"""
        try:
            self._rate_limit()

            if self.config.debug:
                logger.debug(f"请求URL: {url}")

            response = self.client.get(url)
            response.raise_for_status()

            if self.config.debug:
                logger.debug(f"响应状态: {response.status_code}")
                logger.debug(f"响应长度: {len(response.text)}")

            return response.text
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP错误: {e.response.status_code} - {e}")
            return None
        except Exception as e:
            logger.error(f"请求失败: {e}")
            return None

    def search(self, query: str, page: int = 1) -> Optional[FofaResponse]:
        """
        执行搜索

        Args:
            query: 搜索查询字符串
            page: 页码

        Returns:
            FofaResponse对象或None（失败时）
        """
        url = self._build_url(query, page)

        if self.config.debug:
            logger.info(f"搜索查询: {query}")
            logger.info(f"请求URL: {url}")

        html_text = self._make_request(url)
        if not html_text:
            return None

        # 解析JSON数据
        data = self._parse_json_response(html_text)
        if not data:
            logger.warning("无法从响应中提取JSON数据")
            if self.config.debug:
                # 保存响应用于调试
                with open("debug_response.html", "w", encoding="utf-8") as f:
                    f.write(html_text)
                logger.debug("已保存调试响应到 debug_response.html")
            return None

        # 提取资产列表
        assets = self._extract_assets_from_data(data)

        # 转换为SearchResult列表
        results = [self._parse_asset_to_result(asset) for asset in assets]

        # 获取总数
        total = 0
        if "data" in data and isinstance(data["data"], dict):
            total = data["data"].get("total", len(results))
        elif "total" in data:
            total = data["total"]
        else:
            total = len(results)

        return FofaResponse(
            code=200,
            message="success",
            data={
                "assets": [r.model_dump() for r in results],
                "total": total,
                "page": page
            }
        )

    async def search_async(self, query: str, page: int = 1) -> Optional[FofaResponse]:
        """异步搜索"""
        url = self._build_url(query, page)

        if self.config.debug:
            logger.info(f"异步搜索查询: {query}")
            logger.info(f"请求URL: {url}")

        # 使用异步客户端
        async with httpx.AsyncClient(
            headers=self.DEFAULT_HEADERS,
            timeout=self.config.timeout,
            follow_redirects=True,
            http2=True,
            proxies={"all://": self.config.proxy} if self.config.proxy else None
        ) as client:
            try:
                self._rate_limit()
                response = await client.get(url)
                response.raise_for_status()
                html_text = response.text
            except Exception as e:
                logger.error(f"异步请求失败: {e}")
                return None

        # 解析数据（与同步方法相同）
        data = self._parse_json_response(html_text)
        if not data:
            return None

        assets = self._extract_assets_from_data(data)
        results = [self._parse_asset_to_result(asset) for asset in assets]

        total = 0
        if "data" in data and isinstance(data["data"], dict):
            total = data["data"].get("total", len(results))
        elif "total" in data:
            total = data["total"]
        else:
            total = len(results)

        return FofaResponse(
            code=200,
            message="success",
            data={
                "assets": [r.model_dump() for r in results],
                "total": total,
                "page": page
            }
        )

    def search_all(self, query: str, max_pages: int = 10) -> List[SearchResult]:
        """
        搜索所有页面直到达到目标数量

        Args:
            query: 搜索查询
            max_pages: 最大页数限制

        Returns:
            所有搜索结果
        """
        all_results = []
        page = 1

        while len(all_results) < self.config.end_count and page <= max_pages:
            response = self.search(query, page)

            if not response:
                logger.warning(f"第{page}页搜索失败，停止搜索")
                break

            results = response.get_assets()
            if not results:
                logger.info(f"第{page}页无结果，搜索完成")
                break

            all_results.extend(results)
            logger.info(f"已获取第{page}页，共{len(results)}条，总计{len(all_results)}条")

            # 检查是否达到目标数量
            if len(all_results) >= self.config.end_count:
                all_results = all_results[:self.config.end_count]
                break

            page += 1

        return all_results

    def get_count(self, query: str) -> int:
        """
        获取搜索结果总数

        Args:
            query: 搜索查询

        Returns:
            结果总数
        """
        response = self.search(query, page=1)
        if response:
            return response.get_total()
        return 0


class MultiSearchClient:
    """
    多查询客户端 - 支持批量搜索
    """

    def __init__(self, config: SearchConfig):
        self.config = config
        self.client = AnonymousFofaClient(config)

    def search_batch(self, queries: List[str]) -> Dict[str, List[SearchResult]]:
        """
        批量搜索多个查询

        Args:
            queries: 查询列表

        Returns:
            {query: results} 的字典
        """
        results = {}

        for query in queries:
            logger.info(f"开始搜索: {query}")
            query_results = self.client.search_all(query)
            results[query] = query_results
            logger.info(f"搜索完成: {query}, 结果数: {len(query_results)}")

            # 批量搜索时的额外延迟
            if self.config.time_sleep > 0:
                time.sleep(self.config.time_sleep)

        return results

    async def search_batch_async(self, queries: List[str]) -> Dict[str, List[SearchResult]]:
        """
        异步批量搜索

        Args:
            queries: 查询列表

        Returns:
            {query: results} 的字典
        """
        tasks = []

        for query in queries:
            # 为每个查询创建异步任务
            task = self._search_single_async(query)
            tasks.append(task)

        # 并发执行
        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        # 组装结果
        results = {}
        for i, query in enumerate(queries):
            result = results_list[i]
            if isinstance(result, Exception):
                logger.error(f"查询 '{query}' 失败: {result}")
                results[query] = []
            else:
                results[query] = result

        return results

    async def _search_single_async(self, query: str) -> List[SearchResult]:
        """异步搜索单个查询"""
        # 使用异步客户端
        async with httpx.AsyncClient(
            headers=AnonymousFofaClient.DEFAULT_HEADERS,
            timeout=self.config.timeout,
            follow_redirects=True,
            http2=True,
            proxies={"all://": self.config.proxy} if self.config.proxy else None
        ) as client:
            # 模拟速率限制
            await asyncio.sleep(self.config.time_sleep)

            # 执行搜索
            url = f"{AnonymousFofaClient.SEARCH_URL}?qbase64={base64.b64encode(query.encode('utf-8')).decode('utf-8')}"

            try:
                response = await client.get(url)
                response.raise_for_status()

                # 解析响应
                client_sync = AnonymousFofaClient(self.config)
                data = client_sync._parse_json_response(response.text)

                if not data:
                    return []

                assets = client_sync._extract_assets_from_data(data)
                results = [client_sync._parse_asset_to_result(asset) for asset in assets]

                # 数量限制
                if len(results) > self.config.end_count:
                    results = results[:self.config.end_count]

                return results
            except Exception as e:
                logger.error(f"异步搜索 '{query}' 失败: {e}")
                return []