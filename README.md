# 校园通知爬虫 + 多渠道推送系统

自动爬取高校网站通知公告，通过邮件/钉钉/飞书推送到你的设备。

## 功能特性

- **多站点支持**：可同时监控多个学院/部门的通知页面
- **按渠道去重与重试**：按 URL 记录邮件、钉钉的送达状态，失败渠道下次运行重试，成功渠道不重复发送
- **多渠道推送**：支持 QQ 邮件、钉钉机器人、飞书机器人
- **定时运行**：支持 GitHub Actions（免费云）或 Windows 计划任务
- **反爬绕过**：使用 Playwright 持久化浏览器，通过 WAF 检测
- **通用适配**：更换配置中的 URL 和匹配规则即可适配任意高校网站

## 项目结构

```
├── main.py                  # 程序入口
├── config.yaml              # 配置文件（网站、推送渠道等）
├── requirements.txt         # Python 依赖
├── run.bat                  # Windows 一键运行脚本
├── setup_task.ps1           # Windows 计划任务注册脚本
├── .gitignore
├── .github/workflows/       # GitHub Actions 定时运行配置
│   └── schedule.yml
├── notifier/                # 推送模块
│   ├── __init__.py
│   ├── email_sender.py      # 邮件推送（QQ 邮箱 SMTP）
│   └── dingtalk.py          # 钉钉机器人推送
└── storage/                 # 去重存储模块
    ├── __init__.py
    └── history.py           # 基于 JSON 的推送历史管理
```

## 快速开始

### 1. 环境准备

```bash
# 安装 Python 依赖
pip install -r requirements.txt

# 安装 Chromium 浏览器（Playwright 需要）
playwright install chromium
```

### 2. 配置推送渠道

编辑 `config.yaml`，至少配置一种推送方式：

#### 邮件推送（推荐，免费）

```yaml
channels:
  email:
    enabled: true
    smtp_server: smtp.qq.com
    smtp_port: 465
    sender_email: "your_email@qq.com"       # 你的 QQ 邮箱
    sender_password: "your_smtp_code"       # QQ邮箱授权码（非登录密码）
    recipients:
      - "receiver@qq.com"                   # 收件人
```

> **获取 QQ 邮箱授权码**：登录 QQ 邮箱 → 设置 → 账户 → POP3/SMTP 服务 → 开启并生成授权码

#### 钉钉机器人（可选）

```yaml
channels:
  dingtalk:
    enabled: true
    webhook: "https://oapi.dingtalk.com/robot/send?access_token=xxx"
    secret: "your_secret"             # 安全设置→加签
```

#### 飞书机器人（可选）

```yaml
channels:
  feishu:
    enabled: true
    webhook: "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"
```

### 3. 运行

```bash
python main.py
```

首次运行时会自动打开 Chrome 浏览器窗口（用于通过 WAF 验证），后续运行会复用浏览器数据。

## 环境变量（安全推荐）

为避免在配置文件中明文存储敏感信息，可通过环境变量覆盖：

| 环境变量 | 对应配置 | 说明 |
|----------|----------|------|
| `EMAIL_SENDER` | `channels.email.sender_email` | 发件邮箱 |
| `EMAIL_PASSWORD` | `channels.email.sender_password` | SMTP 授权码 |
| `EMAIL_RECIPIENTS` | `channels.email.recipients` | 收件人，逗号分隔 |
| `DINGTALK_WEBHOOK` | `channels.dingtalk.webhook` | 钉钉 Webhook 地址 |
| `DINGTALK_SECRET` | `channels.dingtalk.secret` | 钉钉加签密钥 |
| `FEISHU_WEBHOOK` | `channels.feishu.webhook` | 飞书 Webhook 地址 |

环境变量优先级高于 `config.yaml` 中的值。

## 定时运行

### 方式一：GitHub Actions（推荐，免费）

将项目推送到 GitHub 仓库后，由 GitHub 的云端服务器每天自动运行爬虫，**无需你自己开电脑**。

**工作流说明**（`.github/workflows/schedule.yml`）：

| 环节 | 说明 |
|------|------|
| 定时触发 | 每天北京时间 **8:00** 和 **14:00** 自动执行，也可在 GitHub 网页上手动触发 |
| 安装环境 | 在 Ubuntu 虚拟机上自动安装 Python、Playwright、Chromium 浏览器 |
| 运行爬虫 | 使用仓库 Secrets 中的邮箱密码等敏感信息运行 `python main.py`，推送通知 |
| 保存历史 | 爬完后自动提交 `history.json` 变更并推送回仓库，确保不会重复推送同一条通知 |

**配置步骤**：

1. 将项目推送到 GitHub 仓库
2. 在仓库 Settings → Secrets and variables → Actions 中添加 Secrets：
   - `EMAIL_SENDER`、`EMAIL_PASSWORD`、`EMAIL_RECIPIENTS` 等
3. 工作流默认每天北京时间 8:00 和 14:00 自动运行

> **注意**：GitHub Actions 的虚拟机上没有可见的浏览器窗口，部分 WAF 严格的网站可能会拦截请求。如果你的目标网站属于这种情况，建议使用方式二（Windows 计划任务）。

### 方式二：Windows 计划任务

```powershell
# 以管理员身份运行 PowerShell，执行：
.\setup_task.ps1
```

默认每天 12:00 和 22:00 运行。可在 `setup_task.ps1` 中修改时间。

## 适配其他高校

修改 `config.yaml` 中的 `targets` 配置即可：

```yaml
targets:
  - name: 你的学校名称
    url: https://www.xxx.edu.cn/
    base_url: https://www.xxx.edu.cn
    list_pages:
      - url: https://www.xxx.edu.cn/index/tzgg.htm
        section: 通知公告
    link_patterns:
      - info/       # 通知详情页 URL 中特有的关键字
```

- `list_pages`：要监控的通知列表页 URL
- `link_patterns`：用于识别通知链接的 URL 关键字（如 `info/`、`content.jsp`）
- `lookback_days`：只推送最近 N 天的通知（在 `schedule` 中配置）

## 依赖项

| 包名 | 用途 |
|------|------|
| playwright | 自动化浏览器，处理 JS 反爬 |
| beautifulsoup4 | HTML 解析 |
| lxml | HTML 解析加速 |
| PyYAML | 配置文件解析 |

## 注意事项

- 首次运行时会打开可见的 Chrome 窗口，这是为了通过网站 WAF 验证，之后会复用浏览器数据目录
- `history.json` 同时保存待发送通知和各渠道送达状态，不要手动删除。失败记录在后续运行重试，不受 `lookback_days` 限制；暂时关闭的渠道会保留待发送记录，重新启用后继续。
- 待发送渠道以首次发现通知时启用的邮件、钉钉渠道为准。新启用的渠道不补发此前历史。邮件按整批收件人记录状态，部分拒收时重试整批，已收到的收件人可能重复收到。
- 旧版历史记录没有渠道信息，升级时按已发送处理，不批量重发。旧版已经误记为成功的通知无法自动判断是否送达，需要手动核对后删除对应记录，再让爬虫重新抓取。
- 不要同时启动多个实例。网络超时但服务端实际已接收、或发送后保存状态前程序退出时，下次重试仍可能重复送达。
- QQ 邮箱 SMTP 授权码不是登录密码，需要在 QQ 邮箱设置中单独生成
- GitHub Actions 运行时无法打开可见浏览器窗口，部分严格 WAF 站点可能拦截

## License

MIT
