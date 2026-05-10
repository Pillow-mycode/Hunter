from llm.providers.openai_compat_provider import OpenAICompatProvider


class AnthropicProvider(OpenAICompatProvider):
    PROVIDER_TYPE = "anthropic"
    DEFAULT_BASE_URL = "https://api.anthropic.com"
    RECOMMENDED_MODELS = [
        "claude-opus-4-7",
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
        "claude-sonnet-5",
    ]
    SUPPORTS_JSON_MODE = True
    DEFAULT_CONTEXT_LIMIT = 200000
