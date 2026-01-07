"""
输出处理模块
"""
import csv
import json
from pathlib import Path
from typing import List, Dict, Any

from ..models.search import SearchResult, OutputFormat
from .logger import get_logger

logger = get_logger(__name__)


class OutputHandler:
    """处理搜索结果的输出"""

    def __init__(self, filename: str, output_format: OutputFormat, level: str = "1"):
        """
        初始化输出处理器

        Args:
            filename: 输出文件名（不含扩展名）
            output_format: 输出格式
            level: 搜索级别
        """
        self.filename = filename
        self.output_format = output_format
        self.level = level
        self.header_written = False

        # 根据格式确定完整文件名
        self.filepath = self._get_filepath()

    def _get_filepath(self) -> Path:
        """获取完整文件路径"""
        ext = self.output_format.value
        return Path(f"{self.filename}.{ext}")

    def write(self, results: List[SearchResult]):
        """写入结果"""
        if not results:
            logger.warning("没有结果可写入")
            return

        if self.output_format == OutputFormat.TXT:
            self._write_txt(results)
        elif self.output_format == OutputFormat.JSON:
            self._write_json(results)
        elif self.output_format == OutputFormat.CSV:
            self._write_csv(results)

        logger.info(f"结果已保存到: {self.filepath}")

    def _write_txt(self, results: List[SearchResult]):
        """写入TXT格式"""
        with open(self.filepath, 'a', encoding='utf-8') as f:
            for result in results:
                if self.level == "1":
                    f.write(result.to_txt() + '\n')
                else:
                    f.write(str(result.model_dump()) + '\n')

    def _write_json(self, results: List[SearchResult]):
        """写入JSON格式"""
        data = []

        # 如果文件存在，先读取现有数据
        if self.filepath.exists() and self.filepath.stat().st_size > 0:
            try:
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except:
                data = []

        # 转换结果
        for result in results:
            if self.level == "1":
                data.append(result.to_txt())
            elif self.level == "2":
                data.append({
                    "url": result.link if result.link else result.host,
                    "port": result.port,
                    "title": result.title,
                    "ip": result.ip
                })
            else:
                data.append(result.model_dump())

        # 写入文件
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _write_csv(self, results: List[SearchResult]):
        """写入CSV格式"""
        file_exists = self.filepath.exists() and self.filepath.stat().st_size > 0

        with open(self.filepath, 'a', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)

            # 写入表头（仅当文件不存在或首次写入时）
            if not file_exists:
                headers = [
                    "link", "host", "port", "title", "ip",
                    "city", "asn", "organization", "server", "mtime"
                ]
                writer.writerow(headers)

            # 写入数据
            for result in results:
                if self.level == "1":
                    writer.writerow([result.to_txt()])
                else:
                    writer.writerow(result.to_csv_row())

    def clear_file(self):
        """清空输出文件"""
        if self.filepath.exists():
            self.filepath.unlink()
            logger.info(f"已清空文件: {self.filepath}")


class BatchOutputHandler:
    """批量输出处理器"""

    def __init__(self, base_filename: str, output_format: OutputFormat, level: str = "1"):
        self.base_filename = base_filename
        self.output_format = output_format
        self.level = level

    def write_batch(self, results_dict: Dict[str, List[SearchResult]]):
        """
        批量写入多个查询的结果

        Args:
            results_dict: {query: results} 的字典
        """
        for query, results in results_dict.items():
            if not results:
                continue

            # 为每个查询创建独立的文件名
            safe_query = "".join(c for c in query if c.isalnum() or c in (' ', '-', '_')).rstrip()
            safe_query = safe_query.replace(' ', '_')[:50]  # 限制长度
            filename = f"{self.base_filename}_{safe_query}"

            handler = OutputHandler(filename, self.output_format, self.level)
            handler.write(results)


def export_results(results: List[SearchResult], config) -> str:
    """
    导出结果的便捷函数

    Args:
        results: 搜索结果列表
        config: 搜索配置

    Returns:
        输出文件路径
    """
    handler = OutputHandler(
        filename=config.output_name,
        output_format=config.output_format,
        level=config.level.value
    )

    handler.clear_file()  # 清空旧文件
    handler.write(results)

    return str(handler.filepath)


def export_batch_results(results_dict: Dict[str, List[SearchResult]], config) -> List[str]:
    """
    批量导出结果的便捷函数

    Args:
        results_dict: {query: results} 的字典
        config: 搜索配置

    Returns:
        输出文件路径列表
    """
    handler = BatchOutputHandler(
        base_filename=config.output_name,
        output_format=config.output_format,
        level=config.level.value
    )

    handler.write_batch(results_dict)

    # 返回生成的文件路径
    paths = []
    for query in results_dict.keys():
        safe_query = "".join(c for c in query if c.isalnum() or c in (' ', '-', '_')).rstrip()
        safe_query = safe_query.replace(' ', '_')[:50]
        ext = config.output_format.value
        paths.append(f"{config.output_name}_{safe_query}.{ext}")

    return paths


def save_results(results: List[SearchResult], output_format: OutputFormat, output_name: str) -> str:
    """
    保存搜索结果

    Args:
        results: 搜索结果列表
        output_format: 输出格式
        output_name: 输出文件名（不含扩展名）

    Returns:
        输出文件路径
    """
    if not results:
        return ""

    # 确保目录存在
    output_path = Path(output_name)
    if output_path.parent:
        output_path.parent.mkdir(parents=True, exist_ok=True)

    filepath = Path(f"{output_name}.{output_format.value}")

    if output_format == OutputFormat.TXT:
        with open(filepath, 'w', encoding='utf-8') as f:
            for result in results:
                f.write(result.to_txt() + '\n')

    elif output_format == OutputFormat.JSON:
        import json
        data = [r.model_dump() for r in results]
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    elif output_format == OutputFormat.CSV:
        import csv
        with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            # 写入表头
            headers = ["link", "host", "port", "title", "ip", "city", "asn", "organization", "server", "mtime"]
            writer.writerow(headers)
            # 写入数据
            for result in results:
                writer.writerow(result.to_csv_row())

    return str(filepath)


def save_results_simple(results, filename, output_format):
    """简便保存函数"""
    return save_results(results, OutputFormat(output_format), filename)