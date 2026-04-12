# 域名测试 / 多出口 IP 巡检

在 **RouterOS（MikroTik）** 上为指定内网源地址轮换 **loopback 公网 IP（SNAT）**，用 **Playwright** 驱动本机 **Google Chrome（无痕）** 访问 URL，根据 **HTTP 状态码与可选正文关键词** 判断是否可达，并生成 **Excel** 报告（含失败/受限时的截图嵌入）。

- **配置文件**：仅使用项目根目录下的 **`config.yaml`**。程序会从**当前工作目录**逐级向上查找 `config.yaml`，找不到时再尝试**可编辑安装**时的源码项目根。
- **待测 URL**：**`-d` / `--domains`** 指向外部文本文件（不写进 `config.yaml`）。
- **报告目录**：**`-o` / `--output DIR`**（**可选**），**不在** `config.yaml` 中配置。未写 **`-o`** 时，**报告根目录就是当前工作目录（cwd）**，即在**你执行命令时所在目录**下直接创建 **`run_<时间戳>/`**（内含截图与 Excel）。指定 **`-o`** 时，根目录为你给出的路径（相对路径仍相对 cwd）。

旧版基于 OCR 的脚本 [`domain-test.py`](domain-test.py) 已废弃。

**从开发到发版、分发的完整步骤清单**见 **[`docs/后续操作指南.md`](docs/后续操作指南.md)**。

## 环境要求

- Python **3.10+**
- 能 SSH 到路由器；测试机能通过该路由器上网
- 本机已安装 **Google Chrome**

**无需**执行 `playwright install chromium`：使用系统已安装的 Chrome。

## 安装

### 使用 venv（通用）

```bash
cd /path/to/domain-test
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```

### 使用 conda（macOS 示例）

```bash
cd /path/to/domain-test
conda create -n domain-test python=3.11 -y
conda activate domain-test
pip install -r requirements.txt
pip install -e .
```

安装后，在**已激活**的环境中会出现终端命令 **`domain-test`**（与 **yt-dlp** 类似：pip 在环境的 **`bin/`**（Windows 为 **`Scripts/`**）里放一个入口脚本，调用本包的 **`cli_entry()`**）。**不必**先打成独立 exe 才能用。

## 给别人用：两种常见方式

### 方式 A：从 Git 克隆 + 可编辑安装（适合同事/内网、改代码即生效）

1. 把本仓库推到 **GitHub / GitLab / 自建 Git**（对方需有读权限）。  
2. 对方机器上：  
   ```bash
   git clone <你的仓库URL> domain-test
   cd domain-test
   python3 -m venv .venv && source .venv/bin/activate   # 或 conda 见上
   pip install -r requirements.txt
   pip install -e .
   ```  
3. 对方复制 **`config.yaml`** / **`.env.example`** 按说明填写，准备 **`domains.txt`**，执行 **`domain-test -d domains.txt`**（可加 **`-o`** 指定目录）。  
4. **`pip install -e .`** 会在克隆目录下生成 **`*.egg-info/`**，可删，下次再 `pip install -e .` 会重建。

### 方式 B：wheel + PyPI / 私有源（`pip install domain-test`）

#### 本地构建与自检

```bash
pip install -e ".[dev]"   # 从源码树安装并带上 build、twine；或单独: pip install build twine
python -m build          # 生成 dist/*.whl 与 dist/*.tar.gz
twine check dist/*
pip install dist/*.whl --force-reinstall
domain-test --help
```

#### 发布到 PyPI（官方）

1. 在 [pypi.org](https://pypi.org/account/register/) 注册；创建 [API token](https://pypi.org/manage/account/token/)（范围至少包含要上传的项目）。  
2. **项目名**：`pyproject.toml` 里为 **`domain-test`**。若 PyPI 上已被占用，需改名并同步修改 **`[project] name`** 与文档中的安装命令。  
3. **本机上传**（勿把 token 写进仓库）：  
   ```bash
   export TWINE_USERNAME=__token__
   export TWINE_PASSWORD=pypi-xxxxxxxx   # 你的 token
   twine upload dist/*
   ```  
4. **对方安装**：`pip install domain-test`（建议锁版本：`pip install "domain-test==0.5.0"`）。  
5. **wheel 不含** `config.yaml`；对方需自备配置与 `domains.txt`（可从你的 Git 仓库复制模板）。

#### 用 GitHub Actions 自动发布（已包含在仓库中）

- 工作流：[`.github/workflows/publish-pypi.yml`](.github/workflows/publish-pypi.yml)。  
- 在 GitHub 仓库 **Settings → Secrets and variables → Actions** 新建 **`PYPI_API_TOKEN`**（值为 PyPI 的 token）。  
- 推送 **`v` 开头的 tag**（例如 `git tag v0.5.0 && git push origin v0.5.0`）或手动 **Actions → Publish to PyPI → Run workflow**，会执行 **`python -m build`** 并 **`twine upload`**。  
- 首次发布前务必本地 **`twine check`** 通过；tag 与 **`pyproject.toml` 里的 `version`** 建议一致。

#### 发布到私有 PyPI / Nexus / DevPI 等

本机或 CI 中指定仓库 URL 与凭据（具体 URL 以你们制品库文档为准）：

```bash
python -m build
twine upload dist/* \
  --repository-url "https://your-nexus.example.com/repository/pypi-hosted/" \
  -u YOUR_USER \
  -p YOUR_PASSWORD_OR_TOKEN
```

对方安装示例：

```bash
pip install domain-test \
  --index-url "https://your-nexus.example.com/repository/pypi-group/simple/" \
  --trusted-host your-nexus.example.com
```

或在 **`pip.conf`** 里配置 **`extra-index-url`**，使默认仍走 PyPI、私有包走公司源。

#### 许可证

仓库根目录包含 **[`LICENSE`](LICENSE)**（MIT），已写入 **`pyproject.toml`** 供打包元数据使用。

## 截图与 Playwright

失败/受限等需要留证时，使用 **Playwright 自带的** API **`page.screenshot(..., full_page=True)`** 保存 **全页 PNG**（整页可滚动区域），不是操作系统截屏。成功时默认不截图；若开启 **`browser.screenshot_on_success`**，同样走 Playwright 截图 API。

## 跨平台（Windows / macOS / Linux）

代码按 **三端** 设计（路径用 **`pathlib`**、Chrome 用 **channel / 探测**、无 **playwright install chromium** 依赖）。**不能称为「已在所有环境完美验证」**：路由器输出编码、本机 Chrome 路径、防火墙与 headless 策略因机而异。建议在你要交付的 **每种 OS 上各跑一轮**；若某端异常，把终端报错与 **`router.ssh_encoding` / `CHROME_PATH`** 一并排查。

## 配置

1. 编辑项目内 **`config.yaml`**（路由器、`nat.target_src`、`browser`、`output` 中的 Excel 前缀与嵌入尺寸等）。**不包含**报告根路径。
2. 复制 [`.env.example`](.env.example) 为 **`.env`**（可选），或导出 `ROUTER_*`、`CHROME_PATH` 等。

## 从零开始做一次测试（含 Mac + conda）

1. **进入项目目录**（含 **`config.yaml`**）：`cd /path/to/domain-test`。  
2. **conda**：`conda create -n domain-test python=3.11 -y` → `conda activate domain-test` → `pip install -r requirements.txt` → **`pip install -e .`**。（若用 venv，见上文「安装」。）  
3. **编辑 `config.yaml`**：`router.host/port/user`、`nat.target_src` 等；密码建议 **`.env`** 里 **`ROUTER_PASSWORD`**。  
4. **准备 `domains.txt`**：可复制 [`domains.example.txt`](domains.example.txt) 再改 URL。  
5. **安装 Google Chrome**（macOS 一般为 `/Applications/Google Chrome.app`）。  
6. **网络**：本机能 **SSH 路由器**，且访问外网走你要测的 NAT。  
7. **运行**（在项目根，且 conda 已 **activate**）：  
   - 不写 **`-o`**：报告在**当前目录**下的 **`run_<时间戳>/`**：  
     `domain-test -d domains.txt`  
   - 指定输出根目录：  
     `domain-test -d domains.txt -o ./reports`  
   - 首次建议：  
     `domain-test -d domains.txt --no-headless`  
8. 打开 **`run_<时间戳>/`**（或 **`-o`** 所指目录下的 **`run_<时间戳>/`**）里的 **xlsx** 与 **png**。

## 运行

**必填**：**`-d`**（域名列表文件）。**可选**：**`-o` / `--output`**（报告根目录；**省略则根目录为当前工作目录 cwd**，即在本目录下生成 **`run_<时间戳>/`**）。

```bash
domain-test -d path/to/domains.txt          # 报告在当前目录: ./run_<时间戳>/
domain-test -d path/to/domains.txt -o /tmp/out
```

短选项 **`-d`** 与 **`--domains`** 等价。示例列表见 [`domains.example.txt`](domains.example.txt)。

**可选参数**（仅覆盖内存中的浏览器相关项，**不写回** `config.yaml`）：

| 参数 | 说明 |
|------|------|
| `--headless` | 强制无头模式（`browser.headless=true`） |
| `--no-headless` | 强制有界面，便于调试（`browser.headless=false`） |
| `--timeout MS` | 单次 `page.goto` 超时（毫秒），覆盖 `browser.goto_timeout_ms` |

`--headless` 与 `--no-headless` 不能同时使用。

示例：

```bash
domain-test -d domains.txt -o /tmp/domain-reports --no-headless --timeout 120000
```

未安装为包时：

```bash
python -m domain_test -d domains.example.txt -o ./reports
```

### Chrome 与无痕

- 默认 **`browser.channel: chrome`**，并带 **`--incognito`**（见 `browser.incognito`）。
- 若自动探测失败，设置 **`CHROME_PATH`** 或 **`browser.chrome_executable`**。

### Chrome 启动失败

若未安装 Chrome 或路径不对，程序会 **`RuntimeError`** / **`FileNotFoundError`** 退出，并提示安装官方 Chrome 或配置路径。

## 输出

- 根目录：写了 **`-o`** 用你的路径；**未写**则根目录为**启动命令时的 cwd**（相对路径仍相对 cwd）。其下为 **`run_<时间戳>/`**。
- 内含 PNG 截图（失败/受限时为主；成功时见 `browser.screenshot_on_success`）。
- Excel 文件名：`config.yaml` 中 **`output.excel_prefix`** + 时间戳 + `.xlsx`。

## 判定规则（简要）

- **成功**：主文档 **HTTP 2xx**。
- **受限**：**403 / 451**；或开启正文关键词检测时命中。
- **失败**：超时、网络/TLS 错误、其它 **4xx/5xx**。

## 模块结构

| 文件 | 职责 |
|------|------|
| [`domain_test/paths.py`](domain_test/paths.py) | 解析项目内 `config.yaml` 路径 |
| [`domain_test/router_ssh.py`](domain_test/router_ssh.py) | SSH / NAT / loopback IP |
| [`domain_test/browser_check.py`](domain_test/browser_check.py) | Playwright + 本机 Chrome |
| [`domain_test/chrome_resolve.py`](domain_test/chrome_resolve.py) | 跨平台查找 Chrome |
| [`domain_test/domains_file.py`](domain_test/domains_file.py) | 从文本加载 URL |
| [`domain_test/reporting_excel.py`](domain_test/reporting_excel.py) | Excel 报告 |
| [`domain_test/runner.py`](domain_test/runner.py) | CLI 与主流程 |
| [`domain_test/config.py`](domain_test/config.py) | 加载 YAML 与环境变量 |

## 关于「--router-host」

文档中曾提到的 **`--router-host`** 表示一种**尚未实现**的设想：在命令行里临时指定 **路由器 SSH 地址**，效果上等同于设置环境变量 **`ROUTER_HOST`** 或 `config.yaml` 里的 **`router.host`**，方便脚本/CI 切换设备而不用改文件。

当前如需切换路由器，请使用 **`ROUTER_HOST`**（及 **`ROUTER_PORT`** 等）或编辑 **`config.yaml`**。路由器密码仍建议只用环境变量 **`ROUTER_PASSWORD`**。

## 架构与改进建议

当前结构（**配置加载 → SSH 编排 → Playwright 检测 → Excel**、按模块拆分）对中小型 CLI 工具是**合理且常见**的做法，并非唯一「最佳实践」，但易读、易测。

可考虑的后续改进：

| 方向 | 说明 |
|------|------|
| **结构化日志** | 使用 `logging` + 可选 JSON 行日志，便于排障与自动化解析。 |
| **退出码约定** | 区分配置错误、网络错误、部分 URL 失败（如用 2 表示有失败项）。 |
| **并发与隔离** | 多出口测试目前串行；若需加速可评估每 IP 独立进程（注意 NAT 切换顺序）。 |
| **结果格式** | 除 Excel 外输出 **JSON**，便于接入 CI 与其它系统。 |
| **测试** | 对 `domains_file`、`chrome_resolve`、`parse_lo_ips` 等做单元测试；Playwright 用录屏或 mock。 |
| **类型与配置校验** | 可用 **pydantic** 校验 YAML，减少运行时才发现配置错误。 |
| **依赖注入** | `run()` 注入「路由器客户端」「浏览器工厂」接口，便于 mock 集成测试。 |

## 常见问题

- **找不到 config.yaml**：在包含该文件的**项目根目录**下执行命令，或在该目录执行 `pip install -e .`。
- **SSH 乱码**：调整 `router.ssh_encoding`。
- **Chrome 无法启动**：按报错安装 Chrome 或设置 `CHROME_PATH`。

## `domain_test.egg-info` 目录说明

使用 **`pip install -e .`** 时 setuptools 会生成 **`*.egg-info/`**（内含包名、版本、依赖、**`domain-test` 入口点**等）。**可以整目录删除**，不影响源码；下次再执行 **`pip install -e .`** 会重新生成。已加入 **`.gitignore`**，一般不要提交到 Git。
