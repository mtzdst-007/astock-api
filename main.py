# main.py — 服务入口

import asyncio
import logging
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import db
import data_fetcher as fetcher
import scheduler as sched
from api import router
from config import BATCH_SIZE, FETCH_DELAY

# ─────────────────────────────────────────────
# 日志配置
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# 预热任务 —— 在线程池中执行，不阻塞事件循环
# ─────────────────────────────────────────────
def _sync_warmup():
    """
    同步预热逻辑：获取热门列表 → 过滤已缓存 → 分批拉取写入。
    全部在线程池中执行，避免阻塞 asyncio 事件循环导致
    Render 健康检查超时（No open ports detected）。
    """
    logger.info("🔥  开始预热热门股票数据...")
    try:
        hot_codes = fetcher.fetch_hot_stock_list()
    except Exception as e:
        logger.error("❌  获取热门股票列表失败: %s", e)
        return

    # 过滤掉已有数据的股票
    to_fetch = [c for c in hot_codes if not db.has_data(c)]
    logger.info("🔥  需要预热 %d 只（共 %d 只，已缓存 %d 只）",
                len(to_fetch), len(hot_codes), len(hot_codes) - len(to_fetch))

    if not to_fetch:
        logger.info("✅  所有热门股票已预热，无需重复加载")
        return

    # 分批执行（每批 BATCH_SIZE 只），批次间等待减轻 AkShare 压力
    total_written = 0
    for batch_start in range(0, len(to_fetch), BATCH_SIZE):
        batch = to_fetch[batch_start: batch_start + BATCH_SIZE]
        logger.info("📦  预热批次 %d~%d / %d",
                    batch_start + 1, batch_start + len(batch), len(to_fetch))

        for code in batch:
            try:
                records = fetcher.fetch_stock_history(code)
                if records:
                    written = db.upsert_records(records)
                    total_written += written
                    logger.info("  ✅  %s 写入 %d 条", code, written)
                else:
                    logger.warning("  ⚠️  %s 无数据", code)
            except Exception as e:
                logger.error("  ❌  %s 预热失败: %s", code, e)

            # 单只股票间短暂等待，减轻 AkShare 服务器压力
            time.sleep(FETCH_DELAY)

        # 批次间额外等待
        time.sleep(3)

    logger.info("🏁  预热完成，共写入 %d 条记录", total_written)


# ─────────────────────────────────────────────
# FastAPI Lifespan（替代 on_event，适配新版 FastAPI）
# ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── 启动阶段 ──
    logger.info("🚀  服务启动中...")

    # 1. 初始化数据库
    db.init_db()

    # 2. 启动定时任务
    sched.start_scheduler()

    # 3. 延迟 5 秒后在线程池中启动预热
    #    （等 uvicorn 先绑定端口，避免 Render 健康检查报 "No open ports"）
    loop = asyncio.get_event_loop()
    loop.call_later(5, lambda: loop.run_in_executor(None, _sync_warmup))

    logger.info("✅  服务已就绪，API 可访问")

    yield  # ← 服务运行期间

    # ── 关闭阶段 ──
    logger.info("🛑  服务关闭中...")
    sched.stop_scheduler()


# ─────────────────────────────────────────────
# FastAPI 应用实例
# ─────────────────────────────────────────────
app = FastAPI(
    title="A股多市场历史数据 API",
    description=(
        "轻量级多市场历史日线数据服务。支持 A股 / 指数 / 美股 / 全球指数 / 期货 / 港股。\n\n"
        "- **优先级预热**：启动后优先拉取用户指定的 28 个核心标的（指数/期货/ETF/虚拟货币）\n"
        "- **热门预热**：其次拉取沪深300+中证500成分股 + 用户自选\n"
        "- **按需加载**：首次请求时自动从 AkShare 拉取并缓存\n"
        "- **增量更新**：每个工作日 16:30 自动更新已缓存数据\n"
        "- **多市场**：通过 `config.CODE_TYPE_MAP` 配置资产类型映射"
    ),
    version="1.2.0",
    lifespan=lifespan,
)

# 跨域支持（方便前端直接调用）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(router)


# ─────────────────────────────────────────────
# 本地调试入口
# ─────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=10000,
        reload=False,        # 生产环境不用 reload
        log_level="info",
    )
