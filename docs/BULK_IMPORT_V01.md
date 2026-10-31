# PDF 批量导题 V0.1：本地操作与数据规范

此工具是管理员在可信本地环境运行的命令行流程，不是公网 API。它不改变既有 `RecognitionProvider.recognize(image_bytes, mime_type)` 或识图接口，也不提供新的管理员批量 UI。任何模型输出、拆题边界、公式、图表归属及答案来源均为待审核草稿。

## 环境与边界

- Python 3.11+；安装 `api/requirements.txt`，其中 PDF 提取和页面渲染依赖 `pdfplumber`。通过仓库根目录运行 `python -m api.bulk_import.cli ...`。
- 输入仅支持 PDF。可复制文本优先本地提取；仅扫描/文字极少的页面才经既有视觉 Provider 识别。复杂公式、图片表格、答案标题变体无法保证自动识别正确；本地规则转换的公式及按纵向位置关联的图表会警告。
- `--provider doubao` 是默认选项，但**没有** `--allow-model-call` 时只生成 `PENDING`，绝不发送资料或伪造答案。`--provider mock` 用于演练，生成的 `MOCK` 答案不能入库。真实调用前必须得到资料外发与费用许可。
- 真题来源需要年份及 HTTPS 来源链接；若无合法来源链接，可先产生批次，但校验阻止入库。不要为了绕过校验将真题改标成原创资料。
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
python -m api.bulk_import.cli retry 'C:\batches\econ-001' --item-key '实际item_key' --db 'C:\platform\platform.db' --provider doubao --allow-model-call
python -m api.bulk_import.cli validate 'C:\batches\econ-001' --db 'C:\platform\platform.db'
python -m api.bulk_import.cli preview 'C:\batches\econ-001'
python -m api.bulk_import.cli confirm 'C:\batches\econ-001' --item-key '实际item_key'
python -m api.bulk_import.cli import 'C:\batches\econ-001' --db 'C:\platform\platform.db'
```

`confirm` 会展示单题并要求准确输入 `CONFIRM <item_key>`。只有校验通过、明确确认且确认后未被修改的题会入库；其余保持待处理。每题独立事务，失败记录在 `progress.json`，可改 JSON、重试、复核后再导入。重复运行采用稳定题目 ID，不覆盖已存在 Question；疑似重复只提示，不自动跳过。导入前请备份现有数据库和同目录的题目资源目录。

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

文本任务仅适配当前豆包 Ark 服务：`DOUBAO_ARK_API_KEY`、`DOUBAO_ARK_MODEL` 必填；可选 `DOUBAO_ARK_BASE_URL`（必须 HTTPS）、`DOUBAO_ARK_TIMEOUT_SECONDS`（默认 30）、`DOUBAO_ARK_RETRIES`（最多 3 次额外重试）。扫描页视觉任务继续使用现有 `ECON_RECOGNITION_PROVIDER` 与其豆包配置。按实际账单费率配置 `DOUBAO_ARK_INPUT_PRICE_PER_MILLION`、`DOUBAO_ARK_OUTPUT_PRICE_PER_MILLION`、`DOUBAO_ARK_PRICE_CURRENCY` 才会计算估算成本；未配置则明确为 `null`，不虚构费用。`processing_meta.model_runs` 记录任务、模型、耗时、尝试数、tokens 和估算成本，不记录密钥。不要把密钥放到前端、JSONL、日志或 Git。

## 当前展示与验收限制

现有用户端和管理员端将题干/答案当普通文本显示，未集成 LaTeX 渲染器；本轮只保证 `stem_latex` 数据保存，不保证公式可视化显示。管理员题目中心可查询、编辑 DRAFT，但现有编辑表单不展示独立 AI 答案或 `import_meta_json`。现有审核端点要求 `answer` 和 `analysis` 非空，因此**无来源答案的导入题目前不能审核发布**；不得把 AI 答案复制进来源答案字段以绕过该限制。后续由产品确认展示和审核规则，再由管理员端负责人处理界面。

真实 10–20 题试点尚需 PO 指定 PDF 路径，并确认样本外发与模型费用。试点应人工标注普通文本、复杂公式、经济学图形、多小问、跨页、有/无来源答案；逐题记录文字、公式、拆题、图表、答案、标签准确率，单题模型 tokens/费用与处理时间。当前单元测试只覆盖合成 PDF 与 Mock/隔离 SQLite，不代表真实样本通过。
