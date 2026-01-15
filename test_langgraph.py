"""
测试 LangGraph 1.0+ 兼容性
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def test_imports():
    """测试导入"""
    print("测试导入...")
    
    try:
        from langgraph.graph import StateGraph, END
        print("✓ langgraph.graph.StateGraph, END 导入成功")
    except ImportError as e:
        print(f"✗ langgraph.graph 导入失败: {e}")
        return False
    
    try:
        from langgraph.graph.message import add_messages
        print("✓ langgraph.graph.message.add_messages 导入成功")
    except ImportError as e:
        print(f"✗ langgraph.graph.message.add_messages 导入失败: {e}")
        return False
    
    try:
        from langgraph.checkpoint.memory import MemorySaver
        print("✓ langgraph.checkpoint.memory.MemorySaver 导入成功")
    except ImportError as e:
        print(f"✗ langgraph.checkpoint.memory.MemorySaver 导入失败: {e}")
        return False
    
    try:
        from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
        print("✓ langchain_core.messages 导入成功")
    except ImportError as e:
        print(f"✗ langchain_core.messages 导入失败: {e}")
        return False
    
    return True


def test_state_graph():
    """测试 StateGraph"""
    print("\n测试 StateGraph...")
    
    try:
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
        print("✓ StateGraph 构建成功")
        
        result = graph.invoke({"messages": [], "count": 0})
        print(f"✓ 图执行成功: {result}")
        
        return True
    except Exception as e:
        print(f"✗ StateGraph 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_agentic_rag():
    """测试 AgenticRAG"""
    print("\n测试 AgenticRAG...")
    
    try:
        from app.agents import agentic_rag_manager
        
        print("✓ AgenticRAG 管理器导入成功")
        
        graph = agentic_rag_manager.build_graph()
        print("✓ AgenticRAG 图构建成功")
        
        return True
    except Exception as e:
        print(f"✗ AgenticRAG 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """主函数"""
    print("=" * 50)
    print("LangGraph 1.0+ 兼容性测试")
    print("=" * 50)
    print()
    
    results = []
    
    results.append(("导入测试", test_imports()))
    results.append(("StateGraph 测试", test_state_graph()))
    results.append(("AgenticRAG 测试", test_agentic_rag()))
    
    print("\n" + "=" * 50)
    print("测试结果汇总")
    print("=" * 50)
    
    for name, result in results:
        status = "✓ 通过" if result else "✗ 失败"
        print(f"{name}: {status}")
    
    all_passed = all(result for _, result in results)
    
    print("\n" + "=" * 50)
    if all_passed:
        print("所有测试通过！")
    else:
        print("部分测试失败，请检查错误信息")
    print("=" * 50)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
