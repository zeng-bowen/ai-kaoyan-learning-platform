# 开发协作约定（GitHub Flow）

产品定义以 [PRODUCT_CONTEXT.md](PRODUCT_CONTEXT.md) 为准。此文件只约定代码如何进入主分支。

## 日常流程

1. 从最新 `main` 创建一个短期分支，每个分支只处理一个明确问题。
2. 在分支上实现功能，保留可复查的提交记录；发现产品规则冲突时先更新设计决策。
3. 本地通过相关检查，在 Pull Request 中写清目标、变更、验证结果和演示数据边界。
4. 评审和自动检查通过后合并到 `main`。合并后删除短期分支。

分支名示例：`feat/school-exam-model`、`fix/target-stats`、`docs/question-schema`、`chore/ci`。使用英文小写和连字符，避免一个分支长期承载多个功能。

## 主分支规则

- `main` 始终保持可构建、可运行；功能未完成时使用清楚的空状态或功能开关。
- 不直接在 `main` 开发新功能。紧急修复也从 `main` 建短期分支并通过 PR 合并。
- 不提交 `data/`、`.venv/`、`node_modules/`、`dist/` 或真实账号与密钥。
- 院校招生信息、真题及答案必须有来源和核验状态；演示样本必须明确标识。
- 数据模型变更应有迁移方案；用户学习记录不能因目标院校切换而丢失。

## 提交与 PR

提交信息使用简洁的祈使句，可加范围前缀，例如 `feat: add question review status`、`fix: scope stats by target exam`。PR 建议控制在一个可理解的纵向功能切片内，同时覆盖必要的数据层、管理端、用户端和验证。

提交 PR 前至少执行：

```powershell
pnpm install --frozen-lockfile
pnpm run build
python -m py_compile api/main.py
```

涉及交互的改动，还需手工检查目标院校切换、空状态和学习记录是否符合预期。涉及 API 的改动需验证相应请求和错误状态。

## GitHub 仓库建立后

将本地 `main` 推送到私有仓库，并把它设为默认分支。为 `main` 配置规则：通过 PR 合并、要求 CI 检查通过；如有共同开发者，再启用至少一位独立评审。根据团队规模决定是否允许作者自己合并。此处不预设远程仓库地址或公开范围。
