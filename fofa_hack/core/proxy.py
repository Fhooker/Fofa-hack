"""极速代理管理 - 支持自动刷新和多种策略"""
import httpx
import random
import time
import concurrent.futures
from typing import List, Optional, Dict
from queue import Queue
from threading import Thread

from ..utils.logger import get_logger

logger = get_logger(__name__)


class ProxyManager:
    """代理管理器 - 极速收集，智能切换"""

    def __init__(self, allow_direct: bool = True):
        self.proxies: List[str] = []
        self.failed: Dict[str, int] = {}
        self.idx = 0
        self.pool: Queue = Queue()
        self.is_ready = False
        self.allow_direct = allow_direct

        # 更多更快的代理源
        self.sources = [
            "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
            "https://raw.githubusercontent.com/mertguvencli/http-proxy-list/main/proxies.txt",
            "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
            "https://raw.githubusercontent.com/sunny9577/proxy-scraper/master/proxies/http.txt",
            "https://raw.githubusercontent.com/roosterkid/openproxylist/main/http.txt",
            "https://raw.githubusercontent.com/mmpx12/proxy-list/master/http.txt",
            "https://raw.githubusercontent.com/rdavydov/proxy-list/main/proxies/http.txt",
        ]

    def add_proxy(self, proxy: str):
        """添加单个代理"""
        if proxy and proxy not in self.proxies:
            self.proxies.append(proxy)
            self.pool.put(proxy)

    def get_proxy(self) -> Optional[str]:
        """获取可用代理 - 智能重置"""
        if not self.proxies:
            return None

        # 所有代理失败过多时重置失败计数
        if self.proxies and all(self.failed.get(p, 0) >= 3 for p in self.proxies):
            logger.info("代理失败次数过多，重置失败计数")
            self.failed.clear()

        # 轮询获取可用代理
        for _ in range(len(self.proxies)):
            proxy = self.proxies[self.idx]
            self.idx = (self.idx + 1) % len(self.proxies)
            if self.failed.get(proxy, 0) < 3:
                return proxy

        return None

    def get_next_proxy(self, current_proxy: Optional[str] = None) -> Optional[str]:
        """获取下一个不同的代理"""
        if not self.proxies:
            return None

        if len(self.proxies) == 1:
            return self.proxies[0] if self.failed.get(self.proxies[0], 0) < 3 else None

        # 找到下一个未失败的代理
        for _ in range(len(self.proxies)):
            proxy = self.proxies[self.idx]
            self.idx = (self.idx + 1) % len(self.proxies)
            if proxy != current_proxy and self.failed.get(proxy, 0) < 3:
                return proxy

        return None if self.failed.get(self.proxies[0], 0) >= 3 else self.proxies[0]

    def mark_failed(self, proxy: str):
        """标记代理失败"""
        if proxy:
            self.failed[proxy] = self.failed.get(proxy, 0) + 1
            logger.warning(f"代理失败 {proxy} (第{self.failed[proxy]}次)")

    def mark_success(self, proxy: str):
        """标记代理成功"""
        if proxy and proxy in self.failed:
            self.failed[proxy] = max(0, self.failed[proxy] - 1)

    @property
    def count(self) -> int:
        """返回可用代理数量"""
        return len(self.proxies)

    def get_stats(self) -> Dict[str, any]:
        """获取代理统计"""
        valid_count = len([p for p in self.proxies if self.failed.get(p, 0) < 3])
        return {
            "total": len(self.proxies),
            "valid": valid_count,
            "failed": len(self.failed),
            "is_ready": self.is_ready,
            "allow_direct": self.allow_direct
        }

    def auto_refresh(self, count: int = 5):
        """后台极速刷新代理"""
        if hasattr(self, '_refreshing') and self._refreshing:
            return

        self._refreshing = True
        thread = Thread(target=self._refresh_background, args=(count,), daemon=True)
        thread.start()

    def _fetch_source(self, source: str, timeout: float = 5.0) -> List[str]:
        """从单个源获取代理"""
        try:
            resp = httpx.get(source, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                lines = resp.text.strip().split('\n')
                proxies = []
                for line in lines:
                    line = line.strip()
                    if line and ':' in line and not line.startswith('#'):
                        proxy = f"http://{line}" if not line.startswith('http') else line
                        proxies.append(proxy)
                return proxies
        except Exception:
            pass
        return []

    def _validate_proxy(self, proxy: str, timeout: float = 1.5) -> bool:
        """验证代理 - 测试API端点"""
        try:
            import base64
            import time
            import urllib.parse

            with httpx.Client(
                proxies={"http://": proxy, "https://": proxy},
                timeout=timeout
            ) as client:
                # 测试实际的API搜索端点（快速查询一个简单条件）
                query = "port=80"
                qbase64 = base64.b64encode(query.encode('utf-8')).decode()
                ts = int(time.time() * 1000)

                # 构建简单的测试请求（不需要签名也能测试连通性）
                url = f"https://api.fofa.info/v1/search?qbase64={urllib.parse.quote(qbase64)}&page=1&size=1&full=false&ts={ts}"

                try:
                    resp = client.get(url, timeout=timeout)
                    # 检测Fofa的验证码/封禁机制
                    if resp.status_code == 200:
                        # 解析响应，检查是否被验证码拦截
                        try:
                            data = resp.json()
                            # 有实际数据返回才是有效代理
                            if data.get('code') == 0 and data.get('data'):
                                return True
                            # 检测到验证码或封禁错误码
                            if data.get('code') in [850100, -3000]:
                                return False
                        except:
                            pass
                    # 其他状态码都视为代理无效
                    return False
                except:
                    # 如果API不通，尝试WEB端点
                    pass

                # 备选方案：测试WEB端点
                try:
                    encoded_query = base64.b64encode(query.encode('utf-8')).decode('utf-8')
                    web_url = f"https://fofa.info/result?qbase64={encoded_query}"
                    resp = client.get(web_url, timeout=timeout)
                    # 检查是否重定向到验证码页面
                    if resp.status_code in [200, 301, 302]:
                        # 检查响应内容是否包含验证码相关
                        html = resp.text.lower()
                        if 'captcha' in html or '/captcha' in resp.url:
                            return False
                        return True
                    return False
                except:
                    return False
        except:
            return False

    def _refresh_background(self, count: int):
        """后台极速刷新"""
        try:
            collected: List[str] = []

            # 极速收集 - 并行获取
            logger.info("📡 开始并行收集代理...")
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                future_to_source = {
                    executor.submit(self._fetch_source, source, 5.0): source
                    for source in self.sources
                }
                for future in concurrent.futures.as_completed(future_to_source, timeout=25):
                    try:
                        # 等待源获取结果，超时时间应大于单个获取时间(5秒)
                        proxies = future.result(timeout=10.0)
                        collected.extend(proxies)
                    except:
                        continue

            if not collected:
                logger.warning("❌ 未从任何源获取到代理")
                self.is_ready = True
                return

            collected = list(set(collected))
            logger.info(f"📡 收集到 {len(collected)} 个原始代理")

            # 验证代理 - 确保质量
            valid = []
            test_count = min(20, len(collected))  # 验证前20个提高成功率
            logger.info(f"🔍 开始验证 {test_count} 个代理...")

            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                future_to_proxy = {
                    executor.submit(self._validate_proxy, proxy, 1.5): proxy
                    for proxy in collected[:test_count]
                }
                completed = 0
                failed_validation = 0
                for future in concurrent.futures.as_completed(future_to_proxy, timeout=30):
                    completed += 1
                    proxy = future_to_proxy[future]
                    if completed % 5 == 0:
                        logger.info(f"🔍 验证进度: {completed}/{test_count}")
                    try:
                        # 等待验证结果，超时时间应大于单个验证时间(1.5秒)
                        is_valid = future.result(timeout=3.0)
                        if is_valid:
                            valid.append(proxy)
                            logger.debug(f"✅ 代理验证通过: {proxy}")
                        else:
                            failed_validation += 1
                            logger.debug(f"❌ 代理验证失败: {proxy}")
                    except Exception as e:
                        failed_validation += 1
                        logger.debug(f"❌ 代理验证异常: {proxy} ({e})")
                        continue

            logger.info(f"✅ 验证完成: {len(valid)}/{test_count} 个有效代理 (失败: {failed_validation})")
            if len(valid) < 3:
                logger.warning("⚠️ 验证通过率低，Fofa可能启用了新限制")

            # 智能策略 - 确保只使用验证过的代理
            if len(valid) >= 5:
                self.proxies = valid
                logger.info(f"✅ 代理池就绪: {len(valid)} 个验证代理")
            elif len(valid) >= 1:
                # 验证代理不足，继续验证更多
                logger.info(f"⚠️ 验证代理不足({len(valid)}个)，验证剩余代理中...")

                # 验证剩余的代理
                remaining = [p for p in collected if p not in valid]
                more_valid = []

                logger.info(f"🔍 进入第二阶段验证: {len(remaining)} 个剩余代理...")
                with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                    future_to_proxy = {
                        executor.submit(self._validate_proxy, proxy, 1.5): proxy
                        for proxy in remaining[:50]  # 最多再验证50个
                    }
                    for future in concurrent.futures.as_completed(future_to_proxy, timeout=60):
                        proxy = future_to_proxy[future]
                        try:
                            # 等待验证结果，超时时间应大于单个验证时间(1.5秒)
                            is_valid = future.result(timeout=3.0)
                            if is_valid:
                                more_valid.append(proxy)
                                logger.debug(f"✅ 代理验证通过: {proxy}")
                        except Exception as e:
                            logger.debug(f"❌ 代理验证异常: {proxy} ({e})")
                            continue

                # 只使用验证通过的代理，绝不添加未验证的代理到池中
                self.proxies = valid + more_valid
                logger.info(f"✅ 代理池就绪: {len(self.proxies)} 个验证代理")
            else:
                # 完全没有验证的代理，数据太少
                logger.error("❌ 未收集到有效代理，将尝试直连模式（可能触发验证码）")
                if self.allow_direct:
                    self.proxies = []
                self.is_ready = True
                return

            # 填充队列
            for p in self.proxies:
                self.pool.put(p)

            self.is_ready = True
            logger.info(f"🎯 代理系统就绪，共 {len(self.proxies)} 个代理可用")

        except Exception as e:
            logger.error(f"代理刷新失败: {e}")
        finally:
            self._refreshing = False


class ManualProxyManager(ProxyManager):
    """支持手动指定代理的管理器"""

    def __init__(self, manual_proxies: Optional[List[str]] = None, allow_direct: bool = True):
        super().__init__(allow_direct=allow_direct)

        if manual_proxies:
            for proxy in manual_proxies:
                self.add_proxy(proxy)
            self.is_ready = True
            logger.info(f"📋 使用手动代理: {len(manual_proxies)} 个")

    def add_manual_proxy(self, proxy: str):
        """添加手动代理"""
        self.add_proxy(proxy)
        logger.info(f"➕ 添加手动代理: {proxy}")