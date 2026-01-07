"""精简日志工具"""
import logging
import sys


def get_logger(name=None):
    """获取简单logger"""
    logger = logging.getLogger(name or __name__)

    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    # 控制台处理器
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)

    # 简单格式
    formatter = logging.Formatter('%(message)s')
    handler.setFormatter(formatter)

    logger.addHandler(handler)
    logger.propagate = False

    return logger