"""
启动 Gradio 界面
"""
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from front.app import launch

if __name__ == "__main__":
    launch()
