"""全局异常处理器"""
from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from loguru import logger
from starlette.exceptions import HTTPException as StarletteHTTPException


def _validation_errors_for_response(errors: list) -> list:
    """Pydantic/FastAPI 校验错误的 ctx 中可能含 BaseException，不能直接 json.dumps。"""
    out = []
    for err in errors:
        if not isinstance(err, dict):
            out.append(err)
            continue
        item = dict(err)
        ctx = item.get("ctx")
        if isinstance(ctx, dict):
            item["ctx"] = {
                str(k): (str(v) if isinstance(v, BaseException) else v)
                for k, v in ctx.items()
            }
        out.append(item)
    return out


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """处理HTTP异常"""
    # 4xx 必须落日志：否则前端只显示 axios 通用文案时，后端没有任何痕迹可查
    logger.warning(
        "[HTTP {}] {} {} -> {}",
        exc.status_code, request.method, request.url.path, exc.detail,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.status_code,
            "message": exc.detail,
            "data": None
        }
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """处理请求验证异常（errors 中 ctx 可能含 Exception，须 JSON 安全编码）"""
    logger.warning(
        "[HTTP 422] {} {} -> {}",
        request.method, request.url.path, exc.errors(),
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "code": 422,
            "message": "请求参数验证失败",
            "data": _validation_errors_for_response(exc.errors()),
        },
    )


async def general_exception_handler(request: Request, exc: Exception):
    """处理未捕获的异常"""
    logger.exception(
        "[HTTP 500] {} {} -> {}", request.method, request.url.path, exc,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "code": 500,
            "message": f"服务器内部错误: {str(exc)}",
            "data": None
        }
    )
