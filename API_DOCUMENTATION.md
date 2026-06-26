# AStock API 完整接口文档

> 接口地址 Base URL：`https://astock-api-7ovj.onrender.com`  
> 协议：HTTP/HTTPS，无认证，返回格式：JSON  
> 生成时间：2026-06-26

---

## 目录

1. [快速开始](#快速开始)
2. [接口总览](#接口总览)
3. [接口详细说明](#接口详细说明)
4. [数据格式说明](#数据格式说明)
5. [支持的市场与代码格式](#支持的市场与代码格式)
6. [错误码说明](#错误码说明)
7. [客户端调用示例](#客户端调用示例)
8. [注意事项](#注意事项)

---

## 快速开始

```bash
# 健康检查
curl https://astock-api-7ovj.onrender.com/health

# 查看已缓存的股票列表
curl https://astock-api-7ovj.onrender.com/stocks

# 查询贵州茅台全量历史数据
curl https://astock-api-7ovj.onrender.com/stock/600519

# 查询上证指数最近30条
curl https://astock-api-7ovj.onrender.com/stock/000001/latest?limit=30
```

在线文档（Swagger UI）：`https://astock-api-7ovj.onrender.com/docs`

---

## 接口总览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 重定向到 Swagger 在线文档 |
| GET | `/docs` | Swagger UI 在线接口文档 |
| GET | `/health` | 健康检查 + 数据库统计 |
| GET | `/stocks` | 获取已缓存的股票代码列表 |
| GET | `/stock/{code}` | 获取指定标的全量历史K线 |
| GET | `/stock/{code}/latest` | 获取指定标的最近N条K线 |

---

## 接口详细说明

### 1. GET `/`

**说明**：访问根路径，自动重定向到 Swagger 在线文档页面。

**响应**：HTTP 307 Redirect → `/docs`

---

### 2. GET `/health`

**说明**：健康检查，返回服务运行状态及数据库统计信息。

**请求参数**：无

**响应字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | string | 服务状态，正常时为 `"ok"` |
| `total_codes` | int | 数据库中已缓存的标的个数 |
| `total_rows` | int | 数据库中日K线总条数 |
| `latest_date` | string/null | 数据库中最新的数据日期（`YYYY-MM-DD`） |

**请求示例**：

```bash
curl https://astock-api-7ovj.onrender.com/health
```

**响应示例**：

```json
{
  "status": "ok",
  "total_codes": 156,
  "total_rows": 482391,
  "latest_date": "2026-06-25"
}
```

---

### 3. GET `/stocks`

**说明**：返回数据库中已缓存的全部标的代码列表。  
**注意**：此接口只返回**已经请求过并被缓存**的标的，不是全市场目录。

**请求参数**：无

**响应字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `count` | int | 已缓存标的个数 |
| `stocks` | string[] | 标的代码列表（字符串数组） |

**请求示例**：

```bash
curl https://astock-api-7ovj.onrender.com/stocks
```

**响应示例**：

```json
{
  "count": 3,
  "stocks": ["600519", "000001", "00700"]
}
```

---

### 4. GET `/stock/{code}`

**说明**：获取指定标的的**全量历史**日K线数据。  
**懒加载机制**：如果数据库中不存在该标的，系统会自动从 AkShare 数据源拉取全历史数据并缓存，首次请求耗时较长。

**路径参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `code` | string | 是 | 标的代码（见下方代码格式说明） |

**响应字段**（数组，每条代表一根日K线）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | string | 标的代码 |
| `date` | string | 日期（`YYYY-MM-DD`） |
| `open` | float/null | 开盘价 |
| `high` | float/null | 最高价 |
| `low` | float/null | 最低价 |
| `close` | float/null | 收盘价 |
| `volume` | float/null | 成交量（手） |
| `turnover` | float/null | 成交额（元） |

**请求示例**：

```bash
# 查询贵州茅台全量数据
curl https://astock-api-7ovj.onrender.com/stock/600519

# 查询上证指数全量数据
curl https://astock-api-7ovj.onrender.com/stock/000001

# 查询美股纳斯达克100 ETF
curl https://astock-api-7ovj.onrender.com/stock/QQQ
```

**响应示例**：

```json
[
  {
    "code": "600519",
    "date": "2010-01-04",
    "open": 1680.0,
    "high": 1695.0,
    "low": 1670.5,
    "close": 1688.8,
    "volume": 3214567.0,
    "turnover": 5432100000.0
  },
  {
    "code": "600519",
    "date": "2010-01-05",
    "open": 1688.8,
    "high": 1700.0,
    "low": 1685.0,
    "close": 1695.5,
    "volume": 2987654.0,
    "turnover": 5109876000.0
  }
]
```

**注意**：
- 数据按日期**升序**排列（从最早到最新）
- 全量数据可能非常大（个股通常有数千条），请注意客户端内存消耗
- 首次请求某标的会触发网络抓取，耗时 5~30 秒不等

---

### 5. GET `/stock/{code}/latest`

**说明**：获取指定标的**最近N条**日K线数据，适合移动端或只需近期数据的场景。

**路径参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `code` | string | 是 | 标的代码 |

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `limit` | int | 否 | 30 | 返回条数，范围 1~2000 |

**请求示例**：

```bash
# 默认返回最近30条
curl https://astock-api-7ovj.onrender.com/stock/600519/latest

# 返回最近7条
curl https://astock-api-7ovj.onrender.com/stock/600519/latest?limit=7

# 返回最近2000条（最大值）
curl https://astock-api-7ovj.onrender.com/stock/600519/latest?limit=2000

# 上证指数最近60条
curl https://astock-api-7ovj.onrender.com/stock/000001/latest?limit=60
```

**响应格式**：与 `/stock/{code}` 相同（K线数组，升序）

---

## 数据格式说明

### K线对象（单条日线数据）

```json
{
  "code":     "600519",       // 标的代码
  "date":     "2026-06-25",   // 日期
  "open":     1680.00,        // 开盘价（元）
  "high":     1695.00,        // 最高价（元）
  "low":      1670.50,        // 最低价（元）
  "close":    1688.80,        // 收盘价（元）
  "volume":   3214567.00,     // 成交量（手）
  "turnover": 5432100000.00   // 成交额（元）
}
```

**字段说明**：
- `open`/`high`/`low`/`close`：A股价格为**人民币元**，美股/港股视具体标的而定
- `volume`：A股单位为**手**（1手=100股），期货单位为**手**
- `turnover`：成交额，单位**元（CNY）** 或对应币种
- 停牌日：某些字段可能为 `null`
- 数据来源：AkShare（`ak.stock_zh_a_hist()` 等接口）

---

## 支持的市场与代码格式

### A股个股

| 市场 | 代码格式 | 示例 | 说明 |
|------|----------|------|------|
| 上海主板 | 6位数字，60开头 | `600519` | 贵州茅台 |
| 上海主板 | 6位数字，60开头 | `601318` | 中国平安 |
| 深圳主板 | 6位数字，00开头 | `000001` | 平安银行 |
| 深圳中小板 | 6位数字，002开头 | `002594` | 比亚迪 |
| 创业板 | 6位数字，300开头 | `300750` | 宁德时代 |
| 科创板 | 6位数字，688开头 | `688981` | 中芯国际 |

### A股指数

| 代码 | 说明 |
|------|------|
| `000001` | 上证指数 |
| `399006` | 创业板指 |
| `000688` | 科创50 |
| `000300` | 沪深300（需确认AkShare支持） |

### 美股

| 代码 | 说明 |
|------|------|
| `QQQ` | 纳斯达克100 ETF |
| `TQQQ` | 三倍做多纳斯达克100 ETF |
| `SOXL` | 三倍做多半导体 ETF |
| `BTC` | 比特币信托 ETF |
| `ETH` | 以太坊 ETF |

### 全球指数

| 代码 | 说明 |
|------|------|
| `DJIA` | 道琼斯工业平均指数 |
| `NDX` | 纳斯达克综合指数 |
| `N225` | 日经225指数 |
| `KS11` | 韩国KOSPI指数 |

### 期货

| 代码 | 说明 |
|------|------|
| `lcfi` | 碳酸锂加权指数 |
| `cufi` | 沪铜加权指数 |
| `nifi` | 沪镍加权指数 |
| `GC26N` | COMEX黄金2607合约 |
| `SI26Q` | COMEX白银2608合约 |

### 港股

| 代码 | 说明 |
|------|------|
| `03460` | 华夏SOL（代码格式为5位数字字符串） |

---

## 错误码说明

| HTTP状态码 | 说明 | 触发场景 |
|-----------|------|---------|
| 200 | 成功 | 正常返回数据 |
| 307 | 重定向 | 访问 `/` 时跳转到 `/docs` |
| 404 | 标的不存在 | 股票代码有误，或AkShare无法获取该标的数据 |
| 500 | 服务器内部错误 | 数据库异常、网络异常等 |

**404 响应示例**：

```json
{
  "detail": "股票 999999 数据不存在，且无法从数据源获取（可能代码有误或网络问题）"
}
```

---

## 客户端调用示例

### cURL

```bash
# 健康检查
curl https://astock-api-7ovj.onrender.com/health

# 获取已缓存列表
curl https://astock-api-7ovj.onrender.com/stocks

# 获取全量数据
curl https://astock-api-7ovj.onrender.com/stock/600519

# 获取最近30条
curl https://astock-api-7ovj.onrender.com/stock/600519/latest?limit=30
```

### JavaScript / TypeScript（浏览器 & Node.js）

```javascript
const BASE = 'https://astock-api-7ovj.onrender.com';

// 获取最近30条K线
async function getLatestKline(code, limit = 30) {
  const resp = await fetch(`${BASE}/stock/${code}/latest?limit=${limit}`);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

// 使用示例
getLatestKline('600519', 30).then(data => {
  console.log('最新收盘价：', data[data.length - 1].close);
});

// 健康检查
async function healthCheck() {
  const resp = await fetch(`${BASE}/health`);
  return resp.json();
}
```

### Python

```python
import requests

BASE = 'https://astock-api-7ovj.onrender.com'

def get_latest(code, limit=30):
    resp = requests.get(f'{BASE}/stock/{code}/latest', params={'limit': limit})
    resp.raise_for_status()
    return resp.json()

def get_all(code):
    resp = requests.get(f'{BASE}/stock/{code}')
    resp.raise_for_status()
    return resp.json()

def health_check():
    return requests.get(f'{BASE}/health').json()

# 示例
data = get_latest('600519', limit=30)
print(f"最新收盘价：{data[-1]['close']}")
```

### Swift（iOS）

```swift
let base = "https://astock-api-7ovj.onrender.com"

func fetchLatestKline(code: String, limit: Int = 30) async throws -> [[String: Any]] {
    let url = URL(string: "\(base)/stock/\(code)/latest?limit=\(limit)")!
    let (data, _) = try await URLSession.shared.data(from: url)
    return try JSONSerialization.jsonObject(with: data) as! [[String: Any]]
}

// 使用
Task {
    do {
        let kline = try await fetchLatestKline(code: "600519")
        print("获取到 \(kline.count) 条数据")
    } catch {
        print("错误：\(error)")
    }
}
```

### Kotlin（Android）

```kotlin
val BASE = "https://astock-api-7ovj.onrender.com"

suspend fun getLatestKline(code: String, limit: Int = 30): String {
    return withContext(Dispatchers.IO) {
        URL("$BASE/stock/$code/latest?limit=$limit").readText()
    }
}

// 使用（在 ViewModel 中）
viewModelScope.launch {
    try {
        val resp = getLatestKline("600519")
        val jsonArray = JSONArray(resp)
        // 解析数据...
    } catch (e: Exception) {
        e.printStackTrace()
    }
}
```

### Flutter / Dart

```dart
import 'package:http/http.dart' as http;
import 'dart:convert';

const BASE = 'https://astock-api-7ovj.onrender.com';

Future<List<dynamic>> getLatestKline(String code, {int limit = 30}) async {
  final resp = await http.get(
    Uri.parse('$BASE/stock/$code/latest?limit=$limit'),
  );
  if (resp.statusCode == 200) {
    return jsonDecode(resp.body);
  } else {
    throw Exception('Failed to load: ${resp.statusCode}');
  }
}
```

---

## 注意事项

### ⚠️ 冷启动延迟（Render 免费版）

本服务部署在 Render 免费实例上，闲置后会**休眠**。  
首次请求（或被休眠后第一次请求）需要 **50~120 秒** 唤醒时间。

**建议处理方式**：
1. App 启动时先调用 `/health`，将超时设为 120 秒
2. 在 UI 上提示"正在唤醒服务，请稍候..."
3. 生产环境建议使用 Render 付费版或定时 ping 保活

### 数据更新频率

- 数据库中的每个标的会在**每个工作日 16:30（北京时间）** 自动增量更新
- 手动触发更新：无专门接口，可通过重新请求使缓存刷新（取决于实现）

### 懒加载首次耗时

- 从未请求过的标的，首次调用会实时从 AkShare 抓取全历史
- 个股历史数据量大的，首次请求可能需要 **10~30 秒**
- 建议移动端对首次请求加 loading 提示

### 请求频率限制

- 服务端没有做限流，但 AkShare 数据源有频率限制
- 批量预热已在服务端通过 `FETCH_DELAY=1.5s` 控制
- 客户端建议单次请求间隔 ≥ 1 秒

### 数据免责声明

- 所有数据来源于 AkShare（基于公开数据爬取）
- 仅供参考，不构成投资建议
- 数据可能有延迟，以交易所官方数据为准

---

## 服务端技术栈

| 组件 | 技术 |
|------|------|
| Web框架 | FastAPI（Python） |
| 数据源 | AkShare |
| 数据库 | SQLite（`stock.db`） |
| 定时任务 | APScheduler |
| 部署平台 | Render.com |
| Python版本 | 3.14+ |

---

*文档版本：v1.0 | 最后更新：2026-06-26*
