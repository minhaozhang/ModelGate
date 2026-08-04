# ModelGate Dashboard 性能优化

## 背景

线上 PostgreSQL 出现 `idle-in-transaction` 长事务堆积，内存压力较大（3.6GB）。定位到根因：dashboard 统计查询打在 `request_logs_all` 视图上，该视图是 `request_logs`（40万行 / 568MB）UNION ALL `request_logs_history`（697MB），**每次统计查询全表扫 1.2GB**。连接池配置也过大（pool_size=20 + max_overflow=30）。

---

## 优化项

### 1. 连接池配置走环境变量

**文件**: `app/core/database.py`

| 参数 | 之前 | 现在 |
|------|------|------|
| `pool_size` | 硬编码 20 | `int(os.getenv("DB_POOL_SIZE", "5"))` |
| `max_overflow` | 硬编码 30 | `int(os.getenv("DB_MAX_OVERFLOW", "5"))` |

**部署配合**：docker-compose 加上

```yaml
environment:
  DB_POOL_SIZE: 5
  DB_MAX_OVERFLOW: 5
```

3.6GB 内存机器上限 ~10 连接（每个 ~88MB）是安全的；以后加内存直接调环境变量即可，无需重新构建镜像。

---

### 2. Dashboard 查询改打 live 表（不再扫 view）

**文件**: `app/routes/stats.py`, `app/routes/user.py`

把 `from app.core.database import RequestLogRead as RequestLog` 改成 `import RequestLog`：

| 类 | 映射对象 | 含义 |
|----|---------|------|
| `RequestLogRead` | `request_logs_all` 视图 | **UNION ALL 的 live + history，1.2GB** |
| `RequestLog` | `request_logs` 表 | **live 表，有 `created_at` 索引** |

**各 period 的查询路径：**

| Period | 之前 | 现在 |
|--------|------|------|
| day / week / month | 扫整个 view | 只扫 live 表（带 `created_at` 索引） |
| year | 已用 daily_stats 表 | 不变，今日实时部分改用 live 表 |

实测：原本多秒级的查询降到 **< 100ms**。

---

### 3. Key Stats 加时间范围

**文件**: `app/routes/keys.py` 的 `get_api_key_stats`

之前完全无时间限制，4 个 `count(*)/sum()` 都在扫整个 view。加了 30 天 cutoff：

```python
cutoff = datetime.now() - timedelta(days=30)
# 每个 query 都加 RequestLog.created_at >= cutoff
```

---

### 4. `/stats` 全量汇总改走预聚合表

**文件**: `app/routes/stats.py` 的 `get_stats`

**之前**：4 个无时间限制的 `count(*)/sum()` 打在 view 上，单次 ~400-500ms。

**现在**：拆成「历史」+「今日」两部分相加：

```python
# 历史：日聚合表（696 行，秒查）
hist = select(
    func.sum(ProviderDailyStat.requests),
    func.sum(ProviderDailyStat.tokens),
    func.sum(ProviderDailyStat.errors),
    func.sum(ProviderDailyStat.rate_limited),
).where(ProviderDailyStat.date < today_str)

# 今日：复用已有 in-process 缓存（30s TTL）
today = await get_cached_today_stats(today_start)
```

**边界正确性**：聚合任务 `aggregate_yesterday_stats()` 每天凌晨只把**昨天**数据写入 `*_daily_stats`，所以 `date < today_str` 不会和今日实时数据重复计算。

**实测效果**：

| 调用 | 之前 | 现在 |
|------|------|------|
| 冷启动 | ~400-500ms | 80ms |
| 热缓存 | ~400-500ms | **18ms** |
| 扫描数据量 | 1.2GB | ~50KB（696 行） |

---

## 刻意保留 view 的地方

下列场景确实需要跨 live + history 历史数据，**保留 `RequestLogRead`** 不动：

- `app/routes/logs.py`：管理员日志查看器（用户会翻历史日志）
- `app/services/usage_report.py`：使用量报表导出（需要完整历史）
- `app/services/stats_aggregator.py`：日聚合服务（回填历史数据时需要扫全表）

---

## 涉及的提交

| commit | 内容 |
|--------|------|
| `33eecd9` | dashboard 查询命中 live 表 + 连接池环境变量 + keys.py 加时间范围 |
| `5b8475f` | `/stats` 全量汇总改预聚合表 + 今日缓存 |

镜像：`10.100.2.148:6002/modelgate:latest`（`sha256:6b889c0a`）

---

## 部署 Checklist

1. docker-compose.yml 加环境变量：`DB_POOL_SIZE=5` `DB_MAX_OVERFLOW=5`
2. 拉新镜像部署
3. 观察 PostgreSQL `pg_stat_activity`：长事务应明显减少，连接数稳定在低位
4. dashboard 响应应在百毫秒内（取决于网络），`/stats` 在热缓存下 <50ms
