from abc import ABC, abstractmethod
from typing import Generator


class BaseProvider(ABC):
    """LLM Provider 抽象基类，所有厂商 Provider 继承此类。

    子类必须实现：chat(), get_context_limit()
    子类可选覆盖：chat_stream(), supports_json_mode(), health_check()
    """

    def __init__(self, api_key: str, base_url: str, model: str, **extra_params):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.extra_params = extra_params

    @abstractmethod
    def chat(self, messages: list, **kwargs) -> str:
        """非流式调用，返回完整回复文本。"""
        ...

    def chat_stream(self, messages: list, **kwargs) -> Generator[str, None, None]:
        """流式调用，逐 chunk yield 文本。

        默认实现降级为非流式：调用 chat() 后一次性 yield 整个结果。
        支持 stream 的厂商覆盖此方法。
        """
        yield self.chat(messages, **kwargs)

    def supports_json_mode(self) -> bool:
        """是否支持原生 response_format={"type": "json_object"}。"""
        return False

    @abstractmethod
    def get_context_limit(self) -> int:
        """返回该模型的最大上下文 token 数。"""
        ...

    def health_check(self) -> bool:
        """发送一条最小消息测试 API 连通性。"""
        try:
            self.chat([{"role": "user", "content": "hi"}], max_tokens=5)
            return True
        except Exception:
            return False

    def _merge_kwargs(self, **kwargs) -> dict:
        """合并默认参数与调用时参数。

        优先级: kwargs > extra_params > 类默认值
        子类可覆盖此方法以修改默认 temperature 等。
        """
        default_temp = getattr(self, "DEFAULT_TEMPERATURE", 0.0)
        defaults = {"temperature": default_temp}
        return {**defaults, **self.extra_params, **kwargs}
