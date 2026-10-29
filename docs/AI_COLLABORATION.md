# 经济学考研学习平台 Multi-AI Engineering Workflow V1.0

> 版本：V1.0
>
> 生效日期：2026-10-29
>
> 适用仓库：`zeng-bowen/ai-kaoyan-learning-platform`
>
> 适用对象：Product Owner、Codex、WorkBuddy、豆包，以及后续加入的人工或 AI 工程成员

本文件定义多 AI 协作的工程治理方式。产品规则以根目录的 `PRODUCT_CONTEXT.md` 为准，提交方式以 `CONTRIBUTING.md` 和 `AGENTS.md` 为准；本文件不得覆盖三者，只补充多人并行开发时的任务、契约、隔离、评审和交接规则。

## 1. 角色定义与责任边界

| 角色 | 定位 | 核心责任 | 无权自行决定 |
|---|---|---|---|
| 用户 | Product Owner（PO） | 决定产品范围、优先级、验收口径；批准契约与受保护文件变更；决定 PR 是否进入 Integration Queue | 不适用 |
| Codex | AI Engineer | 默认负责后端、数据、API、集成和回归测试；按 Issue 工作并提交 PR | 不得扩大产品范围、跳过审核边界或代替 PO 批准契约变更 |
| WorkBuddy | AI Engineer | 默认负责管理员端/用户端页面、交互、样式和前端联调；按现有契约消费 API | 不得为适配 UI 私自修改后端契约 |
| 豆包 | AI Engineer | 默认负责国产模型 Provider、AI 独立模块、中文业务质量与专项测试 | 不得将模型输出直接写入正式题库或把密钥写入仓库 |

默认职责只是分工起点。任何任务都以 GitHub Issue 中的 `Owner`、允许修改范围和验收标准为准，不以聊天记忆为准。

## 2. 唯一真相源（Single Source of Truth）

| 信息类型 | 唯一真相源 |
|---|---|
| 产品规则、对象边界、审核要求 | `PRODUCT_CONTEXT.md` |
| 工程协作与进入 `main` 的规则 | `AGENTS.md`、`CONTRIBUTING.md`、本文件 |
| 正式代码与可发布版本 | GitHub `main` |
| 任务范围、Owner、依赖和验收 | GitHub Issues / Project |
| API、数据模型、枚举和 Provider 边界 | Shared Contract Zone 中的受保护文件及已批准的 Contract Change Request |
| 具体实现、验证证据和限制 | 对应 PR、提交和 CI 结果 |

聊天记录、AI 的内部记忆、本地未提交文件和口头约定都不是项目事实。重要决定必须回写到上述真相源。

## 3. 一个 Issue 一个主写 AI

1. 每个实现 Issue 只能有一个 `Owner`，该 Owner 是唯一主写者。
2. 其他 AI 可以评审、复现、补充测试建议，但不得在同一 Issue、同一分支或同一核心文件上并行主写。
3. 一个分支只解决一个明确 Issue。发现额外问题时新建 Issue，不顺手扩展范围。
4. Owner 变更必须先更新 Issue，并完成 Agent Handoff；接手者从 Issue、代码、提交和文档接班，不依赖原聊天上下文。
5. 若两个 Issue 会修改同一文件，默认串行进入开发；后一个 Issue 依赖前一个 PR 合并后再从最新 `main` 建分支。

## 4. Branch + Git Worktree 隔离

### 4.1 分支规则

- 所有任务从最新 `main` 创建短期分支，遵守 GitHub Flow。
- 功能分支格式：`feat/<issue-number>-<short-slug>`。
- 文档、修复、测试分别使用 `docs/`、`fix/`、`test/` 前缀。
- 分支不得混入其他 Issue 的提交；不得直接在 `main` 开发。
- 合并后删除短期分支；Worktree 确认无未提交内容后再移除。

### 4.2 Worktree 规则

每个 Owner 使用独立目录，不共享 `node_modules`、虚拟环境、运行数据库、上传目录或 `.env`。推荐根目录：

```text
E:\经济学考研学习平台-worktrees\
  issue-<number>-recognition-api\
  issue-<number>-recognition-admin-ui\
  issue-<number>-doubao-provider\
```

创建前必须确认：目标目录不存在、分支不存在、基线为最新 `origin/main`、主仓库无未知未提交改动。不得把一个分支同时签出到多个 Worktree。

## 5. 数据库、上传目录与端口隔离

### 5.1 数据隔离

- 每个 Worktree 通过 `ECON_DB_PATH` 指向自身被 Git 忽略的数据库，例如 `data/worktree-codex/platform.db`。
- 截图目录会跟随数据库目录使用对应的 `question-intakes/`，不得复用主仓库或其他 Agent 的目录。
- 禁止把 `data/`、真实用户记录、上传原件、`.env`、缓存、`.venv/`、`node_modules/` 或 `dist/` 提交到 Git。
- 测试必须使用临时数据库或测试夹具，不得运行在开发主库上。
- 需要迁移时必须提供增量迁移和回滚/恢复说明，不得删除或覆盖既有学习记录。

### 5.2 端口隔离

| 环境 | API | Web/Admin | 用途 |
|---|---:|---:|---|
| Integration Queue / `main` 验收 | 8000 | 5173 | 唯一集成验收端口 |
| Codex Worktree | 8011 | 5181 | 后端/API 独立验证 |
| WorkBuddy Worktree | 8012 | 5182 | 管理员 UI 独立验证 |
| 豆包 Worktree | 8013 | 5183 | Provider 独立验证 |

端口仅绑定 `127.0.0.1`。当前代码若尚未支持某端口覆盖，Agent 应优先使用单元测试/TestClient，或在 Issue 中记录阻塞；不得为了临时联调把端口、CORS 或管理员接口改成公网/局域网可访问，也不得把本机临时配置提交到业务 PR。

## 6. Shared Contract Zone

以下内容属于共享契约区，任何修改都可能同时影响多个 Agent：

- `api/recognition.py` 中的 `RecognitionProvider`、`RecognitionCandidate` 和 Provider 加载约定；
- 对外 API 路径、请求/响应结构、HTTP 状态码和错误语义；
- 数据库表、字段、迁移、枚举与审核/发布状态；
- 前后端共享类型、验证模型和接口文档；
- `PRODUCT_CONTEXT.md`、`AGENTS.md`、`CONTRIBUTING.md` 与本文件；
- CI、部署、安全边界和密钥约定。

共享契约区的目标是让多个实现可以独立推进，而不是让所有 Agent 都能同时修改它。

### 6.1 本轮锁定

“管理员 AI 识题闭环 V0.1”期间，`api/recognition.py` 被锁定为 Shared Contract。Codex、WorkBuddy、豆包三个任务均不得自行修改。若现有契约不足，先提交 Contract Change Request，等待 PO 明确批准，并安排独立契约 PR 或指定唯一 Owner 串行修改。

## 7. 受保护文件与契约变更流程

受保护文件包括 Shared Contract Zone 中的文件，以及任一活跃 Issue 明确标为“禁止修改”的文件。

发现必须变更时：

1. 停止修改受保护文件，不把临时改动留在业务 PR 中。
2. 在 GitHub 新建 `Contract Change Request` Issue，说明现状、阻塞、提案、兼容性、迁移和测试影响。
3. 标注所有受影响 Issue/PR，并暂停依赖该契约的合并。
4. 由 PO 批准或拒绝；批准后指定一个唯一 Owner。
5. 契约变更使用独立分支和 PR，先合并到 `main`。
6. 所有依赖任务更新到新 `main`，重新运行回归测试，再进入 Integration Queue。

未经批准的契约变更应从 PR 中移除；“为了让当前实现能跑”不是绕过流程的理由。

## 8. 文件所有权

每个 Issue 必须列出：

- **允许修改**：Owner 可直接编辑的文件或目录；
- **禁止修改**：本任务不得触碰的文件；
- **共享但只读**：实现时可以读取、不能修改的契约；
- **新增文件命名空间**：允许新增的目录和测试文件；
- **潜在重叠**：与其他 Issue 可能冲突的文件。

规则：

1. “允许修改”不是必须修改，也不授权扩大需求。
2. 未列出的核心文件默认只读；确需修改先更新 Issue 的所有权范围。
3. 同一文件不能同时分配给两个活跃 Owner；若无法拆分，任务串行。
4. 新增测试尽量放入 Owner 独占文件，避免多个任务同时追加到同一大型测试文件。

## 9. Issue 模板字段

每个实现 Issue 至少包含以下字段：

```markdown
## Owner
Codex / WorkBuddy / 豆包 / 人工工程师

## Area
backend / admin-ui / provider / contract / data / docs / integration

## Type
feature / fix / test / docs / contract-change / chore

## 目标与用户价值

## 范围

## 依赖
- Depends on: #...
- Blocks: #...

## 文件所有权
- 允许修改：
- 禁止修改：
- 共享但只读：
- 允许新增：

## 当前契约

## 验收标准
- [ ] ...

## 测试要求
- [ ] 自动化测试：...
- [ ] 手工验证：...
- [ ] 回归范围：...

## 安全、数据与审核边界

## 交接要求

## 非目标
```

Issue 建立后才创建对应实现分支。Issue 内容发生实质变化时，由 PO 或 Owner 更新正文并留下变更说明。

## 10. PR 与交叉审查

### 10.1 PR 必填内容

- 关联 Issue（`Closes #<number>` 或 `Refs #<number>`）；
- 用户/管理员任务及对应产品规则；
- 实际修改文件与是否超出原所有权；
- API、数据、枚举、审核状态是否变化；
- 自动化检查命令与结果；
- 手工验证步骤、截图（界面任务）和失败/空/加载状态；
- 演示数据边界、尚未实现项和风险；
- Agent Handoff 摘要。

### 10.2 交叉审查分配

| 主写 Owner | 默认交叉审查 |
|---|---|
| Codex | WorkBuddy 检查契约可消费性；豆包检查 AI/异常边界 |
| WorkBuddy | Codex 检查 API 使用、数据事实源与回归；豆包检查中文状态文案 |
| 豆包 | Codex 检查 Provider 契约、超时/异常与测试；WorkBuddy 检查建议结果的 UI 可用性 |

交叉审查只提交评论或 Review，不直接向主写分支推送未约定的实现。发现契约问题时走 Contract Change Request。

## 11. Integration Queue

Integration Queue 是待进入 `main` 的单一串行队列，由 PO 维护顺序。

进入条件：

1. Issue 范围完成且无未说明的占位实现；
2. PR 与最新 `main` 无冲突；
3. CI 和相关测试通过；
4. 交叉审查完成，阻塞意见已解决；
5. 契约变更已先行合并；
6. 数据迁移、安全与人工审核边界已验证；
7. Agent Handoff 已填写。

合并顺序原则：契约/迁移 → Provider/后端 → 前端 → 集成修复。每合并一个 PR，后续 PR 必须更新基线并重新验证，不进行未经验证的批量合并。

## 12. Agent Handoff

Owner 暂停、换人或提交 PR 时，在 Issue/PR 留下可独立接手的交接信息：

```markdown
## Agent Handoff
- 当前分支 / Worktree：
- 基线提交：
- 已完成：
- 未完成：
- 修改文件：
- 契约与关键假设：
- 验证命令与最后结果：
- 已知失败 / 风险：
- 本地数据或环境变量要求（不含密钥值）：
- 下一步建议：
```

不得只写“见聊天记录”。交接必须让一个没有历史对话的 Agent 能从 GitHub 和仓库继续工作。

## 13. Contract Change Request 模板

```markdown
# Contract Change Request: <标题>

## 提出者与关联任务
## 当前契约与证据
## 阻塞或缺陷
## 建议变更
## 兼容性影响
## 数据迁移 / 回滚方案
## 受影响文件、Issue、PR 和 Owner
## 测试与验收计划
## 安全、审核和密钥影响
## PO 决策
- [ ] 批准
- [ ] 拒绝
- [ ] 需要补充信息
```

批准记录必须留在 GitHub。批准仅覆盖请求中列明的范围。

## 14. 冲突处理

按以下顺序处理：

1. **产品冲突**：以 `PRODUCT_CONTEXT.md` 和 PO 最新书面决策为准。
2. **任务冲突**：以 GitHub Issue 的 Owner、范围和优先级为准。
3. **契约冲突**：停止实现，走 Contract Change Request。
4. **文件冲突**：确认所有权；非 Owner 撤回重叠修改，必要时串行重做。
5. **Git 冲突**：由后进入 Integration Queue 的 Owner 在自己的分支解决并重新测试，不让前一个已验收 PR 承担未知改动。
6. **实现意见不一致**：各方提供代码、测试、日志或产品规则证据，由 PO 决策；不以模型自信度作为证据。

禁止用强制推送覆盖他人分支、删除未知提交、重置共享 Worktree，或把冲突标记直接删除来“解决”问题。

## 15. 敏感信息与密钥规则

- API Key、Access Key、Secret、Token、Cookie、私有端点和真实账号不得进入代码、Issue、PR、日志、截图、测试夹具或提交历史。
- 只通过本地环境变量或批准的 Secret 管理系统注入；仓库只记录变量名和安全配置说明。
- Provider 必须在缺少密钥时明确失败或安全降级，不得使用硬编码演示密钥。
- 错误信息不得回显密钥、完整请求头或不必要的用户/上传内容。
- `.env`、数据库和上传文件必须保持 Git 忽略；如发现泄露，立即停止合并、撤销/轮换密钥并记录安全事件。
- 管理员 API 仅监听 `127.0.0.1`。正式上线前必须完成身份认证、RBAC、审计、部署隔离和安全文件存储。
- 发往第三方模型的题图和文本应遵循最小必要原则；真实用户或受版权保护内容的外发策略须由 PO 另行批准。

## 16. 完成定义（Definition of Done, DoD）

一个 Issue 只有同时满足以下条件才可标记完成：

- [ ] 实现严格落在 Issue 范围和文件所有权内；无未批准的 Shared Contract 修改。
- [ ] 产品行为符合 `PRODUCT_CONTEXT.md`，AI 输出始终是管理员可见建议，不会绕过人工审核发布。
- [ ] 新内容具备来源、标签和审核状态；演示数据显著标识。
- [ ] 加载、空、错误、无权限/未配置、无结果和降级状态按任务适用范围处理。
- [ ] 相关自动化测试通过，并覆盖成功、错误、超时/未配置和审核边界。
- [ ] 至少执行 `pnpm run build`、`python -m py_compile api/main.py`；涉及 API 时执行对应回归测试，涉及交互时完成人工检查。
- [ ] 数据库和上传目录使用隔离路径，未破坏已有用户数据。
- [ ] 未提交密钥、生成目录、真实数据或无关改动。
- [ ] PR 关联 Issue，说明验证证据、限制、占位能力和安全边界。
- [ ] 交叉审查完成，阻塞评论已解决。
- [ ] Agent Handoff 完整，后续 Agent 不依赖聊天历史即可接手。
- [ ] PR 已按 Integration Queue 顺序合并到 `main`；合并后的 `main` 仍可构建、可测试。

## 17. 本轮“管理员 AI 识题闭环 V0.1”边界

本轮拆为三个互不主写同一文件的 Issue：

| Issue / Owner | 任务与分支 | 默认允许修改 | 明确禁止修改 |
|---|---|---|---|
| `#5` Codex | AI 识别 API 与核心流程加固；`feat/5-recognition-api` | `api/main.py`、`api/test_targets.py` | `api/recognition.py`；不得实现具体豆包 Provider |
| `#6` WorkBuddy | 管理员 AI 识图审核 UI；`feat/6-recognition-admin-ui` | `src/admin.tsx`、`src/admin.css` | 后端接口与 `api/recognition.py` |
| `#7` 豆包 | 火山方舟/豆包视觉模型 RecognitionProvider；`feat/7-doubao-provider` | 新增 `api/providers/doubao.py` 和独占测试文件 | `api/main.py`、`api/recognition.py` |

共同规则：识别结果只作为 `RecognitionCandidate[]` 建议；人工选择、修改并保存后仍为草稿；不得自动审核或发布；`api/recognition.py` 在本轮锁定，任何变更必须走 Contract Change Request。

