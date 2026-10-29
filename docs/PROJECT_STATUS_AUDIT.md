# 经济学考研学习平台｜项目现状全景梳理文档

> **版本标识：261029（2026-10-29）审计版本**
> **仓库：** `zeng-bowen/ai-kaoyan-learning-platform`
> **审计基线：** GitHub `main` commit `b9311bbf2f67a50d68d96b0a4890ba70ce97d8b4`
> **基线提交：** `精简院校与考试为考试标签库，并按标签匹配知识与题目 (#3)`
> **审计性质：** 仅盘点代码现状，不把 `PRODUCT_CONTEXT.md` 中的产品规划写成已实现功能，不新增重构或产品规划。

## 审计口径与证据边界

| 项目 | 审计结论 |
|---|---|
| 已核实源码 | 已逐项核对基线提交中的 `src/main.tsx`、`src/admin.tsx`、`api/main.py`、`api/recognition.py`、`api/test_targets.py`、`package.json`、`vite.config.ts`、`README.md`、`PRODUCT_CONTEXT.md`、`CONTRIBUTING.md`、`AGENTS.md` 与 CI 配置。 |
| 本地 Git 状态 | 审计开始时，`E:\经济学考研学习平台` 的已跟踪工作区干净；本地 `main` 从 `7710962d8cca0ced7874c55cccc25efc5ebbf5d5` 快进到远端 `b9311bbf2f67a50d68d96b0a4890ba70ce97d8b4` 后，从该提交创建 `docs/project-status-audit-261029`。创建本文档前，分支相对审计基线无已跟踪文件差异。 |
| 本地未核实变化 | `.gitignore` 排除的 `data/`、`.venv/`、`node_modules/`、`dist/` 属于本地运行数据或构建产物，不属于 GitHub 审计基线；本审计不读取、不修改，也不据此声称本地运行数据状态。 |
| 历史验证记录 | PR #3 和 README 记载过构建与 6 项回归测试结果，但这些历史记录不自动等同于本次审计已重新运行。本文只在“本次验证记录”中陈述本次实际执行结果。 |
| 状态标记 | `✅ 已完成` 表示基线代码已有可执行实现；`⚙️ 开发中` 表示已有部分界面、数据流或接口，但功能闭环不完整；`❌ 仅规划未写代码` 表示只在 PRD/文案中出现，基线没有对应业务实现。 |

---

# 一、产品功能现状全景

## 1.1 管理员端

管理员端入口为 `/admin/`，由 `admin/index.html` 加载 `src/admin.tsx`。它是单页应用，当前只有四个一级工作区，页面切换不改变浏览器 URL。

| 页面/工作区 | 状态 | 前端路径 | 已实现功能 | 未实现或边界 | 代码依据 |
|---|---|---|---|---|---|
| 平台总览 | ✅ 已完成 | `/admin/`，工作区“总览” | 显示近 30 秒活跃做题会话、累计作答、已发布题目、正确率占位、按难度自评均值、待审核题目数、图片队列数；支持手动刷新并约每 2 秒轮询版本。 | 没有真实用户数、活跃用户画像、AI 成本/异常、系统健康监控；正确率固定为 `null`。 | `src/admin.tsx`；`GET /api/admin/stats` |
| 院校与考试 | ✅ 已完成 | `/admin/`，工作区“院校与考试” | 新增/编辑考试标签；表单只含院校、考试科目代码及名称、备注；ID 后端生成；考研届次按中国当前公历年份加一；重复标签返回 409。 | 不维护学院、专业、独立年份、招生信息、来源核验、试卷或题目；无删除接口。 | `src/admin.tsx`；`TargetIn`；`POST/PUT /api/admin/targets` |
| 知识目录 | ✅ 已完成 | `/admin/`，工作区“知识目录” | 新增/编辑知识点；维护科目、模块、名称、概要、来源名称与 HTTPS 来源；绑定一个或多个考试标签；按标签筛选；人工审核发布。编辑知识点会把其已发布关联题目退回草稿。 | 当前是平面列表，不是完整树；没有公式、图形、推导、参考书页码、考法、重要度等字段；无删除与版本比较。 | `src/admin.tsx`；`TopicIn`；`/api/admin/topics*` |
| 题目中心—列表与筛选 | ✅ 已完成 | `/admin/`，工作区“题目中心” | 展示管理编号、题干、来源、考试标签、年份、知识点、审核状态；支持考试标签、年份、知识点、来源类型、审核状态、编号/题干筛选。 | UI 在已加载数据上做客户端筛选；没有分页、排序、批量编辑、去重、下架、删除、版本比较或问题反馈处理。 | `src/admin.tsx` 的 `matches` 与题目表格 |
| 题目中心—录入与编辑 | ✅ 已完成 | `/admin/`，工作区“题目中心” | 新建/编辑题目；管理编号可自填或自动生成；绑定一个考试标签与同标签知识点；填写栏目、题型、难度、年份、来源、题干、答案、解析、截图；编辑后自动回到草稿。 | 题型为自由文本，没有统一题型字典；没有富文本、Markdown/LaTeX 编辑器、公式或图形结构化字段。 | `QuestionIn`；`POST/PUT /api/admin/questions` |
| 题目中心—人工审核 | ✅ 已完成 | `/admin/`，题目列表操作 | 支持发布/退回；发布前校验编号、来源、标签、题干、答案、解析；真题校验年份、HTTPS 来源与人工核验；截图录题校验人工核验；知识点必须已发布且与题目考试标签一致。 | 无审核角色、审核人字段、审计日志；同一操作人可录入并审核；没有审批流。 | `ReviewIn`；`POST /api/admin/questions/{id}/review` |
| 题目资料上传 | ✅ 已完成 | `/admin/`，题目中心“题目资料上传” | 批量上传 PNG/JPEG/WebP，前后端均限制 8 MB；后端检查 Base64、魔数和基本尾部结构；落盘保存并记录 SHA-256；支持查看原图、关联截图、人工录题。 | 不支持 PDF、整卷拆题、裁剪、去重阻止、恶意内容扫描或对象存储；文件与数据库写入不是同一事务。 | `IntakeIn`；`POST /api/admin/intakes`；图片读取接口 |
| 图片 AI 识别 | ⚙️ 开发中 | 管理端 UI 无“识别”按钮；仅后端接口 | 已定义 Provider 协议、动态加载配置、单张与批量识别接口、结构化候选模型；识别结果只进入 `AI_DRAFT` 并保存在管理员队列数据中。 | 仓库没有任何真实模型适配器或 API 调用；未配置时返回 501；UI 没有触发识别或展示候选结果；无超时、重试、任务队列、调用日志、成本和模型版本记录。 | `api/recognition.py`；`POST /api/admin/intakes/{id}/recognize`；`recognize-batch` |
| 真题管理独立视图 | ❌ 仅规划未写代码 | 无 | 真题可在题目中心以 `TARGET_PAST_EXAM`/`RELATED_PAST_EXAM` 来源类型和年份录入。 | 无试卷主表、试卷—单题关系、整卷顺序/分值、扫描件追溯页面。 | `PRODUCT_CONTEXT.md` 6.5；代码无 PastExam 表或独立页面 |
| 精品练习管理独立视图 | ❌ 仅规划未写代码 | 无 | 题目中心可将题目来源标为 `CURATED_EXERCISE`。 | 无 `QuestionSet`、题集排序、专题和推荐理由。 | 仅 `source_type` 枚举 |
| AI 内容管理 | ❌ 仅规划未写代码 | 无 | 只有图片识别适配边界。 | 无组卷规则、提示词/模型管理、AI 答疑日志、成本监控、AI 生成题审核工作台。 | `PRODUCT_CONTEXT.md` 6.7；代码无对应页面/表 |
| 用户与学习数据管理 | ❌ 仅规划未写代码 | 无 | 总览只读聚合统计。 | 无用户列表、目标管理、学习明细权限与异常处理。 | 代码无管理员用户页面 |
| 通知与内容运营 | ❌ 仅规划未写代码 | 无 | 无。 | 无通知表、发布、定时、用户群与订阅。 | 代码无对应对象 |
| 论坛管理 | ❌ 仅规划未写代码 | 无 | 无。 | 无帖子、评论、举报或审核。 | 代码无对应对象 |
| 系统管理 | ❌ 仅规划未写代码 | 无 | 仅有本机访问限制。 | 无管理员账号、RBAC、操作日志、备份、功能开关或系统参数页。 | `guard_admin` 不是身份认证 |

## 1.2 用户端

用户端入口为 `/`，由 `index.html` 加载 `src/main.tsx`。九个一级导航、择校星标和题目训练详情均在同一个 React 单页中切换。

| 页面/功能 | 状态 | 前端路径 | 已实现功能 | 未实现或边界 | 代码依据 |
|---|---|---|---|---|---|
| 全局考试标签切换 | ✅ 已完成 | `/` 顶栏；设置页 | 选择“院校＋考试科目代码”标签并保存到 `localStorage`；切换后知识点、题目、真题和统计按标签过滤；历史作答不删除。 | 没有账号级云同步、多目标管理、学院/专业或考试代码拆分对象。 | `targetId`；`/api/targets` |
| ★ 择校信息中心 | ⚙️ 开发中 | `/` 顶栏星标 | 展示当前标签的院校、科目标签和备注，并提示以官方公告为准。 | 未实现招生简章、参考书目、分数线、招生人数、通知、来源和历史版本。 | `star` 分支；`targets.note` |
| 今日学习 | ⚙️ 开发中 | `/` 一级导航“今日学习” | 展示当前标签、自动届次、累计作答、第一道精品练习和“继续练习”。 | 无任务表、计划、日历、倒计时、院校通知、继续上次会话或规则推荐；当前更接近演示首页。 | `nav === '今日学习'` |
| 知识地图 | ⚙️ 开发中 | `/` 一级导航“知识地图” | 按考试标签显示已审核知识点；中栏切换知识点；显示概要、关联练习和作答数；可进入关联题。 | 不是层级知识树；无知识卡、公式、图形、推导、易错点、掌握度或参考书位置。 | `knowledgeSection()`；`GET /api/topics` |
| 真题 | ⚙️ 开发中 | `/` 一级导航“真题” | 对已审核且来源为 `TARGET_PAST_EXAM` 的题目支持按年份或知识点浏览，并显示空状态。 | 基线无已核验真题种子；无试卷对象、整卷考试、题号/分值与完整度。 | `past`、`years`、`yearMode` |
| 兄弟院校 | ⚙️ 开发中 | `/` 一级导航“兄弟院校” | 展示当前标签下来源类型为 `RELATED_PAST_EXAM` 的已发布题。 | 无兄弟院校关系、推荐理由、近 5 年约束或专门筛选；通常为空。 | `source_type === 'RELATED_PAST_EXAM'` |
| 精品练习 | ✅ 已完成 | `/` 一级导航“精品练习” | 展示当前标签下 `CURATED_EXERCISE` 已发布题；可按知识点进入知识地图并开始训练。 | 没有题集、专题、排序与推荐理由；完成度仅指当前简化题目列表。 | `source_type === 'CURATED_EXERCISE'` |
| 题目训练 | ✅ 已完成 | `/` 内联题目详情，无独立 URL | 显示题干、知识点、题型、难度；录入文本答案；查看参考答案和解析；按 0–3 自评；保存作答；允许重复练习。 | 无自动保存、退出恢复、客观判分、错因、收藏、错题本、公式渲染、图片题干或训练会话对象。 | `selectedQuestion` 分支；`POST /api/attempts` |
| AI 练习 | ❌ 仅规划未写代码 | `/` 一级导航“AI练习” | 只有“功能建设中”状态页。 | 无 AI 组卷、答疑、错题分析或模型调用。 | `nav === 'AI练习'` |
| 学习统计 | ⚙️ 开发中 | `/` 一级导航“学习统计” | 按当前考试标签统计作答次数、已练知识点和知识点自评均值；点击弱项行可回到知识地图。 | 无正确率、题型能力、学习时长、历史趋势、错因、样本可信度或能力指数；自评不代表判分。 | `GET /api/stats` |
| 在线论坛 | ❌ 仅规划未写代码 | `/` 一级导航“在线论坛” | 只有规划中占位页。 | 无帖子、评论、点赞、收藏、举报或治理。 | `nav === '在线论坛'` |
| 设置 | ⚙️ 开发中 | `/` 一级导航“设置” | 可切换目标考试标签；说明记录属于本地演示用户。 | 无账户、通知、学习偏好、AI 设置、数据隐私或导出删除。 | `nav === '设置'` |
| 两端自动刷新 | ✅ 已完成 | `/` 与 `/admin/` | 内容或活动写入后提升版本号；两端约每 2 秒轮询 `/api/versions`，版本变化后刷新数据。 | 不是 WebSocket/推送；轮询错误被静默忽略到下一次显式刷新。 | `change_versions`；两个前端的 `setInterval` |
| 做题在线心跳 | ✅ 已完成 | `/` 题目详情 | 打开题目时立即发送心跳，之后每 10 秒发送；退出题目发送 `active=false`；管理员按最近 30 秒统计。 | 会话仅在 `sessionStorage`，无用户身份、设备信息或清理任务。 | `/api/study-presence` |

## 1.3 已落地业务规则

### 1.3.1 知识点分类体系

- 当前数据库结构是 `subject → module → topic` 的平面字段组合，`topics` 表没有父子层级字段。
- 每个知识点必须绑定至少一个考试标签，关系存入 `topic_target_tags`。
- 用户端只展示 `review_status='APPROVED'` 的知识点。
- 知识点发布前必须有 HTTPS 来源链接和至少一个考试标签。
- 编辑知识点会将知识点改回 `DRAFT`，并将其所有已发布关联题目改回 `DRAFT`，审核备注写为“关联知识点已修改，需重新审核”。

### 1.3.2 题型分类与难度

- `question_type` 是必填字符串，但没有枚举约束；演示数据出现“计算题”“简答题”“图形分析题”。
- `difficulty` 由 Pydantic 限制为 1–5。
- `source_type` 是后端硬编码枚举：`TARGET_PAST_EXAM`、`RELATED_PAST_EXAM`、`CURATED_EXERCISE`、`AI_GENERATED`。
- 目标院校真题和兄弟院校真题必须填写 `exam_year` 与 HTTPS `source_url`；发布时还要求 `source_verified=true`。

### 1.3.3 院校科目标签规则

- 当前 `targets` 在产品层被简化为考试标签：`school + exam_label + note`。
- ID 由后端生成，格式为 `exam-` 加 UUID 十六进制字符串。
- 考研届次由后端按中国标准时间当前年份加一计算，不接受前端传入。
- 创建和更新时按 `school + exam_label` 做应用层重复检查；数据库没有对应组合唯一索引。
- 知识点可绑定多个考试标签；题目只绑定一个考试标签。
- 题目发布时，其知识点必须也绑定同一个考试标签，否则返回 422。

### 1.3.4 两端数据同步逻辑

- 管理员与用户端共用同一个 SQLite 数据库，没有复制数据源。
- 管理员新增/编辑/审核内容时提升 `change_versions.content`；用户作答/心跳时提升 `change_versions.activity`。
- 用户端约每 2 秒只比较内容版本并刷新；管理员端约每 2 秒比较内容和活动版本并刷新。
- 用户端公开题目查询要求题目和知识点都为 `APPROVED`，并要求 `topic_target_tags` 中存在题目标签与知识点的匹配关系。
- 编辑已发布题目会自动变为草稿，并从用户端公开查询中消失。
- 用户切换考试标签只改变筛选和统计范围，不修改 `attempts` 历史记录。

### 1.3.5 权限规则

- 当前没有登录、Token、Cookie Session、管理员账号或 RBAC。
- 所有用户数据固定写入 `user_id='local-demo'`。
- 管理员 API 仅通过请求客户端 IP 是否为 `127.0.0.1`、`::1` 或测试客户端进行限制；`TrustedHostMiddleware` 只允许 `127.0.0.1`、`localhost`、`testserver`。
- CORS 只允许 `http://127.0.0.1:5173` 和 `http://localhost:5173`。
- 该限制是本地开发防护，不是正式鉴权；管理员接口不得暴露到局域网或公网。

---

# 二、系统整体技术架构

## 2.1 分层结构

| 层 | 已用技术 | 已实现职责 | 主要代码 |
|---|---|---|---|
| 用户端前端层 | React 19、TypeScript 5.9、Vite 7、原生 CSS、浏览器 Fetch API | 三栏工作台、九模块导航、考试标签切换、知识/题目浏览、训练、自评、统计和状态页 | `index.html`、`src/main.tsx`、`src/style.css` |
| 管理员前端层 | React 19、TypeScript 5.9、Vite 多入口、原生 CSS | 总览、考试标签、知识目录、题目中心、图片队列、人工审核 | `admin/index.html`、`src/admin.tsx`、`src/admin.css` |
| 后端层 | Python、FastAPI、Pydantic、Starlette、Uvicorn | 26 个业务路由、输入校验、SQLite 读写、本机管理员限制、文件上传、统计、AI Provider 调度 | `api/main.py` |
| 数据层 | SQLite、本地文件系统 | 8 张业务表；`data/platform.db` 保存结构化数据；`data/question-intakes/` 保存上传图片 | `api/main.py` 初始化与增量 `ALTER TABLE` |
| AI 能力层 | Python `Protocol`、动态模块加载、Pydantic 候选模型 | 预留题目图片识别 Provider；将模型输出限制为管理员候选草稿 | `api/recognition.py` |
| 构建与检查 | pnpm、TypeScript、Vite、GitHub Actions、Python `unittest` | 前端安装/构建、Python 语法检查、后端回归测试 | `package.json`、`.github/workflows/ci.yml`、`api/test_targets.py` |

## 2.2 调用关系与数据流

```text
浏览器用户端 /                         浏览器管理员端 /admin/
          │ JSON over HTTP                          │ JSON / Base64 image
          └──────────────────┬───────────────────────┘
                             ↓
                    FastAPI api/main.py
                ┌────────────┼─────────────┐
                ↓            ↓             ↓
          SQLite 事实源   本地图片目录   RecognitionProvider
          platform.db    question-intakes  （当前未配置）
                │            │             │
                └────────────┴─────────────┘
                             ↓
                  管理员人工审核/发布
                             ↓
                 change_versions.content + 1
                             ↓
                两端约 2 秒轮询后刷新
```

主要数据流：

1. 管理员维护考试标签、知识点、题目或上传截图。
2. 新内容先进入 `DRAFT` 或 `AWAITING_PROVIDER`；不会因上传或 AI 输出自动公开。
3. 知识点和题目经管理员审核后变为 `APPROVED`。
4. 用户端只查询已发布且标签关系一致的知识点和题目。
5. 用户提交答案与 0–3 自评后写入 `attempts`，统计从原始作答即时聚合。
6. 题目训练页发送心跳到 `study_presence`；管理员总览按最近 30 秒记录计算活跃会话。

## 2.3 鉴权、返回格式与错误处理

| 项目 | 当前实现 |
|---|---|
| 用户鉴权 | 无；所有作答使用固定用户 `local-demo`。 |
| 管理员鉴权 | 无账号/密码/RBAC；仅检查客户端是否为本机回环地址，并限制 Host。 |
| API 成功返回 | 没有统一响应包络；按接口直接返回列表或对象，如 `{ "id": ..., "saved": true }`。 |
| API 错误返回 | 使用 `HTTPException`，FastAPI 默认输出 `{ "detail": "错误说明" }`；常见状态为 403、404、409、422、501、502、503。 |
| 全局异常 | 没有自定义全局异常处理器；未捕获异常使用 FastAPI 默认 500。 |
| 前端错误 | 管理员端尝试读取 `detail` 并展示；用户端将 GET/POST 错误分别简化为“读取失败/保存失败”，页面显示本地服务连接或保存失败提示。 |
| API 契约 | Pydantic 模型只在后端定义；前端 TypeScript 类型手写，没有 OpenAPI 生成或共享 contracts 包。 |

---

# 三、数据库表结构全集

数据库为 SQLite。连接时执行 `PRAGMA foreign_keys=ON`。基线通过 `CREATE TABLE IF NOT EXISTS` 与导入时的增量 `ALTER TABLE` 维护结构，没有独立 migration 文件或版本表。

## 3.1 `targets` — 考试标签及遗留字段

| 字段 | 类型/约束 | 含义 |
|---|---|---|
| `id` | TEXT，主键 | 稳定考试标签 ID；新建时为 `exam-<uuid>`；演示数据为 `demo-*`。 |
| `school` | TEXT，NOT NULL | 院校名称。 |
| `major` | TEXT，NOT NULL | 遗留专业字段；当前新标签写空字符串，公开接口不返回。 |
| `exam_subject` | TEXT，NOT NULL | 遗留科目字段；当前新标签写入与 `exam_label` 相同内容。 |
| `target_year` | INTEGER，NOT NULL | 遗留存储届次；公开接口实际返回动态计算的当前中国年份加一。 |
| `verified` | INTEGER，NOT NULL，默认 0 | 遗留核验标记；当前标签流程不再使用。 |
| `college` | TEXT，NOT NULL，默认 `''` | 增量迁移遗留学院字段；当前流程不使用。 |
| `exam_code` | TEXT，NOT NULL，默认 `''` | 增量迁移遗留考试代码字段；当前已合并到 `exam_label`。 |
| `exam_label` | TEXT，NOT NULL，默认 `''` | 当前“考试科目代码及名称”标签，如“834 经济学”。 |
| `note` | TEXT，NOT NULL，默认 `''` | 标签备注；明确不等于官方招生信息。 |
| `source_url` | TEXT，NOT NULL，默认 `''` | 遗留来源字段；当前标签接口不使用。 |
| `source_checked_at` | TEXT，可空 | 遗留来源核验时间；当前标签接口不使用。 |
| `updated_at` | TEXT，可空 | 最近更新时间；新建/更新标签写 UTC ISO 8601。 |

- 索引：主键自动索引；没有 `school + exam_label` 唯一索引。
- 外键：无。
- 关联：被 `questions.target_id` 与 `topic_target_tags.target_id` 引用。

## 3.2 `topics` — 知识目录

| 字段 | 类型/约束 | 含义 |
|---|---|---|
| `id` | TEXT，主键 | 知识点 ID，前端录入，后端限制为字母/数字/连字符。 |
| `subject` | TEXT，NOT NULL | 科目，如微观经济学。 |
| `module` | TEXT，NOT NULL | 模块，如消费者理论。 |
| `name` | TEXT，NOT NULL | 知识点名称。 |
| `summary` | TEXT，NOT NULL | 知识概要。 |
| `source_name` | TEXT，NOT NULL，默认“演示内容” | 来源名称。 |
| `source_url` | TEXT，NOT NULL，默认 `''` | HTTPS 来源链接；审核发布前必填。 |
| `review_status` | TEXT，NOT NULL，默认 `APPROVED` | `DRAFT` 或 `APPROVED`；旧数据迁移默认已发布。 |
| `updated_at` | TEXT，可空 | 最近更新时间，UTC ISO 8601。 |

- 索引：主键自动索引；无额外索引。
- 外键：无。
- 关联：被 `questions.topic_id`、`topic_target_tags.topic_id` 引用。

## 3.3 `questions` — 统一题目表

| 字段 | 类型/约束 | 含义 |
|---|---|---|
| `id` | TEXT，主键 | 题目稳定 ID。 |
| `target_id` | TEXT，NOT NULL，外键 | 绑定一个考试标签，引用 `targets.id`。 |
| `topic_id` | TEXT，NOT NULL，外键 | 绑定一个知识点，引用 `topics.id`。 |
| `source_type` | TEXT，NOT NULL | 题目栏目/来源类型；由后端集合校验四种值。 |
| `source_name` | TEXT，NOT NULL | 来源名称。 |
| `question_type` | TEXT，NOT NULL | 题型，自由文本。 |
| `difficulty` | INTEGER，NOT NULL | 难度 1–5。 |
| `stem` | TEXT，NOT NULL | 题干。 |
| `answer` | TEXT，NOT NULL | 参考答案。 |
| `analysis` | TEXT，NOT NULL | 解析。 |
| `review_status` | TEXT，NOT NULL，默认 `DRAFT` | `DRAFT`、`APPROVED` 或 `REJECTED`。 |
| `catalog_number` | TEXT，可空；唯一索引 | 管理编号，自动形如 `Q-000001`，也可手填。 |
| `exam_year` | INTEGER，可空 | 真题年份。 |
| `source_url` | TEXT，NOT NULL，默认 `''` | HTTPS 来源链接。 |
| `source_verified` | INTEGER，NOT NULL，默认 0 | 是否人工核对来源与图片。 |
| `intake_id` | TEXT，可空 | 逻辑关联 `question_intakes.id`，数据库未声明外键。 |
| `reviewed_at` | TEXT，可空 | 最近审核时间，UTC ISO 8601。 |
| `review_note` | TEXT，NOT NULL，默认 `''` | 审核备注或退回原因。 |
| `updated_at` | TEXT，可空 | 最近更新时间，UTC ISO 8601。 |

- 索引：主键自动索引；显式唯一索引 `questions_catalog_number_unique(catalog_number)`。
- 外键：`target_id → targets.id`；`topic_id → topics.id`。
- 关联：被 `attempts.question_id` 引用；`intake_id` 只有应用层存在性校验。

## 3.4 `attempts` — 用户作答

| 字段 | 类型/约束 | 含义 |
|---|---|---|
| `id` | INTEGER，主键，自增 | 作答记录 ID。 |
| `user_id` | TEXT，NOT NULL | 用户 ID；当前固定为 `local-demo`。 |
| `question_id` | TEXT，NOT NULL，外键 | 题目 ID，引用 `questions.id`。 |
| `answer_text` | TEXT，NOT NULL | 用户文本答案。 |
| `self_rating` | INTEGER，NOT NULL | 用户自评 0–3；Pydantic 校验范围。 |
| `created_at` | TEXT，NOT NULL | 保存时间，UTC ISO 8601。 |

- 索引：主键；无 `user_id`、`question_id` 或时间索引。
- 外键：`question_id → questions.id`。
- 关联：统计接口联表 `questions`、`topics` 即时聚合。

## 3.5 `change_versions` — 轮询版本号

| 字段 | 类型/约束 | 含义 |
|---|---|---|
| `scope` | TEXT，主键 | 版本范围；当前固定为 `content`、`activity`。 |
| `version` | INTEGER，NOT NULL，默认 0 | 每次相关写操作递增。 |

- 索引：主键。
- 外键/关联：无外键；两端轮询读取。

## 3.6 `study_presence` — 做题在线心跳

| 字段 | 类型/约束 | 含义 |
|---|---|---|
| `session_id` | TEXT，主键 | 浏览器 `sessionStorage` 会话 UUID。 |
| `active` | INTEGER，NOT NULL | 是否正在题目训练页。 |
| `last_seen` | TEXT，NOT NULL | 最近心跳时间，UTC ISO 8601。 |

- 索引：主键；无 `active/last_seen` 索引。
- 外键：无。
- 关联：管理员统计查询最近 30 秒 `active=1` 的记录。

## 3.7 `question_intakes` — 题目图片上传队列

| 字段 | 类型/约束 | 含义 |
|---|---|---|
| `id` | TEXT，主键 | UUID。 |
| `original_name` | TEXT，NOT NULL | 原始文件名，经 `Path(...).name` 去除路径。 |
| `stored_name` | TEXT，NOT NULL | 本地存储文件名，为 UUID 加扩展名。 |
| `mime_type` | TEXT，NOT NULL | `image/png`、`image/jpeg` 或 `image/webp`。 |
| `sha256` | TEXT，NOT NULL | 图片内容 SHA-256；当前仅记录，不阻止重复。 |
| `status` | TEXT，NOT NULL | 已见状态：`AWAITING_PROVIDER`、`AI_DRAFT`、`DRAFT_LINKED`、`REVIEWED`。 |
| `created_at` | TEXT，NOT NULL | 上传时间，UTC ISO 8601。 |
| `recognition_json` | TEXT，可空 | AI 识别候选 JSON 文本。 |

- 索引：主键；`sha256` 无唯一索引。
- 外键：无。
- 关联：`questions.intake_id` 为应用层逻辑关联。

## 3.8 `topic_target_tags` — 知识点与考试标签多对多关系

| 字段 | 类型/约束 | 含义 |
|---|---|---|
| `topic_id` | TEXT，NOT NULL，复合主键，外键 | 引用 `topics.id`。 |
| `target_id` | TEXT，NOT NULL，复合主键，外键 | 引用 `targets.id`。 |

- 主键：`(topic_id, target_id)`，同时保证同一关系不重复。
- 外键：`topic_id → topics.id`；`target_id → targets.id`。
- 关联：公开题目查询用此表强制题目标签与知识点适用标签一致。

---

# 四、后端接口清单

以下为 26 个业务接口；FastAPI 自动生成的 `/docs`、`/redoc`、`/openapi.json` 不计入业务接口数量。所有接口均定义于 `api/main.py`。

| # | 方法与路径 | 核心请求参数 | 返回结构 | 对应功能 | 后端依据 |
|---:|---|---|---|---|---|
| 1 | `GET /api/health` | 无 | `{ok: true, mode: "local-development"}` | 本地服务健康标识 | `health()` |
| 2 | `GET /api/versions` | 无 | `{content: number, activity: number}` | 两端轮询版本 | `versions()` |
| 3 | `GET /api/targets` | 无 | `Target[]`：`id, school, exam_label, note, target_year` | 获取考试标签；届次动态计算 | `targets()` |
| 4 | `POST /api/admin/targets` | JSON：`school, exam_label, note` | `{id, target_year}` | 新增考试标签 | `create_target()` |
| 5 | `PUT /api/admin/targets/{target_id}` | 路径 ID；同上 JSON | `{id, target_year}` | 编辑考试标签 | `update_target()` |
| 6 | `GET /api/topics` | 可选查询 `target_id` | 已审核 Topic 数组，附 `target_ids[]` | 用户端知识目录 | `topics()` |
| 7 | `GET /api/admin/topics` | 无 | 全部 Topic 数组，附 `target_ids[]` | 管理员知识目录 | `admin_topics()` |
| 8 | `POST /api/admin/topics` | `id, subject, module, name, summary, source_name, source_url, target_ids[]` | `{id, review_status:"DRAFT"}` | 新建知识点草稿 | `create_topic()` |
| 9 | `PUT /api/admin/topics/{topic_id}` | 路径 ID；完整 Topic JSON | `{id, review_status:"DRAFT"}` | 编辑知识点并撤回关联题目审核 | `update_topic()` |
| 10 | `POST /api/admin/topics/{topic_id}/approve` | 路径 ID | `{id, review_status:"APPROVED"}` | 审核发布知识点 | `approve_topic()` |
| 11 | `GET /api/questions` | 可选查询 `target_id` | 已发布且标签匹配的 Question 数组 | 用户端公开题库 | `questions()` |
| 12 | `GET /api/admin/questions` | 可选 `target_id, exam_year, topic_id, source_type, review_status` | Question 数组 | 管理员题目列表/筛选 | `admin_questions()` |
| 13 | `POST /api/attempts` | `question_id, answer_text, self_rating(0–3)` | `{id, saved:true}` | 保存本地演示用户作答 | `create_attempt()` |
| 14 | `GET /api/attempts` | 无 | `local-demo` 的 Attempt 数组，ID 倒序 | 获取历史作答 | `attempts()` |
| 15 | `GET /api/stats` | 可选查询 `target_id` | `{attempt_count, topic_stats[], method}` | 用户端知识点自评统计 | `stats()` |
| 16 | `POST /api/study-presence` | `session_id, active` | `{saved:true}` | 写入/更新训练心跳 | `study_presence()` |
| 17 | `GET /api/admin/stats` | 无 | `{active_training_sessions, attempt_count, published_questions, difficulty_stats[], correct_rate:null, method}` | 管理员总览统计 | `admin_stats()` |
| 18 | `POST /api/admin/questions` | 完整 `QuestionIn`；`catalog_number` 可空 | `{id, catalog_number, review_status:"DRAFT"}` | 新建题目草稿 | `create_question()` |
| 19 | `PUT /api/admin/questions/{question_id}` | 路径 ID；完整 `QuestionIn` | `{id, review_status:"DRAFT"}` | 编辑题目并重新审核 | `update_question()` |
| 20 | `POST /api/admin/questions/{question_id}/review` | `decision: APPROVED/REJECTED, note` | `{id, review_status}` | 审核发布或退回 | `review_question()` |
| 21 | `POST /api/admin/questions/{question_id}/approve` | 路径 ID | 同审核通过结果 | 审核通过兼容接口 | `approve_question()` |
| 22 | `POST /api/admin/intakes` | `file_name, mime_type, base64_data` | `{id, file_name, status:"AWAITING_PROVIDER"}` | 上传题目图片 | `upload_intake()` |
| 23 | `GET /api/admin/intakes` | 无 | `id, original_name, mime_type, status, created_at` 数组 | 图片队列 | `list_intakes()` |
| 24 | `GET /api/admin/intakes/{intake_id}/image` | 路径 ID | 原始图片二进制 `FileResponse` | 查看上传原图 | `intake_image()` |
| 25 | `POST /api/admin/intakes/{intake_id}/recognize` | 路径 ID | 已配置时 `{id,status:"AI_DRAFT",suggestions[]}`；未配置 501 | 单张图片识别 | `recognize_intake()` |
| 26 | `POST /api/admin/intakes/recognize-batch` | `intake_ids[]`，1–50 | 单张识别结果数组；未配置 501 | 批量图片识别 | `recognize_batch()` |

## 4.1 主要校验与错误状态

- `403`：管理员接口不是从回环地址访问。
- `404`：目标对象不存在，或题目不满足公开作答条件。
- `409`：考试标签重复、题目/知识点 ID 重复、管理编号重复。
- `422`：Pydantic 字段不合法、来源链接非 HTTPS、真题缺年份/来源、标签关系不一致、审核条件不完整、图片格式不符等。
- `501`：识别 Provider 未配置。
- `502`：识别 Provider 执行失败。
- `503`：识别 Provider 配置字符串或工厂无效。

---

# 五、项目目录结构

审计基线下的源码目录如下；本次交付会新增 `docs/PROJECT_STATUS_AUDIT.md`。`data/`、`.venv/`、`node_modules/`、`dist/` 为 Git 忽略内容，不属于审计基线。

```text
E:\经济学考研学习平台
├─ .github/
│  ├─ workflows/
│  │  └─ ci.yml                    # main/PR 前端构建与后端测试
│  └─ pull_request_template.md      # PR 验证与边界模板
├─ admin/
│  └─ index.html                    # 管理员端 Vite HTML 入口
├─ api/
│  ├─ main.py                       # 数据库初始化、增量迁移、26 个 API、文件上传与统计
│  ├─ recognition.py                # AI 识图候选模型与 Provider 协议
│  ├─ requirements.txt              # FastAPI、Uvicorn、httpx2
│  └─ test_targets.py               # 6 个 unittest 回归测试方法
├─ src/
│  ├─ main.tsx                      # 用户端单页应用
│  ├─ admin.tsx                     # 管理员端单页应用
│  ├─ style.css                     # 用户端及共享样式
│  ├─ admin.css                     # 管理员端补充样式
│  └─ vite-env.d.ts                 # Vite 类型声明
├─ docs/
│  └─ PROJECT_STATUS_AUDIT.md        # 本次新增审计文档
├─ .gitignore                       # 忽略运行数据、依赖、构建产物和本地环境
├─ AGENTS.md                        # AI Coding 工作约定
├─ CONTRIBUTING.md                  # GitHub Flow、提交与验证规则
├─ PRODUCT_CONTEXT.md               # 产品与工程规则主文档（SSOT）
├─ PRODUCT.md                       # 早期产品概念文档
├─ README.md                        # 当前可运行切片、运行方式和边界
├─ index.html                       # 用户端 Vite HTML 入口
├─ package.json                     # 前端脚本与依赖
├─ pnpm-lock.yaml                   # pnpm 锁文件
├─ pnpm-workspace.yaml              # pnpm 工作区配置
├─ tsconfig.json                    # TypeScript 配置
└─ vite.config.ts                   # 用户端/管理员端双入口构建配置
```

## 5.1 核心文件职责

| 文件 | 作用 |
|---|---|
| `PRODUCT_CONTEXT.md` | 产品规则主文档；包含长期 IA、领域约束、MVP 与 AI 边界，不能将其中规划直接视为已实现。 |
| `CONTRIBUTING.md` | 规定从最新 `main` 建短期分支、PR 合并、最低构建检查与演示数据边界。 |
| `AGENTS.md` | 要求修改前阅读产品规则和现有代码、保留数据、完成验证、不得公开本地管理员接口。 |
| `src/main.tsx` | 用户端全部状态、导航、数据请求、2 秒轮询、训练心跳、作答与统计展示。 |
| `src/admin.tsx` | 管理端四工作区、CRUD 表单、筛选、上传、人工审核和总览。 |
| `api/main.py` | 当前后端单体入口；包含数据库建表/增量迁移、演示种子、校验模型、路由和业务规则。 |
| `api/recognition.py` | 只定义 AI 识图边界；通过 `ECON_RECOGNITION_PROVIDER=module:factory` 动态加载外部适配器。 |
| `api/test_targets.py` | 覆盖旧数据迁移、三字段标签、管理员本机限制、审核发布、心跳统计、标签一致性和图片队列。 |
| `.github/workflows/ci.yml` | PR/main 上执行前端 frozen install + build，以及 Python 3.12 语法检查、依赖安装和 unittest。 |

---

# 六、AI 能力对接现状

## 6.1 已接入、已预留与未实现

| AI 能力 | 状态 | 当前代码事实 |
|---|---|---|
| 题目图片上传与原图保存 | ✅ 已完成（非 AI） | 图片可上传、校验、落盘、查看并关联人工录题。 |
| 图片识别 Provider 抽象 | ✅ 已完成（接口层） | `RecognitionProvider.recognize(image_bytes, mime_type)` 协议已定义。 |
| 单张/批量识别 API | ⚙️ 开发中 | 路由已写；未配置 Provider 时返回 501；没有仓库内真实实现。 |
| AI 识别候选结构 | ✅ 已完成（数据契约） | `RecognitionCandidate` 含题干、科目、难度、答案、解析、题型、置信度说明。 |
| AI 结果人工审核隔离 | ✅ 已完成（后端状态规则） | 识别结果只写 `question_intakes.recognition_json` 和 `AI_DRAFT`，不会自动生成已发布题。 |
| 管理端触发/查看识别结果 | ❌ 仅接口预留 | 管理端只提供上传、查看原图和人工录题，没有“识别”按钮或候选结果面板。 |
| OCR、公式转 LaTeX、图表识别 | ❌ 未接入 | 没有模型、SDK、公式字段或图表坐标数据结构。 |
| 自动知识点匹配 | ❌ 未接入 | 题目录入由管理员手选 `topic_id`；AI 候选结构甚至没有 `topic_id`。 |
| AI 参考答案/解析生成 | ❌ 未接入 | 候选结构有 `answer/analysis` 字段，但无真实调用实现。 |
| AI 组卷、答疑、错题分析 | ❌ 仅产品占位 | 用户端只有“功能建设中”页面，无接口、表或服务。 |
| RAG/向量检索 | ❌ 未写代码 | 无向量库、Embedding、知识库索引或引用格式实现。 |

## 6.2 预留调用方式

环境变量：

```text
ECON_RECOGNITION_PROVIDER=模块名:工厂函数名
```

动态加载流程：

```text
configured_provider()
  → import_module(module_name)
  → getattr(module, factory_name)
  → factory()
  → RecognitionProvider
```

Provider 输入：

```python
recognize(image_bytes: bytes, mime_type: str) -> list[RecognitionCandidate]
```

候选返回字段：

```json
{
  "stem": "题干，必填",
  "subject": "科目，可空",
  "difficulty": 1,
  "answer": "参考答案，可空",
  "analysis": "解析，可空",
  "question_type": "题型，可空",
  "confidence_note": "置信度或人工核对说明，可空"
}
```

接口输出：

```json
{
  "id": "intake UUID",
  "status": "AI_DRAFT",
  "suggestions": [/* RecognitionCandidate[] */]
}
```

关键边界：

- API Key、供应商、模型名、模型版本、提示词、超时、重试和费用均未在仓库实现。
- Provider 由外部本地模块提供，不属于当前 Git 基线。
- `recognition_json` 只保存候选结果；题目仍需管理员另行录入/编辑并审核。
- AI 输出不会直接进入公开题库。

## 6.3 对应代码路径

| 路径 | 作用 |
|---|---|
| `api/recognition.py` | `RecognitionCandidate`、`RecognitionProvider`、`configured_provider()`。 |
| `api/main.py` | 单张/批量识别路由、状态写入、异常转 501/502/503。 |
| `src/admin.tsx` | 图片上传、原图查看与人工录题；没有模型触发和结果展示。 |
| `src/main.tsx` | AI 练习占位页。 |

---

# 七、代码自查：冗余点、风险点与已知问题

## 7.1 重复逻辑、冗余字段与依赖现状

| 类型 | 代码现状 |
|---|---|
| 遗留字段 | `targets` 仍保留 `major`、`exam_subject`、`target_year`、`verified`、`college`、`exam_code`、`source_url`、`source_checked_at`；当前三字段标签接口不再使用其中多数，保留原因是增量迁移和历史数据兼容。 |
| 双重届次来源 | `targets.target_year` 仍存储，但公开接口忽略其值并动态返回中国当前年份加一；管理员前端提示则使用浏览器本地 `new Date().getFullYear()+1`。 |
| 前后端类型重复 | TypeScript 手写 `Target/Topic/Question` 类型，后端另有 Pydantic 模型，没有共享契约或生成流程。 |
| 请求逻辑重复 | 用户端有 `get/post`，管理员端另写通用 `request`；错误文案与返回解析行为不同。 |
| 筛选重复 | 后端 `GET /api/admin/questions` 支持查询筛选，但管理员页面加载全部题目后再次在浏览器内筛选。 |
| 审核接口重复 | 通用 `/review` 已支持 `APPROVED`，另保留 `/approve` 兼容接口。 |
| 依赖现状 | 前端依赖均在源码/构建链使用。`api/requirements.txt` 的 `httpx2` 不被业务源码直接导入，测试通过 FastAPI `TestClient` 间接需要兼容的 `httpx` 实现；当前文件未说明为何使用 `httpx2` 名称。 |
| 未使用表/字段结论 | 8 张表均有代码读写或迁移用途；没有证据表明存在完全未使用的整张表。`recognition_json` 只由后端写入，当前 UI 不读取。 |

## 7.2 临时实现与风险点

| 风险 | 代码事实与影响 |
|---|---|
| 无正式认证授权 | 管理员端没有身份认证、RBAC 或审计，只按客户端回环 IP 限制；若改变监听/代理方式或错误部署，不能视为安全边界。 |
| 固定演示用户 | 所有作答属于 `local-demo`，不同浏览器/人员共享同一数据库时数据混合。 |
| 导入即迁移/播种 | `api/main.py` 导入时创建目录、建表、增量 `ALTER TABLE` 并可能写演示种子；没有可回滚 migration，也没有 schema 版本。 |
| SQLite 并发限制 | 所有请求直接打开 SQLite 连接；上传、编号生成、审核与轮询在并发增加时可能遇到锁竞争。 |
| 标签唯一性竞态 | `school + exam_label` 只做“先查再写”的应用层检查，没有数据库唯一索引；并发创建可能产生重复标签。 |
| 管理编号竞态 | `next_number()` 扫描已有编号取最大值加一；并发创建可能冲突，最终依赖唯一索引返回 409。 |
| 文件与数据库非原子 | 图片先写本地文件，再插入数据库；数据库写入失败时可能留下孤儿文件。删除/清理流程也未实现。 |
| 图片安全校验有限 | 只校验 MIME、大小、魔数和少量结构；没有完整解码验证、恶意内容扫描、像素尺寸/解压炸弹限制或对象存储隔离。 |
| AI 同步阻塞 | 识别在请求线程内同步执行；批量接口逐个调用；无超时、重试、取消、队列或幂等机制，部分成功时没有批次事务。 |
| AI 可追溯性不足 | 未记录供应商、模型、版本、提示词、Token、费用、延迟、引用或错误详情；异常被统一转成通用 502。 |
| 轮询扩展性 | 两端每 2 秒轮询版本；单机演示可用，用户增多后会产生固定查询压力。 |
| 数据查询索引不足 | 作答统计、心跳统计及部分筛选字段没有专用索引；数据量增大后查询会退化。 |
| 状态字典无数据库约束 | `review_status`、`source_type`、`question_intakes.status` 主要靠应用代码维护，SQLite 表没有 CHECK 约束。 |
| `intake_id` 非外键 | 题目通过应用层校验截图存在，但数据库无法阻止未来出现悬空引用。 |
| 内容格式能力不足 | 题干、答案、解析都是纯文本；没有 LaTeX/KaTeX、Markdown、富文本、图形位置或无障碍描述。 |
| 无删除/恢复 | 考试标签、知识点、题目、上传文件均无删除、归档、下架和恢复接口。 |
| 前端自动保存缺失 | 用户作答只在最终保存时写入；刷新、关闭或网络异常会丢失尚未提交的答案。 |

## 7.3 已知功能与交互问题

| 问题 | 当前表现 | 依据 |
|---|---|---|
| AI 识别按钮缺失 | 虽然后端已有识别路由，管理端图片队列只能“查看原图/人工录题”，无法在 UI 发起识别或查看 `suggestions`。 | `src/admin.tsx` 未调用 `/recognize` |
| 批量识别仅 API | `/recognize-batch` 无前端入口，也没有批次进度与失败明细界面。 | `api/main.py` 与 UI 对比 |
| 正确率为空 | 管理端正确率始终显示“—”，因为系统只有主观自评，没有客观判分。 | `admin_stats.correct_rate=None` |
| 今日学习不是任务系统 | “继续练习”实际打开当前标签第一道精品练习，不是保存的学习任务或上次会话。 | `focus = visible.find(...)` |
| 真题页可能长期为空 | 用户端只显示审核通过且来源核验完整的 `TARGET_PAST_EXAM`；种子数据全部是演示精品练习。 | 种子数据与公开查询规则 |
| 兄弟院校不是关系推荐 | 页面仅按 `RELATED_PAST_EXAM` 过滤当前标签题目，没有学校关系和推荐原因。 | `src/main.tsx` |
| 知识地图不是树 | 中栏是知识点平面列表，没有章节树、父子节点或掌握度。 | `topics` 表与 `knowledgeSection()` |
| 题型可产生同义脏数据 | 管理员自由输入题型，后端不限制字典，可能出现同义不同名。 | `question_type: str` |
| 上传数量提示口径偏差 | 管理总览和队列标题使用 `intakes.length`，包含所有历史上传状态，不只“待识别”图片。 | `src/admin.tsx` 未按状态过滤 |
| 识别失败不落状态 | Provider 异常时返回 502，但 `question_intakes.status` 不更新为失败，也不保存错误原因。 | `recognize_intake()` |
| 拒绝题目不更新图片状态 | 关联截图的题目审核通过会把图片改为 `REVIEWED`，退回时没有对应状态迁移。 | `review_question()` |
| URL 状态不可分享 | 管理端工作区和用户端导航/题目详情均由内存状态控制，浏览器地址不体现当前页面或对象。 | 两个单页组件无路由库 |

## 7.4 本次验证记录

本节在文档提交前按本次实际执行结果填写；未执行或因环境受阻的检查将明确标注，不引用历史 PR 结果冒充本次通过。

| 检查 | 本次结果 |
|---|---|
| `pnpm install --frozen-lockfile` | 默认布局失败：E 盘为 exFAT，不支持 pnpm 符号链接。改用 pnpm 提示的 `node-linker=hoisted` 后，锁文件检查与 21 个依赖安装完成。 |
| `pnpm run build` | Codex 运行环境会在执行脚本前再次用默认链接布局检查依赖，因此该封装命令仍被 exFAT 阻止。随后直接执行同一脚本实际包含的 `tsc --noEmit` 与 `vite build`，二者均通过；Vite 构建 31 个模块并产出用户端、管理员端资源。未将受阻的封装命令写成通过。 |
| `python -m py_compile api/main.py api/recognition.py` | 通过。 |
| `python -m unittest discover -s api -p 'test_*.py'` | 未运行。新建的 Git 忽略虚拟环境无法安装 `fastapi>=0.115`：当前 pip 网络/索引连接异常，只返回最高 0.103.2；切换官方 PyPI 地址后结果相同。历史 PR 的“6 项通过”不作为本次本地通过。 |
| 文档范围检查 | 提交前执行；目标分支只允许新增 `docs/PROJECT_STATUS_AUDIT.md`。 |
| 与 `main` 冲突检查 | PR 创建后执行。 |

---

# 附录 A：PRD—代码映射

| PRD/规则主题 | PRD 位置 | 基线代码映射 | 现状判断 |
|---|---|---|---|
| 三栏式用户工作台 | `PRODUCT_CONTEXT.md` 3.3、4 | `src/main.tsx` 的顶栏、`rail`、`catalog`、`workspace` | ✅ 已有壳层实现 |
| 用户端九模块导航 | 4.2、5 | `NAV` 常量与九个条件渲染分支 | ⚙️ 导航齐全，多个模块仅部分或占位 |
| 独立管理员端 | 6 | `admin/index.html`、`src/admin.tsx` | ✅ 已有四工作区 |
| 考试标签库三字段 | 6.2、V0.4 决策 | `TargetIn`、考试标签表单、`current_exam_year()` | ✅ 已实现 |
| 知识点按考试标签匹配 | 6.3、V0.4 决策 | `topic_target_tags`、`TopicIn.target_ids`、公开查询 | ✅ 已实现 |
| 统一 Question 底座 | 7、8 | 单一 `questions` 表，通过 `source_type` 区分栏目 | ✅ 简化实现 |
| 真题完整试卷模型 | 5.3、6.5、10 | 只有题目级 `exam_year/source_type` | ❌ 无 PastExam/Paper 及关联表 |
| 题型与知识双分类 | 12 | `topic_id + question_type` | ⚙️ 已有双字段，题型无字典/能力对象 |
| 训练—作答—统计回流 | 14.1 | `attempts`、`/api/stats`、统计跳知识地图 | ⚙️ 基础自评闭环已实现，无错题/复练对象 |
| 内容来源与审核 | 8、17 | `source_name/source_url/source_verified/review_status` 与审核路由 | ✅ 当前题目/知识点范围已实现 |
| 用户账号与目标配置 | 14.2、21 | `localStorage targetId`、固定 `local-demo` | ❌ 正式账号未实现 |
| 管理员 RBAC 与审计 | 6.11、14.2、17.3 | 只有 `guard_admin` 本机限制 | ❌ 未实现 |
| 今日任务与通知 | 5.1、14 | 今日学习演示页，无任务/通知表 | ❌ 业务对象未实现 |
| 知识卡 | 5.2、13 | 知识点概要面板 | ❌ 无独立 KnowledgeCard 数据结构 |
| 兄弟院校 | 2.3、5.4 | `RELATED_PAST_EXAM` 过滤 | ⚙️ 只有栏目标签，无 SchoolRelation |
| 精品题集 | 5.5、6.6 | `CURATED_EXERCISE` 过滤 | ⚙️ 有题目栏目，无 QuestionSet |
| AI 练习 | 5.6、16 | 用户端占位；识图 Provider 与练习 AI 无直接闭环 | ❌ 组卷/答疑/错题分析未实现 |
| 学习统计与可信度 | 5.7、11 | 作答次数、知识点自评均值、方法说明 | ⚙️ 基础统计；无样本可信度/能力指数 |
| 在线论坛 | 5.8、14.4 | 状态占位页 | ❌ 未实现 |
| 公式与图形支持 | 15.4 | 题干/答案/解析纯文本 | ❌ 未实现 LaTeX/图形结构 |
| AI 内容人工审核 | 16.3、16.4 | `AI_DRAFT`、公开发布仍走人工审核规则 | ⚙️ 后端边界存在，真实 AI 未接入 |

# 附录 B：代码事实依据索引

| 事实 | 直接依据 |
|---|---|
| 8 张业务表 | `api/main.py` 的初始化脚本、增量字段迁移与 `topic_target_tags` 建表 |
| 26 个业务接口 | `api/main.py` 中 26 个 `@app.get/post/put` 装饰器 |
| 用户端九模块 | `src/main.tsx` 的 `NAV` 常量 |
| 管理端四工作区 | `src/admin.tsx` 的 `Section` 类型和导航数组 |
| 公开内容审核边界 | `questions()`、`topics()`、`review_question()`、`approve_topic()` |
| 本机管理员限制 | `TrustedHostMiddleware`、`guard_admin` |
| 两端约 2 秒同步 | 两个前端组件的 `/api/versions` 定时器 |
| 训练心跳 | 用户端 `study-presence` effect 与 `admin_stats()` 30 秒窗口 |
| AI 未实际接入 | `configured_provider()` 默认返回 `None`；仓库无 Provider 实现模块 |
| 演示数据边界 | `api/main.py` 种子数据、`README.md` 的演示声明 |

