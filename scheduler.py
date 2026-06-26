# scheduler.py — 定时增量更新任务

import logging
import time
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import db
import data_fetcher as fetcher
from config import SCHEDULER_HOUR, SCHEDULER_MINUTE, FETCH_DELAY

logger = logging.getLogger(__name__)

# 全局调度器实例（单例）
_scheduler: BackgroundScheduler | None = None


# ─────────────────────────────────────────────
# 增量更新主逻辑
# ─────────────────────────────────────────────
def incremental_update():
    """
    遍历数据库中已有股票，逐只查询最新日期，
    只拉取该日期之后的新数据并写入数据库。
    """
    start_time = datetime.now()
    logger.info("⏰  [%s] 开始增量更新...", start_time.strftime("%Y-%m-%d %H:%M:%S"))

    codes = db.query_stock_list()
    if not codes:
        logger.info("ℹ️  数据库为空，跳过增量更新")
        return

    total_new = 0
    success_count = 0
    fail_count = 0

    for i, code in enumerate(codes):
        try:
            latest_date = db.query_latest_date(code)
            if not latest_date:
                logger.warning("⚠️  %s 无最新日期，跳过", code)
                continue

            records = fetcher.fetch_incremental(code, latest_date)
            if not records:
                logger.debug("✅  %s 无新数据（已最新）", code)
                success_count += 1
                continue

            written = db.upsert_records(records)
            total_new += written
            success_count += 1
            logger.info(
                "✅  [%d/%d] %s 新增 %d 条（截至 %s）",
                i + 1, len(codes), code, written, latest_date,
            )
        except Exception as e:
            fail_count += 1
            logger.error("❌  [%d/%d] %s 增量更新失败: %s", i + 1, len(codes), code, e)

        # 避免高频请求
        if i < len(codes) - 1:
            time.sleep(FETCH_DELAY)

    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info(
        "🏁  增量更新完成 | 总股票: %d | 成功: %d | 失败: %d | 新增记录: %d | 耗时: %.1fs",
        len(codes), success_count, fail_count, total_new, elapsed,
    )


# ─────────────────────────────────────────────
# 启动 / 停止调度器
# ─────────────────────────────────────────────
def start_scheduler():
    """
    启动 APScheduler 后台调度器。
    默认在工作日 16:30（北京时间 UTC+8）执行增量更新。
    """
    global _scheduler

    if _scheduler and _scheduler.running:
        logger.warning("⚠️  调度器已在运行，跳过重复启动")
        return

    _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")

    # 工作日（周一~周五）16:30 执行增量更新
    trigger = CronTrigger(
        day_of_week="mon-fri",
        hour=SCHEDULER_HOUR,
        minute=SCHEDULER_MINUTE,
        timezone="Asia/Shanghai",
    )
    _scheduler.add_job(
        incremental_update,
        trigger=trigger,
        id="incremental_update",
        replace_existing=True,
        misfire_grace_time=3600,  # 若错过执行，1小时内补跑
    )

    _scheduler.start()
    logger.info(
        "📅  定时任务已启动：工作日 %02d:%02d (Asia/Shanghai) 执行增量更新",
        SCHEDULER_HOUR, SCHEDULER_MINUTE,
    )


def stop_scheduler():
    """优雅停止调度器"""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("🛑  定时任务调度器已停止")
