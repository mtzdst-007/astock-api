# data_fetcher.py — AkShare 封装层（多市场支持）

import time
import logging
from typing import List, Dict, Any, Optional

import akshare as ak
import pandas as pd

from config import (
    FETCH_RETRY, FETCH_DELAY, FALLBACK_HOT_STOCKS,
    CODE_TYPE_MAP, CODE_NAME_MAP, CUSTOM_FAVORITES,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════
# 通用工具
# ═══════════════════════════════════════════════

def _retry_call(func, *args, retries=FETCH_RETRY, delay=2.0, **kwargs):
    """带重试的 AkShare 调用"""
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_err = e
            logger.warning("⚠️  第 %d 次调用失败 [%s]: %s", attempt, func.__name__, e)
            if attempt < retries:
                time.sleep(delay)
    raise RuntimeError(f"调用 {func.__name__} 失败（重试 {retries} 次）") from last_err


def _normalize_code(code: str) -> str:
    """去掉交易所前缀，保留核心代码"""
    code = code.strip().upper()
    for prefix in ("SH", "SZ", "BJ"):
        if code.startswith(prefix):
            code = code[2:]
    return code


# ═══════════════════════════════════════════════
# 代码 → 资产类型分类
# ═══════════════════════════════════════════════

def _get_code_type(code: str) -> str:
    """
    根据 CODE_TYPE_MAP 返回资产类型。
    不在映射中的纯6位数字代码默认为 "stock"（A股个股）。
    """
    upper = code.strip().upper()
    if upper in CODE_TYPE_MAP:
        return CODE_TYPE_MAP[upper]
    # 默认：纯数字6位 → A股个股；其他 → 未知
    if upper.isdigit() and len(upper) == 6:
        return "stock"
    return "unknown"


# ═══════════════════════════════════════════════
# 通用列映射 → 标准字典
# ═══════════════════════════════════════════════

# 中文字段名映射（多数据源共用）
_COL_MAP_CN = {
    "日期": "date", "开盘": "open", "最高": "high",
    "最低": "low", "收盘": "close", "成交量": "volume", "成交额": "turnover",
}
# 美股英文字段名映射
_COL_MAP_US = {
    "date": "date", "open": "open", "high": "high",
    "low": "low", "close": "close", "volume": "volume",
}

KEEP_COLS = ["code", "date", "open", "high", "low", "close", "volume", "turnover"]


def _df_to_records(df: pd.DataFrame, code: str, col_map=None) -> List[Dict[str, Any]]:
    """将 DataFrame 转为标准字典列表"""
    if col_map is None:
        col_map = _COL_MAP_CN
    df = df.rename(columns=col_map)
    # 只保留存在的标准列
    existing_cols = [c for c in KEEP_COLS if c in df.columns]
    df = df[existing_cols].copy()
    df["code"] = code
    df["date"] = df["date"].astype(str)
    # 补全缺失列
    for col in KEEP_COLS:
        if col not in df.columns:
            df[col] = None
    return df[KEEP_COLS].to_dict(orient="records")


# ═══════════════════════════════════════════════
# 1. A股个股 —— 三层回退：腾讯 → 新浪 → akshare 默认
#    ak.stock_zh_a_hist_tx（腾讯）— 稳定，缺 volume
#    ak.stock_zh_a_daily（新浪）— 列完整，易封 IP
#    ak.stock_zh_a_hist（akshare 默认）— 最后兜底
# ═══════════════════════════════════════════════

# 腾讯/新浪数据源使用 sh/sz/bj 前缀
def _daily_symbol(code: str) -> str:
    """6位代码 → 带交易所前缀的 symbol（腾讯/新浪格式）"""
    if code.startswith(("60", "68")):
        return f"sh{code}"
    elif code.startswith(("00", "30")):
        return f"sz{code}"
    elif code.startswith(("4", "8")):
        return f"bj{code}"
    return code

# 腾讯数据源列映射：amount 是成交额
_COL_MAP_TX = {
    "date": "date", "open": "open", "high": "high",
    "low": "low", "close": "close", "amount": "turnover",
}


def _fetch_a_stock(code: str, start_date="19900101", end_date="21001231") -> List[Dict]:
    code = _normalize_code(code)
    symbol = _daily_symbol(code)

    # 第1层：腾讯证券（最稳定）
    try:
        df = _retry_call(
            ak.stock_zh_a_hist_tx, symbol=symbol,
            start_date=start_date, end_date=end_date, adjust="qfq",
        )
        if df is not None and not df.empty:
            records = _df_to_records(df, code, col_map=_COL_MAP_TX)
            logger.info("✅  A股 %s 拉取 %d 条（腾讯）", code, len(records))
            return records
    except Exception as e:
        logger.warning("⚠️  stock_zh_a_hist_tx(%s) 失败: %s，尝试新浪接口", symbol, e)

    # 第2层：新浪日线（列完整但易封 IP）
    try:
        df = _retry_call(
            ak.stock_zh_a_daily, symbol=symbol,
            start_date=start_date, end_date=end_date, adjust="qfq",
        )
        if df is not None and not df.empty:
            records = _df_to_records(df, code)
            logger.info("✅  A股 %s 拉取 %d 条（新浪）", code, len(records))
            return records
    except Exception as e:
        logger.warning("⚠️  stock_zh_a_daily(%s) 失败: %s，尝试默认接口", symbol, e)

    # 第3层：akshare 默认接口
    try:
        df = _retry_call(
            ak.stock_zh_a_hist, symbol=code, period="daily",
            start_date=start_date, end_date=end_date, adjust="qfq",
        )
    except Exception as e:
        logger.warning("⚠️  stock_zh_a_hist(%s) 也失败: %s", code, e)
        return []

    if df is None or df.empty:
        logger.warning("⚠️  A股 %s 所有数据源均返回空数据", code)
        return []
    records = _df_to_records(df, code)
    logger.info("✅  A股 %s 拉取 %d 条（默认回退）", code, len(records))
    return records


# ═══════════════════════════════════════════════
# 2. A股指数 —— 东方财富优先，新浪回退
#    东方财富（ak.stock_zh_index_daily_em）支持日期参数
#    新浪（ak.stock_zh_index_daily）不支持日期参数，需拉全量后过滤
# ═══════════════════════════════════════════════

# 指数代码 → AkShare symbol 前缀规则
def _index_symbol(code: str) -> str:
    if code.startswith("0") or code.startswith("6"):
        return f"sh{code}"
    elif code.startswith("3"):
        return f"sz{code}"
    return code


def _fetch_index(code: str, start_date="19900101", end_date="21001231") -> List[Dict]:
    symbol = _index_symbol(code)

    # 首选：东方财富接口（支持日期参数）
    try:
        df = _retry_call(
            ak.stock_zh_index_daily_em, symbol=symbol,
            start_date=start_date, end_date=end_date,
        )
        if df is not None and not df.empty:
            col_map = _COL_MAP_CN
            records = _df_to_records(df, code, col_map=col_map)
            logger.info("✅  指数 %s 拉取 %d 条（东方财富）", code, len(records))
            return records
    except Exception as e:
        logger.warning("⚠️  stock_zh_index_daily_em(%s) 失败: %s，尝试新浪接口", symbol, e)

    # 回退：新浪接口（不支持日期参数，需拉全量后过滤）
    try:
        df = _retry_call(ak.stock_zh_index_daily, symbol=symbol)
    except Exception as e2:
        logger.warning("⚠️  stock_zh_index_daily(%s) 也失败: %s", symbol, e2)

    if df is None or df.empty:
        logger.warning("⚠️  指数 %s 所有数据源均返回空数据", code)
        return []

    # 新浪接口需手动过滤日期范围
    try:
        df["date"] = pd.to_datetime(df["date"])
        start_dt = pd.to_datetime(start_date, format="%Y%m%d")
        end_dt   = pd.to_datetime(end_date,   format="%Y%m%d")
        df = df[(df["date"] >= start_dt) & (df["date"] <= end_dt)]
        df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    except Exception as e2:
        logger.warning("⚠️  指数 %s 日期过滤失败（返回全量）: %s", code, e2)

    col_map = _COL_MAP_US
    records = _df_to_records(df, code, col_map=col_map)
    logger.info("✅  指数 %s 拉取 %d 条（新浪回退）", code, len(records))
    return records


# ═══════════════════════════════════════════════
# 3. 美股ETF/个股 —— ak.stock_us_hist
# ═══════════════════════════════════════════════

def _fetch_us_stock(code: str, start_date="19900101", end_date="21001231") -> List[Dict]:
    df = _retry_call(
        ak.stock_us_hist, symbol=code, period="daily",
        start_date=start_date, end_date=end_date, adjust="qfq",
    )
    if df is None or df.empty:
        logger.warning("⚠️  美股 %s 返回空数据", code)
        return []
    records = _df_to_records(df, code, col_map=_COL_MAP_US)
    logger.info("✅  美股 %s 拉取 %d 条", code, len(records))
    return records


# ═══════════════════════════════════════════════
# 4. 全球指数 —— ak.index_global_hist_em
# ═══════════════════════════════════════════════

def _fetch_global_index(code: str, start_date="19900101", end_date="21001231") -> List[Dict]:
    try:
        df = _retry_call(ak.index_global_hist_em, symbol=code)
    except Exception:
        logger.warning("⚠️  index_global_hist_em(%s) 失败，尝试 index_us_stock_sina", code)
        df = _retry_call(ak.index_us_stock_sina, symbol=f".{code}")
    if df is None or df.empty:
        logger.warning("⚠️  全球指数 %s 返回空数据", code)
        return []
    records = _df_to_records(df, code)
    logger.info("✅  全球指数 %s 拉取 %d 条", code, len(records))
    return records


# ═══════════════════════════════════════════════
# 5. 国内期货 —— 东方财富优先，新浪回退
#    ak.futures_zh_daily_em（东方财富）
#    ak.futures_zh_daily_sina / ak.futures_main_sina（新浪回退）
# ═══════════════════════════════════════════════

def _fetch_cn_futures(code: str, start_date="19900101", end_date="21001231") -> List[Dict]:
    # 首选：东方财富
    try:
        df = _retry_call(ak.futures_zh_daily_em, symbol=code)
        if df is not None and not df.empty:
            records = _df_to_records(df, code)
            logger.info("✅  期货 %s 拉取 %d 条（东方财富）", code, len(records))
            return records
    except Exception as e:
        logger.warning("⚠️  futures_zh_daily_em(%s) 失败: %s，尝试新浪接口", code, e)

    # 回退：新浪
    try:
        df = _retry_call(ak.futures_zh_daily_sina, symbol=code)
    except Exception:
        logger.warning("⚠️  futures_zh_daily_sina(%s) 失败，尝试 futures_main_sina", code)
        df = _retry_call(ak.futures_main_sina, symbol=code)
    if df is None or df.empty:
        logger.warning("⚠️  期货 %s 返回空数据", code)
        return []
    records = _df_to_records(df, code)
    logger.info("✅  期货 %s 拉取 %d 条（新浪回退）", code, len(records))
    return records


# ═══════════════════════════════════════════════
# 6. 国际期货 —— ak.futures_global_hist_em
# ═══════════════════════════════════════════════

def _fetch_global_futures(code: str, start_date="19900101", end_date="21001231") -> List[Dict]:
    try:
        df = _retry_call(ak.futures_global_hist_em, symbol=code)
    except Exception:
        logger.warning("⚠️  futures_global_hist_em(%s) 失败，尝试 futures_foreign_hist", code)
        df = _retry_call(ak.futures_foreign_hist, symbol=code)
    if df is None or df.empty:
        logger.warning("⚠️  国际期货 %s 返回空数据", code)
        return []
    records = _df_to_records(df, code)
    logger.info("✅  国际期货 %s 拉取 %d 条", code, len(records))
    return records


# ═══════════════════════════════════════════════
# 7. 港股 —— ak.stock_hk_hist
# ═══════════════════════════════════════════════

def _fetch_hk_stock(code: str, start_date="19900101", end_date="21001231") -> List[Dict]:
    df = _retry_call(
        ak.stock_hk_hist, symbol=code, period="daily",
        start_date=start_date, end_date=end_date, adjust="qfq",
    )
    if df is None or df.empty:
        logger.warning("⚠️  港股 %s 返回空数据", code)
        return []
    records = _df_to_records(df, code)
    logger.info("✅  港股 %s 拉取 %d 条", code, len(records))
    return records


# ═══════════════════════════════════════════════
# 统一入口
# ═══════════════════════════════════════════════

_DISPATCH = {
    "stock":          _fetch_a_stock,
    "index":          _fetch_index,
    "us":             _fetch_us_stock,
    "global":         _fetch_global_index,
    "cn_futures":     _fetch_cn_futures,
    "global_futures": _fetch_global_futures,
    "hk":             _fetch_hk_stock,
}


def fetch_stock_history(
    code: str,
    start_date: str = "19900101",
    end_date: str   = "21001231",
    adjust: str     = "qfq",          # 仅对 stock/us/hk 有效，其余忽略
) -> List[Dict[str, Any]]:
    """
    统一数据拉取入口，根据代码类型自动选择数据源。
    类型由 config.CODE_TYPE_MAP 决定，默认为 A股个股。
    """
    code_type = _get_code_type(code)
    logger.info("🔍  代码 %s → 类型 %s", code, code_type)

    if code_type == "unknown":
        logger.error("❌  无法识别代码 %s 的类型，跳过", code)
        return []

    fetcher = _DISPATCH.get(code_type)
    if fetcher is None:
        logger.error("❌  不支持的类型 %s", code_type)
        return []

    try:
        return fetcher(code, start_date=start_date, end_date=end_date)
    except Exception as e:
        logger.error("❌  %s [%s] 拉取失败: %s", code, code_type, e)
        return []


# ═══════════════════════════════════════════════
# 增量拉取
# ═══════════════════════════════════════════════

def fetch_incremental(code: str, since_date: str) -> List[Dict[str, Any]]:
    """拉取 since_date 之后（不含）的数据"""
    start = since_date.replace("-", "")
    try:
        dt = pd.Timestamp(since_date) + pd.Timedelta(days=1)
        start = dt.strftime("%Y%m%d")
    except Exception:
        pass
    return fetch_stock_history(code, start_date=start)


# ═══════════════════════════════════════════════
# 热门股票列表
# ═══════════════════════════════════════════════

def fetch_hot_stock_list() -> List[str]:
    """沪深300 + 中证500 + 用户自选 + 兜底 + CODE_TYPE_MAP中的非stock代码"""
    codes: List[str] = []

    # 1. 沪深300
    try:
        df = _retry_call(ak.index_stock_cons, symbol="000300")
        if df is not None and not df.empty:
            col = next(
                (c for c in df.columns if "代码" in c or "Code" in c.lower() or "code" in c.lower()),
                df.columns[0],
            )
            codes += df[col].astype(str).str.strip().tolist()
            logger.info("📋  沪深300成分股: %d 只", len(codes))
    except Exception as e:
        logger.warning("⚠️  沪深300成分股获取失败: %s", e)

    # 2. 中证500（去重）
    try:
        df = _retry_call(ak.index_stock_cons, symbol="000905")
        if df is not None and not df.empty:
            col = next(
                (c for c in df.columns if "代码" in c or "Code" in c.lower() or "code" in c.lower()),
                df.columns[0],
            )
            extra = df[col].astype(str).str.strip().tolist()
            before = len(codes)
            codes += [c for c in extra if c not in codes]
            logger.info("📋  中证500新增: %d 只", len(codes) - before)
    except Exception as e:
        logger.warning("⚠️  中证500成分股获取失败: %s", e)

    # 3. 用户自选（始终加入）
    codes += CUSTOM_FAVORITES
    logger.info("📋  用户自选: %d 只", len(CUSTOM_FAVORITES))

    # 4. 多市场标的（指数/美股/期货/港股等）
    multi_market = [k for k, v in CODE_TYPE_MAP.items() if v != "stock"]
    codes += multi_market
    logger.info("📋  多市场标的: %d 个", len(multi_market))

    # 5. 兜底
    if len(codes) < 50:
        logger.warning("⚠️  数量不足，使用固定兜底列表 (%d 只)", len(FALLBACK_HOT_STOCKS))
        existing = set(codes)
        codes += [c for c in FALLBACK_HOT_STOCKS if c not in existing]

    # 规范化 + 去重保序
    seen = set()
    unique = []
    for c in codes:
        c = _normalize_code(c)
        if c and c not in seen:
            seen.add(c)
            unique.append(c)

    logger.info("🔥  最终热门列表: %d 个标的（含%d种资产类型）",
                len(unique),
                len(set(_get_code_type(c) for c in unique)))
    return unique


# ═══════════════════════════════════════════════
# 批量预热
# ═══════════════════════════════════════════════

def fetch_batch(
    codes: List[str],
    delay: float = FETCH_DELAY,
    on_success=None,
    on_fail=None,
) -> Dict[str, List[Dict]]:
    """批量拉取 codes 的全历史数据"""
    result = {}
    for i, code in enumerate(codes):
        logger.info("🔄  [%d/%d] 拉取 %s ...", i + 1, len(codes), code)
        try:
            records = fetch_stock_history(code)
            result[code] = records
            if on_success and records:
                on_success(code, records)
        except Exception as e:
            result[code] = []
            if on_fail:
                on_fail(code, e)
        if i < len(codes) - 1:
            time.sleep(delay)
    return result


# ═══════════════════════════════════════════════
# 标的名称查询
# ═══════════════════════════════════════════════

# A股名称缓存（内存级，避免重复调用 AkShare）
_a_stock_name_cache: Optional[Dict[str, str]] = None


def _load_a_stock_names() -> Dict[str, str]:
    """从 AkShare 加载全部 A 股代码→名称映射（带缓存）"""
    global _a_stock_name_cache
    if _a_stock_name_cache is not None:
        return _a_stock_name_cache
    try:
        df = _retry_call(ak.stock_info_a_code_name)
        if df is not None and not df.empty:
            # 列名可能是 code/name 或 代码/名称
            code_col = next((c for c in df.columns if c in ("code", "代码")), df.columns[0])
            name_col = next((c for c in df.columns if c in ("name", "名称")), df.columns[1])
            _a_stock_name_cache = dict(zip(df[code_col].astype(str).str.strip(), df[name_col].astype(str).str.strip()))
            logger.info("📋  加载 %d 条 A 股名称", len(_a_stock_name_cache))
        else:
            _a_stock_name_cache = {}
    except Exception as e:
        logger.warning("⚠️  A股名称加载失败: %s", e)
        _a_stock_name_cache = {}
    return _a_stock_name_cache


def get_stock_name(code: str) -> str:
    """
    获取标的名称。
    优先查 CODE_NAME_MAP（已知标的），其次查 AkShare A股名称库，都找不到返回代码本身。
    """
    # 1. 手动映射
    if code in CODE_NAME_MAP:
        return CODE_NAME_MAP[code]
    # 2. A股（6位数字）→ AkShare 名称库
    if code.isdigit() and len(code) == 6:
        names = _load_a_stock_names()
        if code in names:
            return names[code]
    # 3. 兜底
    return code


def get_stock_names(codes: List[str]) -> Dict[str, str]:
    """批量获取标的名称"""
    return {c: get_stock_name(c) for c in codes}
