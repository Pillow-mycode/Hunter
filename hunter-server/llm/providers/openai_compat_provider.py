from openai import OpenAI

from llm.base import BaseProvider

_JSON_FORMAT_HINT = "\n\nPlease respond in valid JSON format only."


class OpenAICompatProvider(BaseProvider):
    """通用 OpenAI 兼容 Provider，兜底所有 API 兼容 OpenAI 的厂商。"""

    PROVIDER_TYPE = "openai_compat"
    DEFAULT_BASE_URL = ""
    RECOMMENDED_MODELS = []
    SUPPORTS_JSON_MODE = False
    DEFAULT_TEMPERATURE = 0.0
    DEFAULT_CONTEXT_LIMIT = 131072  # 保守默认 128K

    # 各模型上下文窗口 token 数（用于精确截断）
    MODEL_CONTEXT_LIMITS = {
        # DeepSeek
        "deepseek-v4": 131072,
        "deepseek-v4-flash": 131072,
        "deepseek-v3.1": 131072,
        "deepseek-r1": 131072,
        # OpenAI
        "gpt-5.5": 1050000,
        "gpt-5.4": 1050000,
        "gpt-5.4-mini": 400000,
        "gpt-5.4-nano": 400000,
        "gpt-4.1": 1047576,
        "gpt-4.1-mini": 1047576,
        "o3": 200000,
        "o4-mini": 200000,
        # Anthropic
        "claude-opus-4-7": 1000000,
        "claude-sonnet-4-6": 200000,
        "claude-haiku-4-5": 200000,
        "claude-sonnet-5": 1000000,
        # Qwen / DashScope
        "qwen3-max": 262144,
        "qwen3.6-plus": 1000000,
        "qwen3.6-flash": 1000000,
        "qwen-plus": 131072,
        "qwen-flash": 131072,
        "qwq-plus": 131072,
        # Zhipu GLM
        "glm-5.1": 203000,
        "glm-5": 203000,
        "glm-5-turbo": 203000,
        "glm-4.7": 205000,
        "glm-4.7-flash": 203000,
        "glm-4.6": 205000,
        # Moonshot / Kimi
        "kimi-k2.6": 262144,
        "kimi-k2.5": 262144,
        "kimi-k2.5-thinking": 262144,
        "kimi-k2-instruct": 131072,
        "kimi-k2-0905": 131072,
        # Groq
        "llama-3.3-70b-versatile": 131072,
        "llama-3.1-8b-instant": 131072,
        "meta-llama/llama-4-maverick-17b-128e-instruct": 131072,
        "meta-llama/llama-4-scout-17b-16e-instruct": 131072,
        "qwen/qwen3-32b": 131072,
        # xAI / Grok
        "grok-4.3": 1000000,
        "grok-4.20-reasoning": 2000000,
        "grok-4.20-non-reasoning": 2000000,
        "grok-4-1-fast-reasoning": 2000000,
        "grok-4-1-fast-non-reasoning": 2000000,
    }

    def __init__(self, api_key, base_url=None, model=None, **kwargs):
        base_url = base_url or self.DEFAULT_BASE_URL
        model = model or (self.RECOMMENDED_MODELS[0] if self.RECOMMENDED_MODELS else "")
        super().__init__(api_key, base_url, model, **kwargs)
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def _ensure_json_format(self, messages):
        """不支持 JSON mode 时，在最后一条 user message 追加 JSON 指令。"""
        msgs = list(messages)
        if msgs and msgs[-1]["role"] == "user":
            msgs[-1] = dict(msgs[-1])
            msgs[-1]["content"] = msgs[-1]["content"] + _JSON_FORMAT_HINT
        return msgs

    def chat(self, messages, **kwargs):
        params = self._merge_kwargs(**kwargs)
        if not self.supports_json_mode():
            messages = self._ensure_json_format(messages)
        else:
            params["response_format"] = {"type": "json_object"}
        completion = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            **params,
        )
        return completion.choices[0].message.content

    def chat_stream(self, messages, **kwargs):
        params = self._merge_kwargs(**kwargs)
        if not self.supports_json_mode():
            messages = self._ensure_json_format(messages)
        else:
            params["response_format"] = {"type": "json_object"}
        params["stream"] = True
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            **params,
        )
        for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def supports_json_mode(self):
        return self.SUPPORTS_JSON_MODE

    def get_context_limit(self):
        if self.model and self.model in self.MODEL_CONTEXT_LIMITS:
            return self.MODEL_CONTEXT_LIMITS[self.model]
        return self.DEFAULT_CONTEXT_LIMIT
