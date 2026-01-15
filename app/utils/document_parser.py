"""
文档解析器
支持多种文件类型的解析
"""
from pathlib import Path
from typing import Dict, Any, Optional
from app.utils.logger import logger


class DocumentParser:
    """文档解析器基类"""
    
    @staticmethod
    def parse(file_path: str) -> Dict[str, Any]:
        """
        解析文档
        
        Args:
            file_path: 文件路径
            
        Returns:
            解析结果，包含 content, metadata 等信息
        """
        path = Path(file_path)
        file_ext = path.suffix.lower()
        
        logger.info(f"开始解析文档: {file_path} (类型: {file_ext})")
        
        try:
            if file_ext == '.pdf':
                return PDFParser.parse(file_path)
            elif file_ext in ['.doc', '.docx']:
                return DocxParser.parse(file_path)
            elif file_ext in ['.ppt', '.pptx']:
                return PptxParser.parse(file_path)
            elif file_ext in ['.xls', '.xlsx']:
                return ExcelParser.parse(file_path)
            elif file_ext == '.txt':
                return TxtParser.parse(file_path)
            elif file_ext in ['.md', '.markdown']:
                return MarkdownParser.parse(file_path)
            else:
                raise ValueError(f"不支持的文件类型: {file_ext}")
        except Exception as e:
            logger.error(f"文档解析失败: {e}")
            raise


class PDFParser:
    """PDF 解析器"""
    
    @staticmethod
    def parse(file_path: str) -> Dict[str, Any]:
        """
        解析 PDF 文件
        
        Args:
            file_path: PDF 文件路径
            
        Returns:
            解析结果
        """
        try:
            import fitz
        except ImportError:
            raise ImportError("请安装 pymupdf: pip install pymupdf")
        
        doc = fitz.open(file_path)
        content = []
        metadata = {
            "page_count": len(doc),
            "title": doc.metadata.get("title", ""),
            "author": doc.metadata.get("author", ""),
            "subject": doc.metadata.get("subject", ""),
            "keywords": doc.metadata.get("keywords", ""),
        }
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text()
            content.append({
                "page": page_num + 1,
                "text": text,
            })
        
        doc.close()
        
        full_text = "\n\n".join([page["text"] for page in content])
        
        return {
            "content": full_text,
            "pages": content,
            "metadata": metadata,
            "file_type": "pdf",
        }


class DocxParser:
    """Word 文档解析器"""
    
    @staticmethod
    def parse(file_path: str) -> Dict[str, Any]:
        """
        解析 Word 文档
        
        Args:
            file_path: Word 文档路径
            
        Returns:
            解析结果
        """
        try:
            from docx import Document
        except ImportError:
            raise ImportError("请安装 python-docx: pip install python-docx")
        
        doc = Document(file_path)
        content = []
        metadata = {}
        
        paragraphs = []
        for para in doc.paragraphs:
            if para.text.strip():
                paragraphs.append(para.text)
        
        full_text = "\n\n".join(paragraphs)
        
        if doc.core_properties.title:
            metadata["title"] = doc.core_properties.title
        if doc.core_properties.author:
            metadata["author"] = doc.core_properties.author
        if doc.core_properties.subject:
            metadata["subject"] = doc.core_properties.subject
        if doc.core_properties.keywords:
            metadata["keywords"] = doc.core_properties.keywords
        
        return {
            "content": full_text,
            "paragraphs": paragraphs,
            "metadata": metadata,
            "file_type": "docx",
        }


class PptxParser:
    """PowerPoint 文档解析器"""
    
    @staticmethod
    def parse(file_path: str) -> Dict[str, Any]:
        """
        解析 PowerPoint 文档
        
        Args:
            file_path: PowerPoint 文档路径
            
        Returns:
            解析结果
        """
        try:
            from pptx import Presentation
        except ImportError:
            raise ImportError("请安装 python-pptx: pip install python-pptx")
        
        prs = Presentation(file_path)
        content = []
        metadata = {}
        
        for slide_num, slide in enumerate(prs.slides):
            slide_text = []
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text.strip():
                    slide_text.append(shape.text)
            
            if slide_text:
                content.append({
                    "slide": slide_num + 1,
                    "text": "\n".join(slide_text),
                })
        
        full_text = "\n\n".join([slide["text"] for slide in content])
        
        if prs.core_properties.title:
            metadata["title"] = prs.core_properties.title
        if prs.core_properties.author:
            metadata["author"] = prs.core_properties.author
        
        return {
            "content": full_text,
            "slides": content,
            "metadata": metadata,
            "file_type": "pptx",
        }


class ExcelParser:
    """Excel 文档解析器"""
    
    @staticmethod
    def parse(file_path: str) -> Dict[str, Any]:
        """
        解析 Excel 文档
        
        Args:
            file_path: Excel 文档路径
            
        Returns:
            解析结果
        """
        try:
            import openpyxl
        except ImportError:
            raise ImportError("请安装 openpyxl: pip install openpyxl")
        
        wb = openpyxl.load_workbook(file_path, data_only=True)
        content = []
        metadata = {
            "sheet_count": len(wb.sheetnames),
            "sheet_names": wb.sheetnames,
        }
        
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            sheet_data = []
            
            for row in ws.iter_rows(values_only=True):
                if any(cell is not None for cell in row):
                    sheet_data.append([str(cell) if cell is not None else "" for cell in row])
            
            if sheet_data:
                content.append({
                    "sheet": sheet_name,
                    "data": sheet_data,
                })
        
        wb.close()
        
        full_text = "\n\n".join([
            f"工作表: {sheet['sheet']}\n" + "\n".join(["\t".join(row) for row in sheet["data"]])
            for sheet in content
        ])
        
        return {
            "content": full_text,
            "sheets": content,
            "metadata": metadata,
            "file_type": "excel",
        }


class TxtParser:
    """纯文本解析器"""
    
    @staticmethod
    def parse(file_path: str) -> Dict[str, Any]:
        """
        解析纯文本文件
        
        Args:
            file_path: 文本文件路径
            
        Returns:
            解析结果
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return {
            "content": content,
            "metadata": {},
            "file_type": "txt",
        }


class MarkdownParser:
    """Markdown 解析器"""
    
    @staticmethod
    def parse(file_path: str) -> Dict[str, Any]:
        """
        解析 Markdown 文件
        
        Args:
            file_path: Markdown 文件路径
            
        Returns:
            解析结果
        """
        try:
            import markdown
        except ImportError:
            raise ImportError("请安装 markdown: pip install markdown")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        html = markdown.markdown(content)
        
        return {
            "content": content,
            "html": html,
            "metadata": {},
            "file_type": "markdown",
        }
