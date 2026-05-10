from openai import OpenAI

from llm.base import BaseProvider


class DeepSeekProvider(BaseProvider):
    PROVIDER_TYPE = "deepseek"
    DEFAULT_BASE_URL = "https://api.deepseek.com"
    RECOMMENDED_MODELS = ["deepseek-v4-flash", "deepseek-v4"]
    SUPPORTS_JSON_MODE = True
    DEFAULT_TEMPERATURE = 0.0
    DEFAULT_CONTEXT_LIMIT = 131072  # 128K tokens

    def __init__(self, api_key, base_url=None, model=None, **kwargs):
        base_url = base_url or self.DEFAULT_BASE_URL
        model = model or self.RECOMMENDED_MODELS[0]
        super().__init__(api_key, base_url, model, **kwargs)
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def chat(self, messages, **kwargs):
        params = self._merge_kwargs(**kwargs)
        if self.supports_json_mode():
            params["response_format"] = {"type": "json_object"}
        completion = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            **params,
        )
        return completion.choices[0].message.content

    def chat_stream(self, messages, **kwargs):
        params = self._merge_kwargs(**kwargs)
        if self.supports_json_mode():
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
