import os
from typing import Dict, List, Optional

from llm.base import BaseProvider
from llm.providers.deepseek_provider import DeepSeekProvider
from llm.providers.openai_compat_provider import OpenAICompatProvider

_env_loaded = False


def _ensure_env():
    """确保 .env 已加载到 os.environ，多次调用只加载一次。"""
    global _env_loaded
    if not _env_loaded:
        from dotenv import load_dotenv
        load_dotenv(override=True)
        _env_loaded = True


class ProviderFactory:
    _instances: Dict[str, BaseProvider] = {}

    _REGISTRY: Dict[str, type] = {
        "deepseek": DeepSeekProvider,
        "openai_compat": OpenAICompatProvider,
    }

    _ENV_PREFIX_MAP: Dict[str, str] = {
        "leader": "LEADER",
        "attacker": "ATTACKER",
        "hawkeye": "HAWKEYE",
        "analyst": "ANALYST",
    }

    _AUTO_DETECT_RULES: Dict[str, str] = {
        "deepseek.com": "deepseek",
        "dashscope": "dashscope",
        "aliyuncs.com": "dashscope",
        "openai.com": "openai",
        "anthropic.com": "anthropic",
        "bigmodel.cn": "zhipu",
    }

    @classmethod
    def create(
        cls,
        provider_type: str,
        api_key: str,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ) -> BaseProvider:
        provider_cls = cls._REGISTRY.get(provider_type)
        if provider_cls is None:
            provider_cls = OpenAICompatProvider
        return provider_cls(api_key=api_key, base_url=base_url, model=model)

    @classmethod
    def auto_detect(cls, base_url: str) -> str:
        if not base_url:
            return "openai_compat"
        base_url_lower = base_url.lower()
        for keyword, provider_type in cls._AUTO_DETECT_RULES.items():
            if keyword in base_url_lower:
                return provider_type
        return "openai_compat"

    @classmethod
    def list_presets(cls) -> List[dict]:
        result = []
        for provider_type, provider_cls in cls._REGISTRY.items():
            result.append({
                "provider_type": provider_type,
                "default_base_url": provider_cls.DEFAULT_BASE_URL,
                "recommended_models": provider_cls.RECOMMENDED_MODELS,
                "supports_json_mode": provider_cls.SUPPORTS_JSON_MODE,
            })
        return result

    @classmethod
    def create_from_env(cls, agent_type: str) -> BaseProvider:
        _ensure_env()
        if agent_type in cls._instances:
            return cls._instances[agent_type]

        prefix = cls._ENV_PREFIX_MAP.get(agent_type, "")

        api_key = os.getenv(f"{prefix}_API_KEY") or os.getenv("DEFAULT_API_KEY")
        base_url = os.getenv(f"{prefix}_BASE_URL") or os.getenv("DEFAULT_BASE_URL")
        model = os.getenv(f"{prefix}_MODEL") or os.getenv("DEFAULT_MODEL")

        provider_type = cls.auto_detect(base_url)

        provider = cls.create(
            provider_type=provider_type,
            api_key=api_key,
            base_url=base_url,
            model=model,
        )
        cls._instances[agent_type] = provider
        return provider

    @classmethod
    def clear_cache(cls):
        cls._instances.clear()
