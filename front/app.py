"""
Gradio 主界面
"""
import gradio as gr
from typing import List, Dict, Any, Tuple
from .api_client import api_client
from .config import (
    APP_TITLE,
    APP_DESCRIPTION,
    APP_VERSION,
    DEFAULT_MAX_RETRIEVALS,
)


class AgenticRAGInterface:
    """AgenticRAG 问答界面"""
    
    def __init__(self):
        self.conversation_history: List[Dict[str, str]] = []
    
    def query(
        self,
        message: str,
        history: List[Dict[str, str]],
        max_retrievals: int,
        show_details: bool,
    ) -> Tuple[List[Dict[str, str]], str, str, str, str]:
        """
        执行 AgenticRAG 查询
        
        Args:
            message: 用户消息
            history: 对话历史
            max_retrievals: 最大检索次数
            show_details: 是否显示详细信息
            
        Returns:
            更新后的对话历史、答案、质量分数、查询分析、检索结果
        """
        if not message.strip():
            return history, "", "", "", ""
        
        # 调用 API
        result = api_client.agentic_rag_query(
            query=message,
            conversation_history=self.conversation_history,
            max_retrievals=max_retrievals,
        )
        
        # 检查错误
        if result.get("error"):
            error_msg = f"查询失败: {result['error']}"
            history.append({"role": "user", "content": message})
            history.append({"role": "assistant", "content": error_msg})
            return history, "", "", "", ""
        
        # 获取答案
        answer = result.get("answer", "")
        quality_score = result.get("quality_score", 0.0)
        
        # 更新对话历史
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": answer})
        self.conversation_history.append({"role": "user", "content": message})
        self.conversation_history.append({"role": "assistant", "content": answer})
        
        # 构建详细信息
        query_analysis = ""
        search_results = ""
        
        if show_details:
            # 查询分析
            analysis = result.get("query_analysis", {})
            if analysis:
                query_analysis = f"""查询类型: {analysis.get('query_type', 'N/A')}
复杂度: {analysis.get('complexity', 'N/A')}
关键词: {', '.join(analysis.get('keywords', []))}
搜索范围: {analysis.get('search_scope', 'N/A')}
建议检索数量: {analysis.get('top_k', 'N/A')}
需要重排序: {'是' if analysis.get('needs_rerank') else '否'}
说明: {analysis.get('explanation', '')}"""
            
            # 检索结果
            results = result.get("reranked_results") or result.get("search_results", [])
            if results:
                search_results = ""
                for i, doc in enumerate(results[:5], 1):
                    text = doc.get("text", doc.get("content", ""))[:200]
                    score = doc.get("relevance_score", doc.get("score", 0))
                    search_results += f"[结果 {i}] (分数: {score:.3f})\n{text}...\n\n"
        
        return history, answer, f"{quality_score:.2f}", query_analysis, search_results
    
    def clear_history(self) -> Tuple[List[Dict[str, str]], str, str, str, str]:
        """清除对话历史"""
        self.conversation_history = []
        return [], "", "", "", ""
    
    def analyze_query(self, query: str) -> str:
        """
        分析查询
        
        Args:
            query: 查询文本
            
        Returns:
            分析结果
        """
        if not query.strip():
            return "请输入查询内容"
        
        result = api_client.agentic_rag_analyze(query)
        
        if result.get("error"):
            return f"分析失败: {result['error']}"
        
        analysis = result.get("analysis", {})
        
        return f"""查询类型: {analysis.get('query_type', 'N/A')}
复杂度: {analysis.get('complexity', 'N/A')}
关键词: {', '.join(analysis.get('keywords', []))}
搜索范围: {analysis.get('search_scope', 'N/A')}
建议检索数量: {analysis.get('top_k', 'N/A')}
需要重排序: {'是' if analysis.get('needs_rerank') else '否'}
说明: {analysis.get('explanation', '')}"""


class DocumentManagerInterface:
    """文档管理界面"""
    
    def list_documents(self, skip: int = 0, limit: int = 10) -> str:
        """
        获取文档列表
        
        Args:
            skip: 跳过数量
            limit: 返回数量
            
        Returns:
            文档列表字符串
        """
        result = api_client.list_documents(skip=skip, limit=limit)
        
        if result.get("error"):
            return f"获取文档列表失败: {result['error']}"
        
        documents = result.get("documents", [])
        
        if not documents:
            return "暂无文档"
        
        output = ""
        for doc in documents:
            output += f"ID: {doc.get('id')}\n"
            output += f"标题: {doc.get('title', 'N/A')}\n"
            output += f"类型: {doc.get('file_type', 'N/A')}\n"
            output += f"块数: {doc.get('chunk_count', 'N/A')}\n"
            output += f"创建时间: {doc.get('created_at', 'N/A')}\n"
            output += "-" * 50 + "\n"
        
        return output
    
    def upload_document(
        self,
        title: str,
        content: str,
        metadata: str,
    ) -> str:
        """
        上传文档（纯文本）
        
        Args:
            title: 文档标题
            content: 文档内容
            metadata: 元数据（JSON 格式）
            
        Returns:
            上传结果
        """
        if not title or not content:
            return "请填写标题和内容"
        
        # 解析元数据
        metadata_dict = None
        if metadata:
            try:
                import json
                metadata_dict = json.loads(metadata)
            except json.JSONDecodeError:
                return "元数据格式错误，请使用有效的 JSON 格式"
        
        result = api_client.upload_document(
            title=title,
            content=content,
            metadata=metadata_dict,
        )
        
        if result.get("error"):
            return f"上传失败: {result['error']}"
        
        return f"文档上传成功！ID: {result.get('id')}"
    
    def upload_document_file(
        self,
        file,
        title: str,
        author: str,
        split_method: str,
        chunk_size: int,
        chunk_overlap: int,
        store_vectors: bool,
    ) -> str:
        """
        上传文档文件
        
        Args:
            file: 上传的文件（Gradio 返回的文件路径）
            title: 文档标题
            author: 作者
            split_method: 切分方法
            chunk_size: 块大小
            chunk_overlap: 块重叠大小
            store_vectors: 是否存储向量
            
        Returns:
            上传结果
        """
        if not file:
            return "请选择文件"
        
        # Gradio 返回的是文件路径字符串
        file_path = file if isinstance(file, str) else str(file)
        
        try:
            result = api_client.upload_document_file(
                file_path=file_path,
                title=title if title else None,
                author=author if author else None,
                split_method=split_method,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                store_vectors=store_vectors,
            )
            
            if result.get("error"):
                return f"上传失败: {result['error']}"
            
            return f"文档上传成功！\nID: {result.get('id')}\n类型: {result.get('file_type')}\n块数: {result.get('chunk_count')}"
        except Exception as e:
            return f"上传失败: {str(e)}"
    
    def delete_document(self, document_id: str) -> str:
        """
        删除文档
        
        Args:
            document_id: 文档 ID
            
        Returns:
            删除结果
        """
        if not document_id:
            return "请输入文档 ID"
        
        try:
            doc_id = int(document_id)
        except ValueError:
            return "文档 ID 必须是整数"
        
        result = api_client.delete_document(doc_id)
        
        if result.get("error"):
            return f"删除失败: {result['error']}"
        
        return "文档删除成功"


class SystemStatusInterface:
    """系统状态界面"""
    
    def check_health(self) -> str:
        """检查系统健康状态"""
        # 检查 API 健康状态
        api_health = api_client.health_check()
        
        # 检查 AgenticRAG 健康状态
        agentic_health = api_client.agentic_rag_health()
        
        output = "=== 系统健康状态 ===\n\n"
        
        # API 状态
        if api_health.get("error"):
            output += f"API 状态: ❌ {api_health['error']}\n"
        else:
            output += "API 状态: ✅ 正常\n"
        
        # AgenticRAG 状态
        if agentic_health.get("error"):
            output += f"AgenticRAG 状态: ❌ {agentic_health['error']}\n"
        else:
            output += f"AgenticRAG 状态: ✅ 正常\n"
            output += f"图已初始化: {'是' if agentic_health.get('graph_initialized') else '否'}\n"
            output += f"最大检索次数: {agentic_health.get('max_retrievals', 'N/A')}\n"
        
        return output
    
    def get_api_info(self) -> str:
        """获取 API 信息"""
        return f"""=== API 信息 ===

应用名称: {APP_TITLE}
应用描述: {APP_DESCRIPTION}
应用版本: {APP_VERSION}

API 基础 URL: {api_client.base_url}

配置参数:
- 默认最大检索次数: {DEFAULT_MAX_RETRIEVALS}
"""


def create_interface():
    """创建 Gradio 界面"""
    
    # 创建界面实例
    agentic_interface = AgenticRAGInterface()
    doc_interface = DocumentManagerInterface()
    status_interface = SystemStatusInterface()
    
    # 创建 AgenticRAG 问答界面
    with gr.Blocks(title=APP_TITLE) as demo:
        gr.Markdown(f"# {APP_TITLE}")
        gr.Markdown(APP_DESCRIPTION)
        
        with gr.Tabs():
            # AgenticRAG 问答标签页
            with gr.Tab("💬 AgenticRAG 问答"):
                with gr.Row():
                    with gr.Column(scale=2):
                        chatbot = gr.Chatbot(
                            label="对话历史",
                            height=500,
                        )
                        with gr.Row():
                            msg_input = gr.Textbox(
                                label="输入问题",
                                placeholder="请输入您的问题...",
                                scale=4,
                            )
                            submit_btn = gr.Button("发送", variant="primary", scale=1)
                        with gr.Row():
                            clear_btn = gr.Button("清除历史", variant="secondary")
                    
                    with gr.Column(scale=1):
                        with gr.Accordion("设置", open=True):
                            max_retrievals = gr.Slider(
                                minimum=1,
                                maximum=5,
                                value=DEFAULT_MAX_RETRIEVALS,
                                step=1,
                                label="最大检索次数",
                            )
                            show_details = gr.Checkbox(
                                value=True,
                                label="显示详细信息",
                            )
                        
                        with gr.Accordion("答案信息", open=True):
                            answer_output = gr.Textbox(
                                label="答案",
                                lines=10,
                                interactive=False,
                            )
                            quality_score = gr.Textbox(
                                label="质量分数",
                                interactive=False,
                            )
                        
                        with gr.Accordion("详细信息", open=False):
                            query_analysis = gr.Textbox(
                                label="查询分析",
                                lines=8,
                                interactive=False,
                            )
                            search_results = gr.Textbox(
                                label="检索结果",
                                lines=10,
                                interactive=False,
                            )
                
                # 事件绑定
                submit_btn.click(
                    fn=agentic_interface.query,
                    inputs=[msg_input, chatbot, max_retrievals, show_details],
                    outputs=[chatbot, answer_output, quality_score, query_analysis, search_results],
                )
                
                msg_input.submit(
                    fn=agentic_interface.query,
                    inputs=[msg_input, chatbot, max_retrievals, show_details],
                    outputs=[chatbot, answer_output, quality_score, query_analysis, search_results],
                )
                
                clear_btn.click(
                    fn=agentic_interface.clear_history,
                    outputs=[chatbot, answer_output, quality_score, query_analysis, search_results],
                )
            
            # 查询分析标签页
            with gr.Tab("🔍 查询分析"):
                with gr.Row():
                    with gr.Column():
                        analyze_input = gr.Textbox(
                            label="输入查询",
                            placeholder="请输入要分析的查询...",
                            lines=3,
                        )
                        analyze_btn = gr.Button("分析", variant="primary")
                    
                    with gr.Column():
                        analyze_output = gr.Textbox(
                            label="分析结果",
                            lines=10,
                            interactive=False,
                        )
                
                analyze_btn.click(
                    fn=agentic_interface.analyze_query,
                    inputs=[analyze_input],
                    outputs=[analyze_output],
                )
            
            # 文档管理标签页
            with gr.Tab("📄 文档管理"):
                with gr.Row():
                    with gr.Column():
                        gr.Markdown("### 上传文件")
                        file_upload = gr.File(
                            label="选择文件",
                            file_types=[".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".txt", ".md"],
                            type="filepath",
                        )
                        file_title = gr.Textbox(label="文档标题（可选）")
                        file_author = gr.Textbox(label="作者（可选）")
                        
                        with gr.Row():
                            split_method = gr.Dropdown(
                                choices=["recursive", "character", "token", "semantic", "paragraph", "sentence"],
                                value="recursive",
                                label="切分方法",
                            )
                            chunk_size = gr.Slider(
                                minimum=100,
                                maximum=2000,
                                value=1000,
                                step=100,
                                label="块大小",
                            )
                            chunk_overlap = gr.Slider(
                                minimum=0,
                                maximum=500,
                                value=200,
                                step=50,
                                label="块重叠大小",
                            )
                        
                        store_vectors = gr.Checkbox(
                            value=True,
                            label="存储向量到 Milvus",
                        )
                        
                        upload_file_btn = gr.Button("上传文件", variant="primary")
                        upload_file_output = gr.Textbox(
                            label="上传结果",
                            lines=5,
                            interactive=False,
                        )
                    
                    with gr.Column():
                        gr.Markdown("### 上传纯文本")
                        doc_title = gr.Textbox(label="文档标题")
                        doc_content = gr.Textbox(
                            label="文档内容",
                            lines=10,
                            placeholder="请输入文档内容...",
                        )
                        doc_metadata = gr.Textbox(
                            label="元数据（JSON 格式，可选）",
                            placeholder='{"key": "value"}',
                            lines=2,
                        )
                        upload_btn = gr.Button("上传文档", variant="primary")
                        upload_output = gr.Textbox(
                            label="上传结果",
                            lines=3,
                            interactive=False,
                        )
                
                with gr.Row():
                    with gr.Column():
                        gr.Markdown("### 文档列表")
                        list_btn = gr.Button("刷新文档列表", variant="secondary")
                        doc_list_output = gr.Textbox(
                            label="文档列表",
                            lines=15,
                            interactive=False,
                        )
                    
                    with gr.Column():
                        gr.Markdown("### 删除文档")
                        doc_id_input = gr.Textbox(label="文档 ID")
                        delete_btn = gr.Button("删除文档", variant="stop")
                        delete_output = gr.Textbox(
                            label="删除结果",
                            lines=2,
                            interactive=False,
                        )
                
                # 事件绑定
                upload_file_btn.click(
                    fn=doc_interface.upload_document_file,
                    inputs=[file_upload, file_title, file_author, split_method, chunk_size, chunk_overlap, store_vectors],
                    outputs=[upload_file_output],
                )
                
                upload_btn.click(
                    fn=doc_interface.upload_document,
                    inputs=[doc_title, doc_content, doc_metadata],
                    outputs=[upload_output],
                )
                
                list_btn.click(
                    fn=doc_interface.list_documents,
                    outputs=[doc_list_output],
                )
                
                delete_btn.click(
                    fn=doc_interface.delete_document,
                    inputs=[doc_id_input],
                    outputs=[delete_output],
                )
            
            # 系统状态标签页
            with gr.Tab("🔧 系统状态"):
                with gr.Row():
                    with gr.Column():
                        health_btn = gr.Button("检查健康状态", variant="primary")
                        health_output = gr.Textbox(
                            label="健康状态",
                            lines=10,
                            interactive=False,
                        )
                    
                    with gr.Column():
                        api_info_output = gr.Textbox(
                            label="API 信息",
                            lines=10,
                            interactive=False,
                            value=status_interface.get_api_info(),
                        )
                
                health_btn.click(
                    fn=status_interface.check_health,
                    outputs=[health_output],
                )
        
        gr.Markdown(f"\n---\n{APP_TITLE} v{APP_VERSION} | 基于 LangGraph 的智能体驱动的 RAG 系统")
    
    return demo


def launch():
    """启动 Gradio 界面"""
    from .config import (
        GRADIO_SERVER_NAME,
        GRADIO_SERVER_PORT,
        GRADIO_SHARE,
        GRADIO_AUTH,
    )
    
    demo = create_interface()
    
    demo.launch(
        server_name=GRADIO_SERVER_NAME,
        server_port=GRADIO_SERVER_PORT,
        share=GRADIO_SHARE,
        auth=GRADIO_AUTH,
    )


if __name__ == "__main__":
    launch()
