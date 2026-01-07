"""
基于RSA签名的Fofa API客户端
支持匿名访问，无需API密钥
"""
import base64
import json
import time
import urllib.parse
from typing import List, Optional, Dict, Any

import httpx
from Cryptodome.Signature import PKCS1_v1_5
from Cryptodome.Hash import SHA256
from Cryptodome.PublicKey import RSA

from ..models.search import SearchConfig, SearchResult, FofaResponse
from ..utils.logger import get_logger

logger = get_logger(__name__)


# RSA私钥（用于生成签名）
RSA_PRIVATE_KEY = '''-----BEGIN RSA PRIVATE KEY-----
MIIEogIBAAKCAQEAv0xjefuBTF6Ox940ZqLLUFFBDtTcB9dAfDjWgyZ2A55K+VdG
c1L5LqJWuyRkhYGFTlI4K5hRiExvjXuwIEed1norp5cKdeTLJwmvPyFgaEh7Ow19
Tu9sTR5hHxThjT8ieArB2kNAdp8Xoo7O8KihmBmtbJ1umRv2XxG+mm2ByPZFlTdW
RFU38oCPkGKlrl/RzOJKRYMv10s1MWBPY6oYkRiOX/EsAUVae6zKRqNR2Q4HzJV8
gOYMPvqkau8hwN8i6r0z0jkDGCRJSW9djWk3Byi3R2oSdZ0IoS+91MFtKvWYdnNH
2Ubhlnu1P+wbeuIFdp2u7ZQOtgPX0mtQ263e5QIDAQABAoIBAD67GwfeTMkxXNr3
5/EcQ1XEP3RQoxLDKHdT4CxDyYFoQCfB0e1xcRs0ywI1be1FyuQjHB5Xpazve8lG
nTwIoB68E2KyqhB9BY14pIosNMQduKNlygi/hKFJbAnYPBqocHIy/NzJHvOHOiXp
dL0AX3VUPkWW3rTAsar9U6aqcFvorMJQ2NPjijcXA0p1MlZAZKODO2wqidfQ487h
xy0ZkriYVi419j83a1cCK0QocXiUUeQM6zRNgQv7LCmrFo2X4JEzlujEveqvsDC4
MBRgkK2lNH+AFuRwOEr4PIlk9rrpHA4O1V13P3hJpH5gxs5oLLM1CWWG9YWLL44G
zD9Tm8ECgYEA8NStMXyAmHLYmd2h0u5jpNGbegf96z9s/RnCVbNHmIqh/pbXizcv
mMeLR7a0BLs9eiCpjNf9hob/JCJTms6SmqJ5NyRMJtZghF6YJuCSO1MTxkI/6RUw
mrygQTiF8RyVUlEoNJyhZCVWqCYjctAisEDaBRnUTpNn0mLvEXgf1pUCgYEAy1kE
d0YqGh/z4c/D09crQMrR/lvTOD+LRMf9lH+SkScT0GzdNIT5yuscRwKsnE6SpC5G
ySJFVhCnCBsQqq+ohsrXt8a99G7ePTMSAGK3QtC7QS3liDmvPBk6mJiLrKiRAZos
vgPg7nTP8VuF0ZIKzkdWbGoMyNxVFZXovQ8BYxECgYBvCR9xGX4Qy6KiDlV18wNu
ElYkxVqFBBE0AJRg/u+bnQ9jWhi2zxLa1eWZgtss80c876I8lbkGNWedOVZioatm
MFLC4bFalqyZWyO7iP7i60LKvfDJfkOSlDUu3OikahFOiqyG1VBz4+M4U500alIU
AVKD14zTTZMopQSkgUXsoQKBgHd8RgiD3Qde0SJVv97BZzP6OWw5rqI1jHMNBK72
SzwpdxYYcd6DaHfYsNP0+VIbRUVdv9A95/oLbOpxZNi2wNL7a8gb6tAvOT1Cvggl
+UM0fWNuQZpLMvGgbXLu59u7bQFBA5tfkhLr5qgOvFIJe3n8JwcrRXndJc26OXil
0Y3RAoGAJOqYN2CD4vOs6CHdnQvyn7ICc41ila/H49fjsiJ70RUD1aD8nYuosOnj
wbG6+eWekyLZ1RVEw3eRF+aMOEFNaK6xKjXGMhuWj3A9xVw9Fauv8a2KBU42Vmcd
t4HRyaBPCQQsIoErdChZj8g7DdxWheuiKoN4gbfK4W1APCcuhUA=
-----END RSA PRIVATE KEY-----'''


class RsaSigner:
    """RSA签名生成器"""

    def __init__(self, private_key: str = RSA_PRIVATE_KEY):
        self.private_key = private_key

    def sign(self, message: str) -> str:
        """生成签名"""
        priv_key = RSA.importKey(self.private_key)
        h = SHA256.new(message.encode('utf-8'))
        signature = PKCS1_v1_5.new(priv_key).sign(h)
        return base64.b64encode(signature).decode()

    def build_signed_url(self, query: str, page: int = 1, size: int = 20, full: bool = False) -> str:
        """
        构建带签名的API URL

        Args:
            query: 搜索查询
            page: 页码
            size: 每页数量
            full: 是否搜索全部数据（默认只搜索最近一年）

        Returns:
            签名的API URL
        """
        qbase64 = base64.b64encode(query.encode('utf-8')).decode()
        ts = int(time.time() * 1000)

        # 构建签名消息（注意：参数顺序很重要）
        message = f'full{str(full).lower()}page{page}qbase64{qbase64}size{size}ts{ts}'
        sign = urllib.parse.quote(self.sign(message))

        # 构建URL
        url = (
            f'https://api.fofa.info/v1/search?'
            f'qbase64={urllib.parse.quote(qbase64)}&'
            f'full={str(full).lower()}&'
            f'page={page}&'
            f'size={size}&'
            f'ts={ts}&'
            f'sign={sign}&'
            f'app_id=9e9fb94330d97833acfbc041ee1a76793f1bc691'
        )
        return url


class ApiFofaClient:
    """基于API的Fofa客户端"""

    def __init__(self, config: SearchConfig):
        self.config = config
        self.signer = RsaSigner()

        # 配置HTTP客户端
        timeout = httpx.Timeout(config.timeout, connect=30.0)
        limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)

        self.client = httpx.Client(
            timeout=timeout,
            limits=limits,
            follow_redirects=True,
            http2=True
        )

        # 设置代理
        if config.proxy:
            self.client.proxies = {"all://": config.proxy}

        # 设置请求头
        self.client.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://fofa.info/",
            "Origin": "https://fofa.info",
            "X-Requested-With": "XMLHttpRequest"
        })

        # 速率限制
        self.request_count = 0
        self.last_request_time = 0

    def _rate_limit(self):
        """速率限制控制"""
        current_time = time.time()
        elapsed = current_time - self.last_request_time

        min_interval = self.config.time_sleep
        if elapsed < min_interval:
            sleep_time = min_interval - elapsed
            time.sleep(sleep_time)

        self.last_request_time = time.time()
        self.request_count += 1

    def _make_request(self, url: str, max_retries: int = 3) -> Optional[Dict[str, Any]]:
        """
        执行API请求，带重试机制

        Args:
            url: 请求URL
            max_retries: 最大重试次数

        Returns:
            JSON响应数据
        """
        for attempt in range(max_retries):
            try:
                self._rate_limit()

                if self.config.debug:
                    logger.debug(f"请求URL: {url}")
                    logger.debug(f"尝试次数: {attempt + 1}/{max_retries}")

                response = self.client.get(url)
                response.raise_for_status()

                data = response.json()

                # 检查是否被封禁
                if data.get('code') == -3000:
                    error_msg = data.get('message', 'IP被封禁')
                    logger.error(f"API错误: {error_msg}")

                    if self.config.proxy:
                        logger.info("尝试切换代理或增加延迟...")
                    else:
                        logger.warning("建议使用代理来避免IP封禁")

                    return None

                # 检查是否需要验证码（2025年Fofa新机制）
                if data.get('code') == 850100:
                    error_msg = data.get('message', '需要完成验证码')
                    logger.error(f"API错误: {error_msg}")
                    logger.error("🚨 Fofa已启用验证码验证，公共代理无法使用！")
                    logger.error("💡 建议方案：")
                    logger.error("   1. 使用--no-proxy参数尝试直连（可能仍需验证码）")
                    logger.error("   2. 手动登录Fofa账号获取cookie")
                    logger.error("   3. 更换高质量私密代理")
                    return None

                # 检查是否成功
                if data.get('code') == 0 or 'data' in data:
                    return data

                # 其他错误
                logger.warning(f"未知响应: {data}")
                return None

            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP错误 ({attempt + 1}/{max_retries}): {e.response.status_code}")
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2  # 指数退避
                    logger.info(f"等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)

            except json.JSONDecodeError as e:
                logger.error(f"JSON解析错误 ({attempt + 1}/{max_retries}): {e}")
                if self.config.debug:
                    logger.debug(f"原始响应: {response.text[:500]}")

            except Exception as e:
                logger.error(f"请求异常 ({attempt + 1}/{max_retries}): {e}")

            # 最后一次尝试失败
            if attempt == max_retries - 1:
                logger.error(f"请求失败，已重试 {max_retries} 次")
                return None

        return None

    def search(self, query: str, page: int = 1, size: Optional[int] = None) -> Optional[FofaResponse]:
        """
        执行搜索

        Args:
            query: 搜索查询
            page: 页码
            size: 每页数量（默认使用配置中的end_count，但不超过10000）

        Returns:
            FofaResponse对象
        """
        if size is None:
            # API限制单次最多10000条
            size = min(self.config.end_count, 10000)

        url = self.signer.build_signed_url(query, page=page, size=size)

        data = self._make_request(url)
        if not data:
            return None

        # 解析数据
        api_data = data.get('data', {})
        if not api_data:
            logger.warning("API返回数据为空")
            return FofaResponse(code=data.get('code', -1), message=data.get('message', '未知错误'), data={})

        assets = api_data.get('assets', [])
        total = api_data.get('total', 0)

        # 转换为SearchResult列表
        results = []
        for asset in assets:
            result = SearchResult(
                link=asset.get('link', ''),
                host=asset.get('host', ''),
                port=int(asset.get('port', 0)) if asset.get('port') else 0,
                title=asset.get('title', ''),
                ip=asset.get('ip', ''),
                city=asset.get('city', ''),
                asn=str(asset.get('asn', '')),
                organization=asset.get('organization', ''),
                server=asset.get('server', ''),
                mtime=asset.get('mtime', '')
            )
            results.append(result)

        return FofaResponse(
            code=200,
            message='success',
            data={
                'assets': [r.model_dump() for r in results],
                'total': total,
                'page': page
            }
        )

    def search_all(self, query: str, max_pages: int = 10) -> List[SearchResult]:
        """
        搜索所有页面直到达到目标数量

        Args:
            query: 搜索查询
            max_pages: 最大页数

        Returns:
            所有搜索结果
        """
        all_results = []
        page = 1

        while len(all_results) < self.config.end_count and page <= max_pages:
            response = self.search(query, page=page)

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

            # 检查是否还有更多结果
            total = response.get_total()
            if total > 0 and len(all_results) >= total:
                logger.info(f"已获取所有结果（共{total}条）")
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
        response = self.search(query, page=1, size=1)
        if response:
            return response.get_total()
        return -1  # -1表示查询失败


class MultiQueryApiClient:
    """多查询API客户端"""

    def __init__(self, config: SearchConfig):
        self.config = config
        self.client = ApiFofaClient(config)

    def search_batch(self, queries: List[str]) -> Dict[str, List[SearchResult]]:
        """
        批量搜索多个查询

        Args:
            queries: 查询列表

        Returns:
            {query: results} 的字典
        """
        results = {}

        for i, query in enumerate(queries, 1):
            logger.info(f"[{i}/{len(queries)}] 开始搜索: {query}")
            query_results = self.client.search_all(query)
            results[query] = query_results
            logger.info(f"[{i}/{len(queries)}] 搜索完成: {query}, 结果数: {len(query_results)}")

            # 批量搜索时的额外延迟
            if self.config.time_sleep > 0:
                time.sleep(self.config.time_sleep)

        return results

    async def search_batch_async(self, queries: List[str]) -> Dict[str, List[SearchResult]]:
        """
        异步批量搜索（需要实现异步客户端）

        Args:
            queries: 查询列表

        Returns:
            {query: results} 的字典
        """
        # 同步实现（异步需要额外的异步HTTP客户端）
        return self.search_batch(queries)


def create_client(config: SearchConfig):
    """
    创建合适的客户端

    Args:
        config: 配置对象

    Returns:
        客户端实例
    """
    # 优先使用API客户端（基于RSA签名）
    return ApiFofaClient(config)