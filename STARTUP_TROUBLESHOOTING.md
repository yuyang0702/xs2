# DeterminFlow 启动故障排除指南

## 问题诊断

### 问题：BAT启动器报错"Service failed to start (exit code 1)"

这个错误表示 Python 服务在启动时崩溃。以下是诊断步骤：

#### 1. **直接运行 Python 脚本获取详细错误信息**

打开 PowerShell 或 CMD，进入项目目录：

```powershell
cd C:\xs2\DeterminFlow
.\.venv\Scripts\python.exe run.py
```

这会显示具体的错误堆栈跟踪。

#### 2. **检查启动日志**

启动脚本现已改进，会自动生成日志文件：

```
C:\xs2\DeterminFlow\logs\startup_yyyyMMdd_HHmmss.log
```

查看最新的日志文件获取更多细节。

#### 3. **常见问题与解决方案**

| 错误 | 原因 | 解决 |
|------|------|------|
| `ModuleNotFoundError: No module named 'xxx'` | 依赖未安装 | 运行 `pip install -r requirements.txt` |
| `FileNotFoundError: [Errno 2] No such file or directory` | 配置文件或目录缺失 | 确认 `.env` 和 `config/` 文件存在 |
| `Port 8020 already in use` | 端口被占用 | 修改 `.env` 中的 `WEB_PORT` 或关闭占用该端口的程序 |
| `Uvicorn/FastAPI startup error` | 应用逻辑错误 | 查看详细错误堆栈，检查 `src/web_server.py` |

### 推荐的启动流程

```powershell
# 1. 进入项目目录
cd C:\xs2\DeterminFlow

# 2. 激活虚拟环境
.\.venv\Scripts\Activate.ps1

# 3. 确保依赖最新
python -m pip install --upgrade pip
pip install -r requirements.txt

# 4. 直接运行（查看实时输出）
python run.py

# 5. 如果成功，按 Ctrl+C 停止，然后使用脚本启动
.\start_determinflow.bat
```

## 改进的启动脚本特性

新版 `start_determinflow.ps1` 现在：

- ✅ 自动捕获启动输出到日志文件
- ✅ 启动失败时显示最后50行日志
- ✅ 提供清晰的错误信息而不是模糊的"exit code 1"
- ✅ 保留完整的诊断信息用于故障排除

## 环境要求

- Python 3.11+ (当前: 3.11.9 ✅)
- 虚拟环境: `.venv` ✅
- 所有依赖: `requirements.txt` 

## 必要的配置文件

启动前确保存在：

```
DeterminFlow/
├── .env                          # 环境变量配置
├── config/
│   ├── models_config.json       # 模型配置
│   └── (其他配置文件)
├── logs/                         # 日志目录
├── data/                         # 数据存储
└── web/dist/                     # 前端构建输出
```

如果缺少 `.env`，脚本会从 `.env.example` 复制。

## 性能优化建议

在 `.env` 中调整这些参数以优化性能：

```env
# 并发限制（CPU密集型任务）
UVICORN_LIMIT_CONCURRENCY=200      # 默认200，可根据CPU调整
UVICORN_BACKLOG=2048               # 连接队列

# 日志级别
LOG_LEVEL=INFO                      # 可改为 DEBUG 获取详细日志

# Web 服务器
WEB_HOST=0.0.0.0                   # 监听地址
WEB_PORT=8020                      # 监听端口
```

## 前端构建

脚本会自动检测前端源码是否更新并重新构建。如果需要手动构建：

```bash
cd web
npm install
npm run build
```

## 插件系统

脚本会自动检查并安装必要的插件。如果插件安装失败，可以手动运行：

```bash
python setup_plugins.py
```

## 获取更多帮助

1. 查看详细日志：`logs/` 目录
2. 检查 `.env` 配置
3. 运行 `python run.py` 查看实时输出
4. 查看项目文档：`DESIGN.md`, `README.md`
