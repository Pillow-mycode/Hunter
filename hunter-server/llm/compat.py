import json
import re


class LLMJsonParseError(Exception):
    """LLM 返回内容无法解析为 JSON。"""


class RateLimitError(Exception):
    """API 频率限制。"""

    def __init__(self, message="", retry_after=None):
        super().__init__(message)
        self.retry_after = retry_after


class AuthError(Exception):
    """API 认证失败（API Key 无效或无权限）。"""


class ContextTooLongError(Exception):
    """上下文超过模型限制。"""


class LLMAPIError(Exception):
    """通用 LLM API 错误，保留原始错误信息。"""


def parse_json_response(raw_text: str) -> dict:
    """解析 LLM 返回的文本为 JSON dict。

    处理常见情况：
    - 纯 JSON 文本
    - markdown 代码块包裹（```json ... ```）
    - JSON 前后有废话文字
    - 多重 ``` 代码块（取最后一个 JSON 块）
    """
    if not raw_text or not raw_text.strip():
        raise LLMJsonParseError("empty response")

    text = raw_text.strip()

    # 1. 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. 尝试提取 markdown json 代码块
    # 匹配 ```json ... ``` 或 ``` ... ```
    pattern = r"```(?:json)?\s*\n?(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL)
    if matches:
        # 取最后一个代码块（最近的是 LLM 的实际响应）
        for match in reversed(matches):
            try:
                return json.loads(match.strip())
            except json.JSONDecodeError:
                continue

    # 3. 找到第一个 { 到最后一个 }
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidate = text[first_brace : last_brace + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    raise LLMJsonParseError(f"cannot parse JSON from: {text[:200]}")


def map_provider_error(exception: Exception) -> Exception:
    """将厂商原始异常映射为项目标准异常。"""
    msg = str(exception)
    msg_lower = msg.lower()

    status_code = getattr(exception, "status_code", None)

    if status_code == 429 or "rate_limit" in msg_lower or "rate limit" in msg_lower:
        retry_after = None
        if hasattr(exception, "response") and exception.response:
            retry_after = exception.response.headers.get("Retry-After")
        return RateLimitError(msg, retry_after=retry_after)

    if status_code in (401, 403) or "unauthorized" in msg_lower or "invalid api key" in msg_lower:
        return AuthError(msg)

    if status_code == 400 and ("context length" in msg_lower or "token" in msg_lower or "too long" in msg_lower):
        return ContextTooLongError(msg)

    return LLMAPIError(msg)
