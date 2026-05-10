"""
配置热加载机制。

ConfigManager 是单例类，负责：
- 从 .env 文件重新加载环境变量
- 通知 ProviderFactory 清空缓存
- 下次 create_from_env() 自动使用新配置
"""
import os
import logging
from dotenv import load_dotenv

from llm.factory import ProviderFactory

logger = logging.getLogger(__name__)


class ConfigManager:
    """配置管理器单例。"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def reload(self):
        """从 .env 文件重新加载所有环境变量到 os.environ。

        调用后，ProviderFactory 缓存被清空，
        下次 create_from_env() 自动使用新配置。
        """
        # 强制覆盖现有环境变量
        load_dotenv(override=True)
        # 清空 Provider 实例缓存
        ProviderFactory.clear_cache()
        logger.info("Config reloaded from .env, provider cache cleared")

    @staticmethod
    def get_env_path() -> str:
        """返回 .env 文件路径。"""
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(project_root, ".env")


def get_config_manager() -> ConfigManager:
    """返回 ConfigManager 单例。"""
    return ConfigManager()
