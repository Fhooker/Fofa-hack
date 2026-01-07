"""
搜索配置和数据模型
"""
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


class OutputFormat(str, Enum):
    """输出格式枚举"""
    TXT = "txt"
    JSON = "json"
    CSV = "csv"


class SearchLevel(str, Enum):
    """搜索详细级别"""
    BASIC = "1"      # 只有URL
    MEDIUM = "2"     # URL + 端口 + 标题 + IP
    FULL = "3"       # 完整信息


class SearchConfig(BaseModel):
    """搜索配置模型"""
    keyword: str = Field(..., description="搜索关键词")
    output_format: OutputFormat = Field(default=OutputFormat.TXT, description="输出格式")
    output_name: str = Field(default="fofa_results", description="输出文件名")
    level: SearchLevel = Field(default=SearchLevel.BASIC, description="搜索详细级别")
    end_count: int = Field(default=100, description="目标结果数量")
    time_sleep: float = Field(default=3.0, description="请求间隔(秒)")
    timeout: int = Field(default=180, description="请求超时时间(秒)")
    fuzz: bool = Field(default=False, description="是否启用fuzz模式")
    debug: bool = Field(default=False, description="是否启用调试模式")
    proxy: Optional[str] = Field(default=None, description="代理地址")
    fofa_key: Optional[str] = Field(default=None, description="Fofa API Key")
    input_file: Optional[str] = Field(default=None, description="批量搜索文件")
    time_type: str = Field(default="day", description="时间类型: day/hour")


class SearchResult(BaseModel):
    """单条搜索结果"""
    link: str = Field(default="", description="完整URL")
    host: str = Field(default="", description="主机地址")
    port: int = Field(default=0, description="端口")
    title: str = Field(default="", description="页面标题")
    ip: str = Field(default="", description="IP地址")
    city: str = Field(default="", description="城市")
    asn: str = Field(default="", description="ASN编号")
    organization: str = Field(default="", description="组织")
    server: str = Field(default="", description="服务器信息")
    mtime: str = Field(default="", description="最后修改时间")

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return self.model_dump()

    def to_txt(self) -> str:
        """转换为文本格式"""
        if self.link:
            return self.link
        return self.host

    def to_csv_row(self) -> List[str]:
        """转换为CSV行"""
        return [
            self.link, self.host, str(self.port), self.title,
            self.ip, self.city, self.asn, self.organization,
            self.server, self.mtime
        ]


class FofaResponse(BaseModel):
    """Fofa API响应模型"""
    code: int = Field(default=0, description="状态码")
    message: str = Field(default="", description="消息")
    data: Dict[str, Any] = Field(default_factory=dict, description="响应数据")

    def get_assets(self) -> List[Dict[str, Any]]:
        """获取资产列表"""
        return self.data.get("assets", [])

    def get_total(self) -> int:
        """获取总数"""
        return self.data.get("total", 0)

    def get_next_token(self) -> Optional[str]:
        """获取下一页token"""
        return self.data.get("next")