# 教材内容产出工具

这是一个用于 `上传英文教材 PDF -> 解析 -> 生成结构化板块 -> 审核 -> 导出` 的 FastAPI 项目骨架。

当前阶段：

- 已完成项目结构和基础接口骨架
- 已提供占位解析、占位生成、审核、导出链路
- 尚未接入真实 PDF 解析和真实 prompt 生成能力

## 运行方式

安装依赖：

```bash
pip install -r requirements.txt
```

本地密钥：

```bash
cp .env.example .env.local
```

把 API Key 只写入 `.env.local`，不要写进代码，也不要提交到 GitHub。

启动服务：

```bash
uvicorn app.main:app --reload
```

打开：

```text
http://127.0.0.1:8000/
```

功能总览页：

```text
http://127.0.0.1:8000/overview
```

## 当前接口

- `POST /api/v1/upload`
- `POST /api/v1/parse/{job_id}`
- `GET /api/v1/jobs/{job_id}`
- `GET /api/v1/results/{job_id}`
- `GET /api/v1/results/{job_id}/units/{unit_id}`
- `PATCH /api/v1/review/items/{target_type}/{target_id}`
- `POST /api/v1/review/units/{unit_id}/batch`
- `POST /api/v1/export`
- `GET /api/v1/export/{export_id}/download`

## 当前限制

- 解析模块仍是占位实现
- 生成内容仍是示例数据
- 审核页只有基础页面，主要通过 API 调用
- 导出拦截逻辑已存在，但审核状态需手动推进

## GitHub 版本管理

- 项目应通过 Git 管理并推送到 GitHub
- `.env.local`、`data/` 和缓存文件已加入 `.gitignore`
- 如果后续需要接入 API Key，优先使用环境变量或 `.env.local`
