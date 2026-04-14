# 深云通 RouterOS 多出口 IP 网站可达性巡检

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

## License

This project is licensed under the GNU Affero General Public License v3.0 (AGPLv3).

If your organization's policies do not permit the use of AGPLv3-licensed software, or if you wish to avoid the open-source obligations of AGPLv3, please contact us at: reef@doohuan.com

Full text / notice: [LICENSE](LICENSE)
