# AI 实战

一个本机运行的 AI 公众号内容工作台。它把 AI 资讯采集、评分选题、人工审核、网页预览、Markdown 与配图导出整合到一个 Docker 项目中。

> 适合希望稳定产出「AI 工具、开源项目、实战教程」类公众号内容的个人创作者。系统不会自动群发，所有稿件都需要人工审核与批准。

## 能做什么

- 从 OpenAI、Anthropic、Hugging Face、Hacker News、arXiv、GitHub 等信息源采集资讯。
- 按事件聚类、去重，并用 AI 对时效性、实用性、影响力和公众号匹配度评分。
- 每次运行从当天资讯中生成可审核的候选稿，候选数量可在工作流设置中调整。
- 粘贴公开文章网址，或上传 TXT、Markdown、HTML、JSON、DOC、DOCX、PDF 文件，生成待审核的公众号稿件。
- 在审核页手动修改标题、导语、事实概述、价值解读和行动建议，并保留版本历史。
- 为已批准稿件生成公众号成品：Markdown、可本地预览的 HTML、封面 JPG 与章节配图 JPG（同时保留 SVG 源文件）。
- 下载生成的 HTML、Markdown、封面和配图；支持查看 PostgreSQL 业务数据和运行记录。

## 界面预览

项目启动后访问 `http://localhost:8080`。页面无需登录，默认仅允许本机访问。

## 快速开始

### 1. 准备环境

安装并启动 [Docker Desktop](https://www.docker.com/products/docker-desktop/)。Windows 用户建议启用 WSL 2 后端。

### 2. 配置环境变量

在项目根目录复制配置模板：

```powershell
Copy-Item .env.example .env
```

至少修改以下内容：

```env
POSTGRES_PASSWORD=请设置一个数据库密码
DATABASE_URL=postgresql+psycopg://ai_news:请设置同一个数据库密码@postgres:5432/ai_news
INTERNAL_API_KEY=请设置一串随机字符
N8N_ENCRYPTION_KEY=请设置一串更长的随机字符
OPENAI_API_KEY=你的 API Key
```

`OPENAI_API_KEY` 为空时，资讯采集仍可运行；AI 评分、写稿和成品生成会降级或进入人工核验。

模型与兼容 API 地址可按需调整：

```env
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_TEXT_MODEL=gpt-5-mini
OPENAI_IMAGE_MODEL=gpt-image-1
```

### 3. 启动项目

双击根目录的 [一键启动项目.bat](<一键启动项目.bat>)，或在 PowerShell 中执行：

```powershell
docker compose up -d --build
```

首次构建需要下载镜像，完成后打开：

| 服务 | 地址 | 用途 |
| --- | --- | --- |
| AI 实战 | http://localhost:8080 | 审核、工作流、数据库 |
| n8n | http://localhost:5678 | 查看或手动执行 n8n 工作流 |
| Adminer | http://localhost:8081 | PostgreSQL 可视化管理 |
| API 文档 | http://localhost:8000/docs | FastAPI 接口文档 |

停止项目可双击 [一键关闭项目.bat](<一键关闭项目.bat>)，或执行：

```powershell
docker compose stop
```

停止不会删除数据库、导出文件、图片或历史记录。

## 推荐使用流程

### 资讯到候选稿

1. 打开「工作流」。
2. 在「资讯到候选稿」卡片中点击「设置」，选择信息源、每个平台采集数量和候选稿数量。
3. 点击「启动」。系统会依次完成采集、当天评分、去重与候选稿生成。
4. 在「稿件审核」中查看候选稿；不需要的稿件可直接删除。

### 从一篇文章或文件生成稿件

在「稿件审核」顶部：

1. 粘贴公开文章链接后点击「从网站生成」；或选择本地文件后点击「从文件生成」。
2. 生成结果进入待审核列表。
3. 根据自己的判断修改内容、核对事实和来源后再批准。

请只处理你拥有授权、可合理使用或用于个人学习的内容。系统的目标是帮助重组和编辑信息，不应被用于逐句复制受版权保护的文章。

### 生成公众号成品

1. 在审核页完成编辑，点击「批准」。
2. 点击「生成公众号成品」，或在「工作流」中启动「公众号成品生成」。
3. 系统为所有已批准稿件生成独立成品目录，不同稿件、不同批次不会互相覆盖。
4. 在生成结果中打开网页预览或下载 Markdown、HTML、封面和配图。

生成目录位于：

```text
data/exports/publications/article-文章编号/时间戳/
```

其中包含：

```text
article.md             # 公众号 Markdown 稿
preview.html           # 可直接在浏览器打开的预览页
cover.jpg              # 公众号封面（1800×766）
cover.svg              # 可继续编辑的封面源文件
images/*.jpg           # 章节配图（1200×500）
images/*.svg           # 章节配图源文件
manifest.json          # 本次生成的文件清单
```

## 工作流说明

| 编号 | 名称 | 用途 |
| --- | --- | --- |
| 01 | 资讯到候选稿 | 采集、当天评分、去重、选题和生成候选稿 |
| 04 | 公众号成品生成 | 为已批准或已导出的稿件生成网页、Markdown、封面和章节配图 |
| 05 | 失败检查 | 汇总需要人工处理的失败或部分失败任务 |

`n8n/workflows/` 中提供对应可导入的 JSON 文件。n8n 是可选的调度入口；即使不打开 n8n，也可以直接在网页中手动运行以上工作流。

## 项目结构

```text
├─ backend/                 # FastAPI、采集、评分、写稿、导出逻辑
├─ frontend/                # React 审核后台
├─ n8n/workflows/           # 可导入 n8n 工作流
├─ data/                    # 本机持久化数据（不会提交到 Git）
│  ├─ postgres/             # PostgreSQL 数据库
│  ├─ assets/               # 图片与资源
│  ├─ exports/              # 公众号成品和导出文件
│  └─ n8n/                  # n8n 配置与执行数据
├─ scripts/                 # 备份、恢复与辅助脚本
├─ docker-compose.yml
├─ 一键启动项目.bat
└─ 一键关闭项目.bat
```

## 数据与安全

- 前端和后端默认绑定到 `127.0.0.1`，仅限当前电脑访问。
- `.env`、数据库、生成图片与导出文件均已在 `.gitignore` 中排除；请不要将真实 API Key、密码或 `data/` 内容提交到 GitHub。
- n8n 当前端口仍为 `5678`。如果你的电脑处于不可信局域网，请在 `docker-compose.yml` 中将它改为 `127.0.0.1:5678:5678`，或为 n8n 启用自身认证。
- 系统不提供公众号自动群发功能。
- 面向公开文章时只保存处理所需的信息；重要数字、日期、模型名称和事实结论仍应由人工核验。

## 公众号草稿箱（可选）

默认配置：

```env
WECHAT_MODE=mock
```

此模式只模拟草稿请求，不会连接或发布到公众号。注册并完成公众号接口权限配置后，可填写：

```env
WECHAT_MODE=real
WECHAT_APP_ID=你的 AppID
WECHAT_APP_SECRET=你的 AppSecret
```

请先使用测试账号验证权限与素材上传流程。无论何种模式，本项目都不会自动群发。

## 备份、恢复与开发

备份：

```powershell
.\scripts\backup.ps1
```

恢复示例：

```powershell
.\scripts\restore.ps1 -BackupDir .\data\backups\20260722-120000
```

后端测试：

```powershell
docker compose run --rm -T backend python -m pytest -q
```

前端构建：

```powershell
docker compose build frontend
```

## 开源前检查

推送到 GitHub 前，请运行：

```powershell
git status
git check-ignore .env data/postgres data/exports
```

确认输出中没有 `.env`、`data/` 内的内容、真实密钥、个人文章或用户上传文件。若密钥曾被提交到 Git 历史，请立即在对应平台撤销并重新生成。

欢迎交流 2959681988@qq.com

## 许可证

本项目采用 [MIT License](LICENSE) 开源。
