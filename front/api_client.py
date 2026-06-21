"""
API 客户端
用于与后端 API 交互
"""
import requests
from typing import Dict, Any, List, Optional
from .config import API_V1_URL
import json


class APIClient:
    """API 客户端类"""
    
    def __init__(self, base_url: str = API_V1_URL):
        self.base_url = base_url
        self.session = requests.Session()
    
    def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        发送 HTTP 请求
        
        Args:
            method: HTTP 方法
            endpoint: API 端点
            data: 请求数据
            params: 查询参数
            
        Returns:
            响应数据
        """
        url = f"{self.base_url}{endpoint}"
        
        try:
            if method.upper() == "GET":
                response = self.session.get(url, params=params)
            elif method.upper() == "POST":
                response = self.session.post(url, json=data)
            elif method.upper() == "PUT":
                response = self.session.put(url, json=data)
            elif method.upper() == "DELETE":
                response = self.session.delete(url, params=params)
            else:
                raise ValueError(f"不支持的 HTTP 方法: {method}")
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            return {
                "error": f"请求失败: {str(e)}",
                "status_code": getattr(e.response, "status_code", None) if hasattr(e, "response") else None
            }
    
    def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        return self._request("GET", "/health")
    
    def agentic_rag_query(
        self,
        query: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        max_retrievals: int = 2,
        tenant_id: str = "default",
    ) -> Dict[str, Any]:
        """
        执行 AgenticRAG 查询
        
        Args:
            query: 用户查询
            conversation_history: 对话历史
            max_retrievals: 最大检索次数
            
        Returns:
            查询结果
        """
        data = {
            "query": query,
            "max_retrievals": max_retrievals,
            "tenant_id": tenant_id,
        }
        
        if conversation_history:
            data["conversation_history"] = conversation_history
        
        return self._request("POST", "/ai/agentic-rag/query", data=data)
    
    def agentic_rag_analyze(self, query: str) -> Dict[str, Any]:
        """
        分析查询
        
        Args:
            query: 用户查询
            
        Returns:
            分析结果
        """
        data = {"query": query}
        return self._request("POST", "/ai/agentic-rag/analyze", data=data)
    
    def agentic_rag_health(self) -> Dict[str, Any]:
        """AgenticRAG 健康检查"""
        return self._request("GET", "/ai/agentic-rag/health")
    
    def create_embedding(self, text: str) -> Dict[str, Any]:
        """
        创建嵌入向量
        
        Args:
            text: 输入文本
            
        Returns:
            嵌入向量
        """
        data = {"input": text}
        return self._request("POST", "/ai/embedding", data=data)
    
    def search_vectors(
        self,
        query: str,
        top_k: int = 10,
        rerank_top_k: int = 5,
    ) -> Dict[str, Any]:
        """
        搜索向量
        
        Args:
            query: 查询文本
            top_k: 检索数量
            rerank_top_k: 重排序后返回数量
            
        Returns:
            搜索结果
        """
        data = {
            "query": query,
            "top_k": top_k,
            "rerank_top_k": rerank_top_k,
        }
        return self._request("POST", "/ai/search", data=data)
    
    def upload_document(
        self,
        title: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        tenant_id: str = "default",
        store_vectors: bool = False,
        split_method: str = "recursive",
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ) -> Dict[str, Any]:
        """
        上传文档（纯文本）
        
        Args:
            title: 文档标题
            content: 文档内容
            metadata: 元数据
            
        Returns:
            上传结果
        """
        data = {
            "tenant_id": tenant_id,
            "title": title,
            "content": content,
            "store_vectors": store_vectors,
            "split_method": split_method,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
        }
        
        if metadata:
            data["metadata"] = metadata
        
        return self._request("POST", "/documents", data=data)
    
    def upload_document_file(
        self,
        file_path: str,
        title: Optional[str] = None,
        author: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        split_method: str = "recursive",
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        store_vectors: bool = True,
        tenant_id: str = "default",
    ) -> Dict[str, Any]:
        """
        上传文档文件
        
        Args:
            file_path: 文件路径
            title: 文档标题（可选，默认使用文件名）
            author: 作者
            metadata: 文档元数据（JSON 对象）
            split_method: 切分方法 (recursive, character, token, semantic, paragraph, sentence)
            chunk_size: 块大小
            chunk_overlap: 块重叠大小
            store_vectors: 是否存储向量
            
        Returns:
            上传结果
        """
        url = f"{self.base_url}/documents/upload"
        
        try:
            with open(file_path, 'rb') as f:
                files = {'file': f}
                data = {
                    'tenant_id': tenant_id,
                    'split_method': split_method,
                    'chunk_size': chunk_size,
                    'chunk_overlap': chunk_overlap,
                    'store_vectors': store_vectors,
                }
                
                if title:
                    data['title'] = title
                if author:
                    data['author'] = author
                if metadata is not None:
                    data['metadata'] = json.dumps(metadata, ensure_ascii=False)
                
                response = self.session.post(url, files=files, data=data)
                response.raise_for_status()
                return response.json()
                
        except requests.exceptions.RequestException as e:
            return {
                "error": f"请求失败: {str(e)}",
                "status_code": getattr(e.response, "status_code", None) if hasattr(e, "response") else None
            }
        except FileNotFoundError:
            return {
                "error": f"文件不存在: {file_path}",
            }
    
    def list_documents(
        self,
        skip: int = 0,
        limit: int = 10,
        tenant_id: str = "default",
    ) -> Dict[str, Any]:
        """
        获取文档列表
        
        Args:
            skip: 跳过数量
            limit: 返回数量
            
        Returns:
            文档列表
        """
        params = {"skip": skip, "limit": limit, "tenant_id": tenant_id}
        return self._request("GET", "/documents", params=params)
    
    def get_document(self, document_id: int, tenant_id: str = "default") -> Dict[str, Any]:
        """
        获取文档详情
        
        Args:
            document_id: 文档 ID
            
        Returns:
            文档详情
        """
        return self._request("GET", f"/documents/{document_id}", params={"tenant_id": tenant_id})
    
    def delete_document(self, document_id: int, tenant_id: str = "default") -> Dict[str, Any]:
        """
        删除文档
        
        Args:
            document_id: 文档 ID
            
        Returns:
            删除结果
        """
        return self._request("DELETE", f"/documents/{document_id}", params={"tenant_id": tenant_id})


# 创建全局 API 客户端实例
api_client = APIClient()
