# PDF 批量导题 V0.1：本地操作与数据规范

此工具是管理员在可信本地环境运行的命令行流程，不是公网 API。它不改变既有 `RecognitionProvider.recognize(image_bytes, mime_type)` 或识图接口，也不提供新的管理员批量 UI。任何模型输出、拆题边界、公式、图表归属及答案来源均为待审核草稿。

## 环境与边界

- Python 3.11+；安装 `api/requirements.txt`，其中 PDF 提取和页面渲染依赖 `pdfplumber`。通过仓库根目录运行 `python -m api.bulk_import.cli ...`。
- 输入仅支持 PDF。可复制文本优先本地提取；仅扫描/文字极少的页面才经既有视觉 Provider 识别。复杂公式、图片表格、答案标题变体无法保证自动识别正确；本地规则转换的公式及按纵向位置关联的图表会警告。
- `prepare` 默认 `--provider doubao`，用于现有视觉/拆题能力；纯文本 `retry` 默认 `--provider deepseek`，历史批量文字增强固定使用 DeepSeek。可选 `none`、`mock`、`doubao`、`deepseek`。**没有** `--allow-model-call` 时真实 Provider 只生成 `PENDING`，绝不发送资料或伪造答案。`--provider mock` 用于演练，生成的 `MOCK` 答案不能入库。真实题目调用前必须得到资料外发与费用许可。
- 真题须有来源名称、原 PDF、SHA-256、页码、年份和考试标签；`source_url` 可空，空值只提示 Warning，填写时须为有效 HTTPS URL。不得为了绕过校验将真题改标成原创资料。
- 不提交原 PDF、题图、`manifest.json`、`questions.jsonl`、`progress.json`、数据库或密钥。输出目录应放在仓库外，或保持在忽略目录内。不要将此本地管理员工具或演示版管理员 API 暴露到公网。

## 运行顺序（PowerShell 示例）

以下路径与标签 ID 仅为占位，先在现有管理员端确认考试标签和知识点 ID；试点样本由 Product Owner 指定。

```powershell
python -m api.bulk_import.cli prepare 'C:\sample\economics.pdf' --out 'C:\batches\econ-001' --source-name '某校经济学试卷' --source-kind TARGET_PAST_EXAM --target-id '实际标签ID' --exam-year 2024 --source-url 'https://实际来源页' --db 'C:\platform\platform.db' --provider none
python -m api.bulk_import.cli preview 'C:\batches\econ-001'
python -m api.bulk_import.cli validate 'C:\batches\econ-001' --db 'C:\platform\platform.db'
```

检查并人工修改 `questions.jsonl`（每行一个完整 JSON 对象），尤其核对题目数量与顺序、跨页、小问、`stem_raw` / `stem_latex`、图表资源、来源答案、来源证据、知识点、题型、难度。无原答案时保持 `source_answer.status=ABSENT`、`kind=NONE`、`text=""`。只有来源证据明确且人工核对后，才可设 `kind=OFFICIAL` 和 `human_verified=true`。不确定知识点时保持 `topic_id=null`，不要猜测。编辑后重新 `validate`；任何内容更改都会撤销原确认。

获许可并配置模型后，可仅重试指定题目的 AI 答案和缺失标签推荐：

```powershell
python -m api.bulk_import.cli retry 'C:\batches\econ-001' --item-key '实际item_key' --db 'C:\platform\platform.db' --provider deepseek --allow-model-call
python -m api.bulk_import.cli validate 'C:\batches\econ-001' --db 'C:\platform\platform.db'
python -m api.bulk_import.cli preview 'C:\batches\econ-001'
python -m api.bulk_import.cli confirm 'C:\batches\econ-001' --item-key '实际item_key'
python -m api.bulk_import.cli import 'C:\batches\econ-001' --db 'C:\platform\platform.db'
```

`confirm` 会展示单题并要求准确输入 `CONFIRM <item_key>`。只有校验通过、明确确认且确认后未被修改的题会入库；其余保持待处理。每题独立事务，失败记录在 `progress.json`，可改 JSON、重试、复核后再导入。重复运行采用稳定题目 ID，不覆盖已存在 Question；疑似重复只提示，不自动跳过。导入前请备份现有数据库和同目录的题目资源目录。

## 复用历史 PDF 候选（零 AI）

已有 `pdf_question_candidates` 时，不要重新解析整份 PDF。以下两个命令只读历史 SQLite；第二个命令写入**新建、原本为空**的本地批次目录，不写数据库、不调用模型，也不修改历史候选：

```powershell
python -m api.bulk_import.cli audit-legacy --db 'C:\platform\platform.db' --target-id '实际标签ID' --source-contains '834'
python -m api.bulk_import.cli normalize-legacy --db 'C:\platform\platform.db' --target-id '实际标签ID' --source-contains '834' --out 'C:\batches\legacy-834-001'
```

可重复传入 `--year 2023 --year 2022` 缩小年份范围。审计只打印年份、状态和完整率；每个转换批次只允许一份来源 PDF。转换复用同一个单题 Schema、校验器和指纹逻辑，产生 `manifest.json`、`questions.jsonl`、`progress.json`、`assets/`，另有 `pilot-manifest.json` 和使用同一 Schema 的 `pilot.jsonl`（16 条代表题）。批次保存原 PDF 副本，视觉候选只渲染其必要页：同时保留 OCR 坐标局部图和整页供人工核对，不重新 OCR 全书。输出位于 Git 忽略的 `data/` 或仓库外，绝不提交来源资料与真题文本。

历史资料的 `answer` 只映射为 `REFERENCE`，即使其 `analysis` 与 `answer` 相同也绝不当成独立 AI 答案或官方答案。AI 一律 `PENDING`；历史难度不论数值均清空待重新评估；题型只允许名词解释、选择/填空、简答题、论述题、计算题，未知值留空。`processing_meta.legacy_status` 记录七类初筛；`legacy_gate=BLOCKED` 的拆题、视觉、原件缺失候选不得直接重试模型或入库。已找到题目节标题但答案边界不可靠的记录保留 `NEED_AI_SPLIT`，不自动把来源答案分派给新题。局部裁剪未经过语义核验，视觉题的文本答案适配器仍禁止运行。

`pilot-manifest.json` 仅保存组别与候选定位，`pilot.jsonl` 为 8 条文本、5 条视觉、3 条反例的标准单题快照，不代表已经真实调用或通过审核。后续须人工对照 PDF，按需选择极少量题进行模型试验；未经 Product Owner 明确批准，不执行带 `--allow-model-call` 的命令，也不执行 `import`。人工修改 JSON 后运行同一 `validate`；只有处理门槛、独立 AI 答案、主知识点、固定题型和已评估难度满足校验，且逐题确认后才可能入 DRAFT。

### 历史候选的纯文本增强（独立输出，不入库）

人大 834 八题 A/B Pilot 后，Product Owner 指定纯文本答案和标签默认采用 `deepseek-flash`。以下入口只接受已有 `normalize-legacy` 的批次，读取历史 SQLite 中当前考试标签绑定的知识点；不再解析整份 PDF，不调用视觉、拆题或豆包文本任务。先执行无模型调用的预检，再由已获批的管理员显式开启真实调用：

```powershell
python -m api.bulk_import.cli enrich-legacy --source-batch 'C:\batches\legacy-834-001' --out 'C:\batches\legacy-834-text-001' --db 'C:\platform\platform.db' --plan-only
python -m api.bulk_import.cli enrich-legacy --source-batch 'C:\batches\legacy-834-001' --out 'C:\batches\legacy-834-text-001' --db 'C:\platform\platform.db' --allow-model-call
python -m api.bulk_import.cli report-legacy-enrichment 'C:\batches\legacy-834-text-001'
```

实际调用前须在后端环境配置 `DEEPSEEK_API_KEY`、`DEEPSEEK_MODEL=deepseek-flash`。一次仅运行一个进程，串行处理；每题答案与标签分别保存检查点，成功项续跑时不会再调用。无效 JSON 最多定向重试两次；明确 `OUTPUT_TRUNCATED` 不重复发送同样请求。HTTP 401/403 停止批次，429/暂时性 5xx/超时使用适配器已有的有限重试。中断后用同一命令、同一输出目录续跑；不要更换输入 JSONL 或模型。失败与中断时在途的任务默认不再自动重试；核对后方可显式加 `--retry-failed`。刚发出但尚未来得及保存结果的在途请求无法提供严格的外部 exactly-once 保证。

增强输出包括 `manifest.json`、`items/<item_key>.json`、`questions.jsonl`、`progress.json`、完成后的 `summary.json` 和 `review-sample.json`。最后一个命令仅从本地结果重建统计、重复题 Warning 和约 30 题抽检清单，不发模型请求。所有结果保留来源答案和历史标签快照；AI 答案只写 `ai_answer`，标签结果只写 `classification`，历史 SQLite 始终只读。`ANSWER_CONFLICT` 是保守的数值结果不一致候选警告，不代表模型或来源谁正确；未能自动比对的答案应进入人工核验范围。抽检清单不含完整长答案，人工审查须对照单题检查点和来源 PDF。输出目录须保持 Git 忽略，不得直接把增强批次当作已审核正式题库。

## 批次格式与字段映射

`manifest.json` 记录 PDF 文件名、SHA-256、页数、页错误、题数；`questions.jsonl` 使用 [单题 JSON Schema](../api/bulk_import/schema_v01.json)，每题包含 `schema_version: "0.1"`；`assets/` 保存原 PDF 副本和页面裁图；`progress.json` 保存单题状态、尝试数、人工确认摘要和入库 ID。四部分作为一个批次整体备份、传递或导出，不要只传 JSONL 后丢失资源。重新导入时用同一批次运行 `validate` → `confirm` → `import`，可被其他系统按同一 Schema 消费。不要手工修改 `item_key` 或原文件哈希来规避幂等保护。

| JSON 路径 | 正式 questions 字段或去向 |
| --- | --- |
| `source.kind/name/url/exam_year` | `source_type/source_name/source_url/exam_year` |
| `exam_scope.target_id` | `target_id`（一个考试标签） |
| `classification.topic_id/question_type/difficulty` | `topic_id/question_type/difficulty`（一个主知识点） |
| `content.stem_latex` | `stem`；原题、页码、图表及图片路径保存在 `import_meta_json` |
| `source_answer.text/analysis/kind` | `answer/analysis/source_answer_kind`；无来源答案时空字符串和 `NONE` |
| `ai_answer` | 独立的 `ai_answer_json`，从不写入 `answer` |
| `validation`、`processing_meta` | 重复警告及处理记录写入 `import_meta_json`；校验错误不入库 |
| 确认与审核 | 导入只写 `review_status=DRAFT`；原有人工审核流程后续单独操作 |

数据库迁移仅为 `questions` 增加 `source_answer_kind TEXT NOT NULL DEFAULT 'UNKNOWN'`、`ai_answer_json TEXT` 和 `import_meta_json TEXT`。已有题目保留不动，来源答案类型为 `UNKNOWN`。运行现有 FastAPI 时可自动执行幂等迁移；命令行首次正式导入也会执行。没有新增批次/单题数据库表，批次状态只在本地文件。现有管理员题目查询、编辑和审核端点保持原有 URL；本次没有新增 HTTP API。

## 模型配置与安全

文本任务支持豆包 Ark 与 DeepSeek 两个轻量适配器，共用 `answer_generation`（`answer`、`analysis`）和 `tag_recommendation`（现有 `topic_id`、固定题型、难度 1–5）契约。DeepSeek 不承担视觉或拆题；扫描页视觉仍复用现有 `ECON_RECOGNITION_PROVIDER`，不修改其契约。真实 Provider 默认关闭，必须显式添加 `--allow-model-call`。

| Provider | 必填环境变量 | 可选环境变量 | 默认 Base URL |
| --- | --- | --- | --- |
| 豆包 | `DOUBAO_ARK_API_KEY`, `DOUBAO_ARK_MODEL` | `DOUBAO_ARK_BASE_URL`, `DOUBAO_ARK_TIMEOUT_SECONDS`, `DOUBAO_ARK_RETRIES` | `https://ark.cn-beijing.volces.com/api/v3` |
| DeepSeek | `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL` | `DEEPSEEK_BASE_URL`, `DEEPSEEK_TIMEOUT_SECONDS`, `DEEPSEEK_RETRIES` | `https://api.deepseek.com` |

超时默认 30 秒；额外重试默认 2 次、最多 3 次，仅对 429、暂时性 5xx 与网络/超时错误重试；401/403 和 JSON 格式错误不重试。Base URL 必须为 HTTPS。两家费用估算均只使用运营者另行配置的 `{前缀}_INPUT_PRICE_PER_MILLION`、`{前缀}_OUTPUT_PRICE_PER_MILLION`、`{前缀}_PRICE_CURRENCY`（前缀分别为 `DOUBAO_ARK` 和 `DEEPSEEK`）；费率或 usage 缺失时 `estimated_cost=null`，不得当成免费。`processing_meta.model_runs` 统一记录 task、provider、model、tokens、duration_ms、attempts、estimated_cost、currency、脱敏 error。密钥仅从后端环境变量读取，不进入前端、JSONL、数据库、日志或 Git。

首轮文字 Pilot 中三次长答案均在旧的 2,000 输出 Token 上限处返回无效 JSON。现在两家共用的答案上限为 4,000，标签任务仍为 2,000；Prompt 和题干不因 Provider 改动。两家文本请求均显式发送 `response_format={"type":"json_object"}`，减少仅靠 Prompt 约束导致的格式错误。若 API 明确返回 `finish_reason=length`，记录 `OUTPUT_TRUNCATED`，不盲目重复调用。已生成的成功结果不应为此重跑。真实试验观察到豆包某些文本调用超过默认 30 秒；试验时可单独配置超时，不能把超时或无效 JSON 当成正确答案。

PowerShell 仅在本机当前会话设置，下面占位内容须由管理员在本机替换，不要发到聊天或提交：

```powershell
$env:DOUBAO_ARK_API_KEY = '在本机填入豆包密钥'
$env:DOUBAO_ARK_MODEL = '在本机填入 Ark 模型或接入点 ID'
$env:DEEPSEEK_API_KEY = '在本机填入 DeepSeek 密钥'
$env:DEEPSEEK_MODEL = '在本机填入已开通的 DeepSeek 模型 ID'
```

连接 Smoke Test 仅发送一条通用、无版权的需求曲线问题，不读取 PDF，不写数据库；输出 JSON 格式检查与调用元数据，不打印答案正文。以下付费命令仅在 Product Owner 明确批准后使用；本地历史 Smoke Test 成功不代表后续配置与网络仍然可用：

```powershell
python -m api.bulk_import.cli model-smoke --provider doubao --allow-model-call
python -m api.bulk_import.cli model-smoke --provider deepseek --allow-model-call
```

无需密钥的本地门槛演练可运行 `python -m api.bulk_import.cli model-smoke --provider mock`。自动化测试全部 Mock HTTP，不使用真实密钥；Smoke Test 仅证明连接、模型配置、JSON 和 usage 响应，不证明经济学答案质量。

## 当前展示与验收限制

现有用户端和管理员端将题干/答案当普通文本显示，未集成 LaTeX 渲染器；本轮只保证 `stem_latex` 数据保存，不保证公式可视化显示。管理员题目中心可查询、编辑 DRAFT，但现有编辑表单不展示独立 AI 答案或 `import_meta_json`。现有审核端点要求 `answer` 和 `analysis` 非空，因此**无来源答案的导入题目前不能审核发布**；不得把 AI 答案复制进来源答案字段以绕过该限制。后续由产品确认展示和审核规则，再由管理员端负责人处理界面。

真实 10–20 题试点尚需 PO 指定 PDF 路径，并确认样本外发与模型费用。试点应人工标注普通文本、复杂公式、经济学图形、多小问、跨页、有/无来源答案；逐题记录文字、公式、拆题、图表、答案、标签准确率，单题模型 tokens/费用与处理时间。当前单元测试只覆盖合成 PDF 与 Mock/隔离 SQLite，不代表真实样本通过。
