# GitHub Proxy Scanner

一个本地运行的 GitHub 公开代码代理候选提取工具。它通过 GitHub 官方 REST API 搜索公开代码，提取 `host:port` / `scheme://host:port` 格式，去重后写入 CSV/JSONL。

边界：

- 使用 GitHub 官方 API，不做绕过限速、绕过鉴权或批量爬站。
- 默认只做格式提取，不会自动通过代理访问第三方网站。
- 连通性验证必须显式运行，并建议使用你自己控制的 `--check-url`。
- 默认过滤内网、localhost、保留地址等非公网 IP。

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

设置 GitHub Token：

```powershell
$env:GITHUB_TOKEN="github_pat_xxx"
```

GitHub Code Search 通常需要认证。建议使用最小权限的 fine-grained token，只用于读取公开代码搜索结果。

## 扫描一次

```powershell
github-proxy-scanner scan --pages 1 --per-page 50
```

默认输出：

- `data/proxies.csv`
- `data/proxies.jsonl`

查看将会执行的搜索词：

```powershell
github-proxy-scanner scan --dry-run
```

使用自定义搜索词：

```powershell
github-proxy-scanner scan --query '"socks5://" extension:txt' --query 'filename:proxies.txt "http://"'
```

循环扫描：

```powershell
github-proxy-scanner scan --loop --interval-seconds 3600
```

## Web 控制台

启动本地 Web 界面：

```powershell
github-proxy-scanner web --host 127.0.0.1 --port 8787
```

或者使用独立入口：

```powershell
github-proxy-scanner-web --host 127.0.0.1 --port 8787
```

未安装项目时，也可以在项目目录直接运行：

```powershell
python run_web.py --host 127.0.0.1 --port 8787
```

打开：

```text
http://127.0.0.1:8787
```

Web 控制台提供：

- GitHub Token / Token 环境变量配置
- 搜索词、页数、每页数量、请求间隔配置
- 后台扫描任务启动和停止
- 实时日志
- 结果表格、筛选和 CSV 下载
- 手动验证入口

## 可选验证

验证不会在扫描时自动执行。你需要明确指定检查 URL：

```powershell
github-proxy-scanner verify --input data/proxies.csv --output data/verified.csv --check-url https://your-domain.example/ip
```

内置验证器只使用 Python 标准库，支持 HTTP/HTTPS 代理；SOCKS 候选会被标记为 `skipped`。

## 配置

默认查询在 `config/queries.json`：

```json
{
  "queries": ["\"http://\" \"proxy\" extension:txt"],
  "pages_per_query": 1,
  "per_page": 50,
  "min_delay_seconds": 2.0,
  "max_file_bytes": 524288
}
```

可以通过命令行参数覆盖页数、每页数量、请求间隔和输出路径。

## 开发检查

```powershell
python -m unittest discover -s tests
```

## 参考

- GitHub REST API Code Search: https://docs.github.com/en/rest/search/search
- GitHub REST API rate limits: https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api
