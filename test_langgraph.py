"""
测试 LangGraph 1.0+ 兼容性
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def test_imports():
    """测试导入"""
    from langgraph.graph import StateGraph, END  # noqa: F401
    from langgraph.graph.message import add_messages  # noqa: F401
    from langgraph.checkpoint.memory import MemorySaver  # noqa: F401
    from langchain_core.messages import SystemMessage, HumanMessage, AIMessage  # noqa: F401

    assert StateGraph is not None
    assert END is not None
    assert add_messages is not None
    assert MemorySaver is not None
    assert SystemMessage is not None
    assert HumanMessage is not None
    assert AIMessage is not None


def test_state_graph():
    """测试 StateGraph"""
    from langgraph.graph import StateGraph, END
    from langgraph.graph.message import add_messages
    from typing import TypedDict, Annotated

    class TestState(TypedDict):
        messages: Annotated[list, add_messages]
        count: int

    def test_node(state: TestState) -> TestState:
        return {"count": state.get("count", 0) + 1}

    workflow = StateGraph(TestState)
    workflow.add_node("test", test_node)
    workflow.set_entry_point("test")
    workflow.add_edge("test", END)

    graph = workflow.compile()
    result = graph.invoke({"messages": [], "count": 0})

    assert result["count"] == 1


def test_agentic_rag():
    """测试 AgenticRAG"""
    from app.agents import agentic_rag_manager

    graph = agentic_rag_manager.build_graph()
    assert graph is not None


def main():
    """主函数"""
    print("=" * 50)
    print("LangGraph 1.0+ 兼容性测试")
    print("=" * 50)
    print()

    tests = [
        ("导入测试", test_imports),
        ("StateGraph 测试", test_state_graph),
        ("AgenticRAG 测试", test_agentic_rag),
    ]

    results = []
    for name, fn in tests:
        try:
            fn()
            results.append((name, True))
        except Exception as exc:  # pragma: no cover
            print(f"{name}: ✗ 失败 - {exc}")
            results.append((name, False))

    print("\n" + "=" * 50)
    print("测试结果汇总")
    print("=" * 50)

    for name, result in results:
        status = "✓ 通过" if result else "✗ 失败"
        print(f"{name}: {status}")

    all_passed = all(result for _, result in results)
    print("\n" + "=" * 50)
    print("所有测试通过！" if all_passed else "部分测试失败，请检查错误信息")
    print("=" * 50)
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
