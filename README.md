# 经研｜经济学考研学习平台

第一版本地开发切片。产品范围与长期规则以 [PRODUCT_CONTEXT.md](PRODUCT_CONTEXT.md) 为准。

后续开发采用 [GitHub Flow 协作约定](CONTRIBUTING.md)：从 `main` 创建短期分支，通过 Pull Request 检查和合并。

## 已实现

- React + TypeScript 用户端九模块三栏工作台和目标院校切换；
- FastAPI + SQLite 本地数据服务；
- 知识点与练习题浏览、作答、参考答案、自评、持久保存和统计回流；
- 管理员端练习题草稿录入与审核发布；
- 真题、兄弟院校、AI 和论坛的状态页。

当前三个目标院校配置、三个知识点及三道题均为**演示样本**。专业课配置尚未核验，演示题不是院校真题。管理员端无登录和权限控制，只允许在本机开发环境使用。不得直接部署到公网。

## 运行

需要 Python 3.12+、Node.js 20+、pnpm。

在项目根目录分别启动两个终端：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r api\requirements.txt
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

```powershell
pnpm install
pnpm run dev
```

打开 `http://127.0.0.1:5173/`。若本机开发热更新受环境权限限制，可执行 `pnpm run build` 后用 `pnpm exec vite preview --host 127.0.0.1 --port 5173` 预览构建结果。

数据保存在 `data/platform.db`，再次启动不会清空。API 文档位于 `http://127.0.0.1:8000/docs`。

## 下一步

优先补齐账号与管理员权限、院校考试配置及来源核验、知识树管理、真题试卷与单题关联，再把统计从自评扩展到可靠的作答证据。AI 接入排在结构化内容和学习记录之后。
