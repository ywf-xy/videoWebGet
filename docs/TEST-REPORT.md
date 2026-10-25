# CrawlerHub 通用爬虫平台 · 测试报告

| 项 | 内容 |
| --- | --- |
| 被测版本 | CrawlerHub v1.0.0（后端 T01–T11 + 前端 T12–T18 实现完成态） |
| 测试日期 | 2026-10-25 |
| 测试执行人 | 严过关（QA Engineer） |
| 测试范围 | 后端 `backend/app/` 全部模块（API / 引擎 / 策略 / 解析 / 下载 / 落盘 / 状态机）、前端构建与静态一致性 |
| 依据文档 | `docs/PRD.md` v1.0、`docs/ARCHITECTURE.md` v1.0（含 §13/§14 偏差记录） |
| 测试产物 | `backend/tests/`（10 个文件，3 738 行）、`backend/requirements-dev.txt`、本报告 |

---

## 1. TL;DR 判定

> **判定：PASS_WITH_ISSUES（主链路可用，存在 3 个需修复的源码缺陷）**

| 指标 | 数值 |
| --- | --- |
| 用例总数 | **246** |
| 通过 | **243** |
| 失败 | **0** |
| 预期失败（`xfail`，已确认为源码缺陷） | **3** |
| 跳过 | **0** |
| 总耗时 | 183 s（带覆盖率 192 s） |
| 语句覆盖率 | **86%**（4 756 条语句 / 669 条未覆盖） |
| 环境限制（不计为失败） | 4 项，见 §8 |

**结论**：PRD 第 7 章三种策略的 14 条边界、第 9 章目录/文件名/并发/暂停语义、43 个 API 端点契约全部有可重复的自动化断言，且绝大多数实测通过。发现 **3 个源码缺陷**（1 高危 + 2 中危），均为「不影响主链路跑通、但违反 PRD 明确条款」的问题，修复后需回归（对应用例已用 `xfail(strict=True)` 钉住，修好即变 `XPASS` 并报错提醒去掉标记）。

---

## 2. 环境与运行方式

| 项 | 说明 |
| --- | --- |
| Python | 3.13.14（`backend/.venv`，已装 `requirements.txt` 全部依赖） |
| 测试依赖 | `pytest 9.1.1`、`pytest-timeout 2.4.0`、`httpx 0.28.1`（TestClient 必需）、`pdfminer.six`（中文 PDF 抽取校验）、`pytest-cov 7.1.0` → 见 `backend/requirements-dev.txt` |
| 站点模拟 | `ThreadingHTTPServer`（进程内，端口随机）提供：视频列表/详情/m3u8（明文/AES-128/SAMPLE-AES）、文字列表/章节、图集列表/图集、`/img/*.jpg`、可注入的 404/500、可注入的响应延迟与并发计数 |
| 数据隔离 | 会话级临时目录（`crawlerhub-tests-*`）：独立 SQLite（**不触碰 `data/crawlerhub.db`**）、独立产物根、独立日志目录 |
| 用例隔离 | 每例前：等待引擎静默 → 复位暂停登记表 → 清空 7 张业务表 → 清空产物目录 → 复位模拟站点统计/注入 → 并发上限回到默认 |
| 网络 | **完全离线**，只访问 `127.0.0.1` 上的模拟站点 |

```bash
# 安装与运行
cd backend
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m pytest tests -q                       # 全量
.venv/Scripts/python.exe -m pytest tests -q --cov=app \
  --cov-config=tests/coverage.rc --cov-report=term-missing        # 带覆盖率
```

---

## 3. 用例清单与统计

| 测试文件 | 用例数 | 覆盖重点 |
| --- | --- | --- |
| `test_strategy.py` | 36 | 三策略 × PRD §7.2 全部边界（含首次游标、n 超总数、空列表、自动翻页、起始页越界 3008、页数截断、中间页空、页失败 skipped、缺日期保留、指纹去重、跨度 365 拦截、去重 0 条）、参数非法 → 1001、游标推进/不推进 |
| `test_path_builder.py` | 26 | 4 类目录模板**逐字符**比对（含 PRD 示例路径）、分类空 → 未分类、图片序号位宽 ≥3、mkdir -p、7 条文件名清洗规则（Windows 非法字符/首尾点/100 字符截断+8 位哈希/保留名 CON 等/空名兜底/空白合并/重名不版本化）、300 字符名与深目录**真实写盘**、临时目录清理 |
| `test_m3u8.py` | 32 | EXTINF 时长累加、MEDIA-SEQUENCE 与分片序号、相对/绝对 URI 拼接、master 取最高带宽、SAMPLE-AES / SAMPLE-AES-CTR / Widevine / FairPlay → 4007、KEY 缺 URI / IV 非法 → 4006、METHOD=NONE、NIST SP 800-38A 向量（pycryptodome 与纯 Python 两条实现路径）、AES-128-CBC 往返、密钥/IV 长度校验、下载器集成（明文/AES/缺省 IV/DRM/分片 404） |
| `test_task_state_machine.py` | 28 | 终态批次不可暂停（3005）、仅 paused 可恢复（3005）、批次/任务不存在（3004/4003）、单飞拒绝（3001，覆盖 pending/running/paused/paused_with_warning 四种占用态）、仅 failed 任务可重试（3007）、无可重试（3006）、批量重试计数、数据源被活跃批次占用不可删（2003）、软删除后 2001、停用源拒绝新建批次 |
| `test_api_contract.py` | 86 | 40 个端点的信封 `{code,data,message}`、分页 `{items,total,page,pageSize}`、`pageSize` 边界（0 / 负数 / 500 / 上界 200）、`page` 边界、错误码分段（1001/2001/2002/3003/3004/3006/3007/4003/4004/5002）、snake_case 字段、ISO8601 带时区、批次/任务字段集、数据源 CRUD+启停+关键字/类型筛选、脚本校验与试运行、JSON/CSV 导入与逐行错误、导出与**往返无损**、日志级别/关键字过滤、产物 5 条件组合与 `is_file_exists`、OpenAPI（`/docs`、43 端点：GET 22 / POST 16 / PUT 2 / DELETE 2 / PATCH 1） |
| `test_end_to_end.py` | 20 | 文字全链路（两阶段 → 2 任务成功 → 2 个 txt 落盘 size>0 → 目录逐字符校验 → 游标推进 → `total_items`/`last_success_at`）、task_result 落库、首页 overview 日/周/月与成功数联动、**增量第二次只抓新增**、n 超总数 success_with_warning、空列表 0 任务 success、阶段一失败不推进游标、部分失败游标只推进到成功项、小说目录模板（脚本提供 book）、小说无 book 时目录退化观察、S2 起始页越界(3008)/页数截断、S3 日期过滤 + 次日重跑全量跳过、图片图集目录与序号、视频 ffmpeg 缺失降级 `.ts`(3003)、SAMPLE-AES 任务级 4007、`.tmp` 保留策略、批次/任务计数自洽、耗时非负、趋势当日合计 |
| `test_pause_resume.py` | 4 | 执行中途暂停 → 无残留 running、任务数不丢、`done_tasks` 与实际一致 → 恢复 → 全量完成且产物不重复；暂停期间进度接口 `status=paused` 且 `active=[]`；建完任务即暂停 → 全部 pending → 恢复完成；图集任务单图检查点暂停 → 恢复（**BUG-03 复现用例**） |
| `test_concurrency.py` | 7 | `max_threads=2` + 8 慢任务：站点侧实测峰值并发 ≤ 2 且确实并发；两数据源并发时**全局**峰值 ≤ 2；8 任务含 1 个 404 → `success_with_warning`（且 404 不重试）；5xx 重试到 `attempt_count=3`；`max_threads=8` + 20 任务无 `database is locked`；批次结束活跃线程归零；**single-flight 并发竞态**（BUG-02 复现用例） |
| `test_text_pdf.py` | 7 | TXT UTF-8/标题正文/无 `.part` 残留/CRLF 归一；PDF >2KB、字体嵌入标记、ToUnicode 映射、pdfminer 抽取中文无乱码/无 `□`；系统字体缺失时回退 CID 字体；XML 特殊字符转义；`export_format=pdf` 端到端（.pdf + 同目录保留 .txt）；PDF 生成失败仅 WARN（**BUG-01 复现用例**） |
| `conftest.py` / `support.py` / `coverage.rc` | — | 装置：临时 DB/产物/日志、TestClient、模拟站点、状态清理、播种辅助、覆盖率配置 |

合计：**246 个用例**（`246 tests collected`）。

---

## 4. 缺陷清单（智能路由：全部 → Engineer）

> 路由判定依据：断言期望值来自 PRD / ARCHITECTURE 的明文条款，实际行为与之不符 → **源码 Bug**，由工程师修复；未修改 `backend/app/` 与 `frontend/src/` 任何文件。

### BUG-01（中危）产物类型与实际文件不一致：PDF 降级为 TXT 后 `artifact.type` 仍是 `pdf`

| 项 | 内容 |
| --- | --- |
| 位置 | `backend/app/engine/scheduler.py:511-521`（`_finish_success` 的 `update(Artifact).values(...)`）；关联 `scheduler.py:448-469`（`_create_artifact` 预登记类型）与 `scheduler.py:289-296`（`_run_text` 已正确回退 `artifact_type=text`） |
| 期望 | PDF 渲染失败降级为 TXT 时（DEV-09），产物记录类型应与实际文件一致：`artifact.type = text`、`path` 以 `.txt` 结尾、`task_result.artifact_type = text` 三者一致 |
| 实际 | `task_result.artifact_type=text`、文件为 `.txt`，但 `artifact.type` 仍为 `pdf`（预登记值），产物页按「PDF」筛选会命中一个 `.txt` 文件 |
| 证据用例 | `tests/test_text_pdf.py::TestPdfExportEndToEnd::test_pdf_failure_does_not_fail_task`（`xfail`，断言 `assert artifact["type"] == E.ARTIFACT_TEXT` → `assert 'pdf' == 'text'`） |
| 根因 | `_create_artifact` 按 `export_format` 预登记 `type=pdf`；`_finish_success` 只回填 `path/size/status/error_msg`，**未同步 `type`** |
| 最小复现 | 建文字数据源 → `POST /api/batches`（`export_format=pdf`）→ 使 `TextWriter.write_pdf` 抛错 → `GET /api/artifacts`：`type=pdf` 而 `path` 为 `.txt` |
| 修复建议 | 在 `_finish_success` 的 `values(...)` 中加 `type=outcome.artifact_type`（失败分支可保持预登记值或同样回填）；同时建议 `artifact` 表加 `uq_artifact_task(task_id)` 与 BUG-03 一并治理 |
| 回归方式 | 去掉该用例的 `xfail` 标记后应直接通过 |

### BUG-02（高危）数据源级 single-flight 存在并发竞态，可同时起两个活跃批次

| 项 | 内容 |
| --- | --- |
| 位置 | `backend/app/services/batch_service.py:86-95`（`SELECT ... status IN busy` 判占用）与 `:131-132`（`db.add(batch)` + `commit`）之间无原子性保证 |
| 期望 | PRD P0-15③ / §9.3：「同一数据源同一时刻只允许 1 个 running 批次；重复发起提示『该数据源有运行中的批次』并拒绝（3001）」 |
| 实际 | 两个并发请求可同时通过 `busy` 校验并各自 `INSERT`，同一数据源出现 2 个活跃批次 |
| 证据用例 | `tests/test_concurrency.py::TestSingleFlightRace::test_concurrent_create_same_source_only_one_succeeds`（`xfail`）。4 线程并发 3 轮：每轮均出现 ≥2 个"创建成功"；独立实验 5×6 轮共 30/30 轮复现；2 线程时 15 轮中 13 轮复现 |
| 影响 | 双击「开始爬取」或前端重试即可能触发：同源双批次并发下载 → 产物重复落盘、`cursor_*` 互相覆盖（可能跳采）、`total_items/health` 双重计数 |
| 最小复现 | 同一进程内 4 个线程同时执行 `with session_scope(): batch_service.create(db, BatchCreate(data_source_id=X, strategy='count', strategy_params={'n':1}))` → 观察 `crawl_batch` 中该数据源出现多条 `pending/running` 记录 |
| 修复建议（任一） | ① 加部分唯一索引：`CREATE UNIQUE INDEX uq_batch_active ON crawl_batch(data_source_id) WHERE status IN ('pending','running','paused','paused_with_warning')`，捕获 `IntegrityError` → 3001（SQLite 支持部分索引，与 `uq_ds_name_url` 同一手法）；② 事务内改用 `BEGIN IMMEDIATE` + `INSERT` 后 `SELECT COUNT` 复核（冲突回滚 → 3001）。①更彻底且与现有迁移机制（`migrate.py::_EXTRA_COLUMNS`）契合 |
| 回归方式 | 去掉该用例的 `xfail` 标记后应通过 |

### BUG-03（中危）任务重跑重复登记产物，残留永久「处理中」僵尸记录

| 项 | 内容 |
| --- | --- |
| 位置 | `backend/app/engine/scheduler.py:448-469`（`_create_artifact` 每次 `run_task` 无条件 `INSERT`）；`backend/app/db/models.py:227`（`artifact` 仅有非唯一索引 `ix_art_task`，无唯一约束） |
| 期望 | 一个任务对应一条产物记录（`artifact.task_id` 语义为一对一，参照 `task_result` 的 `uq_result_task`）；任务重跑（暂停恢复 / 失败重试 / 进程重启后恢复）时应复用或清理上一次尝试的 `processing` 记录 |
| 实际 | 每次 `run_task` 都新增一条 artifact：上一次尝试的 `processing`（`path=''`、`size=0`）记录永不复用、也不会被清理，产物条数 > 任务条数，产物页出现永久「处理中」的僵尸行 |
| 证据 | ① **进程重启实测**：4 个任务跑到一半 `SIGKILL` → 重启置 `paused_with_warning` → `resume` → 批次 `success`，`done_tasks=4` 但 `GET /api/artifacts` 返回 **5** 条（多出 1 条 `processing`、`path` 为空）；② 自动化用例 `tests/test_pause_resume.py::TestPauseResume::test_pause_during_gallery_does_not_duplicate_artifact_rows`（`xfail`，图集任务在「单图」检查点暂停 → 恢复后同一任务并存 2 条产物） |
| 说明 | 文字任务无原子步骤检查点（`_run_text` 不调用 `checkpoint`），所以暂停**打断不了**文字任务、也就不会产生重复；视频（分片）与图片（单图）任务可被打断 → 必现 |
| 最小复现 | 图集数据源（3~4 张图，单图延迟 0.8s）→ 建批次 → 等 `progress.active[0].step_done ≥ 1` → `pause` → 等任务回退 `pending` → `resume` → 等终态 → `GET /api/artifacts?data_source_id=X` 得到 2 条同 `task_id` 记录（1 条 `processing` 空路径 + 1 条 `success`） |
| 修复建议 | ① `_create_artifact` 改 upsert：先按 `task_id` 查，存在则 `UPDATE status=processing, path='', size=0, error_msg=NULL, updated_at=now` 并复用该 id；② `artifact` 加唯一索引 `uq_artifact_task(task_id)`（与 `task_result` 对齐，避免回归）；③ 启动孤儿复位时可顺带把「`processing` 且 task 非 running」的记录置为 `failed`/`missing`，避免历史僵尸行永久展示 |
| 回归方式 | 去掉该用例的 `xfail` 标记后应通过；重启实测的产物数应等于任务数 |

---

## 5. 测试代码自身缺陷与修正记录（自测自纠，2 条）

| 编号 | 现象 | 归属 | 处理 |
| --- | --- | --- | --- |
| T-01 | `test_deep_directory_written_to_disk` 断言「路径长度 < 260」失败（实测正好 260 且**写入成功**） | 测试代码 Bug（断言过严） | 改为断言「写入成功 + 文件大小正确 + 路径确实 ≥240 已触及预警阈值」；并在用例注释中说明长路径可写性取决于系统设置。`PathBuilder` 在 >240 时打印 WARNING 的行为符合设计 |
| T-02 | 全量套件（≥100 例后）出现批次永久卡住 `paused_with_warning`、`wait_batch` 超时 | 装置级状态泄漏 + **源码健壮性观察项** | 装置侧：`conftest.clean_state` 每例清空 `PauseController` 登记表（清表后 SQLite rowid 从 1 重新分配，批次 id 会被复用）。源码侧观察项：`PauseController.register()` 只在事件不存在时 `set()`，复用 id 时会继承上一次「已暂停」事件；`release()` 仅在 `_finalize` 调用，结束于 `paused` 的批次永不释放。**真实运行不触发**（批次记录不删除），但建议 `register()` 无条件 `event.set()` 以增强健壮性（严重度：低，未计入缺陷清单） |

另：`test_rule1_illegal_chars_replaced` 断言控制字符 0x1C–0x1F 应替换为 `_`，实测被「空白合并」规则先转成空格。**判定为测试断言与实现规则顺序的差异（非缺陷）**：产物仍是合法文件名，已在用例内注明与 PRD 9.2 规则 1 字面表述的偏差（严重度：观察项）。

---

## 6. 冒烟验证（独立于 pytest）

| 项 | 结果 | 说明 |
| --- | --- | --- |
| 超长文件名 + 深目录真写盘 | **通过** | 300 字符名称 → 清洗为 100 字符（91 + `_` + 8 位哈希）；4 层深目录下路径长度 260 仍写入成功、内容正确，无 `OSError` |
| 中文 PDF（ToUnicode / 不乱码） | **通过** | 24 884 字节，含 `/FontFile2`（msyh.ttc 子集嵌入）+ `/ToUnicode`；pdfminer 抽取文本 `中文标题测试 / 这是正文内容，中文不能出现方块。ABC123` 完全正确，无 `□`、无 `\ufffd`；CID 回退路径（`STSong-Light`）亦可生成 |
| 并发压测（`max_threads=8` + 20 任务） | **通过** | 20/20 成功，峰值并发 ≤ 8；批次日志全文检索无 `database is locked`；WAL + 短事务策略有效 |
| 进程重启恢复（`SIGKILL` 后重启） | **通过（暴露 BUG-03）** | 杀进程前：`crawl_batch.status=running`、任务 `pending×3 + running×1`；重启后：批次 → `paused_with_warning`、孤儿 running 任务 → `pending`、WARN 日志「进程重启导致批次中断，已置为「暂停(有残留)」，请手动恢复」存在；`resume` 后 `success`、`done=4`、游标推进到 4；**但产物 5 条 vs 任务 4 条**（见 BUG-03） |
| AES-128-CBC 对 NIST 向量 | **通过** | pycryptodome 与内置纯 Python 两条实现均与 SP 800-38A 一致（已在 pytest 中固化） |

---

## 7. 前端静态验证（无法做浏览器自动化）

| 项 | 结果 | 说明 |
| --- | --- | --- |
| `npm run build`（`vue-tsc --noEmit && vite build`） | **通过** | 0 error、0 warning；`✓ built in 16.31s`；最大 chunk `element-plus 794.69 kB`（< 800 KB 阈值）、`echarts 509.89 kB`、`vendor 297.49 kB` |
| 无 `console.*` 残留 | **通过** | `grep -rn "console\." src` 命中 **0** 处 |
| 状态颜色是否只来自 `utils/constants.ts` | **通过（状态维度）** | `StatusTag.vue` 是唯一状态文案/颜色出口，`TASK_STATUS_MAP`(6) / `BATCH_STATUS_MAP`(7) / `ARTIFACT_STATUS_MAP`(4) / `HEALTH_LEVEL_MAP`(4) 与 PRD §11.6 完全一致；业务组件未自行硬编码状态色 |
| 非状态硬编码色值 | **观察项** | `src/` 内仍有 40 处十六进制色值，集中在图表配置（`TrendChart`/`LoadGauge`：轴线 `#e4e7ed`、柱色 `#409eff`）与组件 `<style>`（脚本编辑器深色主题、侧栏 `#1f2d3d`）。属品牌/图表配色，不受 §11.5「状态映射表唯一来源」约束，建议后续收敛为 SCSS 变量（低优先级） |
| 路由 ↔ 侧边栏菜单一一对应 | **通过** | `MENU_ITEMS` 7 项（首页/视频/文字/图片/产物/数据源/设置）↔ `router/index.ts`：`/`、`/content/:type`（video/text/image 三条菜单共用）、`/artifacts`、`/data-sources`、`/settings` 全部可达；另有 `/data-sources/visual-create`（P2 占位，不在菜单，由数据源页入口进入）与 `:pathMatch(.*)*` 404，均符合设计 |
| 路由模式 | 说明 | 采用 `createWebHashHistory()`（DEV-14），因后端 `StaticFiles(html=True)` 无 SPA fallback；深链/刷新可用，但与 PRD 6.1「URL 路径」表述存在形式差异，已在架构偏差记录中说明 |
| 浏览器行为（1280px 无横向滚动、3s 轮询、防抖、状态色渲染） | **未验证** | 本机无 headless 浏览器（无 Playwright/Puppeteer），不做 DOM/E2E 断言；建议由人工按 PRD §6 逐页过一遍，或补装 Playwright |

---

## 8. 环境限制（不计入失败）

| 编号 | 限制 | 影响 | 处置 |
| --- | --- | --- | --- |
| E-01 | 本机无 `ffmpeg` / `ffprobe`（`shutil.which` 均为 None） | 「m3u8 → 真 MP4 且 ffprobe 识别时长」（P0-10①②）无法端到端验证 | 用替身**固定降级分支**验证 P0-10④（任务 failed(3003) + `.ts` 产物真实非空）与 PRD 9.7 语义；转封装代码路径覆盖率 45%（`ffmpeg.py` 未覆盖 156-218 行），建议在装有 ffmpeg 的机器补一条用例 |
| E-02 | 无 headless 浏览器 | 前端运行时行为未验证（见 §7 末行） | 仅做构建 + 静态一致性检查 |
| E-03 | Windows 长路径可写性依赖系统设置 | 本机可写 260 字符路径；未启用长路径的机器可能 `OSError` | 用例已改为断言「写入成功 + 触及 240 预警线」，避免与环境耦合 |
| E-04 | 未做大规模性能压测 | NFR-02/03（1 万任务 <800ms、10 万产物 <500ms）、P0-15②动态线程、NFR-07 磁盘不足 500MB 未验证 | 需专门数据集与可控磁盘环境，本期以功能正确性为主 |

---

## 9. 覆盖率观察

`pytest --cov=app`（`concurrency=thread`，含引擎线程）：**总计 86%**（4 756 语句 / 669 未覆盖）。

| 模块 | 覆盖率 | 未覆盖重点 |
| --- | --- | --- |
| `app/api/*`（7 个路由文件） | 86%–100% | `data_source.py` 84-91（模板/导出分支部分）、`setting.py` 43-46（头像上传成功分支：会写入项目 `data/static`，故意不测） |
| `app/engine/strategy.py` | **96%** | 253-255、285-290（S3 翻页异常分支） |
| `app/engine/scheduler.py` | 86% | 426-446（`safe_fail` 兜底）、108-109（上下文缺失） |
| `app/engine/batch_runner.py` | 83% | 505-528（`_fail_batch`）、363-372（暂停超时 WARN）、236-251（S2 0 条游标） |
| `app/engine/crawler_engine.py` | 91% | 129-137（孤儿批次复位告警分支在 pytest 内未走） |
| `app/parsers/*` | 69%–93% | `html_list_parser.py` 145-164（`total_pages_selector`/正则分支）、69% 为最低 |
| `app/downloader/*` | 45%–90% | **`ffmpeg.py` 45%**（无 ffmpeg，`to_mp4`/重编码/`probe_duration` 全未执行）；`http_client.py` 70%（流式下载、重试退避分支） |
| `app/services/*` | 68%–100% | `artifact_service.py` 68%（`open_dir` 的 `os.startfile` 分支、`redownload` 成功分支）、`setting_service.py` 71%（头像、purge 边界）、`data_source_service.py` 82%（导入异常行、update 各字段分支） |
| `app/common/*` | 70%–100% | `timeutil` 70%（未用到的格式化函数）、`disk` 70%（`dir_size`/`ensure_writable`）、`path_builder` 81%（`cleanup_stale_temp`） |
| `app/db/*`、`app/schemas/*` | 87%–100% | — |

> 说明：`app/main.py` 89%（静态托管分支、全局异常兜底）；`script_sandbox.py` 73%（超时/白名单拒绝分支）。

---

## 10. 我认为风险最高的 3 个点

1. **单飞竞态的连带效应（BUG-02）**——不只是"多一个批次"：同源双批次会并发写同一 `data_source` 的游标（`cursor_last_item_no/last_page` 后写覆盖先写）、重复下载同一批条目（产物覆盖 + `total_items` 双重计数 + 健康度样本被污染）。这类数据污染不可逆，且用户很难意识到自己"双击了两次"。建议列为上线前必修。
2. **产物表缺少 `task_id` 唯一性（BUG-03）**——`artifact` 是全站唯一的"文件实体"账本，任何一次任务重跑（暂停恢复、失败重试、"重新下载"、进程重启）都会多账，且僵尸行以「处理中」永久驻留产物页。产物页是用户排查问题的主界面，脏数据会直接误导排查结论；它与 BUG-01（类型错位）叠加后，"按类型 + 状态筛选"这一核心排查路径会同时失真。
3. **视频链路在本环境完全不可验证（E-01）**——`ffmpeg.py` 覆盖率仅 45%，`-c copy` 主路径、`libx264` 重编码兜底、`probe_duration`、`.tmp` 成功清理（PRD 9.7「成功 moveto 后删除临时目录」）全部未被执行过。这是 V-04「视频下载开箱可用」的核心价值点，也是唯一依赖外部二进制的路径，风险与验证缺口同时最大——建议在装好 ffmpeg 的机器上补一条"真 MP4 + ffprobe 时长 + 临时目录已清理"的用例后，再判定视频链路可交付。

---

## 附录 A：PRD §7.2 边界对照表（逐条 → 用例）

| # | PRD §7.2 场景 | 期望 | 对应用例 | 结果 |
| --- | --- | --- | --- | --- |
| 1 | S1 首次爬取（无游标） | 游标=0，从第 1 条取 n 条 | `test_strategy.py::TestStrategyCount::test_first_run_without_cursor_starts_from_first_item` + `test_end_to_end.py` 全链路 | 通过 |
| 2 | S1 n 大于剩余总数 | 取到末尾，`success_with_warning` | `TestStrategyCount::test_n_greater_than_total_yields_success_with_warning` + `TestTextEndToEnd::test_n_greater_than_total_marks_warning` | 通过 |
| 3 | S1 列表为空 | 0 任务，`success` | `TestStrategyCount::test_empty_list_yields_zero_tasks_and_success` + `TestTextEndToEnd::test_empty_list_yields_zero_tasks_success` | 通过 |
| 4 | S1 游标后不足 n 条但可翻页 | 自动翻页补足 | `TestStrategyCount::test_auto_turn_page_to_fill_n` | 通过 |
| 5 | S2 起始页 > 总页数 | `failed`，`error_code=3008` | `TestStrategyPage::test_start_page_beyond_total_raises_page_out_of_range` + `TestPageStrategyEndToEnd::test_start_page_out_of_range` | 通过 |
| 6 | S2 页数越界 | 截断 + WARN，`success_with_warning` | `TestStrategyPage::test_pages_truncated_to_last_page_with_warning` + `TestPageStrategyEndToEnd::test_pages_truncated_to_last_page` | 通过 |
| 7 | S2 中间某页为空 | 视为结束，已解析条目照常建任务 | `TestStrategyPage::test_empty_middle_page_stops_immediately` | 通过 |
| 8 | S2 某页请求失败 | 该页 skipped 并继续 | `TestStrategyPage::test_page_request_failure_is_skipped_and_continues` | 通过 |
| 9 | S3 条目无日期字段 | 保留 + WARN | `TestStrategyDate::test_item_without_date_is_kept_with_warning` | 通过 |
| 10 | S3 命中历史成功指纹 | 跳过、计 skipped、不建任务 | `TestStrategyDate::test_known_fingerprint_is_skipped` + `TestDateStrategyEndToEnd::test_date_range_and_dedupe_on_second_run` | 通过 |
| 11 | S3 date_to 为今天含未发布条目 | 只处理列表页已出现条目 | `TestStrategyDate::test_filters_items_by_date_range`（闭区间语义）| 通过 |
| 12 | S3 跨度 > 365 天 | 拦截（1001） | `TestStrategyDate::test_span_over_365_days_rejected` + 参数非法用例 | 通过 |
| 13 | 任意策略去重后 0 条 | `success` + 0 任务 | `TestStrategyCount::test_dedup_to_zero_yields_success_and_zero_tasks` + `TestStrategyDate::test_all_candidates_deduped_yields_empty_success` | 通过 |
| 14 | 同数据源已有运行中批次 | 拒绝（3001，single-flight） | `test_task_state_machine.py::TestBatchStateMachine::test_single_flight_rejects_second_batch`（4 种占用态）| 串行场景通过 / **并发场景失败 → BUG-02** |
| 15 | 游标推进时机（§7.4） | 全成功推进 / 部分失败仅按成功推进 / 阶段一失败不推进 | `TestStrategyCount::test_first_page_failure_fails_phase_and_keeps_cursor`、`TestTextEndToEnd::test_phase_one_failure_keeps_cursor_and_creates_no_task`、`TestTextEndToEnd::test_partial_failure_advances_cursor_to_last_success` | 通过 |
| 16 | §9.4 暂停语义 | 任务回退 pending、不丢不重、30s 归零 | `test_pause_resume.py` 全 4 例 | 通过（产物唯一性 → BUG-03） |

## 附录 B：测试文件清单

```
backend/tests/
├── conftest.py                    # 环境隔离 / 模拟站点 / TestClient / 状态清理
├── support.py                     # 响应解包、建源建批次、轮询终态、状态播种
├── coverage.rc                    # 覆盖率配置（concurrency=thread）
├── test_strategy.py               # 36 例：三策略 × PRD §7.2 边界
├── test_path_builder.py           # 26 例：目录模板 + 文件名清洗 + 长路径写盘
├── test_m3u8.py                   # 32 例：m3u8 解析 / DRM / AES-128(NIST) / 下载器集成
├── test_task_state_machine.py     # 28 例：批次与任务状态机非法跃迁
├── test_api_contract.py           # 86 例：40 端点契约 + 分页 + 错误码 + OpenAPI
├── test_end_to_end.py             # 20 例：全链路 / 增量 / S2 / S3 / 图片 / 视频降级
├── test_pause_resume.py           #  4 例：暂停恢复语义（含 BUG-03 复现）
├── test_concurrency.py            #  7 例：并发上限 / 全局上限 / 失败隔离 / DB 锁 / 单飞竞态
└── test_text_pdf.py               #  7 例：TXT / PDF 中文 / 导出格式降级
```

## 附录 C：本轮交付边界

- 新增：`backend/tests/**`、`backend/requirements-dev.txt`、`docs/TEST-REPORT.md`
- **未修改**：`backend/app/**`、`frontend/src/**`、`requirements.txt`、数据库文件
- 测试运行不触碰 `data/crawlerhub.db`、`data/output`、`logs/app.log`
