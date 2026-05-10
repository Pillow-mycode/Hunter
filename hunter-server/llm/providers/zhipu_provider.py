from llm.providers.openai_compat_provider import OpenAICompatProvider


class ZhipuProvider(OpenAICompatProvider):
    PROVIDER_TYPE = "zhipu"
    DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
    RECOMMENDED_MODELS = [
        "glm-5.1",
        "glm-5",
        "glm-5-turbo",
        "glm-4.7",
        "glm-4.7-flash",
        "glm-4.6",
    ]
    SUPPORTS_JSON_MODE = True
    DEFAULT_CONTEXT_LIMIT = 131072
