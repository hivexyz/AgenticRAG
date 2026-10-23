"""
LLM 模型管理
支持 OpenAI 兼容的 API
"""
from openai import AsyncOpenAI
from typing import List, Dict, Any, Optional
from app.config import settings
from app.log_context import current_request_context
from app.services.tenant_limits import tenant_limits
from app.utils.logger import logger


class LLMManager:
    """LLM 模型管理器"""
    
    def __init__(self):
        self.api_key = settings.OPENAI_API_KEY
        self.base_url = settings.OPENAI_BASE_URL
        self.model = settings.OPENAI_MODEL
        self.client: Optional[AsyncOpenAI] = None
        self.temperature = settings.OPENAI_TEMPERATURE
        self.max_tokens = settings.OPENAI_MAX_TOKENS
        self.top_p = settings.OPENAI_TOP_P
        self.frequency_penalty = settings.OPENAI_FREQUENCY_PENALTY
        self.presence_penalty = settings.OPENAI_PRESENCE_PENALTY
    
    def connect(self):
        """初始化 OpenAI 客户端"""
        if not self.api_key:
            logger.warning("未配置 OPENAI_API_KEY，LLM 功能将不可用")
            return
        
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url if self.base_url else None,
        )
        logger.info(f"LLM 客户端初始化成功，模型: {self.model}")

    def disconnect(self):
        """关闭客户端引用。"""
        self.client = None

    def _tenant_id_for_accounting(self) -> str:
        return current_request_context().get("tenant_id") or settings.DEFAULT_TENANT_ID

    def _estimate_text_tokens(self, text: str) -> int:
        normalized = text or ""
        if not normalized:
            return 0
        try:
            import tiktoken

            encoding = tiktoken.encoding_for_model(self.model)
            return len(encoding.encode(normalized))
        except Exception:
            return max(1, len(normalized) // 4)

    def _estimate_messages_tokens(self, messages: List[Dict[str, str]]) -> int:
        total = 0
        for message in messages or []:
            total += self._estimate_text_tokens(str(message.get("role") or ""))
            total += self._estimate_text_tokens(str(message.get("content") or ""))
        return total

    def _record_usage(self, usage: Optional[Dict[str, Any]], *, fallback_tokens: int = 0) -> None:
        token_count = 0
        if isinstance(usage, dict):
            token_count = int(usage.get("total_tokens") or 0)
        if token_count <= 0:
            token_count = fallback_tokens
        if token_count > 0:
            tenant_limits.record_tokens(self._tenant_id_for_accounting(), token_count)
    
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        stream: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """
        聊天补全
        
        Args:
            messages: 消息列表，格式为 [{"role": "user", "content": "..."}]
            temperature: 温度参数
            max_tokens: 最大 token 数
            top_p: top_p 参数
            stream: 是否流式输出
            **kwargs: 其他参数
            
        Returns:
            响应结果
        """
        if not self.client:
            raise RuntimeError("LLM 客户端未初始化")
        
        try:
            reserved_tokens = 0
            if stream:
                reserved_tokens = self._estimate_messages_tokens(messages) + int(max_tokens if max_tokens is not None else self.max_tokens)
                self._record_usage(None, fallback_tokens=reserved_tokens)
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature if temperature is not None else self.temperature,
                max_tokens=max_tokens if max_tokens is not None else self.max_tokens,
                top_p=top_p if top_p is not None else self.top_p,
                stream=stream,
                **kwargs
            )
            
            if stream:
                return {"stream": True, "response": response}
            else:
                payload = {
                    "id": response.id,
                    "object": response.object,
                    "created": response.created,
                    "model": response.model,
                    "choices": [
                        {
                            "index": choice.index,
                            "message": {
                                "role": choice.message.role,
                                "content": choice.message.content,
                            },
                            "finish_reason": choice.finish_reason,
                        }
                        for choice in response.choices
                    ],
                    "usage": {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                        "total_tokens": response.usage.total_tokens,
                    },
                }
                self._record_usage(payload["usage"])
                return payload
        except Exception as e:
            logger.error(f"LLM 聊天补全失败: {e}")
            raise
    
    async def completion(
        self,
        prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        stream: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """
        文本补全
        
        Args:
            prompt: 提示文本
            temperature: 温度参数
            max_tokens: 最大 token 数
            top_p: top_p 参数
            stream: 是否流式输出
            **kwargs: 其他参数
            
        Returns:
            响应结果
        """
        if not self.client:
            raise RuntimeError("LLM 客户端未初始化")
        
        try:
            reserved_tokens = 0
            if stream:
                reserved_tokens = self._estimate_text_tokens(prompt) + int(max_tokens if max_tokens is not None else self.max_tokens)
                self._record_usage(None, fallback_tokens=reserved_tokens)
            response = await self.client.completions.create(
                model=self.model,
                prompt=prompt,
                temperature=temperature if temperature is not None else self.temperature,
                max_tokens=max_tokens if max_tokens is not None else self.max_tokens,
                top_p=top_p if top_p is not None else self.top_p,
                stream=stream,
                **kwargs
            )
            
            if stream:
                return {"stream": True, "response": response}
            else:
                payload = {
                    "id": response.id,
                    "object": response.object,
                    "created": response.created,
                    "model": response.model,
                    "choices": [
                        {
                            "index": choice.index,
                            "text": choice.text,
                            "finish_reason": choice.finish_reason,
                        }
                        for choice in response.choices
                    ],
                    "usage": {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                        "total_tokens": response.usage.total_tokens,
                    },
                }
                self._record_usage(payload["usage"])
                return payload
        except Exception as e:
            logger.error(f"LLM 文本补全失败: {e}")
            raise
    
    async def count_tokens(self, text: str) -> int:
        """
        计算 token 数量
        
        Args:
            text: 输入文本
            
        Returns:
            token 数量
        """
        try:
            import tiktoken
            
            encoding = tiktoken.encoding_for_model(self.model)
            return len(encoding.encode(text))
        except Exception as e:
            logger.warning(f"无法计算 token 数量: {e}")
            return len(text.split())
