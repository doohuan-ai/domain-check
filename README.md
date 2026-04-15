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

## 出口与 Excel 说明

- **公网IP**：路由器 loopback 上本批次 SNAT 目标（脚本从 RouterOS 读取并切换）。
- **`probe.enabled`**：是否启用探针（总开关）。**`probe.urls: []`** 关闭 trace/连通类探针；**`probe.egress_verify_urls: []`** 关闭「看我 IP」出口校验；两者至少保留一类非空列表，否则校验报错。
- **探针 / 探针链路画像**：来自 **`probe.urls`** 的 HTTP 响应（例如 Cloudflare `cdn-cgi/trace` 的 `ip=`、`loc=` 等键），**不是** Excel 里业务待测的 **URL** 列。只有当你在 `probe.urls` 里放了 trace 类地址时，「探针链路画像」才会出现 `ip`、`loc` 等字段。
- **出口校验**：来自 **`probe.egress_verify_urls`**，与「公网IP」列及（若存在）trace 里的 `ip` 交叉比对；同批次各业务 URL 行复用同一段说明。
- **如何理解「每条 URL 用哪个 IP」**：同一批次内先跑完探针再开浏览器多标签，**不会逐 URL 换出口**；因此「公网IP」列 +「出口校验」一致时，可认为该批次所有业务 URL 与截图页面同源出口。若需逐连接验证，应在路由器侧抓包或看 connection 表，已超出本工具范围。
- **Excel 排版**：同一公网 IP 下若有多条业务 URL，**公网IP**、**探针**、**探针链路画像**、**出口校验** 四列会纵向合并，只在块首展示一份（同批次探针数据本就应该相同；换一批出口 IP 后内容会随之变化）。

## License

This project is licensed under the GNU Affero General Public License v3.0 (AGPLv3).

If your organization's policies do not permit the use of AGPLv3-licensed software, or if you wish to avoid the open-source obligations of AGPLv3, please contact us at: reef@doohuan.com

Full text / notice: [LICENSE](LICENSE)
