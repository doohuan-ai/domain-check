# domain-check：RouterOS 多出口 IP 网站可达性巡检

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

## 许可协议

完整条文见仓库根目录 [LICENSE](LICENSE)（**Domain-Check License v1.0**，英文）。

简要说明（不构成法律意见；以 LICENSE 正文为准）：

- **分发或向第三方提供**本软件及其修改版（含以网络服务形式提供）时，须**公开完整对应源代码**，并以**同一许可证**免费提供获取方式。
- **商业使用**（例如营利主体在生产环境使用、作为收费或广告支撑产品/服务的一部分、向第三方提供托管/类似服务等）须事先取得版权方**书面授权**（另行商业许可或协议）。
- 个人学习、教育或**真实非营利**用途在遵守上述分发义务的前提下可免费使用与修改。

本安排**不属于** OSI 定义的「宽松开源」范畴；更接近「源码可见 + 商业单独授权」。商业合作请通过本仓库公开渠道联系维护者。
