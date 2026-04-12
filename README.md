# 域名测试 / 多出口 IP 巡检

在 **RouterOS** 上轮换 **loopback 公网 IP（SNAT）**，用 **Playwright + 本机 Chrome** 访问 URL，生成 **Excel**（含截图）。

- **配置**：包内有默认 YAML；可用环境变量 **`ROUTER_*`、`ROUTER_PASSWORD`** 等；或用 **`-c`** 指定自己的 YAML（与默认合并）。**各键含义写在 [`config.yaml`](config.yaml) 文件顶部的注释里**，复制该文件改数值即可。
- **域名列表**：**`-d`** 指向文本文件；**报告目录**：**`-o`** 可选，不写则在当前目录生成 **`run_<时间戳>/`**。
- **发版、PyPI、给别人用**：见 **[`docs/后续操作指南.md`](docs/后续操作指南.md)**。

## 环境

Python **3.10+**，本机 **Google Chrome**，能 **SSH** 到路由器；**不必**执行 `playwright install chromium`。

## 安装

```bash
cd /path/to/domain-test
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```

安装后出现命令 **`domain-test`**。未打包安装时：`python -m domain_test ...`

## 运行

```bash
domain-test --help
domain-test -d domains.txt
domain-test -d domains.txt -c ./config.yaml -o ./reports -W
```

常用选项：**`-d`** 域名文件；**`-c`** 配置 YAML；**`-o`** 报告根目录；**`-H`** 无头；**`-W`** 有界面（见下）；**`-t`** 超时毫秒。Chrome 路径异常时设 **`CHROME_PATH`**。

## 输出与判定（极简）

- 目录：**`-o`** 或 cwd 下的 **`run_<时间戳>/`**，内含 **xlsx**、**png**。
- **成功** 2xx；**受限** 403/451 或（若开启）正文关键词；**失败** 超时与其它错误码。

## 常见问题

- 缺路由器或 NAT 源：配 **`.env`** 或 **`-c`** 里的 `router` / `nat.target_src`。
- SSH 乱码：改 **`router.ssh_encoding`**（见 `config.yaml` 注释）。
- Chrome 起不来：安装 Chrome 或 **`CHROME_PATH`**。
