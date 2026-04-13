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
```

**`local-only.yaml` 最小示例**（可与内置合并，只覆盖 `urls` 即可）：

```yaml
urls:
  - "https://www.example.com"
  - "https://www.wikipedia.org"
```

**`--local-browser`**：`--config` 里**只需写 `urls`（及 `browser`/`output`/`access` 等如需）**，`router` / `nat` 可留空；**不校验**路由器与 NAT、**不执行** **`get_lo_ips` / `change_nat`**。Excel 第一列公网 IP 为占位 **`本机(无路由器)`**，其余与正式报告一致。

报告根目录由 YAML 的 **`output.dir`** 控制（默认 **`.`**），其下为 **`run_<时间戳>/`**，内含 **xlsx**、**png**。

### Excel 版式

- **纵向**：每个待测 URL **一行**，列为 **`公网IP` / `URL` / `结果` / `截图`**（同一公网 IP 会重复多行）。
- **截图**：嵌入高度固定为 **`output.embed_screenshot_max_height`**（默认 **180** 像素），宽度按原图比例由 **Pillow** 读取尺寸后计算，避免横向拉伸变形；有截图时 **行高**按 **96 dpi** 换算为 Excel **磅**（约 **180px → 135pt**），与图高对齐。无截图行使用 **`output.data_row_height`**（磅，默认约 **24**）。

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
| **不要提交** | 含真实密码的 **`config.yaml`** 副本、业务产生的 **`run_*`**、大 xlsx |
| **可删** | **`build/`**、**`dist/`**、**`*.egg-info/`**（会再生）、本地 **`run_*`** |
| **应提交** | **`domain_test/`**、**`pyproject.toml`**、**`README.md`**、**`LICENSE`**、**`.github/workflows/`** |

打包时请确认 **`pyproject.toml`** 里 **`[tool.setuptools.package-data]`** 包含 **`domain_test/builtin_config.yaml`**，否则安装后无法加载内置默认。

## 常见问题

- **配置校验失败**：**`--config`** 是否含 **`urls`**（至少一条）、**`router.host` / `user` / `password`**、**`nat.target_src`**。
- **SSH / NAT 失败**：账号密码、防火墙、**`router.ssh_encoding`**。
- **Chrome 无法启动**：安装 Chrome，或在 **`--config`** 中设 **`browser.chrome_path`**。
- **PyPI 上传失败**：版本是否已存在、token 是否正确、是否先 **`twine check`**。

## 可选后续

CHANGELOG、**`pytest`** 与 CI、非 0 退出码、JSON 报告等（按需再加）。
