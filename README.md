# RouterOS 多出口 IP 网站可达性巡检

Copyright (c) 2026 doohuan-ai (REEF Jones)

## 快速开始

### 环境要求

- Python 3.10～3.12
- 本机已安装 Google Chrome

### 安装

```bash
pip install "https://github.com/doohuan-ai/domain-check/releases/latest/download/syt_dc-0.post0-py3-none-any.whl"
syt-dc --version
syt-dc --help
```

### 升级
```bash
pip install --upgrade --force-reinstall "https://github.com/doohuan-ai/domain-check/releases/latest/download/syt_dc-0.post0-py3-none-any.whl"
syt-dc --version
syt-dc --help
```

### 开发环境

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

```bash
cp config.example.yaml config.yaml
syt-dc --config ./config.yaml
```

无路由器本机调试：

```bash
syt-dc --config ./config.yaml --skip-router
```

## 必填配置

最少需要这些字段：

- `urls`
- `router.host`
- `router.user`
- `router.password`
- `nat.target_src`

`--skip-router` 模式下只需 `urls`。

## Maintainer / Contact

- Company: `doohuan-ai`
- Maintainer: `REEF Jones`
- Email: `reef@doohuan.com`
- GitHub: [https://github.com/doohuan-ai](https://github.com/doohuan-ai)

## License

This project is licensed under the GNU Affero General Public License v3.0 (AGPLv3).

If your organization's policies do not permit the use of AGPLv3-licensed software, or if you wish to avoid the open-source obligations of AGPLv3, please contact us at: reef@doohuan.com

Full text / notice: [LICENSE](LICENSE) / [NOTICE](NOTICE)
