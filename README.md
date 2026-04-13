# 域名测试 / 多出口 IP 巡检

在 **RouterOS** 上轮换 **loopback 公网 IP（SNAT）**，用 **Playwright + 本机 Chrome** 访问 URL，生成 **Excel**（含截图）。

- **运行**：**`domain-test --config path/to.yaml`**。先读包内 **`domain_test/builtin_config.yaml`**（完整键 + 默认值，敏感项为空），再与 **`--config`** 文件**深度合并**。
- **最少填写**：**`--config`** 中一般补 **`urls`**、**`router.host` / `user` / `password`**、**`nat.target_src`** 即可；其余沿用内置。
- **带注释的完整模板**：**`domain-test --template`**（输出与 **`builtin_config.yaml`** 一致，含全部 `#` 注释）。仓库根 **[`config.yaml`](config.yaml)** 为可改数值的示例副本。

## 目录与命名

- **`domain_test/`**：Python **包目录**（与 PyPI 发行名 **`domain-test`** 对应）。模块名不能含连字符，故发行名用 **`domain-test`**、import 路径用 **`domain_test`**，这是常见约定（与 **`pip install beautifulsoup4` → `import bs4`** 同类）。
- **结构**：单包 + 根目录 **`config.yaml`** 示例 + **`README`** / **`LICENSE`** / **CI**，对当前体量足够清晰；若日后多子命令或插件，再考虑迁到 **`src/domain_test/`** 布局。

## 环境

Python **3.10+**，本机 **Google Chrome**，能 **SSH** 到路由器；**不必**执行 `playwright install chromium`。

## 安装

```bash
cd /path/to/domain-test
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```

安装后出现命令 **`domain-test`**。未安装为包时：`python -m domain_test --config ./config.yaml`

## 运行

```bash
domain-test --help
domain-test --template
domain-test --config ./config.yaml
# 本机无路由器时：只测 Chrome + Excel（不 SSH、不切 NAT）
domain-test --config ./local-only.yaml --local-browser
# 关闭 Rich 终端美化（日志重定向、CI 等）
domain-test --config ./config.yaml --plain
```

终端默认使用 **[Rich](https://github.com/Textualize/rich)** 输出（圆角分区、步骤前缀、表格汇总、旋转状态），风格接近常见「代码助手」CLI；**stdout 不是 TTY**（如管道）时自动纯文本，也可显式 **`--plain`**。

**`local-only.yaml` 最小示例**（可与内置合并，只覆盖 `urls` 即可）：

```yaml
urls:
  - "https://www.example.com"
  - "https://www.wikipedia.org"
```

**`--local-browser`**：`--config` 里**只需写 `urls`（及 `browser`/`output`/`access` 等如需）**，`router` / `nat` 可留空；**不校验**路由器与 NAT、**不执行** **`get_lo_ips` / `change_nat`**。Excel 第一列公网 IP 为占位 **`本机(无路由器)`**，其余与正式报告一致。

报告根目录由 YAML 的 **`output.dir`** 控制（默认 **`.`**），其下为 **`<excel_prefix>_<时间戳>/`**（与 **`output.excel_prefix`** 一致，默认形如 **`domain_check_1776051316/`**），内含 **xlsx**、**png**。

### 浏览器与访问策略

- **单次运行只启动一次浏览器**（每个出口 IP 一轮）：在 **一个 BrowserContext** 内用 **异步 Playwright** 按批并行打开多个 **Page**（多标签），不再每 URL 开关浏览器。
- **`browser.tabs_batch_size`**：**0** 表示一批内同时跑完全部 URL；设为 **5** 等则每批最多 5 个并行，批与批之间间隔 **`browser.tabs_batch_delay_ms`**。
- **`browser.tab_stagger_ms`**：同一批内，第 *k* 个 URL 会比第 0 个晚 *k*×该毫秒数再开始 **`goto`**（包括 `tabs_batch_size: 0` 时），用于缓和瞬时并发；设为 **0** 则同批内同时发起导航。
- **重试**：单 URL 导航失败（超时、网络错误、HTTP 非成功且非「受限」）时，间隔 **`browser.navigation_retry_delay_ms`** 后再次 **`goto`**（含重定向链），最多 **`browser.navigation_max_attempts`** 次；**403/451/正文关键词受限**不重试。
- **截图**：均为 **视口**（可见区域），非整页长图。
- **渲染等待**：**`post_goto_try_load_state`**（默认再等 **`load`**）+ **`post_goto_settle_ms`**（默认约 **1.5s**）在导航返回后、正文检测与截图前执行，减轻 SPA 只出现加载动画就关页的问题；仍不够时可加大 settle 或把 **`wait_until`** 设为 **`load`** / **`networkidle`**（后者易因长连接卡住，慎用）。
- **参考本地项目 aips-desktop（Electron + playwright-extra + stealth）的思路**（实现见 **`domain_test/browser_launch.py`**）：可选去掉默认 **`--enable-automation`**、追加 **`AutomationControlled`** 相关启动参数；可选 **`locale` / `timezone_id`**（与 aips 默认 **zh-CN / Asia/Shanghai** 类似时可配置）；可选注入 **清理 WebDriver/Selenium 遗留 `window` 属性** 的脚本。**未**引入 Node 的 `playwright-extra`、**未**做 Canvas 指纹噪声（避免误伤通用巡检）。可用 **`browser.use_stealth_launch_args`**、**`inject_automation_cleanup_script`** 等关闭。

### Excel 版式

- **纵向**：每个待测 URL **一行**，列为 **`公网IP` / `URL` / `结果` / `出口探针` / `截图`**（同一公网 IP 会重复多行）。
- **表头**：深蓝底白字、居中、底边加粗；**冻结首行**；**自动筛选**。
- **配色**：**`结果`** 与 **`截图`** 列同底色（正常绿 / 受限与验证墙黄 / 失败红）；**`公网IP`/`URL`/`出口探针`** 为浅灰底。
- **对齐**：**`公网IP`/`URL`/`结果`/`出口探针`** 文字**垂直居中**（URL/结果可换行）；截图列居中。
- **截图**：显示尺寸按 **视口宽高 × `embed_screenshot_max_height`** 固定，**`截图` 列宽**与之匹配；嵌入使用 **`twoCell` 锚点（随单元格移动/隐藏）**，减轻筛选隐藏行后图片仍浮在表上的叠图问题（Excel 对浮动图仍有局限，极端情况可关筛选或拆表）。
- **边框**：全表细线网格。
- 无截图行：**`output.data_row_height`**（磅）。

### 验证墙与随机浏览

- **`access.captcha_keywords`**：HTTP **2xx** 时扫正文，命中则判 **`challenge`（验证墙）**，**不尝试绕过**滑块/验证码；可与业务受限区分颜色（同为黄色系）。
- **`browser.random_surfer_*`**：在 **2xx 且通过正文规则后**、截图前，可 **随机滚动 / 轻微鼠标移动 / 随机点击若干可见链接**（有次数与总时长上限）。**默认关闭**；开启后请自行评估对目标站的影响与合规性。

### 出口探针（可选）

- 配置顶层 **`probe`**：`enabled: true` 与 **`urls`** 列表；在 **每次 `change_nat` 之后、开浏览器测 URL 之前**，由本机 **`urllib`** 发 GET，摘要写入 Excel **「出口探针」**列（同一公网 IP 多行重复同一段摘要）。**无需另建服务**；与浏览器共用当前 PC 的出口路径。

## 输出与判定（简要）

- **成功**：主文档 **HTTP 2xx**。
- **受限**：**403 / 451**；或开启 **`access.enable_body_keyword_check`** 且正文命中 **`access.block_keywords`**。
- **失败**：超时、网络/TLS 错误、其它 **4xx/5xx**。

## 日常开发与发版

1. 改代码后一般 **`git pull`** 即可；若 **`pyproject.toml`** 依赖有变，再执行 **`pip install -e ".[dev]"`**。
2. **发版前**：改 **`pyproject.toml`** 的 **`version`**，并同步 **`domain_test/__init__.py`** 的 **`__version__`**；提交并推送。
3. **本地构建 wheel / sdist**：

```bash
pip install -e ".[dev]"
rm -rf dist build *.egg-info
python -m build
twine check dist/*
```

4. **发布到 PyPI**：在 [pypi.org](https://pypi.org) 注册并创建 [API Token](https://pypi.org/manage/account/token/)，然后：

```bash
export TWINE_USERNAME=__token__
export TWINE_PASSWORD=pypi-你的token
twine upload dist/*
```

5. **GitHub Actions 自动发布**：仓库 **[`.github/workflows/publish-pypi.yml`](.github/workflows/publish-pypi.yml)**；在 GitHub **Settings → Secrets → Actions** 配置 **`PYPI_API_TOKEN`**；推送 **`v0.1.0`** 形式 tag 或手动运行 workflow。**`version` 与 tag 建议一致**。

6. **私有源**：同样 **`python -m build`** 后 **`twine upload`**，加 **`--repository-url`** 与凭据；使用方 **`pip install --index-url https://.../simple/`** 等。

7. **给同事 / 客户（不发 PyPI）**：对方 **`git clone`** → 建 venv → **`pip install -r requirements.txt`** → **`pip install -e .`**；发去密码脱敏后的 **`config.yaml`** 副本。**wheel 内含 `.py` 源码**；对方自备 **`--config`** 配置。

## 仓库卫生

| 建议 | 说明 |
|------|------|
| **不要提交** | 含真实密码的 **`config.yaml`** 副本、业务产生的 **`domain_check_*`** 等输出目录、大 xlsx |
| **可删** | **`build/`**、**`dist/`**、**`*.egg-info/`**（会再生）、本地 **`domain_check_*`** 输出目录 |
| **应提交** | **`domain_test/`**、**`pyproject.toml`**、**`README.md`**、**`LICENSE`**、**`.github/workflows/`** |

打包时请确认 **`pyproject.toml`** 里 **`[tool.setuptools.package-data]`** 包含 **`domain_test/builtin_config.yaml`**，否则安装后无法加载内置默认。

## 常见问题

- **配置校验失败**：**`--config`** 是否含 **`urls`**（至少一条）、**`router.host` / `user` / `password`**、**`nat.target_src`**。
- **SSH / NAT 失败**：账号密码、防火墙、**`router.ssh_encoding`**。
- **Chrome 无法启动**：安装 Chrome，或在 **`--config`** 中设 **`browser.chrome_path`**。
- **PyPI 上传失败**：版本是否已存在、token 是否正确、是否先 **`twine check`**。

## 可选后续

CHANGELOG、**`pytest`** 与 CI、非 0 退出码、JSON 报告等（按需再加）。
