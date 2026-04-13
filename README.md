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

## 保护版 wheel（可选）

在需降低「解压即得源码」风险时，可在**目标操作系统与架构**上执行：

```bash
pip install -e ".[protected-build]"
python scripts/build_protected_wheel.py
```

产物默认在 `dist/protected/`。安装与命令仍为 `pip install …whl` 与 `domain-check`，用法不变。说明：wheel 内含 PyArmor 原生扩展（`.so` / `.pyd`），须在**与构建机一致的操作系统与架构**上使用，并建议在 Linux / Windows 等环境各自执行一次脚本；文件名可能仍带 `py3-none-any`，勿跨平台混用。混淆不能等同加密，正式分发请自行评估合规与 PyArmor 许可。
