# YouTube KOL Mailer

YouTube 博主自动化邮件系统 —— 在 YouTube 页面抓取 KOL 信息，选择邮件模板，写入飞书多维表格，通过飞书群 Bot 确认后批量发送合作邀请邮件。

## 一、系统组成

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│ Chrome Extension │────▶│  FastAPI Backend  │────▶│ Feishu Bitable  │
│ 抓取+选模板+写入  │     │  模板/渲染/发信    │     │ 唯一 KOL 表     │
└─────────────────┘     └──────┬───┬────────┘     └─────────────────┘
                               │   │
                     ┌─────────┘   └──────────┐
                     ▼                         ▼
              ┌────────────┐           ┌──────────────┐
              │ SQLite DB  │           │ Lark SMTP    │
              │ 模板库+配置  │           │ 465/SSL 发信  │
              └────────────┘           └──────────────┘
                                              ▲
                                       ┌──────────────┐
                                       │ Feishu Bot   │
                                       │ 群内确认+播报  │
                                       └──────────────┘
```

| 组件 | 技术 | 职责 |
|------|------|------|
| Chrome Extension | Manifest V3, 原生 JS | 抓取 YouTube KOL 信息、选模板、写入后端 |
| Python Backend | FastAPI + SQLite | 模板管理、Bitable 读写、变量渲染、SMTP 发信、状态更新 |
| SQLite 数据库 | 后端本地 | 存储模板库、操作者配置、发送任务（不存 KOL 数据） |
| Feishu Bitable | 飞书多维表格 | 唯一 KOL 业务台账（一张表） |
| Feishu Bot | 应用机器人 API（/im/v1/messages） | 群内汇总、预览确认、触发发送、结果播报 |
| Lark Mail SMTP | smtp.larksuite.com:465 SSL | 飞书企业邮箱发信通道 |

## 二、目录结构

```
youtube-kol-mailer/
├── backend/
│   ├── app.py                       # FastAPI 入口，路由注册，CORS，启动初始化
│   ├── config.py                    # 环境变量配置（从 .env 读取）
│   ├── api/
│   │   ├── templates.py             # 模板 CRUD + 预览渲染 API
│   │   ├── kols.py                  # KOL upsert + pending 查询 + 状态更新 API
│   │   ├── send.py                  # 预览发送 + 正式发送 + 重试 API
│   │   ├── bot.py                   # 飞书 Bot 命令处理 API
│   │   └── settings.py              # 配置查询 API
│   ├── services/
│   │   ├── bitable_service.py       # 飞书 Bitable 读写（鉴权+CRUD+upsert）
│   │   ├── template_service.py      # 模板 CRUD 业务逻辑
│   │   ├── render_service.py        # 模板变量渲染
│   │   ├── smtp_service.py          # SMTP 邮件发送
│   │   ├── send_validator.py        # 发送前校验（邮箱/模板/SMTP）
│   │   ├── queue_service.py         # 发送队列（延迟/断点续发/防重）
│   │   └── bot_service.py           # 飞书群消息推送
│   ├── repositories/
│   │   ├── template_repo.py         # templates 表 SQLite CRUD
│   │   ├── operator_repo.py         # operators 表（多操作者，预留）
│   │   └── send_job_repo.py         # send_jobs 表（预留）
│   ├── models/
│   │   ├── db.py                    # SQLite 建表 + 连接管理
│   │   ├── schemas.py               # Pydantic 请求/响应模型
│   │   └── constants.py             # 状态机 + Bitable 字段映射
│   ├── web_admin/                   # Admin 后台页面（骨架）
│   ├── requirements.txt
│   └── .env.example                 # 配置模板（不含真实值）
├── extension/
│   ├── manifest.json                # Chrome 扩展清单（Manifest V3）
│   ├── content.js                   # YouTube 页面 KOL 信息抓取
│   ├── background.js                # Service Worker：API 请求中转
│   └── icons/                       # 扩展图标
├── scripts/
│   ├── init_db.py                   # 数据库建表脚本
│   ├── seed_templates.py            # 示例模板导入脚本
│   ├── smoke_test.py                # 基础冒烟测试
│   └── smoke_test_bitable.py        # Bitable 集成测试
├── data/                            # SQLite 数据库文件目录
└── README.md
```

## 三、环境准备

### 3.1 系统要求

- **Python**: 3.10+（推荐 3.12）
- **Chrome**: 最新版本（支持 Manifest V3）
- **操作系统**: Windows / macOS / Linux

### 3.2 飞书开放平台配置

1. 登录 [飞书开放平台](https://open.feishu.cn/app)
2. 创建一个企业自建应用
3. 在「凭证与基础信息」中获取 `App ID` 和 `App Secret`
4. 在「权限管理」中添加以下权限：
   - `bitable:app` — 多维表格读写
   - `bitable:app:readonly` — 多维表格只读（可选）
5. 发布应用并审批通过

### 3.3 飞书 Bitable 表创建

#### 方式一：自动创建（推荐）

后端支持自动创建 KOL 表和所有字段，无需手动操作：

1. 在飞书中创建一个空的多维表格（Bitable）
2. 从浏览器地址栏获取 `LARK_BITABLE_APP_TOKEN`（URL 中 `/base/` 后的字符串）
3. 填入 `.env` 文件
4. 启动后端后，访问 Admin Dashboard (`https://api.youtube-kol.com/admin/`)
5. 点击「初始化 Bitable」按钮，系统自动创建 KOL 表和所有字段
6. 将返回的 `LARK_BITABLE_TABLE_ID` 填入 `.env`，重启后端

也可以通过 API 初始化：
```bash
curl -X POST https://api.youtube-kol.com/api/admin/init-bitable
```

**权限要求：** 应用必须有 `bitable:app`（多维表格读写）权限。若初始化失败提示权限不足，请在飞书开放平台为应用添加此权限并重新发布。

#### 方式二：手动创建

如果你希望手动创建表和字段，在飞书多维表格中添加以下字段（**字段名必须完全一致**）：

| 字段名 | 字段类型 | 说明 |
|--------|---------|------|
| kol_id | 文本 | 后端生成的唯一 ID（如 yt_9f7c2a1d） |
| kol_name | 文本 | 博主名/频道名 |
| email | 文本 | 联系邮箱 |
| channel_url | 文本 | 频道主页链接 |
| template_id | 文本 | 模板标识（存储 template_key） |
| operator | 文本 | 操作者 |
| category | 文本 | 内容分类 |
| followers_text | 文本 | 粉丝数文本（如 152K） |
| last_error | 文本 | 最近失败原因 |
| sent_at | 文本 | 发送成功时间 |
| kol_contact_status | 单选 | 联系状态：未联系/已联系 |

创建后，从浏览器地址栏获取：
- `LARK_BITABLE_APP_TOKEN`：URL 中 `/base/` 后的字符串
- `LARK_BITABLE_TABLE_ID`：URL 中 `?table=` 后的字符串

#### init-bitable 故障排查

| 错误 | 原因 | 解决 |
|------|------|------|
| `Failed to get tenant_token: invalid param` | LARK_API_BASE 与应用平台不匹配 | 检查 .env 中 LARK_API_BASE 是否与应用创建平台一致 |
| `Access denied...scope required: bitable:app` | 应用缺少 Bitable 权限 | 在飞书开放平台添加 `bitable:app` 权限并重新发布 |
| `app_token 无效或不存在` | LARK_BITABLE_APP_TOKEN 配置错误 | 检查 .env 中的值是否与 Bitable URL 一致 |
| `无创建表权限` | 应用没有读写权限 | 确认 `bitable:app` 权限已添加（非只读） |
| `无创建字段权限` | 应用权限不足 | 同上，确认有读写权限 |

### 3.4 飞书 SMTP 邮箱配置

1. 确保你的飞书企业邮箱已启用
2. 进入飞书邮箱 > 设置 > 客户端设置
3. 生成「客户端专用密码」（不是登录密码）
4. SMTP 服务器信息：
   - Host: `smtp.larksuite.com`
   - Port: `465`
   - 加密: SSL
5. 确保域名已配置 SPF / DKIM / DMARC 记录

### 3.5 飞书应用机器人配置（交互卡片方案）

本项目使用**应用机器人 + 交互卡片**方案（非自定义机器人 webhook），支持群内 @Bot 发命令、点击卡片按钮确认发送。

#### 3.5.1 启用机器人能力

1. 登录飞书开放平台，进入你的应用
2. 在「应用能力 > 机器人」中启用机器人能力

#### 3.5.2 添加所需权限

在「权限管理」中添加以下权限：

| 权限 | 说明 |
|------|------|
| `im:message:send_as_bot` | 以机器人身份发送消息 |
| `im:message` | 获取与更新消息 |
| `im:chat:readonly` | 读取群信息 |
| `bitable:app` | 多维表格读写（已有） |

添加后需重新发布应用。

#### 3.5.3 配置事件订阅

1. 进入应用 → 「事件与回调」→ 「事件配置」
2. 请求地址填：`https://你的域名/api/bot/event`
3. 添加事件：`im.message.receive_v1`（接收消息）
4. 首次保存时飞书会发送 challenge 验证（后端自动处理）

#### 3.5.4 配置卡片交互回调

1. 在同一页面找到「卡片交互回调」设置
2. 请求地址填：`https://你的域名/api/bot/card-callback`

#### 3.5.5 将机器人添加到群

1. 在目标飞书群中，进入「设置 > 群机器人 > 添加机器人」
2. 搜索并选择你的应用机器人（不是自定义机器人）
3. 添加成功后，群成员就可以 @Bot 发命令

#### 3.5.6 Bot 使用流程

1. 在群中 `@Bot 发送邮件` → Bot 回复交互卡片（待发送摘要 + 按钮）
2. 点击「发送预览」→ 发一封预览到操作者邮箱，卡片更新状态
3. 点击「确认发送」→ 正式发送全部待发 KOL，卡片更新结果
4. 点击「刷新列表」→ 重新拉取待发送列表，更新卡片

> **注意：** 本项目使用应用机器人 API 发送消息，不需要配置自定义机器人 Webhook。

### 3.6 .env 配置文件

```bash
cd backend
cp .env.example .env
```

打开 `.env`，填入你的真实值。详见 `.env.example` 中的注释说明。

| 配置项 | 必填 | 说明 |
|--------|------|------|
| `LARK_APP_ID` | 是 | 飞书应用 App ID |
| `LARK_APP_SECRET` | 是 | 飞书应用 App Secret |
| `LARK_BITABLE_APP_TOKEN` | 是 | 多维表格 token |
| `LARK_BITABLE_TABLE_ID` | 是 | KOL 表 ID |
| `LARK_SMTP_USER` | 是 | 飞书企业邮箱地址 |
| `LARK_SMTP_PASSWORD` | 是 | 邮箱客户端专用密码 |
| `PREVIEW_RECEIVER_EMAIL` | 否 | 全局预览邮箱 fallback（登录用户从 Dashboard 配置） |
| `LARK_SMTP_FROM_NAME` | 否 | 发件人显示名 |
| `SEND_DELAY_MIN` / `MAX` | 否 | 每封邮件间隔秒数（默认 5-15） |

## 四、启动步骤

### 步骤 1：安装后端依赖

```bash
cd backend
pip install -r requirements.txt
```

### 步骤 2：配置环境

```bash
cp .env.example .env
# 编辑 .env，填入真实的飞书凭证和 SMTP 配置
```

### 步骤 3：初始化数据库

```bash
# 建表
python ../scripts/init_db.py

# 导入示例模板（demo 内容，可随时替换）
python -X utf8 ../scripts/seed_templates.py
```

### 步骤 4：启动后端

```bash
python -m uvicorn app:app --reload --port 8000
```

验证：
- 浏览器打开 https://api.youtube-kol.com/api/health → 应返回 `{"status": "ok"}`
- 打开 https://api.youtube-kol.com/api/templates → 应返回 2 个示例模板

### 步骤 5：加载 Chrome 扩展

1. Chrome 地址栏输入 `chrome://extensions/`
2. 右上角打开「开发者模式」
3. 点击「加载已解压的扩展程序」
4. 选择项目中的 `extension/` 目录
5. 扩展图标出现在 Chrome 工具栏

### 步骤 6：配置扩展

1. 右键扩展图标 → 选项
2. 后端地址填入 `https://api.youtube-kol.com`
3. 操作者名称填入你的名字
4. 点击「测试连接」→ 应显示 "连接成功"

### 步骤 7：运行冒烟测试

```bash
# 基础测试（无需飞书配置也可通过）
cd youtube-kol-mailer
python -X utf8 scripts/smoke_test.py

# Bitable 集成测试（需要飞书配置）
cd backend
python -X utf8 ../scripts/smoke_test_bitable.py
```

## 五、端到端流程

完整使用流程，按顺序执行：

### 第 1 步：抓取 KOL

1. 在 Chrome 中打开一个 YouTube 频道页面（如 `youtube.com/@某频道`）
2. 点击扩展图标，popup 自动抓取频道名、链接、邮箱、订阅数等
3. 如果邮箱未抓取到，手动填写

### 第 2 步：选择模板

1. 在 popup 的「邮件模板」下拉框中选择一个模板
2. 模板列表从后端 `/api/templates` 实时获取，不缓存在扩展中

### 第 3 步：写入 KOL 表

1. 确认信息无误后，点击「写入 KOL」
2. 后端生成 kol_id，将记录写入飞书 Bitable KOL 表
3. 新记录默认 kol_contact_status = `未联系`
4. 如果该 KOL 已存在（按 kol_id 去重），执行更新

### 第 4 步：Bot 汇总待发送

1. 在飞书群中发送 `@Bot 发送邮件`
2. Bot 返回待发送汇总：数量、模板分布、KOL 列表摘要

### 第 5 步：测试发送

1. 在群中发送 `@Bot 测试发送`
2. Bot 取第一条待发 KOL，渲染模板，发送预览到 `PREVIEW_RECEIVER_EMAIL`
3. 检查你的邮箱，确认邮件标题、正文、变量替换是否正确

### 第 6 步：确认正式发送

1. 预览无误后，在群中发送 `@Bot 确认发送`
2. 后端逐条发送：校验 → 随机延迟 → SMTP 发信 → 回写 kol_contact_status
3. 每封邮件间隔 5-15 秒（可通过 `.env` 调整）

### 第 7 步：查看结果

1. 发送完成后，Bot 在群内播报结果：成功数、失败数、失败详情
2. 成功的 KOL：kol_contact_status → `已联系`，写入 `sent_at`
3. 失败的 KOL：写入 `last_error` 记录失败原因

### 第 8 步：重试失败项

1. 如有失败，在群中发送 `@Bot 重试失败`
2. Bot 只重发有 `last_error` 且 kol_contact_status 非 `已联系` 的 KOL
3. kol_contact_status = `已联系` 的永远不会重复发送

## 六、排查指南

### SMTP 登录失败

```
SMTP authentication failed
```

- 检查 `LARK_SMTP_USER` 是否为完整邮箱地址（如 `name@company.com`）
- 检查 `LARK_SMTP_PASSWORD` 是否为「客户端专用密码」（不是登录密码）
- 确认飞书邮箱已启用 SMTP 访问
- 确认 SMTP 端口为 465（SSL），不是 587

### 飞书 token 获取失败

```
Failed to get tenant_token: invalid param
```

- 检查 `LARK_APP_ID` 和 `LARK_APP_SECRET` 是否正确
- 确认飞书应用已发布并审批通过
- 确认应用类型为「企业自建应用」

### Bitable 写入失败

```
Bitable create failed: ...
```

- 检查 `LARK_BITABLE_APP_TOKEN` 和 `LARK_BITABLE_TABLE_ID`
- 确认飞书应用已授权访问该多维表格
- 确认 KOL 表字段名与本文档完全一致（区分大小写）
- 在飞书多维表格中，给应用添加「可管理」权限

### 模板变量缺失

```
Variable '{category}' used in template but not provided
```

- 这是 warning 不是 error，不会阻断发送
- 缺失的变量会保留原始 `{xxx}` 文本
- 如需补充，在 KOL 记录中填写对应字段

### 扩展无法请求后端

```
连接失败: Failed to fetch
```

- 确认后端已启动：`python -m uvicorn app:app --reload --port 8000`
- 确认扩展 Options 中的后端地址正确（默认 `https://api.youtube-kol.com`）
- 检查 Chrome 控制台是否有 CORS 错误（后端默认允许所有来源）
- 如果后端端口不是 8000，需同时修改 `extension/manifest.json` 中的 `host_permissions`

### 已联系状态重复发送保护

```
Already sent, skipping
```

- 这是正常行为：kol_contact_status = `已联系` 的 KOL 永远不会被重复发送
- `已联系` 是终态，不允许重复发送
- 如果确实需要重发，需手动在 Bitable 中将 kol_contact_status 改回 `未联系`

## 七、发送安全提醒

> **务必遵守以下原则，避免邮箱被标记为垃圾邮件或被封禁。**

### 先测试预览

每次修改模板后，先通过「测试发送」给自己发一封预览邮件，检查：
- 邮件标题是否正确
- 正文中变量是否全部替换（无残留 `{xxx}`）
- HTML 格式是否正常
- 发件人名称是否正确

### 阶梯爬坡

新邮箱或新域名，建议按以下节奏发送：

| 天数 | 建议发送量 | 说明 |
|------|----------|------|
| 第 1-2 天 | 20 封/天 | 观察退信率和投递率 |
| 第 3-5 天 | 50 封/天 | 确认无异常后放量 |
| 第 6-10 天 | 100 封/天 | 稳定后逐步增加 |
| 之后 | 按需调整 | 保持退信率 < 5% |

### DNS 配置检查

正式发送前，确认以下 DNS 记录已正确配置：
- **SPF 记录**：允许飞书邮件服务器代发
- **DKIM 记录**：邮件签名验证
- **DMARC 记录**：定义未通过验证邮件的处理策略

可使用 [MXToolbox](https://mxtoolbox.com/) 在线检查。

### 发送纪律

- 不要一次性发送超过 100 封
- 不要在短时间内反复重试失败项
- 每封邮件间隔至少 5 秒（系统默认 5-15 秒随机延迟）
- 退信率超过 5% 时应立即暂停，排查原因
- 定期清理无效邮箱（将其标记为 `skipped`）

## 八、API 速查

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/templates` | 模板列表 |
| GET | `/api/templates/{key}` | 模板详情 |
| POST | `/api/templates` | 创建模板 |
| PUT | `/api/templates/{key}` | 更新模板 |
| DELETE | `/api/templates/{key}` | 软删除模板 |
| POST | `/api/templates/preview` | 渲染预览 |
| POST | `/api/kols/upsert` | 写入/更新 KOL |
| GET | `/api/kols/pending` | 待发送 KOL 列表 |
| GET | `/api/kols/{kol_id}` | 查询单条 KOL |
| POST | `/api/kols/{kol_id}/contact-status` | 更新 KOL 联系状态（kol_contact_status） |
| POST | `/api/render/preview` | 渲染模板（不发送） |
| POST | `/api/mail/preview-send` | 发送预览到自己邮箱 |
| POST | `/api/mail/send` | 正式批量发送 |
| POST | `/api/send/confirm` | Bot 确认发送入口 |
| POST | `/api/send/retry` | 重试失败项 |
| POST | `/api/bot/event` | 飞书事件订阅入口（im.message.receive_v1） |
| POST | `/api/bot/card-callback` | 飞书卡片交互回调（按钮点击） |
| POST | `/api/bot/command` | Bot 命令处理（手动/测试） |
| POST | `/api/bot/test-text` | 发送测试文本到群（Admin 用） |
| POST | `/api/bot/test-card` | 发送测试交互卡片到群（Admin 用） |
| GET | `/api/settings` | 当前配置信息 |
| POST | `/api/admin/init-bitable` | 自动创建 KOL 表 + 补齐字段 |
| GET | `/api/admin/bitable-status` | 查询 Bitable 初始化状态 |

## 九、关于示例数据

项目包含 2 条示例邮件模板（`scripts/seed_templates.py`），均为 demo 内容：

- `tmpl_youtube_general_v1` — YouTube 通用合作邀请
- `tmpl_mc_global_v1` — Minecraft 社区邀请

可通过以下方式替换为真实模板：
- Admin 后台页面编辑
- `PUT /api/templates/{key}` API 更新
- 直接修改 `seed_templates.py` 后重新运行

## 十、最小可用验收 Checklist

以下是确认系统可用的最小验收步骤：

- [ ] 后端启动，`/api/health` 返回 `ok`
- [ ] `/api/templates` 返回模板列表
- [ ] Chrome 扩展加载成功，Options 页面测试连接通过
- [ ] 在 YouTube 频道页点击扩展，自动抓取频道名和链接
- [ ] 扩展模板下拉框显示后端模板
- [ ] 点击"写入 KOL"，后端接收到请求（有 Bitable 配置时写入成功）
- [ ] `/api/render/preview` 能正确渲染模板变量
- [ ] `/api/mail/preview-send` 发送预览到操作者邮箱（需 SMTP 配置）
- [ ] Bot 命令 `发送邮件` 返回待发送汇总（需 Bitable 配置）
- [ ] Bot 命令 `测试发送` 发送预览邮件（需 SMTP + Bitable 配置）
- [ ] Bot 命令 `确认发送` 正式发送并播报结果
- [ ] 发送成功的 KOL kol_contact_status 变为 `已联系`，再次提交时被跳过
- [ ] 发送失败的 KOL `last_error` 记录失败原因
- [ ] Bot 命令 `重试失败` 重新发送失败项
