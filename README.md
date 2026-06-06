# Job Insight Collector

一个**浏览器自动化 + 数据解析**的技术演示项目：用 Python 驱动真实浏览器，采集公开招聘网站的职位描述（JD），支持登录态复用、列表搜索、详情抓取与 JSONL/CSV 导出。

> 本项目仅用于学习与技术研究，演示如何用浏览器自动化稳定地采集页面数据。请在合法合规前提下使用，详见下方免责声明。

## 合规说明 / Legal Notice

本项目仅供个人学习与技术研究，演示浏览器自动化数据采集技术原理。

**使用须知：**
- 本工具需使用**你自己的账号**通过正常登录流程获取数据，不绕过任何身份验证机制
- 采集结果**仅供个人使用**，不得用于商业目的或向第三方分发
- 请遵守各平台服务条款（Boss 直聘、牛客网等），默认延迟配置（≥2秒/请求）请勿擅自降低
- 采集数据中**不保存招聘者个人信息**（姓名、联系方式等），仅保留岗位和公司维度数据
- 本项目不存储、不分发任何采集数据（data/ 目录已在 .gitignore 中排除）
- 作者不对任何滥用行为承担责任

This project is for personal learning and research only. Users are responsible for
complying with applicable laws and the terms of service of target websites.

## 环境要求

- Python 3.10+
- macOS / Linux / Windows

## 安装

```bash
cd job-insight-collector
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env        # 按需修改
```

## 使用

**重要**：请使用项目虚拟环境里的 Python，不要用系统自带的 `python`（否则会报 `No module named 'playwright'`）。

```bash
source .venv/bin/activate          # 方式一：激活环境
python -m src.cli login

# 或不用 activate（方式二，推荐）：
./run.sh login
```

### 1. 登录（首次必须）

```bash
./run.sh login
```

脚本会用 **CDP 模式启动你本机真实的 Google Chrome**（带远程调试端口 9222，独立配置目录 `auth/cdp-profile/`），并打开 Boss 直聘。因为这是你自己的 Chrome、由系统正常会话启动，所以**不会被识别为自动化、不会白屏**。

在弹出的 Chrome 里**微信扫码**或手机号登录，完成后回终端**按 Enter**（脚本每 2 秒自动检测，检测到会自动继续）。

> 登录后请**保持该 Chrome 窗口开着**，随后直接 `./run.sh scrape`，采集会复用这个已登录窗口。

**如果浏览器没起来 / 想手动控制**

```bash
./run.sh chrome          # 仅启动带调试端口的 Chrome
# 在该窗口里手动登录 Boss，然后：
./run.sh scrape --keyword "Java后端" --city 101010100 --max-pages 1
```

**仍然空白 / 无法跳转**

- 在该 Chrome 地址栏手动打开 `https://www.zhipin.com`，点右上角「登录」
- 有滑块就手动拖动完成；关闭 VPN/代理后刷新（F5）
- 确认右上角出现头像/「消息」后回终端按 Enter

### 2. 检查登录态

```bash
python -m src.cli check
```

### 3. 抓取 JD

```bash
./run.sh scrape --keyword "Java后端" --city 101010100 --max-pages 3
```

**不想登录？直接爬公开数据：**

```bash
./run.sh scrape --keyword "Java后端" --city 101010100 --max-pages 1 --no-login
```

`--no-login` 跳过登录，仅采集搜索列表的公开字段（岗位名、公司、薪资、城市等）。未登录时详情 JD 正文可能不完整、翻多页后 Boss 可能弹登录限制，建议配合较小的 `--max-pages`。

也可在 `.env` 中配置 `KEYWORD`、`CITY`、`MAX_PAGES`、`DELAY_MS`。

输出默认：`data/jobs_YYYYMMDD.jsonl`

### 4. 导出 CSV

```bash
python -m src.cli export --format csv
```

## 配置

| 变量 | 说明 |
|------|------|
| `KEYWORD` | 搜索关键词 |
| `CITY` | 城市 code（见 `config.yaml`） |
| `MAX_PAGES` | 列表滚动页数上限 |
| `DELAY_MS` | 请求间隔基数（实际随机 1x~2x） |
| `HEADLESS` | 是否无头（建议 scrape 时 false） |

常用城市 code 见 [config.yaml](config.yaml)。

## 输出字段

| 字段 | 说明 |
|------|------|
| `job_id` | 职位 ID |
| `job_title` | 岗位名称 |
| `salary_desc` | 薪资描述 |
| `job_description` | JD 正文 |
| `jd_text` | 拼接后的纯文本（便于 Agent / CareerMate） |
| `detail_url` | 详情页链接 |

## 故障排查

| 现象 | 处理 |
|------|------|
| 提示未找到登录态 | 运行 `python -m src.cli login` |
| 登录态无效 | 重新 `login` |
| `job_description` 为空 | 查看 `failed_ids.txt`，加长 `DELAY_MS` 后重试 |
| 滑块/验证码 | 使用有头模式，人工完成后继续 |
| 列表为 0 | 确认关键词与城市 code，检查是否被风控 |

## 项目结构

```
job-insight-collector/
├── src/
│   ├── auth.py      # 登录与登录态校验
│   ├── scraper.py   # 列表 + 详情采集
│   ├── parser.py    # 字段归一化
│   ├── exporter.py  # JSONL/CSV
│   └── cli.py       # 命令行入口
├── auth/            # 登录态（本地）
├── data/            # 输出数据（本地）
└── config.yaml
```

## 与 CareerMate 衔接

导出记录中的 `jd_text` 字段格式与 CareerMate 岗位匹配输入一致，可直接粘贴或后续编写导入脚本写入 RAGForge JD 知识库。
