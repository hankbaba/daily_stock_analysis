# 股票数据获取机制详解

本文档详细说明项目如何获取股票数据，包括所有数据源、配置方式和优先级机制。

---

## 目录

1. [数据源列表](#1-数据源列表)
2. [历史数据获取](#2-历史数据获取)
3. [实时行情获取](#3-实时行情获取)
4. [数据切换逻辑](#4-数据切换逻辑)
5. [ETF数据获取](#5-etf数据获取)
6. [配置说明](#6-配置说明)
7. [数据流示意图](#7-数据流示意图)

---

## 1. 数据源列表

项目实现了以下 6 个数据源：

| 数据源 | 文件路径 | 默认优先级 | 特点 |
|--------|----------|-----------|------|
| **Efinance** | `data_provider/efinance_fetcher.py` | 0 | 东方财富，数据全面，免费，易被封 |
| **Akshare** | `data_provider/akshare_fetcher.py` | 1 | 综合源，支持 em/sina/tencent 子源 |
| **Tushare** | `data_provider/tushare_fetcher.py` | -1/2 | 付费需Token，配置后优先级最高 |
| **Pytdx** | `data_provider/pytdx_fetcher.py` | 2 | 通达信，本地安装 |
| **Baostock** | `data_provider/baostock_fetcher.py` | 3 | 免费但数据有限 |
| **Yfinance** | `data_provider/yfinance_fetcher.py` | 4 | 专门用于美股 |

### 数据源基类

**文件**: `data_provider/base.py`

所有数据源继承自 `BaseDataFetcher` 基类，实现了统一的接口：
- `get_daily_data()` - 获取历史日线数据
- `get_realtime_quote()` - 获取实时行情

---

## 2. 历史数据获取

### 2.1 优先级配置

**代码位置**: `data_provider/base.py:363-410`

**默认优先级顺序**:
```
Efinance(0) → Akshare(1) → Tushare(2) → Pytdx(2) → Baostock(3) → Yfinance(4)
```

数值越小，优先级越高。

### 2.2 Tushare 特殊处理

**代码位置**: `data_provider/base.py:193-199`

```python
# 如果配置了 TUSHARE_TOKEN 且初始化成功，优先级设为 -1（绝对最高）
if self._tushare_available:
    tushare.priority = -1
```

### 2.3 默认初始化

**代码位置**: `data_provider/base.py:396-403`

```python
self._fetchers = [
    efinance,      # 默认优先级 0
    akshare,       # 默认优先级 1
    tushare,       # 动态优先级 -1/2
    pytdx,         # 默认优先级 2
    baostock,      # 默认优先级 3
    yfinance,      # 默认优先级 4
]
```

---

## 3. 实时行情获取

### 3.1 优先级配置

**配置文件**: `src/config.py:616` 和 `.env.example:374-375`

**默认优先级**:
```
tencent > akshare_sina > efinance > akshare_em
```

### 3.2 支持的数据源

| 数据源 | 说明 | 优点 | 缺点 |
|--------|------|------|------|
| `tencent` | 腾讯财经 | 量比/换手率/PE/PB全，单股查询稳定 | 需逐个查询 |
| `akshare_sina` | 新浪财经 | 基本行情稳定 | 无量比 |
| `efinance` | 东财(efinance库) | 数据最全 | 易被封 |
| `akshare_em` | 东财(akshare库) | 数据全面 | 全量拉取易被封 |
| `tushare` | Tushare Pro | 数据全面 | 需2000积分 |

### 3.3 自动注入逻辑

**代码位置**: `src/config.py:676-686`

```python
# 如果配置了 TUSHASE_TOKEN 但未显式设置 REALTIME_SOURCE_PRIORITY
# 自动将 tushare 添加到首位
if tushare_token:
    resolved = f'tushare,{default_priority}'
    logger.info(f"TUSHARE_TOKEN detected, auto-injecting tushare into realtime priority: {resolved}")
```

注入后的优先级变为:
```
tushare > tencent > akshare_sina > efinance > akshare_em
```

### 3.4 实时行情功能开关

**配置文件**: `src/config.py:227-234`

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `ENABLE_REALTIME_QUOTE` | true | 启用实时行情 |
| `ENABLE_REALTIME_TECHNICAL_INDICATORS` | true | 用实时价计算MA/多头排列 |
| `ENABLE_CHIP_DISTRIBUTION` | true | 启用筹码分布 |
| `ENABLE_EASTMONEY_PATCH` | false | 东财接口补丁 |

---

## 4. 数据切换逻辑

### 4.1 故障切换策略

**代码位置**: `data_provider/base.py:417-502`

```python
def get_daily_data(self, symbol: str, start_date, end_date):
    errors = []

    for fetcher in self._fetchers:
        try:
            df = fetcher.get_daily_data(symbol, start_date, end_date)
            if df is not None and not df.empty:
                return df, fetcher.name
        except Exception as e:
            errors.append(f"[{fetcher.name}] 失败: {str(e)}")
            continue

    # 所有数据源都失败
    raise DataFetchError(f"所有数据源失败: {'; '.join(errors)}")
```

### 4.2 特殊路由

**代码位置**: `data_provider/base.py:454-476`

- **美股指数**: 直接使用 `YfinanceFetcher`
- **美股股票**: 直接使用 `YfinanceFetcher`
- **A股**: 按优先级依次尝试所有数据源

### 4.3 实时行情切换逻辑

**代码位置**: `data_provider/base.py:585-744`

1. **美股特殊处理**: 美股和美股指数直接使用 `YfinanceFetcher`
2. **A股优先级切换**: 按配置的优先级顺序尝试
3. **字段补充**: 如果主要数据源缺少某些字段，从后续数据源补充
4. **熔断器机制**: 连续失败后跳过该数据源（冷却时间5分钟）

### 4.4 缓存机制

- **缓存时间**: `realtime_cache_ttl`（默认600秒）
- **批量预取**: 当股票数量≥5时自动预取
- **熔断冷却**: `CIRCUIT_BREAKER_COOLDOWN`（默认300秒）

---

## 5. ETF数据获取

ETF（交易型开放式指数基金）与普通股票在数据获取上存在显著差异，项目对 ETF 实现了专门的识别和处理机制。

### 5.1 ETF 代码识别规则

#### A股 ETF 代码格式

**代码位置**: 各 `fetcher.py` 文件的 `_is_etf_code()` 方法

| 市场 | ETF 代码前缀 | 示例 |
|------|-------------|------|
| 上交所 | `51xxxx`, `52xxxx`, `56xxxx`, `58xxxx` | 510300, 512000 |
| 深交所 | `15xxxx`, `16xxxx`, `18xxxx` | 159915, 159919 |

```python
# efinance_fetcher.py:138-139
etf_prefixes = ('51', '52', '56', '58', '15', '16', '18')
return stock_code.startswith(etf_prefixes) and len(stock_code) == 6
```

#### 国际 ETF 识别

**代码位置**: `src/search_service.py:999-1021`

通过股票名称关键词识别：
- 关键词: `'ETF'`, `'FUND'`, `'TRUST'`, `'INDEX'`, `'TRACKER'`, `'UNIT'`
- 结合代码格式（1-5个大写字母）判断

### 5.2 ETF 专用数据接口

各数据源为 ETF 提供了专门的接口：

| 数据源 | 普通股票接口 | ETF 专用接口 | 代码位置 |
|--------|-------------|-------------|---------|
| **EFinance** | `ef.stock.get_quote_history()` | `ef.fund.get_quote_history()` | `efinance_fetcher.py:330-396` |
| **Akshare** | `stock_zh_a_hist()` | `fund_etf_hist_em()` | `akshare_fetcher.py:449-471` |
| **Tushare** | `daily()` | `fund_daily()` | `tushare_fetcher.py:330-335` |

### 5.3 ETF 实时行情差异

#### EFinance ETF 实时行情

**代码位置**: `efinance_fetcher.py:571-665`

```python
# ETF 需要显式传入 ['ETF'] 参数
df = ef.stock.get_realtime_quotes(['ETF'])
```

#### 独立缓存机制

- **独立缓存**: `_etf_realtime_cache`（与股票行情分离）
- **独立熔断器**: `"efinance_etf"`
- **缓存 TTL**: 30秒（与股票相同）

### 5.4 ETF 数据处理差异

#### 数据格式差异

| 项目 | 普通股票 | ETF |
|------|---------|-----|
| 价格数据 | OHLC | 净值数据（单位净值、累计净值） |
| 数据补全 | 直接获取 | 需要补全 OHLC 列 |
| 交易数据 | 标准格式 | 可能需要格式转换 |

#### 分析差异

**代码位置**: `src/analyzer.py:948-953`

ETF 在 AI 分析时采用不同的约束逻辑：
- 重点关注指数走势而非公司基本面
- 不进行市盈率、市净率等估值指标分析
- 更关注跟踪误差和折溢价率

### 5.5 ETF 核心代码位置

| 文件 | 功能 | 行号 |
|------|------|------|
| `efinance_fetcher.py` | ETF识别 `_is_etf_code()` | 124-139 |
| `efinance_fetcher.py` | ETF历史数据 `_fetch_etf_data()` | 330-396 |
| `efinance_fetcher.py` | ETF实时行情 `_get_etf_realtime_quote()` | 571-665 |
| `efinance_fetcher.py` | ETF缓存 `_etf_realtime_cache` | 117-122 |
| `akshare_fetcher.py` | ETF识别 `_is_etf_code()` | 90-106 |
| `akshare_fetcher.py` | ETF历史数据 `_fetch_etf_data()` | 449-471 |
| `tushare_fetcher.py` | ETF识别 `_is_etf_code()` | 50-59 |
| `tushare_fetcher.py` | ETF接口切换 | 330-335 |
| `src/search_service.py` | ETF搜索识别 `is_index_or_etf()` | 1003-1021 |
| `src/core/pipeline.py` | ETF标志设置 | 492-494 |
| `src/analyzer.py` | ETF特殊分析约束 | 948-953 |

### 5.6 ETF 数据流示意图

```
                    ┌─────────────────┐
                    │   识别 ETF 代码  │
                    └────────┬────────┘
                             │
                ┌────────────┼────────────┐
                │            │            │
                ▼            ▼            ▼
           ┌─────────┐ ┌─────────┐ ┌─────────┐
           │ 上交所ETF │ │ 深交所ETF │ │ 国际ETF │
           │ 51xxxx │ │ 15xxxx │ │ 关键词 │
           │ 52xxxx │ │ 16xxxx │ │ 识别 │
           │ 56xxxx │ │ 18xxxx │ │ │
           │ 58xxxx │ │ │ │ │
           └────┬────┘ └────┬────┘ └────┬────┘
                │            │            │
                ▼            ▼            ▼
           ┌──────────────────────────────────┐
           │      调用 ETF 专用数据接口       │
           │  ef.fund.get_quote_history()    │
           │  ak.fund_etf_hist_em()          │
           │  fund_daily()                   │
           └───────────────┬──────────────────┘
                           │
                ┌──────────┼──────────┐
                ▼          ▼          ▼
           ┌─────────┐ ┌─────────┐ ┌─────────┐
           │历史数据 │ │实时行情 │ │独立缓存 │
           └─────────┘ └─────────┘ └─────────┘
```

### 5.7 使用示例

```bash
# .env 文件中添加 ETF 代码
STOCK_LIST=510300,159915,512000

# 510300 - 沪深300ETF (上交所)
# 159915 - 深证ETF (深交所)
# 512000 - 券商ETF (上交所)
```

---

## 6. 配置说明

### 6.1 环境变量配置

**文件**: `.env`

```bash
# Tushare配置（可选，推荐配置）
TUSHARE_TOKEN=your_token_here

# 实时行情优先级配置
REALTIME_SOURCE_PRIORITY=tencent,akshare_sina,efinance,akshare_em,tushare

# 实时功能开关
ENABLE_REALTIME_QUOTE=true
ENABLE_REALTIME_TECHNICAL_INDICATORS=true
ENABLE_CHIP_DISTRIBUTION=true
ENABLE_EASTMONEY_PATCH=false

# 流控配置
CIRCUIT_BREAKER_COOLDOWN=300
```

### 6.2 数据源优先级配置示例

```bash
# 示例1: 默认配置（推荐）
REALTIME_SOURCE_PRIORITY=tencent,akshare_sina,efinance,akshare_em

# 示例2: 有Tushare高积分账号
REALTIME_SOURCE_PRIORITY=tushare,tencent,akshare_sina,efinance,akshare_em

# 示例3: 只用新浪（最稳定但数据简单）
REALTIME_SOURCE_PRIORITY=akshare_sina
```

---

## 7. 数据流示意图

```
                    ┌─────────────────┐
                    │  get_daily_data │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
        ┌──────────┐   ┌──────────┐   ┌──────────┐
        │ 美股指数  │   │   美股   │   │   A股    │
        └────┬─────┘   └────┬─────┘   └────┬─────┘
             │              │              │
             ▼              ▼              ▼
        Yfinance      Yfinance      ┌─────────┐
                                   │ Efinance │──┐
                                   └─────────┘  │
                                        ▼       │
                                   ┌─────────┐  │
                                   │ Akshare │──┤
                                   └─────────┘  │
                                        ▼       │
                                   ┌─────────┐  │
                                   │ Tushare │──┤  (按优先级依次尝试)
                                   └─────────┘  │
                                        ▼       │
                                   ┌─────────┐  │
                                   │  Pytdx  │──┤
                                   └─────────┘  │
                                        ▼       │
                                   ┌─────────┐  │
                                   │Baostock │──┤
                                   └─────────┘  │
                                        ▼       │
                                   ┌─────────┐  │
                                   │Yfinance │──┘
                                   └─────────┘
```

### 实时行情数据流

```
                    ┌──────────────────┐
                    │ get_realtime_quote│
                    └─────────┬────────┘
                              │
                ┌─────────────┼─────────────┐
                │             │             │
                ▼             ▼             ▼
           ┌─────────┐  ┌─────────┐  ┌─────────┐
           │ 美股指数 │  │  美股   │  │   A股   │
           └────┬────┘  └────┬────┘  └────┬────┘
                │             │             │
                ▼             ▼             ▼
           Yfinance     Yfinance     ┌──────────┐
                                    │ Tencent  │──┐
                                    └──────────┘  │
                                          ▼       │
                                    ┌──────────┐  │
                                    │Sina/Akshare│─┤  (按配置优先级)
                                    └──────────┘  │
                                          ▼       │
                                    ┌──────────┐  │
                                    │ Efinance │──┤
                                    └──────────┘  │
                                          ▼       │
                                    ┌──────────┐  │
                                    │ Tushare  │──┘
                                    └──────────┘
```

---

## 8. 代码参考

### 8.1 核心文件

| 文件 | 说明 |
|------|------|
| `data_provider/base.py` | 数据源管理基类，优先级控制，切换逻辑 |
| `data_provider/efinance_fetcher.py` | 东方财富数据源实现 |
| `data_provider/akshare_fetcher.py` | Akshare数据源实现 |
| `data_provider/tushare_fetcher.py` | Tushare数据源实现 |
| `data_provider/pytdx_fetcher.py` | 通达信数据源实现 |
| `data_provider/baostock_fetcher.py` | Baostock数据源实现 |
| `data_provider/yfinance_fetcher.py` | Yahoo Finance数据源实现 |
| `src/config.py` | 配置管理，优先级解析 |

### 8.2 关键方法

| 方法 | 位置 | 说明 |
|------|------|------|
| `_init_default_fetchers()` | `base.py:363-410` | 初始化数据源和默认优先级 |
| `get_daily_data()` | `base.py:417-502` | 获取历史数据，实现故障切换 |
| `get_realtime_quote()` | `base.py:585-744` | 获取实时行情，支持字段补充 |
| `_resolve_realtime_source_priority()` | `config.py:661-688` | 解析实时行情优先级配置 |

---

## 9. 常见问题

### Q1: 如何更改数据源优先级？

A: 在 `.env` 文件中配置 `REALTIME_SOURCE_PRIORITY`:

```bash
REALTIME_SOURCE_PRIORITY=tushare,tencent,akshare_sina,efinance,akshare_em
```

### Q2: Tushare 优先级为什么会自动提升？

A: 当检测到有效的 `TUSHARE_TOKEN` 时，系统会自动将 Tushare 的优先级设为 -1（最高），确保付费数据源优先使用。

### Q3: 如何查看当前使用的哪个数据源？

A: 查看日志文件，系统会记录每次数据获取所使用的数据源：
```
[INFO] 使用数据源: efinance
```

### Q4: 实时行情获取失败怎么办？

A: 系统会自动切换到下一个优先级的数据源。如果所有数据源都失败，会记录详细错误信息。

### Q5: 如何禁用某个数据源？

A: 在 `REALTIME_SOURCE_PRIORITY` 配置中不包含该数据源即可。

---

*最后更新: 2026-03-05*
