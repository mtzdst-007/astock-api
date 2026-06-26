# data_fetcher.py — AkShare 封装层

import time
import logging
from typing import List, Dict, Any, Optional

import akshare as ak
import pandas as pd

from config import FETCH_RETRY, FETCH_DELAY, FALLBACK_HOT_STOCKS

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# 内部工具：带重试的 AkShare 调用
# ─────────────────────────────────────────────
def _retry_call(func, *args, retries=FETCH_RETRY, delay=2.0, **kwargs):
    """
    对 func(*args, **kwargs) 做最多 retries 次重试。
    每次失败后等待 delay 秒，最终失败则抛出异常。
    """
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


# ─────────────────────────────────────────────
# 规范化股票代码（去掉交易所前缀，只保留6位数字）
# ─────────────────────────────────────────────
def _normalize_code(code: str) -> str:
    code = code.strip().upper()
    # 去掉 SH/SZ/BJ 前缀
    for prefix in ("SH", "SZ", "BJ"):
        if code.startswith(prefix):
            code = code[2:]
    return code


# ─────────────────────────────────────────────
# AkShare 列名映射
# ─────────────────────────────────────────────
# ak.stock_zh_a_hist 返回的列名（adjust="qfq"）
_COL_MAP = {
    "日期":   "date",
    "开盘":   "open",
    "最高":   "high",
    "最低":   "low",
    "收盘":   "close",
    "成交量": "volume",
    "成交额": "turnover",
}


def _df_to_records(df: pd.DataFrame, code: str) -> List[Dict[str, Any]]:
    """将 AkShare 返回的 DataFrame 转为标准字典列表"""
    df = df.rename(columns=_COL_MAP)
    # 只保留需要的列（有些版本列名不同，做容错）
    keep = ["date", "open", "high", "low", "close", "volume", "turnover"]
    existing = [c for c in keep if c in df.columns]
    df = df[existing].copy()
    df["code"] = code
    df["date"] = df["date"].astype(str)
    # 补全缺失列
    for col in keep:
        if col not in df.columns:
            df[col] = None
    records = df[["code"] + keep].to_dict(orient="records")
    return records


# ─────────────────────────────────────────────
# 核心：拉取某只股票的历史日线
# ─────────────────────────────────────────────
def fetch_stock_history(
    code: str,
    start_date: str = "19900101",
    end_date: str   = "21001231",
    adjust: str     = "qfq",          # 前复权
) -> List[Dict[str, Any]]:
    """
    拉取某只股票从 start_date 到 end_date 的日线数据。
    返回标准化字典列表，失败返回空列表。
    """
    code = _normalize_code(code)
    try:
        df = _retry_call(
            ak.stock_zh_a_hist,
            symbol=code,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust=adjust,
        )
        if df is None or df.empty:
            logger.warning("⚠️  股票 %s 返回空数据", code)
            return []
        records = _df_to_records(df, code)
        logger.info("✅  %s 拉取 %d 条", code, len(records))
        return records
    except Exception as e:
        logger.error("❌  股票 %s 拉取失败: %s", code, e)
        return []


# ─────────────────────────────────────────────
# 增量拉取（只取最新日期之后的数据）
# ─────────────────────────────────────────────
def fetch_incremental(code: str, since_date: str) -> List[Dict[str, Any]]:
    """
    拉取 since_date 之后（不含）的数据。
    since_date 格式：YYYY-MM-DD
    """
    # AkShare 的 start_date 格式：YYYYMMDD
    start = since_date.replace("-", "")
    # 加 1 天，避免重复拉取已有日期
    try:
        dt = pd.Timestamp(since_date) + pd.Timedelta(days=1)
        start = dt.strftime("%Y%m%d")
    except Exception:
        pass
    return fetch_stock_history(code, start_date=start)


# ─────────────────────────────────────────────
# 获取热门股票列表（指数成分 + 兜底）
# ─────────────────────────────────────────────
def fetch_hot_stock_list() -> List[str]:
    """
    优先从 AkShare 获取沪深300 / 中证500 成分股；
    两者都失败则使用 config.py 中的固定兜底列表。
    """
    codes: List[str] = []

    # 1. 沪深300
    try:
        df = _retry_call(ak.index_stock_cons, symbol="000300")
        if df is not None and not df.empty:
            # 列名可能是 "品种代码" 或 "成分券代码Scode"
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

    # 3. 兜底
    if len(codes) < 50:
        logger.warning("⚠️  指数成分股不足，使用固定兜底列表 (%d 只)", len(FALLBACK_HOT_STOCKS))
        # 合并（去重）
        existing = set(codes)
        codes += [c for c in FALLBACK_HOT_STOCKS if c not in existing]

    # 规范化
    codes = [_normalize_code(c) for c in codes]
    # 去重保序
    seen = set()
    unique = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            unique.append(c)

    logger.info("🔥  最终热门股票列表: %d 只", len(unique))
    return unique


# ─────────────────────────────────────────────
# 批量预热（供启动时调用）
# ─────────────────────────────────────────────
def fetch_batch(
    codes: List[str],
    delay: float = FETCH_DELAY,
    on_success=None,
    on_fail=None,
) -> Dict[str, List[Dict]]:
    """
    批量拉取 codes 的全历史数据。
    - delay：每只股票之间的间隔（秒）
    - on_success(code, records)：成功回调
    - on_fail(code, err)：失败回调
    返回 {code: records} 字典。
    """
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
        # 限速
        if i < len(codes) - 1:
            time.sleep(delay)
    return result
