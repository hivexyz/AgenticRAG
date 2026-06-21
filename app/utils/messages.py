"""
消息角色转换工具
用于统一 LangChain 与 OpenAI 兼容消息格式之间的映射。
"""
from typing import Any, Dict, List


ROLE_MAPPING = {
    "human": "user",
    "ai": "assistant",
    "system": "system",
    "tool": "tool",
}


def normalize_message_role(role: str) -> str:
    """将内部消息角色统一映射为 OpenAI 兼容角色。"""
    return ROLE_MAPPING.get(role, role)


def langchain_message_to_dict(message: Any) -> Dict[str, str]:
    """将 LangChain 消息对象转换为 OpenAI 兼容字典。"""
    return {
        "role": normalize_message_role(getattr(message, "type", "")),
        "content": getattr(message, "content", ""),
    }


def langchain_messages_to_dicts(messages: List[Any]) -> List[Dict[str, str]]:
    """批量转换 LangChain 消息对象。"""
    return [langchain_message_to_dict(message) for message in messages]
