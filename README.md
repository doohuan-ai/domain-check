# domain-check

`domain-check` 用于在 RouterOS 多出口 IP 场景下，批量访问 URL 并生成带截图的 Excel 巡检报告。

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

## 输出结果

- 在 `output.dir` 下生成 `domain_check_<timestamp>/`
- 目录内包含 `xlsx` 报告和 `png` 截图

## 开发与打包

```bash
pip install -e ".[dev]"
rm -rf dist build *.egg-info
python -m build
twine check dist/*
```

## 仓库约定

- 对外项目名和命令：`domain-check`
- Python 包内部目录：`domain_check`（Python 模块名不能包含 `-`）
- 不要提交含真实密码的配置文件和巡检输出目录
