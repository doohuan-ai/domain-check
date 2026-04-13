# domain-check

`domain-check` 用于在 RouterOS 多出口 IP 场景下，批量访问 URL 并生成 Excel 巡检报告。

## 快速开始

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

```bash
domain-check --template
domain-check --wizard
domain-check --config ./config.yaml
```

无路由器本机调试：

```bash
domain-check --config ./config.yaml --local-browser
```

## 必填配置

最少需要这些字段：

- `urls`
- `router.host`
- `router.user`
- `router.password`
- `nat.target_src`

`--local-browser` 模式下只需 `urls`。

## 开源协议

本项目采用 [MIT License](LICENSE) 授权。
