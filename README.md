# domain-check - RouterOS 多出口 IP 网站可达性巡检

## 快速开始

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

```bash
cp config.example.yaml config.yaml   # 复制示例后编辑登录凭据
domain-check --template               # 或导出完整模板自行修改
domain-check --wizard
domain-check --config ./config.yaml
```

无路由器本机调试：

```bash
domain-check --config ./config.yaml --skip-router
```

## 必填配置

最少需要这些字段：

- `urls`
- `router.host`
- `router.user`
- `router.password`
- `nat.target_src`

`--skip-router` 模式下只需 `urls`。

## 开源协议

本项目采用 [MIT License](LICENSE) 授权。
