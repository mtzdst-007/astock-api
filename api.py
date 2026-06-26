# api.py — FastAPI 路由定义

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

import db
import data_fetcher as fetcher

logger = logging.getLogger(__name__)

router = APIRouter()


# ─────────────────────────────────────────────
# GET / — 重定向到 API 文档
# ─────────────────────────────────────────────
@router.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


# ─────────────────────────────────────────────
# 响应模型
# ─────────────────────────────────────────────
class KLine(BaseModel):
    code:     str
    date:     str
    open:     Optional[float]
    high:     Optional[float]
    low:      Optional[float]
    close:    Optional[float]
    volume:   Optional[float]
    turnover: Optional[float]


class StockItem(BaseModel):
    code: str
    name: str


class StockListResponse(BaseModel):
    count:  int
    stocks: List[StockItem]


class StockInfoResponse(BaseModel):
    code:      str
    name:      str
    type:      str
    has_data:  bool
    row_count: Optional[int] = None
    latest_date: Optional[str] = None


class HealthResponse(BaseModel):
    status:      str
    total_codes: int
    total_rows:  int
    latest_date: Optional[str]


# ─────────────────────────────────────────────
# 内部：按需拉取并写入（Lazy Load）
# ─────────────────────────────────────────────
def _lazy_load(code: str) -> bool:
    """
    如果数据库中没有该股票，则从 AkShare 拉取全历史写入。
    返回 True 表示成功写入（或已存在），False 表示拉取失败。
    """
    if db.has_data(code):
        return True
    logger.info("📥  Lazy Load: %s 不在缓存，开始拉取...", code)
    records = fetcher.fetch_stock_history(code)
    if not records:
        return False
    written = db.upsert_records(records)
    logger.info("📥  Lazy Load: %s 写入 %d 条", code, written)
    return True


# ─────────────────────────────────────────────
# GET /stock/{code}
# ─────────────────────────────────────────────
@router.get(
    "/stock/{code}",
    response_model=List[KLine],
    summary="获取标的全量历史K线",
    description=(
        "返回指定标的全量历史日线数据（升序）。首次请求时自动拉取并缓存。\n\n"
        "支持多市场：A股个股 / A股指数 / 美股ETF / 全球指数 / 期货 / 港股"
    ),
)
def get_stock_history(code: str, background_tasks: BackgroundTasks):
    code = code.strip()
    ok = _lazy_load(code)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"股票 {code} 数据不存在，且无法从数据源获取（可能代码有误或网络问题）",
        )
    rows = db.query_all(code)
    if not rows:
        raise HTTPException(status_code=404, detail=f"股票 {code} 暂无数据")
    return rows


# ─────────────────────────────────────────────
# GET /stock/{code}/latest
# ─────────────────────────────────────────────
@router.get(
    "/stock/{code}/latest",
    response_model=List[KLine],
    summary="获取标的最近N条K线",
    description="返回最近 limit 条日线数据（升序），默认30条。支持多市场：A股个股 / 指数 / 美股 / 期货 / 港股等。",
)
def get_stock_latest(
    code:  str,
    limit: int = Query(default=30, ge=1, le=2000, description="返回条数，默认30"),
):
    code = code.strip()
    ok = _lazy_load(code)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"股票 {code} 数据不存在，且无法从数据源获取",
        )
    rows = db.query_latest(code, limit)
    if not rows:
        raise HTTPException(status_code=404, detail=f"股票 {code} 暂无数据")
    return rows


# ─────────────────────────────────────────────
# GET /stocks
# ─────────────────────────────────────────────
@router.get(
    "/stocks",
    response_model=StockListResponse,
    summary="获取数据库中股票列表（含名称）",
    description="返回数据库中已缓存的全部股票代码及名称。",
)
def get_stock_list():
    codes = db.query_stock_list()
    names = fetcher.get_stock_names(codes)
    items = [{"code": c, "name": names.get(c, c)} for c in codes]
    return {"count": len(items), "stocks": items}


# ─────────────────────────────────────────────
# GET /stock/{code}/info — 标的基本信息
# ─────────────────────────────────────────────
@router.get(
    "/stock/{code}/info",
    response_model=StockInfoResponse,
    summary="获取标的基本信息",
    description="返回代码、名称、资产类型、是否有缓存数据等基本信息。不触发数据拉取。",
)
def get_stock_info(code: str):
    from data_fetcher import _get_code_type
    code = code.strip()
    code_type = _get_code_type(code)
    name = fetcher.get_stock_name(code)
    has = db.has_data(code)
    row_count = None
    latest_date = None
    if has:
        rows = db.query_all(code)
        row_count = len(rows)
        latest_date = rows[-1]["date"] if rows else None
    return {
        "code":        code,
        "name":        name,
        "type":        code_type,
        "has_data":    has,
        "row_count":   row_count,
        "latest_date": latest_date,
    }


# ─────────────────────────────────────────────
# GET /health
# ─────────────────────────────────────────────
@router.get(
    "/health",
    response_model=HealthResponse,
    summary="健康检查",
    description="返回服务状态及数据库统计信息。",
)
def health_check():
    stats = db.get_stats()
    return {
        "status":      "ok",
        "total_codes": stats["total_codes"],
        "total_rows":  stats["total_rows"],
        "latest_date": stats["latest_date"],
    }


# ─────────────────────────────────────────────
# DELETE /stock/{code}/cache — 清空单只股票缓存
# ─────────────────────────────────────────────
class CacheResponse(BaseModel):
    code:    str
    deleted: int
    message: str


@router.delete(
    "/stock/{code}/cache",
    response_model=CacheResponse,
    summary="清空指定股票的缓存数据",
    description="删除该股票在数据库中的全部缓存记录。下次请求时将自动从数据源重新拉取。",
)
def clear_stock_cache(code: str):
    code = code.strip()
    deleted = db.delete_stock_data(code)
    return {
        "code":    code,
        "deleted": deleted,
        "message": f"已清空 {code} 的 {deleted} 条缓存记录，下次请求将重新拉取",
    }


# ─────────────────────────────────────────────
# DELETE /cache — 清空全部缓存
# ─────────────────────────────────────────────
class AllCacheResponse(BaseModel):
    deleted: int
    message: str


@router.delete(
    "/cache",
    response_model=AllCacheResponse,
    summary="清空全部缓存数据",
    description="删除数据库中全部股票缓存记录。下次请求时将自动从数据源重新拉取。",
)
def clear_all_cache():
    deleted = db.delete_all_data()
    return {
        "deleted": deleted,
        "message": f"已清空全部 {deleted} 条缓存记录",
    }
