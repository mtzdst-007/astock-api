# db.py — SQLite 数据库操作层

import sqlite3
import logging
from contextlib import contextmanager
from typing import List, Dict, Any, Optional

from config import DB_PATH

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# 连接工厂（线程安全，每次用完即关）
# ─────────────────────────────────────────────
@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # 开启 WAL 模式，读写并发性更好
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ─────────────────────────────────────────────
# 建表 & 索引
# ─────────────────────────────────────────────
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS stock_data (
    code     TEXT    NOT NULL,
    date     TEXT    NOT NULL,
    open     REAL,
    high     REAL,
    low      REAL,
    close    REAL,
    volume   REAL,
    turnover REAL,
    PRIMARY KEY (code, date)
);
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_stock_date ON stock_data (code, date DESC);
"""


def init_db():
    """初始化数据库（建表 + 索引）"""
    with get_conn() as conn:
        conn.execute(CREATE_TABLE_SQL)
        conn.execute(CREATE_INDEX_SQL)
    logger.info("✅ 数据库初始化完成：%s", DB_PATH)


# ─────────────────────────────────────────────
# 写入（批量，去重）
# ─────────────────────────────────────────────
INSERT_SQL = """
INSERT OR REPLACE INTO stock_data
    (code, date, open, high, low, close, volume, turnover)
VALUES
    (:code, :date, :open, :high, :low, :close, :volume, :turnover)
"""


def upsert_records(records: List[Dict[str, Any]]) -> int:
    """
    批量写入记录。如 (code, date) 已存在则覆盖（INSERT OR REPLACE）。
    确保后续数据源（如东方财富）可覆盖之前的数据（如新浪回退）。
    返回实际写入行数。
    """
    if not records:
        return 0
    with get_conn() as conn:
        cur = conn.executemany(INSERT_SQL, records)
        return cur.rowcount


# ─────────────────────────────────────────────
# 查询：全量
# ─────────────────────────────────────────────
def query_all(code: str) -> List[Dict]:
    sql = """
        SELECT code, date, open, high, low, close, volume, turnover
        FROM   stock_data
        WHERE  code = ?
        ORDER  BY date ASC
    """
    with get_conn() as conn:
        rows = conn.execute(sql, (code,)).fetchall()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────
# 查询：最近 N 条
# ─────────────────────────────────────────────
def query_latest(code: str, limit: int = 30) -> List[Dict]:
    sql = """
        SELECT code, date, open, high, low, close, volume, turnover
        FROM   stock_data
        WHERE  code = ?
        ORDER  BY date DESC
        LIMIT  ?
    """
    with get_conn() as conn:
        rows = conn.execute(sql, (code, limit)).fetchall()
    # 返回升序
    return [dict(r) for r in reversed(rows)]


# ─────────────────────────────────────────────
# 查询：该股票最新日期（用于增量更新）
# ─────────────────────────────────────────────
def query_latest_date(code: str) -> Optional[str]:
    sql = "SELECT MAX(date) as md FROM stock_data WHERE code = ?"
    with get_conn() as conn:
        row = conn.execute(sql, (code,)).fetchone()
    return row["md"] if row else None


# ─────────────────────────────────────────────
# 查询：数据库中已有股票列表
# ─────────────────────────────────────────────
def query_stock_list() -> List[str]:
    sql = "SELECT DISTINCT code FROM stock_data ORDER BY code"
    with get_conn() as conn:
        rows = conn.execute(sql).fetchall()
    return [r["code"] for r in rows]


# ─────────────────────────────────────────────
# 查询：某股票是否有数据
# ─────────────────────────────────────────────
def has_data(code: str) -> bool:
    sql = "SELECT 1 FROM stock_data WHERE code = ? LIMIT 1"
    with get_conn() as conn:
        row = conn.execute(sql, (code,)).fetchone()
    return row is not None


# ─────────────────────────────────────────────
# 统计信息（健康检查用）
# ─────────────────────────────────────────────
def get_stats() -> Dict[str, Any]:
    with get_conn() as conn:
        total_rows  = conn.execute("SELECT COUNT(*) FROM stock_data").fetchone()[0]
        total_codes = conn.execute("SELECT COUNT(DISTINCT code) FROM stock_data").fetchone()[0]
        latest_date = conn.execute("SELECT MAX(date) FROM stock_data").fetchone()[0]
    return {
        "total_rows":  total_rows,
        "total_codes": total_codes,
        "latest_date": latest_date,
    }
