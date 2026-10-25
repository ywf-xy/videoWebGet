# CrawlerHub 通用爬虫平台

面向个人与小团队的**本地化通用爬虫工作台**：以「数据源 + 策略」为统一抽象，把视频 / 文字 / 图片
三类站点采集、任务调度、产物归档收敛到一套可视化界面里，零命令行完成从配置到落盘。

- 详细需求：`docs/PRD.md`
- 系统设计（含任务分解 / API 契约 / 数据表字段）：`docs/ARCHITECTURE.md`

## 技术栈

| 层 | 选型 |
| --- | --- |
| 后端 | Python 3.11+ · FastAPI · SQLAlchemy 2.x（同步）· Pydantic v2 · SQLite（WAL） |
| 前端 | Vue 3 · Vite · Element Plus · Pinia · ECharts |
| 外部依赖 | ffmpeg / ffprobe（视频转封装，缺失时降级为 `.ts`） |

## 快速开始

### 0. 安装 ffmpeg（视频转 MP4 必需，可选）

视频站点多为 m3u8，转 MP4 依赖 ffmpeg，任选其一：

- **项目内置（推荐，免改系统 PATH）**：把 ffmpeg 解压到 `tools/ffmpeg/`，使
  `tools/ffmpeg/bin/ffmpeg.exe`（及 `ffprobe.exe`）存在即可，后端启动时自动探测。
- **系统 PATH**：安装任意 Windows 版 ffmpeg 并加入 PATH，后端优先使用 PATH 中的版本。

未安装时不报错，视频任务会降级为「分片下载 + 合并 .ts」并在界面红字提示（任务标 3003）。

### 1. 后端

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

启动后：

- API 文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/api/health>
- 数据库文件：`data/crawlerhub.db`（首启自动创建，7 张表 + 索引 + 默认设置）
- 产物根目录：`data/output`（可在设置页修改）
- 应用日志：`logs/app.log`（5MB × 3 滚动）

环境变量（均可选）：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `CRAWLERHUB_HOST` | `127.0.0.1` | 监听地址（默认仅本机） |
| `CRAWLERHUB_PORT` | `8000` | 端口 |
| `CRAWLERHUB_DB` | `data/crawlerhub.db` | SQLite 文件路径 |
| `CRAWLERHUB_OUTPUT` | `data/output` | 默认产物根目录 |
| `CRAWLERHUB_LOG_DIR` | `logs` | 日志目录 |

### 2. 前端

```bash
cd frontend
npm install
npm run dev      # http://127.0.0.1:5173 ，/api 代理到 8000
npm run build    # 产物由后端单端口 8000 托管
```

## 目录结构

```text
backend/
  run.py                 # 启动脚本
  requirements.txt
  app/
    main.py              # FastAPI 入口（日志/DB/引擎/路由/静态托管）
    config.py            # 配置 + 枚举字面量 + 默认值
    common/              # 错误码、日志、时间、文件名清洗、路径构建、磁盘、指纹
    db/                  # SQLAlchemy 模型（7 表）、会话、迁移、种子
    schemas/             # Pydantic v2 DTO
    api/                 # 路由（仅参数校验 + 统一响应）
    services/            # 业务编排与事务边界
    engine/              # 引擎 / 批次执行器 / 调度 / 策略 / 暂停 / 健康度 / 脚本沙箱
    parsers/            # 内置 3 解析器 + 注册表
    downloader/          # HTTP / ffmpeg / m3u8 / 图片 / 文字落盘
  scripts/
    selftest_offline.py  # 离线自测（本地 HTTP 服务模拟三类站点）
```

## 关键语义速查

| 主题 | 规则 |
| --- | --- |
| 三种策略 | 按条数（游标 seq_no）/ 按分页（start+pages，越界截断）/ 按日期（区间+历史指纹去重） |
| 两阶段 | 阶段一解析列表建任务；阶段二线程池执行；阶段一失败不建任务、不推进游标 |
| 并发 | 实际并发 = `min(批次线程数, 全局上限)`，全局上限默认 4（1-32，设置页可改） |
| 单飞 | 同一数据源同时只允许 1 个 pending/running/paused 批次 |
| 暂停 | 不杀线程，任务在原子步骤结束后回退 `pending`；30s 未归零则 `paused_with_warning` |
| 重试 | 仅 failed；退避 `1s × 2^(n-1)` 上限 30s；404/403/脚本错误不重试 |
| 落盘 | 视频 `数据源/分类/名称.mp4`；小说 `数据源/分类/小说名/章节.txt`；图片 `数据源/分类/日期/图集/001.jpg` |
| m3u8 | 支持 AES-128（显式/缺省 IV）；SAMPLE-AES / DRM 明确报 4007 |
| 错误码 | 0 成功；1xxx 入参；2xxx 数据源；3xxx 调度；4xxx 解析下载；5xxx 系统 |

## 离线自测

```bash
cd backend
.venv/Scripts/python.exe scripts/selftest_offline.py     # Windows
# .venv/bin/python scripts/selftest_offline.py           # macOS/Linux
```

脚本会启动一个本地 HTTP 服务模拟「视频页 + m3u8（3 个分片）」「小说章节页」「图片列表页」，
跑通「解析 → 建任务 → 下载 → 产物落盘」三条链路，并校验产物文件真实存在且大小 > 0。

## 已知限制

- 需要登录 / 验证码 / 动态签名的站点不支持（本期不含浏览器自动化与登录态托管）。
- m3u8 仅支持 AES-128；SAMPLE-AES、Widevine / FairPlay / PlayReady 等 DRM 明确报错。
- ffmpeg 缺失时视频任务标记失败（3003），但会保留可播放 `.ts` 产物，装好 ffmpeg 后重试可复用分片。
- 同名产物本期直接覆盖并写 WARN 日志（版本化/去重为 P2-04）。
- 解析脚本按「本机可信用户」处理，仅做 60s 超时与异常捕获，不做进程级隔离。
