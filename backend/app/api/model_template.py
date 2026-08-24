"""模型模板相关路由（支持动态策略创建与注册）"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, Body, UploadFile, File
from fastapi.responses import StreamingResponse
from bson import ObjectId
import os
from pathlib import Path
from typing import Optional

# GridFS Bucket 导入兼容：motor 3.x 在 motor.motor_asyncio 中提供 AsyncIOMotorGridFSBucket，
# motor 4.x 改名为 MotorGridFSBucket 并移至顶层 motor 包（motor.motor_gridfs 仅含 Agnostic 基类）
try:
    from motor.motor_asyncio import AsyncIOMotorGridFSBucket
except ImportError:
    from motor import MotorGridFSBucket as AsyncIOMotorGridFSBucket

from app.schemas.model_template import ModelTemplateCreate, ModelTemplateOut
from app.schemas.response import Response
from app.services.model_template_service import ModelTemplateService
from app.models.model_template import ModelTemplate
from app.config.database import Database

router = APIRouter()

# PDF 存储：MongoDB GridFS（bucket=template_pdfs → template_pdfs.files / template_pdfs.chunks）
# 历史文件系统目录仅作存量迁移兜底，不再作为读写路径
PDF_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "data" / "template_pdfs"


def _get_gridfs() -> AsyncIOMotorGridFSBucket:
    return AsyncIOMotorGridFSBucket(Database.get_database(), bucket_name="template_pdfs")


def _gridfs_files_collection():
    """GridFS 元数据集合（普通文档，可按 filename 查询）。"""
    return Database.get_database()["template_pdfs.files"]


async def _delete_gridfs_by_filename(filename: str) -> None:
    """删除 GridFS 中指定文件名的所有版本（重复上传时先清旧版）。

    注意：bucket.find() 返回的是 GridOut 流对象而非字典，
    因此从 files 元数据集合取 _id 再调 bucket.delete()。
    """
    fs = _get_gridfs()
    async for doc in _gridfs_files_collection().find({"filename": filename}, {"_id": 1}):
        await fs.delete(doc["_id"])


async def _find_gridfs_file(filename: str):
    """按文件名查找 GridFS 文件元数据，不存在返回 None。"""
    return await _gridfs_files_collection().find_one({"filename": filename})


async def _save_pdf_to_gridfs(filename: str, content: bytes) -> None:
    """保存 PDF 到 GridFS：同名旧版本先删除，保证单文件唯一。"""
    await _delete_gridfs_by_filename(filename)
    fs = _get_gridfs()
    await fs.upload_from_stream(filename, content, metadata={"content_type": "application/pdf"})


def validate_object_id(id_str: str) -> str:
    """验证ObjectId格式"""
    if not ObjectId.is_valid(id_str):
        raise HTTPException(
            status_code=400,
            detail=f"无效的ID格式: {id_str}, 必须是24位十六进制字符串"
        )
    return id_str


def get_template_service() -> ModelTemplateService:
    return ModelTemplateService()


@router.get("/", response_model=Response[List[ModelTemplateOut]], summary="模型模板列表")
async def list_templates(
    include_source_code: bool = Query(False, description="是否包含源代码"),
    service: ModelTemplateService = Depends(get_template_service)
):
    """
    获取所有模型模板列表
    
    **参数格式说明：**
    
    每个模板包含 `parameters` 字段，是一个参数定义数组，每个参数对象包含：
    
    **1. Select 下拉框 (param_type="select")**
    ```json
    {
        "name": "optimization_mode",
        "label": "优化模式",
        "param_type": "select",
        "default_value": "min_variance",
        "options": ["min_variance", "max_sharpe", "target_return"],
        "description": "选择优化目标",
        "required": true
    }
    ```
    - `options`: 字符串数组，每个元素是一个可选值
    - 前端应渲染为 `<select>` 或下拉框组件
    
    **2. Slider 滑块 (param_type="slider")**
    ```json
    {
        "name": "lookback_days",
        "label": "回望天数",
        "param_type": "slider",
        "default_value": 60,
        "min_value": 20,
        "max_value": 252,
        "step": 10,
        "description": "计算协方差矩阵的历史数据天数",
        "required": true
    }
    ```
    - `min_value`: 最小值
    - `max_value`: 最大值
    - `step`: 步长（可选）
    - 前端应渲染为滑块组件 `<input type="range">` 或 Slider
    
    **3. Checkbox 复选框 (param_type="boolean")**
    ```json
    {
        "name": "allow_short",
        "label": "允许做空",
        "param_type": "boolean",
        "default_value": false,
        "description": "是否允许负权重（做空）",
        "required": false
    }
    ```
    - `default_value`: true 或 false
    - 前端应渲染为 `<input type="checkbox">` 或开关组件
    
    **4. Number 数字输入框 (param_type="number")**
    ```json
    {
        "name": "max_weight",
        "label": "最大权重",
        "param_type": "number",
        "default_value": 0.3,
        "min_value": 0.0,
        "max_value": 1.0,
        "description": "单个资产最大权重限制",
        "required": true
    }
    ```
    - 可能包含 `min_value` 和 `max_value` 用于验证
    - 前端应渲染为 `<input type="number">`
    
    **5. String 文本输入框 (param_type="string")**
    ```json
    {
        "name": "description",
        "label": "描述",
        "param_type": "string",
        "default_value": "",
        "description": "策略描述信息",
        "required": false
    }
    ```
    - 前端应渲染为 `<input type="text">` 或 `<textarea>`
    
    **通用字段：**
    - `name`: 参数名称（用于提交数据）
    - `label`: 显示标签（用于界面展示）
    - `param_type`: 参数类型
    - `default_value`: 默认值
    - `description`: 参数说明
    - `required`: 是否必填
    """
    templates = await service.list_templates(is_active=True, skip=0, limit=100)
    data = []
    for t in templates:
        template_dict = t.dict()
        # 根据参数决定是否包含源代码
        if not include_source_code:
            template_dict.pop('source_code', None)
        data.append(ModelTemplateOut(**template_dict))
    return Response.success(data=data)


@router.post("/", response_model=Response[str], summary="创建模板")
async def create_template(
    template_in: ModelTemplateCreate,
    service: ModelTemplateService = Depends(get_template_service),
):
    # 如果包含源代码,验证语法
    if template_in.source_code:
        try:
            compile(template_in.source_code, '<string>', 'exec')
        except SyntaxError as e:
            raise HTTPException(
                status_code=400,
                detail=f"代码语法错误: {str(e)}"
            )
    
    template = ModelTemplate(**template_in.dict())
    template_id = await service.create_template(template)
    return Response.success(data=template_id, message="模板创建成功")


@router.post("/migrate-pdfs-to-gridfs", response_model=Response[dict], summary="一次性迁移存量PDF到GridFS")
async def migrate_pdfs_to_gridfs():
    """
    将历史文件系统目录中的 PDF 一次性迁移到 MongoDB GridFS。
    
    - 幂等：GridFS 中已存在同名文件时跳过
    - 迁移成功后删除源文件（GridFS 作为唯一存储）
    """
    migrated, skipped = [], []
    if not PDF_DIR.exists():
        return Response.success(
            data={"migrated": migrated, "skipped": skipped},
            message="存量目录不存在，无需迁移",
        )
    
    for file_path in sorted(PDF_DIR.glob("*.pdf")):
        existing = await _find_gridfs_file(file_path.name)
        if existing:
            skipped.append(file_path.name)
            file_path.unlink()
            continue
        content = file_path.read_bytes()
        await _save_pdf_to_gridfs(file_path.name, content)
        file_path.unlink()
        migrated.append(file_path.name)
    
    return Response.success(
        data={"migrated": migrated, "skipped": skipped},
        message=f"迁移完成：新增 {len(migrated)} 个，已存在跳过 {len(skipped)} 个",
    )


@router.get("/pdf/{filename}", summary="下载策略PDF文档")
async def download_template_pdf(filename: str):
    """
    下载策略模板PDF文档（GridFS 存储）
    
    - 优先从 MongoDB GridFS 读取
    - 存量兜底：尚未迁移的历史文件从目录读取
    - 文件名仅允许 `xxx.pdf` 形式，文件不存在时返回404
    """
    # 安全校验：文件名不允许包含路径分隔符等特殊字符
    if not filename or filename != os.path.basename(filename) or not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=403, detail="非法的文件名")
    
    grid_file = await _find_gridfs_file(filename)
    if grid_file:
        fs = _get_gridfs()
        stream = await fs.open_download_stream(grid_file["_id"])
        return StreamingResponse(
            stream,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )
    
    # 存量兜底：尚未迁移到 GridFS 的历史文件仍从目录读取
    legacy_path = (PDF_DIR / filename).resolve()
    if PDF_DIR.exists() and str(legacy_path).startswith(str(PDF_DIR.resolve())) and legacy_path.exists():
        return StreamingResponse(
            iter([legacy_path.read_bytes()]),
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )
    
    raise HTTPException(status_code=404, detail=f"PDF文件不存在: {filename}")


@router.get("/{code}", response_model=Response[ModelTemplateOut], summary="获取单个模板")
async def get_template(
    code: str,
    include_source_code: bool = Query(True, description="是否包含源代码"),
    service: ModelTemplateService = Depends(get_template_service)
):
    """
    根据模板代码获取单个模板详情
    
    **返回示例：**
    ```json
    {
        "code": "risk_parity",
        "name": "风险平价策略",
        "description": "各资产风险贡献相等的组合配置策略",
        "source_code": "class RiskParityStrategy...",
        "parameters": [
            {
                "name": "lookback_days",
                "label": "回望天数",
                "param_type": "slider",
                "default_value": 60,
                "min_value": 20,
                "max_value": 252,
                "step": 10,
                "required": true
            },
            {
                "name": "rebalance_freq",
                "label": "调仓频率",
                "param_type": "select",
                "default_value": "monthly",
                "options": ["daily", "weekly", "monthly"],
                "required": true
            }
        ]
    }
    ```
    
    **参数类型说明：**
    - `select`: 下拉框，必须包含 `options` 数组
    - `slider`: 滑块，必须包含 `min_value`、`max_value`，可选 `step`
    - `boolean`: 复选框/开关，`default_value` 为 true/false
    - `number`: 数字输入，可选 `min_value`、`max_value`
    - `string`: 文本输入
    """
    template = await service.get_template_by_code(code)
    if not template:
        raise HTTPException(status_code=404, detail=f"模板不存在: {code}")
    
    template_dict = template.dict()
    
    # 根据参数决定是否包含源代码
    if not include_source_code:
        template_dict.pop('source_code', None)
    
    return Response.success(data=ModelTemplateOut(**template_dict))


@router.put("/{template_id}", response_model=Response[bool], summary="更新模型模板")
async def update_template_api(
    template_id: str,
    template_in: ModelTemplateCreate,
    service: ModelTemplateService = Depends(get_template_service),
):
    validate_object_id(template_id)
    
    # 验证模板是否存在
    existing_template = await service.get_template(template_id)
    if not existing_template:
        raise HTTPException(status_code=404, detail=f"模板不存在: {template_id}")
    
    update_data = template_in.dict(exclude_unset=True)
    
    # 如果包含源代码,验证语法
    if 'source_code' in update_data and update_data['source_code']:
        try:
            compile(update_data['source_code'], '<string>', 'exec')
        except SyntaxError as e:
            raise HTTPException(
                status_code=400,
                detail=f"代码语法错误: {str(e)}"
            )
    
    success = await service.update_template(template_id, update_data)
    if not success:
        raise HTTPException(status_code=500, detail="更新失败")
    
    return Response.success(data=success, message="模板更新成功")


@router.delete("/{template_id}", response_model=Response[bool], summary="删除模型模板")
async def delete_template_api(template_id: str, service: ModelTemplateService = Depends(get_template_service)):
    validate_object_id(template_id)
    success = await service.delete_template(template_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"模板不存在: {template_id}")
    return Response.success(data=success, message="模板删除成功")


@router.post("/validate", response_model=Response[dict], summary="验证模板有效性")
async def validate_template(
    template_in: ModelTemplateCreate = Body(...),
    service: ModelTemplateService = Depends(get_template_service)
):
    """
    验证模板的有效性（包括源代码语法、参数定义等）
    
    返回验证结果：
    - valid: 是否有效
    - errors: 错误列表
    - warnings: 警告列表
    - strategy_class: 策略类名（如果成功加载）
    """
    template = ModelTemplate(**template_in.dict())
    validation = await service.validate_template(template)
    
    if validation["valid"]:
        return Response.success(data=validation, message="模板验证通过")
    else:
        return Response.fail(
            message="模板验证失败",
            data=validation
        )


@router.get("/{code}/schema", response_model=Response[dict], summary="获取模板的参数Schema")
async def get_template_schema(
    code: str,
    service: ModelTemplateService = Depends(get_template_service)
):
    """
    获取模板的参数Schema（用于前端动态生成表单）
    
    返回格式兼容 StrategyParamSchema
    
    **返回示例：**
    ```json
    {
        "strategy_type": "risk_parity",
        "display_name": "风险平价策略",
        "description": "各资产风险贡献相等",
        "params": [
            {
                "name": "lookback_days",
                "label": "回望天数",
                "type": "slider",
                "default": 60,
                "min_value": 20,
                "max_value": 252,
                "step": 10,
                "description": "计算协方差矩阵的历史数据天数",
                "required": true
            },
            {
                "name": "optimization_mode",
                "label": "优化模式",
                "type": "select",
                "default": "min_variance",
                "options": [
                    ["min_variance", "最小方差"],
                    ["max_sharpe", "最大夏普"],
                    ["target_return", "目标收益"]
                ],
                "description": "选择优化目标",
                "required": true
            },
            {
                "name": "allow_short",
                "label": "允许做空",
                "type": "checkbox",
                "default": false,
                "description": "是否允许负权重",
                "required": false
            }
        ]
    }
    ```
    
    **前端渲染指南：**
    
    1. **Select 下拉框** (`type="select"`)
       - 读取 `options` 字段
       - 如果是 `[[value, label], ...]` 格式，显示 label，提交 value
       - 如果是 `[value1, value2, ...]` 格式，value 和 label 相同
    
    2. **Slider 滑块** (`type="slider"`)
       - 使用 `min_value`、`max_value` 设置范围
       - 使用 `step` 设置步长（默认 1）
       - 使用 `default` 设置初始值
    
    3. **Checkbox 复选框** (`type="checkbox"`)
       - `default` 为 boolean 类型
       - 渲染为开关或复选框
    
    4. **Number 数字输入** (`type="number"`)
       - 可选使用 `min_value`、`max_value` 验证
    
    5. **Text 文本输入** (`type="text"`)
       - 普通文本输入框
    """
    template = await service.get_template_by_code(code)
    if not template:
        raise HTTPException(status_code=404, detail=f"模板不存在: {code}")
    
    # 转换为策略参数Schema格式
    schema = template.to_strategy_param_schema()
    return Response.success(data=schema.to_dict())


@router.post("/{template_id}/upload-pdf", summary="上传策略PDF文档")
async def upload_template_pdf(
    template_id: str,
    file: UploadFile = File(...),
    service: ModelTemplateService = Depends(get_template_service)
):
    """
    为策略模板上传PDF文档
    
    - 支持PDF文件格式
    - 文件大小限制 50MB
    - 自动关联到模板 code
    """
    validate_object_id(template_id)
    
    # 验证模板是否存在
    template = await service.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"模板不存在: {template_id}")
    
    # 验证文件类型
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="仅支持PDF文件格式")
    
    # 验证文件大小（50MB）
    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件大小不能超过50MB")
    
    # 文件名：使用模板code作为基础，存储到 MongoDB GridFS
    safe_filename = f"{template.code}.pdf"
    await _save_pdf_to_gridfs(safe_filename, content)
    
    # 更新模板记录
    update_data = {"pdf_filename": safe_filename}
    await service.update_template(template_id, update_data)
    
    return Response.success(
        data={"pdf_filename": safe_filename},
        message="PDF文档上传成功"
    )


@router.get("/{template_id}/pdf-url", summary="获取策略PDF文档URL")
async def get_template_pdf_url(
    template_id: str,
    service: ModelTemplateService = Depends(get_template_service)
):
    """
    获取策略模板PDF文档的访问URL
    
    返回格式：{"pdf_url": "/api/v1/model-templates/pdf/xxx.pdf"}
    """
    validate_object_id(template_id)
    
    template = await service.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"模板不存在: {template_id}")
    
    if not template.pdf_filename:
        return Response.success(data={"pdf_url": None}, message="该模板未上传PDF文档")
    
    # GridFS 与存量文件系统中都不存在时返回 None，避免前端拿到死链
    grid_file = await _find_gridfs_file(template.pdf_filename)
    legacy_path = PDF_DIR / template.pdf_filename
    if not grid_file and not legacy_path.exists():
        return Response.success(data={"pdf_url": None}, message="该模板未上传PDF文档")
    
    pdf_url = f"/api/v1/model-templates/pdf/{template.pdf_filename}"
    return Response.success(data={"pdf_url": pdf_url})


@router.delete("/{template_id}/pdf", summary="删除策略PDF文档")
async def delete_template_pdf(
    template_id: str,
    service: ModelTemplateService = Depends(get_template_service)
):
    """
    删除策略模板关联的PDF文档
    
    - 同时删除 GridFS 文件和清除数据库中的 pdf_filename 字段
    """
    validate_object_id(template_id)
    
    template = await service.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"模板不存在: {template_id}")
    
    # 删除 GridFS 文件与存量文件系统文件
    if template.pdf_filename:
        await _delete_gridfs_by_filename(template.pdf_filename)
        legacy_path = PDF_DIR / template.pdf_filename
        if legacy_path.exists():
            legacy_path.unlink()
    
    # 清除数据库记录
    await service.update_template(template_id, {"pdf_filename": None})
    
    return Response.success(message="PDF文档已删除")