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
        if "temperature" not in params:
            params["temperature"] = self.DEFAULT_TEMPERATURE
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
        return self.DEFAULT_CONTEXT_LIMIT
