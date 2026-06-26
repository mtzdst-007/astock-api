# A股历史数据 API 服务

> 轻量级多市场历史日线数据服务：A股/指数/美股/期货/港股，热门股票预热 + 按需加载 + SQLite 缓存 + 增量更新

---

## 项目结构

```
2.0/
├── main.py                # FastAPI 入口，负责初始化、预热、启动
├── api.py                 # API 路由定义（5个端点）
├── db.py                  # SQLite 数据库操作层
├── data_fetcher.py        # AkShare 封装（多市场分发、重试、批量）
├── scheduler.py           # APScheduler 定时增量更新
├── config.py              # 全局配置 + 兜底列表 + 多市场代码映射
├── requirements.txt       # Python 依赖
├── stock.db               # 运行后自动生成的 SQLite 数据库
├── API_DOCUMENTATION.md   # 完整 API 接口文档（含调用示例）
└── API_DOCUMENTATION.txt  # 同上，纯文本格式
```

---

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/stock/{code}` | GET | 获取标的全量历史K线（升序），支持多市场 |
| `/stock/{code}/latest?limit=30` | GET | 获取最近 N 条K线，默认30条，上限2000 |
| `/stock/{code}/cache` | DELETE | 清空指定股票缓存，下次请求重新拉取 |
| `/cache` | DELETE | 清空全部缓存数据 |
| `/stocks` | GET | 查看数据库中已缓存的标的列表 |
| `/health` | GET | 健康检查 + 数据库统计 |
| `/docs` | GET | Swagger 自动文档（FastAPI 自带） |

> 📖 完整 API 文档（含各语言调用示例）：见 `API_DOCUMENTATION.md`

---

## 支持的市场

| 市场 | 代码格式 | 示例 |
|------|----------|------|
| A股个股 | 6位数字 | `600519`（茅台）、`000001`（平安银行） |
| A股指数 | 6位数字 | `000001`（上证指数）、`399006`（创业板指） |
| 美股ETF | 字母代码 | `QQQ`、`TQQQ`、`SOXL` |
| 全球指数 | 字母代码 | `DJIA`（道琼斯）、`NDX`（纳指） |
| 国内期货 | 字母代码 | `lcfi`（碳酸锂加权）、`cufi`（沪铜） |
| 国际期货 | 字母代码 | `GC26N`（COMEX黄金） |
| 港股 | 5位数字字符串 | `03460` |

数据源为 AkShare，通过 `config.CODE_TYPE_MAP` 配置代码类型，未配置的6位数字默认按 A股个股处理。

---

## 数据更新

- **首次请求**：自动从 AkShare 拉取全历史并缓存（Lazy Load）
- **增量更新**：每工作日 16:30（北京时间）自动追加最新数据
- **全量刷新**：重新启动服务触发预热（仅热门标的）

---

## 数据库建表 SQL

```sql
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

CREATE INDEX IF NOT EXISTS idx_stock_date ON stock_data (code, date DESC);
```

---

## 本地运行

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动服务
uvicorn main:app --host 0.0.0.0 --port 10000

# 3. 访问 API 文档
http://localhost:10000/docs
```

---

## Render 部署说明

### 1. 新建 Web Service

登录 [render.com](https://render.com) → **New** → **Web Service** → 选择你的 GitHub 仓库

### 2. 配置部署参数

| 字段 | 值 |
|------|-----|
| **Runtime** | Python 3 |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `uvicorn main:app --host 0.0.0.0 --port 10000` |

### 3. 环境变量

| 变量名 | 说明 | 推荐值 |
|--------|------|--------|
| `DATA_DIR` | SQLite 文件存放目录 | `/data`（见下方持久化说明） |

### 4. SQLite 持久化（重要）

Render 免费实例重启后 **文件系统会重置**，SQLite 数据会丢失。解决方案：

**方案A（推荐）：Render Disk（付费 $0.25/GB/月）**
- Dashboard → 你的 Service → **Disks** → **Add Disk**
- Mount Path 填 `/data`，设置环境变量 `DATA_DIR=/data`
- 重启后数据仍然保留

**方案B（免费替代）：PostgreSQL 替换 SQLite**
- 在 Render 创建免费 PostgreSQL 实例
- 将 `db.py` 中的 `sqlite3` 改为 `psycopg2`
- 将 `DB_PATH` 替换为 `DATABASE_URL` 环境变量

**方案C（临时）：接受数据丢失**
- 免费实例每次重启都会重新触发预热
- 适合演示/测试，不适合生产

---

## 核心流程说明

### 热门股票初始化逻辑

```
服务启动
  └── 1. init_db()            — 建表 + 索引
  └── 2. start_scheduler()    — 启动定时任务（不阻塞）
  └── 3. warmup_task()        — 异步后台执行，不阻塞 API 就绪
        └── fetch_hot_stock_list()
              ├── 尝试获取沪深300成分股（AkShare index_stock_cons 000300）
              ├── 尝试获取中证500成分股（AkShare index_stock_cons 000905）
              └── 两者都失败 → 使用 config.py 中100只固定列表
        └── 过滤已有数据的股票（避免重复拉取）
        └── 分批（每批20只）拉取全历史日线数据
        └── 批量写入 SQLite（INSERT OR REPLACE，新数据覆盖旧数据）
```

### 按需加载（Lazy Load）

```
GET /stock/000001
  └── db.has_data("000001") → True  → 直接查 SQLite 返回
  └── db.has_data("000001") → False → 调 AkShare 拉全历史
                                    → 写入 SQLite
                                    → 返回数据
```

### 增量更新

```
每工作日 16:30（Asia/Shanghai）
  └── 遍历 db.query_stock_list()
  └── 对每只股票:
        query_latest_date(code) → "2024-06-25"
        fetch_incremental(code, "2024-06-25")
          → AkShare 拉取 2024-06-26 至今的数据
        upsert_records(records)  → INSERT OR REPLACE 写入（覆盖同日旧数据）
```

---

## 容错机制

- **AkShare 重试**：每次调用失败自动重试 3 次，间隔 2 秒
- **数据源回退**：东方财富优先，失败自动切新浪/其他源；东方财富偶尔成功时覆盖同日旧数据
- **单只失败不影响批处理**：捕获异常后记录日志并继续下一只
- **数据缺失跳过**：返回空列表时跳过写入，不报错
- **API Lazy Load 失败**：返回 404，不抛服务器错误

---

## 性能说明

- 所有查询优先命中 SQLite，**不实时请求 AkShare**
- `INSERT OR REPLACE` + `executemany` 批量写入，新数据自动覆盖同日旧数据
- WAL 模式 + 复合索引 `(code, date DESC)` 加速范围查询
- 预热在后台异步执行，**不阻塞服务启动**，启动后即可响应 API

---

## 更新日志

### v1.1.1 (2026-06-26)

- **数据源优先级全面调整为东方财富优先**：
  - `_fetch_index`（A股指数）：东方财富 `stock_zh_index_daily_em` → 新浪 `stock_zh_index_daily` 回退
  - `_fetch_a_stock`（A股个股）：新增东方财富 `stock_zh_a_hist_em` 为首选，原接口回退
  - `_fetch_cn_futures`（国内期货）：新增东方财富 `futures_zh_daily_em` 为首选，新浪双接口回退
  - 全球指数、国际期货已是东方财富优先，无需改动
- **DB 写入策略改为覆盖**：`INSERT OR IGNORE` → `INSERT OR REPLACE`，确保东方财富偶尔拉到的数据能覆盖之前新浪写入的同日记录
- **新增清空缓存接口**：`DELETE /stock/{code}/cache` 清空单只股票缓存，`DELETE /cache` 清空全部缓存，下次请求自动重新拉取
- 修复 `api.py` 中 `BackgroundTasks` 未导入的问题

### v1.1.0 (2026-06-26)

- 新增完整 API 文档 `API_DOCUMENTATION.md`（含 cURL/JS/Python/Swift/Kotlin/Flutter 调用示例）
- 修复指数接口 404 问题：`_fetch_index` 优先使用新浪数据源（`stock_zh_index_daily`），东方财富接口（`stock_zh_index_daily_em`）作为回退
- 指数 fallback 后正确做日期过滤，避免返回全量数据
- 指数接口正确处理英文字段名映射

### v1.0.0 (2026-06-XX)

- 初始版本，支持 A股/指数/美股/期货/港股多市场数据
- Lazy Load 按需加载 + 定时增量更新
- Swagger 在线文档（`/docs`）
- Render.com 部署支持
