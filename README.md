# 域名测试 / 多出口 IP 巡检

在 **RouterOS** 上轮换 **loopback 公网 IP（SNAT）**，用 **Playwright + 本机 Chrome** 访问 URL，生成 **Excel**（含截图）。

- **运行**：**`domain-test -c path/to.yaml`**。先读包内 **`domain_test/builtin_config.yaml`**（完整键 + 默认值，敏感项为空），再与 **`-c`** **深度合并**。
- **最少填写**：**`-c`** 中一般补 **`urls`**、**`router.host` / `user` / `password`**、**`nat.target_src`** 即可；其余沿用内置。
- **带注释的完整模板**：**`domain-test --print-template`**（输出与 **`builtin_config.yaml`** 一致，含全部 `#` 注释）。**`domain-test --help`** 末尾为可传键摘要。仓库根 **[`config.yaml`](config.yaml)** 为可改数值的示例副本。

## 目录说明：为什么是 `domain_test/` 包？

**`domain_test/`** 是 **Python 包**（可安装、可 `import`、可打进 wheel）。**`scripts/run_domain_test.py`** 是历史遗留：在未 `pip install` 时把项目根塞进 **`sys.path`** 再调 **`main()`**；现在用 **`pip install -e .`** 或 **`python -m domain_test`** 即可，该脚本已删除。

## 环境

Python **3.10+**，本机 **Google Chrome**，能 **SSH** 到路由器；**不必**执行 `playwright install chromium`。

## 安装

```bash
cd /path/to/domain-test
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```

安装后出现命令 **`domain-test`**。未安装为包时：`python -m domain_test -c ./config.yaml`

## 运行

```bash
domain-test --help
domain-test --print-template
domain-test -c ./config.yaml
```

报告根目录由 YAML 的 **`output.dir`** 控制（默认 **`.`**），其下为 **`run_<时间戳>/`**，内含 **xlsx**、**png**。

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

7. **给同事 / 客户（不发 PyPI）**：对方 **`git clone`** → 建 venv → **`pip install -r requirements.txt`** → **`pip install -e .`**；发去密码脱敏后的 **`config.yaml`** 副本。**wheel 内含 `.py` 源码**；对方自备 **`-c`** 配置。

## 仓库卫生

| 建议 | 说明 |
|------|------|
| **不要提交** | 含真实密码的 **`config.yaml`** 副本、业务产生的 **`run_*`**、大 xlsx |
| **可删** | **`build/`**、**`dist/`**、**`*.egg-info/`**（会再生）、本地 **`run_*`** |
| **应提交** | **`domain_test/`**、**`pyproject.toml`**、**`README.md`**、**`LICENSE`**、**`.github/workflows/`** |

打包时请确认 **`pyproject.toml`** 里 **`[tool.setuptools.package-data]`** 包含 **`domain_test/builtin_config.yaml`**，否则安装后无法加载内置默认。

## 常见问题

- **配置校验失败**：**`-c`** 是否含 **`urls`**（至少一条）、**`router.host` / `user` / `password`**、**`nat.target_src`**。
- **SSH / NAT 失败**：账号密码、防火墙、**`router.ssh_encoding`**。
- **Chrome 无法启动**：安装 Chrome，或在 **`-c`** 中设 **`browser.chrome_path`**。
- **PyPI 上传失败**：版本是否已存在、token 是否正确、是否先 **`twine check`**。

## 可选后续

CHANGELOG、**`pytest`** 与 CI、非 0 退出码、JSON 报告等（按需再加）。
