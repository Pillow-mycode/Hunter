"""
配置管理 API 端点
"""
import os
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from llm.factory import ProviderFactory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/config", tags=["config"])

ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")


# ============== 数据模型 ==============

class AgentConfigModel(BaseModel):
    provider_type: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None


class ConfigUpdateModel(BaseModel):
    default: Optional[AgentConfigModel] = None
    leader: Optional[AgentConfigModel] = None
    attacker: Optional[AgentConfigModel] = None
    hawkeye: Optional[AgentConfigModel] = None
    analyst: Optional[AgentConfigModel] = None


class TestConfigModel(BaseModel):
    provider_type: str
    base_url: str
    model: str
    api_key: str


# ============== 工具函数 ==============

def _mask_api_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return key[:4] + "****" + key[-4:]


def _reload_config():
    """触发热加载：reload .env → 清空 Provider 缓存。"""
    try:
        from llm.config_manager import get_config_manager
        get_config_manager().reload()
    except ImportError:
        from dotenv import load_dotenv
        load_dotenv(override=True)
        ProviderFactory.clear_cache()


def _get_agent_config(agent_type: str) -> dict:
    prefix_map = {
        "leader": "LEADER",
        "attacker": "ATTACKER",
        "hawkeye": "HAWKEYE",
        "analyst": "ANALYST",
    }
    prefix = prefix_map.get(agent_type, "")
    api_key = os.getenv(f"{prefix}_API_KEY") or os.getenv("DEFAULT_API_KEY") or ""
    base_url = os.getenv(f"{prefix}_BASE_URL") or os.getenv("DEFAULT_BASE_URL") or ""
    model = os.getenv(f"{prefix}_MODEL") or os.getenv("DEFAULT_MODEL") or ""
    provider_type = ProviderFactory.auto_detect(base_url) if base_url else ""

    return {
        "provider_type": provider_type,
        "base_url": base_url,
        "model": model,
        "api_key": _mask_api_key(api_key),
    }


def _write_env(config_dict: dict):
    """将配置字典写入 .env 文件，保留注释和空白行。"""
    env_path = os.path.normpath(ENV_FILE)

    if not os.path.exists(env_path):
        # 如果 .env 不存在，创建新的
        lines = []
    else:
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    # 构建 key → line_index 映射
    prefix_map = {
        "default": "DEFAULT",
        "leader": "LEADER",
        "attacker": "ATTACKER",
        "hawkeye": "HAWKEYE",
        "analyst": "ANALYST",
    }

    updates = {}
    for agent_type, agent_config in config_dict.items():
        if agent_config is None:
            continue
        prefix = prefix_map.get(agent_type, "")
        if not prefix:
            continue
        if agent_config.get("api_key") is not None:
            updates[f"{prefix}_API_KEY"] = agent_config["api_key"]
        if agent_config.get("base_url") is not None:
            updates[f"{prefix}_BASE_URL"] = agent_config["base_url"]
        if agent_config.get("model") is not None:
            updates[f"{prefix}_MODEL"] = agent_config["model"]

    # 更新现有行或追加新行
    updated_keys = set()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            key = stripped.split("=")[0].strip()
            if key in updates:
                lines[i] = f"{key}={updates[key]}\n"
                updated_keys.add(key)

    # 追加未更新的 key
    for key, value in updates.items():
        if key not in updated_keys:
            lines.append(f"{key}={value}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    logger.info("Config written to .env, %d keys updated", len(updates))


# ============== API 端点 ==============

@router.get("")
async def get_config():
    """返回当前所有 Agent 的配置（API Key 脱敏）。"""
    return {
        "default": _get_agent_config("default"),
        "leader": _get_agent_config("leader"),
        "attacker": _get_agent_config("attacker"),
        "hawkeye": _get_agent_config("hawkeye"),
        "analyst": _get_agent_config("analyst"),
    }


@router.post("")
async def update_config(body: ConfigUpdateModel):
    """更新配置并触发热加载。"""
    config_dict = {}
    for agent_type in ["default", "leader", "attacker", "hawkeye", "analyst"]:
        val = getattr(body, agent_type, None)
        if val is not None:
            config_dict[agent_type] = val.model_dump(exclude_none=True)

    if not config_dict:
        raise HTTPException(status_code=400, detail="No config provided")

    _write_env(config_dict)

    _reload_config()

    logger.info("Config updated and reloaded")
    return {"ok": True}


@router.get("/presets")
async def get_presets():
    """返回所有已注册 Provider 的预设信息。"""
    return ProviderFactory.list_presets()


@router.post("/test")
async def test_connection(body: TestConfigModel):
    """测试 LLM 连接。"""
    import time as _time
    start = _time.time()

    try:
        provider = ProviderFactory.create(
            provider_type=body.provider_type,
            api_key=body.api_key,
            base_url=body.base_url,
            model=body.model,
        )
        ok = provider.health_check()
        latency_ms = int((_time.time() - start) * 1000)
        if ok:
            return {"ok": True, "latency_ms": latency_ms}
        else:
            return {"ok": False, "error": "Health check returned false"}
    except Exception as e:
        latency_ms = int((_time.time() - start) * 1000)
        return {"ok": False, "error": str(e), "latency_ms": latency_ms}


@router.post("/reload")
async def reload_config():
    """强制从 .env 重读所有配置。"""
    _reload_config()

    logger.info("Config reloaded")
    return {"ok": True}
