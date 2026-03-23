# 私密信息填写与实际运行指南

本文档面向实际操作人员，按操作顺序说明从零到成功发送邮件的全部步骤。

---

## 第一部分：需要填写的私密信息总览

共 4 项必填信息（启动和登录所必需），其余在 Dashboard 中按用户配置：

| # | 配置项 | 填到哪里 | 来源 | 用途 | 缺失影响 |
|---|--------|---------|------|------|---------|
| 1 | `LARK_APP_ID` | `backend/.env` | 飞书开放平台 | OAuth 登录 + API 访问令牌 | 无法登录，无法读写 Bitable |
| 2 | `LARK_APP_SECRET` | `backend/.env` | 飞书开放平台 | 同上 | 同上 |
| 3 | `LARK_API_BASE` | `backend/.env` | 见 .env.example 说明 | 飞书 API 基础地址 | API 调用失败 |
| 4 | `OAUTH_REDIRECT_URI` | `backend/.env` | 与开放平台后台一致 | OAuth 回调地址 | 登录回调失败 |

> Bitable 表格和 SMTP 邮箱由每个用户在 Dashboard 中自行配置，不再需要在 .env 中全局配置。

---

## 第二部分：逐项获取指南

### 2.1 飞书应用凭证（LARK_APP_ID + LARK_APP_SECRET）

**操作步骤：**

1. 打开浏览器，访问 https://open.feishu.cn/app
2. 登录你的飞书企业账号
3. 点击「创建企业自建应用」
4. 填写应用名称（如 "KOL Mailer"）和描述
5. 创建完成后，进入应用详情页
6. 在左侧菜单选择「凭证与基础信息」
7. 复制 `App ID` 和 `App Secret`

**添加权限：**

8. 在左侧菜单选择「权限管理」→「API 权限」
9. 搜索并添加以下权限：
   - `bitable:app`（多维表格 - 读写）
10. 点击「批量开通」
11. 在左侧选择「版本管理与发布」→ 创建版本 → 提交审核 → 等待管理员审批
12. 审批通过后应用生效

**填入 .env：**

```
LARK_APP_ID=cli_xxxxxxxxxxxx
LARK_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxx
```

### 2.2 多维表格凭证（LARK_BITABLE_APP_TOKEN + LARK_BITABLE_TABLE_ID）

**创建 KOL 表：**

1. 在飞书中打开「多维表格」（Bitable）
2. 创建一个新的多维表格，命名为 "KOL 台账"
3. 在表格中添加以下字段（所有字段类型选「文本」）：

```
kol_id, kol_name, platform, channel_url, email,
country_region, language, followers_text, category,
template_id, template_name, status, operator, notes,
last_error, sent_at, created_at, updated_at
```

> 字段名必须与上述完全一致（英文、下划线、小写）。

**获取 token：**

4. 创建完成后，看浏览器地址栏，URL 格式类似：
   ```
   https://your-company.feishu.cn/base/bascnXXXXXXXXXXXXX?table=tblXXXXXXXXXXXXXXX&view=...
   ```
5. 从中提取：
   - `bascnXXXXXXXXXXXXX` → 这是 `LARK_BITABLE_APP_TOKEN`
   - `tblXXXXXXXXXXXXXXX` → 这是 `LARK_BITABLE_TABLE_ID`

**授权应用访问：**

6. 在多维表格右上角点击「...」→「更多」→「高级权限」
7. 添加你在 2.1 中创建的应用，权限选择「可管理」

**填入 .env：**

```
LARK_BITABLE_APP_TOKEN=bascnXXXXXXXXXXXXX
LARK_BITABLE_TABLE_ID=tblXXXXXXXXXXXXXXX
```

### 2.3 企业邮箱 SMTP（LARK_SMTP_USER + LARK_SMTP_PASSWORD）

**操作步骤：**

1. 打开飞书邮箱（邮件图标或 mail.feishu.cn）
2. 点击右上角齿轮 →「邮箱设置」
3. 找到「客户端设置」或「IMAP/SMTP」部分
4. 确认 SMTP 服务已开启
5. 点击「生成客户端专用密码」
6. 复制生成的密码（只显示一次，请妥善保存）

> 注意：这里的密码不是你的飞书登录密码，而是专门为第三方客户端生成的密码。

**填入 .env：**

```
LARK_SMTP_USER=your.name@yourcompany.com
LARK_SMTP_PASSWORD=xxxxxxxxxxxxxxxxxxxx
```

### 2.4 预览接收邮箱（PREVIEW_RECEIVER_EMAIL）

> **注意：** 本项目使用应用机器人 API 发送群消息，不需要配置自定义机器人 Webhook。
> Bot 功能通过 LARK_APP_ID 的 tenant_access_token + chat_id 实现。

这是你自己的邮箱地址，用于接收测试预览邮件。可以是：
- 你的飞书企业邮箱
- 你的个人邮箱（Gmail、Outlook 等）
- 任何能接收邮件的地址

**填入 .env：**

```
PREVIEW_RECEIVER_EMAIL=your.name@yourcompany.com
```

---

## 第三部分：完整的 .env 文件示例

将 `backend/.env.example` 复制为 `backend/.env`，填入你的真实值：

```bash
cd backend
cp .env.example .env
```

填写后的 `.env` 应类似：

```env
APP_ENV=dev
APP_HOST=0.0.0.0
APP_PORT=8000

DB_PATH=./data/app.db

LARK_APP_ID=cli_xxxxxxxxxxxx
LARK_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxx

LARK_BITABLE_APP_TOKEN=bascnXXXXXXXXXXXXX
LARK_BITABLE_TABLE_ID=tblXXXXXXXXXXXXXXX

LARK_SMTP_HOST=smtp.larksuite.com
LARK_SMTP_PORT=465
LARK_SMTP_USER=your.name@yourcompany.com
LARK_SMTP_PASSWORD=xxxxxxxxxxxxxxxxxxxx
LARK_SMTP_FROM_NAME=Your Name

PREVIEW_RECEIVER_EMAIL=your.name@yourcompany.com
SEND_DELAY_MIN=5
SEND_DELAY_MAX=15
```

> 切勿将 `.env` 文件提交到 Git。

---

## 第四部分：本地启动顺序

```bash
# 1. 进入后端目录
cd youtube-kol-mailer/backend

# 2. 安装 Python 依赖
pip install -r requirements.txt

# 3. 复制并编辑配置
cp .env.example .env
# 用编辑器打开 .env，填入第二部分获取的所有真实值

# 4. 初始化数据库
python ../scripts/init_db.py

# 5. 导入示例模板
python -X utf8 ../scripts/seed_templates.py

# 6. 启动后端服务
python -m uvicorn app:app --reload --port 8000

# 7. 验证启动成功（另开一个终端）
python -X utf8 ../scripts/smoke_test.py
# 预期输出：3/3 passed
```

启动成功后可访问：
- 健康检查：https://api.youtube-kol.com/api/health
- 模板列表：https://api.youtube-kol.com/api/templates
- Admin 后台：https://api.youtube-kol.com/admin/

---

## 第五部分：从启动到成功发送一封测试邮件

确保后端已启动且 `.env` 已填写完整。

### 步骤 1：确认 SMTP 配置可用

```bash
curl -X POST https://api.youtube-kol.com/api/mail/preview-send \
  -H "Content-Type: application/json" \
  -d '{
    "template_key": "tmpl_youtube_general_v1",
    "variables": {
      "kol_name": "TestChannel",
      "category": "Gaming",
      "operator": "YourName",
      "email": "test@example.com"
    }
  }'
```

**成功响应：**
```json
{
  "success": true,
  "message": "Preview email sent",
  "data": {
    "sent_to": "your.name@yourcompany.com",
    "subject": "[PREVIEW] Collaboration Opportunity with TestChannel",
    ...
  }
}
```

**失败排查：**
- `SMTP config incomplete` → .env 中 SMTP 配置未填写
- `SMTP authentication failed` → 密码错误或未使用客户端专用密码
- `PREVIEW_RECEIVER_EMAIL not configured` → 预览邮箱未填写

### 步骤 2：检查邮箱

打开你的 `PREVIEW_RECEIVER_EMAIL` 邮箱，应收到一封：
- 标题以 `[PREVIEW]` 开头
- 发件人显示为 `LARK_SMTP_FROM_NAME <LARK_SMTP_USER>`
- 正文中 `{kol_name}` 已替换为 "TestChannel"
- 正文中 `{category}` 已替换为 "Gaming"
- `{today}` 已替换为当天日期

如果邮件在垃圾箱中，说明域名 SPF/DKIM 可能未配置好（见第十部分）。

### 步骤 3：测试邮件发送成功

恭喜！你的 SMTP 配置正确，系统可以发送邮件。

---

## 第六部分：完整业务流程（扩展 → Bitable → Bot → 发送）

### 步骤 1：安装并配置 Chrome 扩展

1. 打开 Chrome，地址栏输入 `chrome://extensions/`
2. 右上角开启「开发者模式」
3. 点击「加载已解压的扩展程序」→ 选择项目中的 `extension/` 目录
4. 扩展图标出现在工具栏（蓝色方块）
5. 右键扩展图标 → 「选项」
6. 填写：
   - 后端地址：`https://api.youtube-kol.com`
   - 操作者名称：你的名字（如 `Brian`）
7. 点击「测试连接」→ 应显示 "连接成功"

### 步骤 2：在 YouTube 抓取 KOL

1. 在 Chrome 中打开一个 YouTube 频道页面
   - 例如：`https://www.youtube.com/@某频道`
2. 点击工具栏中的扩展图标
3. Popup 自动抓取：频道名、链接、订阅数、分类
4. 邮箱栏：如果自动抓取到了邮箱，会自动填入；如果没有，手动输入
5. 检查信息是否正确，可手动修改任何字段

### 步骤 3：选择模板并写入 KOL

1. 在 Popup 的「邮件模板」下拉框中选择一个模板
2. 可选：填写备注
3. 点击「写入 KOL」按钮
4. 成功提示：`写入成功！KOL ID: yt_xxxxxxxx`
5. 打开飞书多维表格，确认新记录已出现，status 为 `pending`

### 步骤 4：重复步骤 2-3，录入多个 KOL

逐个打开 YouTube 频道页，抓取并写入。每条记录都会在 Bitable 中出现。

### 步骤 5：Bot 汇总待发送

1. 打开飞书群（已添加自定义机器人的群）
2. 发送消息：`@KOL邮件助手 发送邮件`（或你的机器人名称）

   > 如果使用 API 测试（不通过飞书群）：
   > ```bash
   > curl -X POST https://api.youtube-kol.com/api/bot/command \
   >   -H "Content-Type: application/json" \
   >   -d '{"command": "发送邮件", "operator": "Brian"}'
   > ```

3. Bot 在群内回复汇总消息，包含：
   - 待发送数量
   - 模板分布
   - KOL 列表摘要

### 步骤 6：先测试发送

1. 在群内发送：`@KOL邮件助手 测试发送`
2. Bot 取第一条待发 KOL，渲染模板，发送到你的预览邮箱
3. Bot 回复："预览邮件已发送，请检查邮件内容"
4. 打开邮箱，检查预览邮件内容是否正确

### 步骤 7：确认正式发送

1. 预览无误后，在群内发送：`@KOL邮件助手 确认发送`
2. Bot 回复："开始正式发送，X 封，预计耗时 Y 分钟"
3. 系统逐条发送：
   - 每封之间随机延迟 5-15 秒
   - 已 sent 的自动跳过
   - 失败的写入 last_error
4. 发送完成后，Bot 回复结果：
   ```
   📊 发送结果
   总计：10 封
   成功：8 ✅
   失败：1 ❌
   跳过：1 ⏭️

   失败详情：
     - yt_abc123: SMTP 550 mailbox unavailable
   ```

### 步骤 8：处理失败项

1. 检查 Bitable 中 status = `failed` 的记录和 `last_error` 原因
2. 如果是临时错误（网络/超时），在群内发送：`@KOL邮件助手 重试失败`
3. 如果是永久错误（邮箱不存在），在 Bitable 中手动将 status 改为 `skipped`

### 步骤 9：确认最终状态

打开飞书多维表格，检查：
- 成功发送的 KOL：status = `sent`，sent_at 有时间
- 失败的 KOL：status = `failed`，last_error 有原因
- 忽略的 KOL：status = `skipped`

---

## 第七部分：常见报错与排查

### 错误 1：`Failed to get tenant_token: invalid param`

**含义：** 飞书应用凭证不正确或未配置。

**排查：**
1. 检查 `.env` 中 `LARK_APP_ID` 和 `LARK_APP_SECRET` 是否填写
2. 确认值复制完整，无多余空格
3. 确认应用已发布并审批通过
4. 确认应用类型是「企业自建应用」，不是「商店应用」

### 错误 2：`SMTP authentication failed`

**含义：** SMTP 登录失败。

**排查：**
1. `LARK_SMTP_USER` 必须是完整邮箱地址（如 `name@company.com`）
2. `LARK_SMTP_PASSWORD` 必须是「客户端专用密码」，不是飞书登录密码
3. 确认 SMTP 端口为 465（SSL），不是 587
4. 确认 `LARK_SMTP_HOST` 为 `smtp.larksuite.com`
5. 在飞书邮箱设置中确认 SMTP 服务已开启

### 错误 3：`Bitable create failed` 或 `Bitable update failed`

**含义：** 无法写入多维表格。

**排查：**
1. 检查 `LARK_BITABLE_APP_TOKEN` 和 `LARK_BITABLE_TABLE_ID`
2. 确认应用已授权访问该多维表格（高级权限 → 可管理）
3. 确认表中字段名与文档完全一致（英文、下划线、小写）
4. 确认应用已获得 `bitable:app` 权限

### 错误 4：`Variable '{xxx}' used in template but not provided`

**含义：** 模板中使用了变量但 KOL 记录中没有对应值。

**排查：**
- 这是 warning 不是 error，不会阻断发送
- 缺失的变量在邮件中会保留原始 `{xxx}` 文本
- 如需解决：在 Bitable 中补充 KOL 对应字段，或修改模板移除该变量

### 错误 5：`连接失败: Failed to fetch`（扩展）

**含义：** Chrome 扩展无法连接后端。

**排查：**
1. 确认后端已启动：`python -m uvicorn app:app --reload --port 8000`
2. 检查扩展 Options 中的后端地址是否正确
3. 如果后端端口不是 8000，需同步修改 `extension/manifest.json` 中的 `host_permissions`
4. 检查是否有防火墙/杀毒软件阻止本地连接

### 错误 6：`SMTP config incomplete, missing: ...`

**含义：** SMTP 配置缺少必要字段。

**排查：**
- 检查 `.env` 中响应字段是否为空
- 注意 `.env` 中 `=` 号后面不能有注释（行内注释用 `#` 会被当作值的一部分）
- 正确写法：`LARK_SMTP_USER=name@company.com`
- 错误写法：`LARK_SMTP_USER=name@company.com # 我的邮箱`

### 错误 7：`Already sent, skipping`

**含义：** 该 KOL 已成功发送过，系统拒绝重复发送。

**这是正常保护行为。** 如果确实需要重发：
1. 在 Bitable 中将该 KOL 的 status 手动改为 `pending`
2. 清空 `sent_at` 和 `last_error`
3. 重新触发发送

---

## 第八部分：正式上线前安全检查清单

### DNS 配置

- [ ] SPF 记录已添加，允许飞书邮件服务器代发
- [ ] DKIM 记录已配置
- [ ] DMARC 记录已设置（建议初期设为 `p=none` 监控模式）
- [ ] 使用 https://mxtoolbox.com/spf.aspx 验证 SPF
- [ ] 使用 https://mxtoolbox.com/dkim.aspx 验证 DKIM

### 发送纪律

- [ ] 先用「测试发送」给自己发一封预览，确认内容正确
- [ ] 首日发送不超过 20 封
- [ ] 前 3 天按 20 → 50 → 100 封阶梯爬坡
- [ ] 观察退信率，超过 5% 立即暂停
- [ ] 每封邮件间隔至少 5 秒（系统默认 5-15 秒）

### 配置安全

- [ ] `.env` 文件不在 Git 版本控制中（检查 `.gitignore`）
- [ ] `ADMIN_PASSWORD` 已改为强密码
- [ ] 飞书应用 App Secret 仅存在 `.env` 中，未出现在代码里
- [ ] SMTP 密码使用客户端专用密码，不是登录密码

### 功能验证

- [ ] 健康检查 `/api/health` 返回 ok
- [ ] 模板列表 `/api/templates` 返回你的真实模板
- [ ] 扩展能抓取 YouTube 频道信息
- [ ] 扩展能写入 KOL 到 Bitable
- [ ] 预览邮件能到达你的邮箱
- [ ] 预览邮件不在垃圾箱中
- [ ] 预览邮件的发件人名称正确
- [ ] 预览邮件正文中变量全部替换完毕
- [ ] Bot 能在群内返回汇总
- [ ] 正式发送后 Bitable 状态正确更新

### 运行环境

- [ ] 后端服务稳定运行（建议使用 `nohup` 或 `screen` 保持后台）
- [ ] 确认后端机器有稳定的网络连接（需访问飞书 API 和 SMTP）
- [ ] 如需远程访问后端，配置反向代理并添加 HTTPS

---

## 附录：快速命令参考

```bash
# 启动后端
cd backend && python -m uvicorn app:app --reload --port 8000

# 冒烟测试
python -X utf8 scripts/smoke_test.py

# Bitable 集成测试
cd backend && python -X utf8 ../scripts/smoke_test_bitable.py

# 手动触发 Bot 命令（不通过飞书群）
curl -X POST https://api.youtube-kol.com/api/bot/command \
  -H "Content-Type: application/json" \
  -d '{"command": "发送邮件", "operator": "Brian"}'

# 手动发送预览
curl -X POST https://api.youtube-kol.com/api/mail/preview-send \
  -H "Content-Type: application/json" \
  -d '{"template_key": "tmpl_youtube_general_v1", "variables": {"kol_name": "Test", "operator": "Brian", "email": "test@example.com"}}'

# 手动正式发送
curl -X POST https://api.youtube-kol.com/api/mail/send \
  -H "Content-Type: application/json" \
  -d '{"kol_ids": ["yt_xxxxxxxx"]}'

# 查看模板列表
curl https://api.youtube-kol.com/api/templates

# 查看待发送 KOL
curl https://api.youtube-kol.com/api/kols/pending
```
