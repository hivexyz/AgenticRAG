"""
应用入口文件
用于启动开发服务器和 Gradio 界面
"""
import threading
import time
import uvicorn
from app.main import app
from app.config import settings
from front.app import create_interface
from front.config import (
    GRADIO_SERVER_NAME,
    GRADIO_SERVER_PORT,
    GRADIO_SHARE,
)


def start_fastapi():
    """启动 FastAPI 后端服务"""
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,  # 线程模式下禁用重载
        log_level=settings.LOG_LEVEL.lower(),
    )


def start_gradio():
    """启动 Gradio 界面"""
    demo = create_interface()
    demo.launch(
        server_name=GRADIO_SERVER_NAME,
        server_port=GRADIO_SERVER_PORT,
        share=GRADIO_SHARE,
        quiet=False,
    )


if __name__ == "__main__":
    print("=" * 50)
    print("启动 AgenticRAG 系统")
    print("=" * 50)
    print()
    
    print(f"[1/2] 启动 FastAPI 后端服务...")
    print(f"      地址: http://{settings.HOST}:{settings.PORT}")
    print(f"      API 文档: http://{settings.HOST}:{settings.PORT}/docs")
    print()
    
    fastapi_thread = threading.Thread(target=start_fastapi, daemon=True)
    fastapi_thread.start()
    
    time.sleep(3)
    
    print(f"[2/2] 启动 Gradio 界面...")
    print(f"      地址: http://{GRADIO_SERVER_NAME}:{GRADIO_SERVER_PORT}")
    print()
    
    print("=" * 50)
    print("系统启动完成！")
    print("=" * 50)
    print()
    print("按 Ctrl+C 停止所有服务")
    print()
    
    try:
        start_gradio()
    except KeyboardInterrupt:
        print("\n正在停止服务...")
        print("服务已停止")

