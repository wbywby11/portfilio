"""附件上传与管理服务"""
import uuid
import os
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
import pandas as pd
import numpy as np
from loguru import logger

UPLOAD_DIR = Path("data/uploads")
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv"}

# 内存存储附件元数据（单worker），key=attachment_id
_attachments: Dict[str, Dict[str, Any]] = {}


class AttachmentService:

    @staticmethod
    def ensure_upload_dir():
        """确保上传目录存在"""
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _meta_path(attachment_id: str) -> Path:
        """元数据文件路径"""
        return UPLOAD_DIR / f"{attachment_id}.meta.json"

    @staticmethod
    async def save_file(file_name: str, file_content: bytes) -> Dict[str, Any]:
        """
        保存上传文件并返回元数据

        流程：
        1. 校验文件扩展名
        2. 校验文件大小
        3. 生成 attachment_id
        4. 保存文件到 data/uploads/{attachment_id}_{filename}
        5. 用pandas读取前100行生成预览
        6. 存储元数据到内存字典
        7. 返回 {attachment_id, file_name, file_size, format, preview}
        """
        # 1. 校验文件扩展名
        ext = Path(file_name).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f"不支持的文件类型: {ext}，仅支持 {', '.join(ALLOWED_EXTENSIONS)}")

        # 2. 校验文件大小
        file_size = len(file_content)
        if file_size > MAX_FILE_SIZE:
            raise OverflowError(
                f"文件大小 {file_size / 1024 / 1024:.1f}MB 超过限制 "
                f"{MAX_FILE_SIZE / 1024 / 1024:.0f}MB"
            )

        # 3. 生成 attachment_id
        attachment_id = uuid.uuid4().hex[:16]

        # 4. 确保目录存在并保存文件
        AttachmentService.ensure_upload_dir()
        saved_name = f"{attachment_id}_{file_name}"
        file_path = UPLOAD_DIR / saved_name
        file_path.write_bytes(file_content)
        logger.info("附件已保存: {} ({}KB)", saved_name, file_size // 1024)

        # 5. 用pandas读取前100行生成预览
        preview = AttachmentService._generate_preview(file_path, ext)

        # 6. 存储元数据到内存字典
        metadata = {
            "attachment_id": attachment_id,
            "file_name": file_name,
            "file_size": file_size,
            "format": ext.lstrip("."),
            "file_path": str(file_path),
            "preview": preview,
            "created_at": datetime.now().isoformat(),
        }
        _attachments[attachment_id] = metadata

        # 6.1 持久化元数据到 JSON 文件
        try:
            meta_path = AttachmentService._meta_path(attachment_id)
            meta_path.write_text(
                json.dumps(metadata, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            logger.debug("附件元数据已持久化: {}", meta_path.name)
        except Exception as e:
            logger.warning("持久化附件元数据失败: {}, {}", attachment_id, e)

        # 7. 返回结果
        return {
            "attachment_id": attachment_id,
            "file_name": file_name,
            "file_size": file_size,
            "format": ext.lstrip("."),
            "preview": preview,
        }

    @staticmethod
    def _generate_preview(file_path: Path, ext: str) -> Dict[str, Any]:
        """读取文件生成预览数据"""
        try:
            if ext in (".xlsx", ".xls"):
                df = pd.read_excel(file_path, nrows=100)
            else:
                # CSV 尝试多种编码
                for encoding in ("utf-8", "gbk", "gb2312"):
                    try:
                        df = pd.read_csv(file_path, nrows=100, encoding=encoding)
                        break
                    except UnicodeDecodeError:
                        continue
                else:
                    df = pd.read_csv(file_path, nrows=100, encoding="utf-8", errors="replace")

            columns = df.columns.tolist()
            total_rows = len(df)

            # 取前5行作为预览
            preview_df = df.head(5)

            # 处理 NaN 为 None，datetime 转为 ISO 字符串
            rows = []
            for _, row in preview_df.iterrows():
                row_dict = {}
                for col in columns:
                    val = row[col]
                    if pd.isna(val):
                        row_dict[col] = None
                    elif isinstance(val, (pd.Timestamp, datetime)):
                        row_dict[col] = val.isoformat()
                    elif isinstance(val, (np.integer,)):
                        row_dict[col] = int(val)
                    elif isinstance(val, (np.floating,)):
                        row_dict[col] = float(val)
                    else:
                        row_dict[col] = val
                rows.append(row_dict)

            # 如果需要获取全文件总行数（nrows=100只读了100行）
            # 对于预览目的，total_rows 是实际读取的行数
            return {
                "columns": columns,
                "total_rows": total_rows,
                "sample_rows": rows,
            }
        except Exception as e:
            logger.warning("生成预览失败: {}", e)
            return {
                "columns": [],
                "total_rows": 0,
                "sample_rows": [],
                "error": str(e),
            }

    @staticmethod
    def get_attachment(attachment_id: str) -> Optional[Dict[str, Any]]:
        """获取附件元数据（先查内存缓存，再查持久化文件）"""
        # 内存缓存命中
        if attachment_id in _attachments:
            return _attachments[attachment_id]

        # 文件持久化读取
        meta_path = AttachmentService._meta_path(attachment_id)
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                _attachments[attachment_id] = meta  # 回填缓存
                return meta
            except Exception as e:
                logger.warning("读取附件元数据失败: {}, {}", attachment_id, e)

        return None

    @staticmethod
    def get_file_path(attachment_id: str) -> Optional[Path]:
        """获取附件文件的实际路径"""
        meta = AttachmentService.get_attachment(attachment_id)
        if meta and "file_path" in meta:
            p = Path(meta["file_path"])
            if p.exists():
                return p
        return None

    @staticmethod
    def cleanup_expired(max_age_seconds: int = 3600):
        """清理过期附件（默认1小时），同时清理文件和元数据JSON"""
        now = datetime.now()
        expired_ids = []

        # 扫描 UPLOAD_DIR 中的所有 .meta.json 文件，确保持久化附件也能被清理
        AttachmentService.ensure_upload_dir()
        for meta_file in UPLOAD_DIR.glob("*.meta.json"):
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                aid = meta.get("attachment_id", "")
                created = datetime.fromisoformat(meta["created_at"])
                if (now - created).total_seconds() > max_age_seconds:
                    expired_ids.append(aid)
                    # 确保内存中也有记录以便后续清理
                    if aid not in _attachments:
                        _attachments[aid] = meta
            except Exception as e:
                logger.warning("读取元数据文件失败 {}: {}", meta_file.name, e)

        for aid in expired_ids:
            meta = _attachments.pop(aid, None)
            if meta:
                try:
                    # 删除附件文件
                    fp = Path(meta["file_path"])
                    if fp.exists():
                        fp.unlink()
                    # 删除元数据 JSON 文件
                    mp = AttachmentService._meta_path(aid)
                    if mp.exists():
                        mp.unlink()
                    logger.info("已清理过期附件: {}", meta["file_name"])
                except Exception as e:
                    logger.warning("清理附件失败 {}: {}", aid, e)

        if expired_ids:
            logger.info("共清理 {} 个过期附件", len(expired_ids))
