#!/usr/bin/env bash
# DeterminFlow 通用启动脚本 - Linux/macOS
# 支持自动依赖检测和安装

set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo ""
echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}DeterminFlow 通用启动脚本${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""

# [1/6] 环境检查
echo -e "${YELLOW}[1/6] 环境检查...${NC}"
if [ -f "$ROOT/scripts/check_environment.py" ]; then
    for cmd in python3 python py; do
        if command -v $cmd &> /dev/null; then
            $cmd "$ROOT/scripts/check_environment.py" 2>/dev/null || true
            break
        fi
    done
else
    echo -e "${YELLOW}⚠️  环境检查脚本不存在，跳过...${NC}"
fi
echo ""

# [2/6] 查找 Python 3.11+
echo -e "${YELLOW}[2/6] 查找 Python 3.11+...${NC}"
PYTHON=""
for candidate in "$ROOT/.venv/bin/python" python3.13 python3.12 python3.11 python3 python; do
    if command -v $candidate &> /dev/null || [ -x "$candidate" ]; then
        VERSION=$($candidate --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
        MAJOR=$(echo $VERSION | cut -d. -f1)
        MINOR=$(echo $VERSION | cut -d. -f2)

        if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 11 ]; then
            PYTHON=$candidate
            echo -e "${GREEN}✅ 找到 Python $VERSION${NC}"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo -e "${RED}❌ 错误: 未找到 Python 3.11+${NC}"
    echo ""
    echo -e "${YELLOW}请安装 Python 3.11 或更高版本:${NC}"
    echo "  Ubuntu/Debian: sudo apt install python3.11 python3.11-venv"
    echo "  CentOS/RHEL: sudo yum install python311"
    echo "  macOS: brew install python@3.11"
    echo "  或从官网下载: https://www.python.org/downloads/"
    echo ""
    exit 1
fi
echo ""

# [3/6] 配置虚拟环境
echo -e "${YELLOW}[3/6] 配置虚拟环境...${NC}"
VENV_PYTHON="$ROOT/.venv/bin/python"
if [ ! -f "$VENV_PYTHON" ]; then
    echo -e "${CYAN}创建虚拟环境...${NC}"
    $PYTHON -m venv "$ROOT/.venv"
    echo -e "${GREEN}✅ 虚拟环境创建成功${NC}"
else
    echo -e "${GREEN}✅ 虚拟环境已存在${NC}"
fi
echo ""

# [4/6] 安装 Python 依赖
echo -e "${YELLOW}[4/6] 安装 Python 依赖...${NC}"
if [ -f "$ROOT/requirements.txt" ]; then
    echo -e "${CYAN}更新 pip...${NC}"
    $VENV_PYTHON -m pip install --quiet --upgrade pip setuptools wheel

    echo -e "${CYAN}安装依赖包（首次运行可能需要几分钟）...${NC}"
    $VENV_PYTHON -m pip install --quiet -r "$ROOT/requirements.txt"

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✅ Python 依赖安装完成${NC}"
    else
        echo -e "${YELLOW}⚠️  部分依赖安装失败，但继续启动...${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  requirements.txt 不存在，跳过依赖安装${NC}"
fi
echo ""

# [5/6] 初始化配置
echo -e "${YELLOW}[5/6] 初始化配置...${NC}"
if [ ! -f "$ROOT/.env" ]; then
    if [ -f "$ROOT/.env.example" ]; then
        cp "$ROOT/.env.example" "$ROOT/.env"
        echo -e "${GREEN}✅ 从 .env.example 创建 .env${NC}"
    else
        echo -e "${YELLOW}⚠️  .env.example 不存在，跳过${NC}"
    fi
else
    echo -e "${GREEN}✅ .env 已存在${NC}"
fi

if [ ! -f "$ROOT/config/models_config.json" ]; then
    if [ -f "$ROOT/config/models_config.example.json" ]; then
        mkdir -p "$ROOT/config"
        cp "$ROOT/config/models_config.example.json" "$ROOT/config/models_config.json"
        echo -e "${GREEN}✅ 从示例创建模型配置${NC}"
    else
        echo -e "${YELLOW}⚠️  models_config.example.json 不存在，跳过${NC}"
    fi
else
    echo -e "${GREEN}✅ 模型配置已存在${NC}"
fi
echo ""

# [6/6] 启动服务
echo -e "${YELLOW}[6/6] 启动服务...${NC}"
echo ""

# 创建日志目录
mkdir -p "$ROOT/logs"

echo -e "${CYAN}正在启动 DeterminFlow...${NC}"
echo ""

# 启动服务
$VENV_PYTHON "$ROOT/run.py" &
PID=$!

# 等待服务启动
echo -e "${CYAN}等待服务启动...${NC}"
READY=0
MAX_WAIT=180

for i in $(seq 1 $MAX_WAIT); do
    sleep 1

    # 检查进程是否退出
    if ! kill -0 $PID 2>/dev/null; then
        echo ""
        echo -e "${RED}❌ 服务启动失败${NC}"
        echo ""
        echo -e "${YELLOW}故障排除:${NC}"
        echo "  1. 查看上面的错误信息"
        echo "  2. 手动运行查看详细错误: .venv/bin/python run.py"
        echo "  3. 检查端口 8020 是否被占用: lsof -i :8020"
        echo "  4. 查看文档: STARTUP_TROUBLESHOOTING.md"
        echo ""
        exit 1
    fi

    # 尝试访问服务
    if curl -s -f -o /dev/null http://127.0.0.1:8020/docs 2>/dev/null; then
        READY=1
        break
    fi

    # 显示进度
    if [ $((i % 10)) -eq 0 ]; then
        echo "  等待中... ($i/$MAX_WAIT 秒)"
    fi
done

echo ""
if [ $READY -eq 1 ]; then
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}✅ DeterminFlow 启动成功！${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo -e "${CYAN}🌐 Web 界面:  http://localhost:8020/${NC}"
    echo -e "${CYAN}📚 API 文档:  http://localhost:8020/docs${NC}"
    echo ""
    echo -e "${YELLOW}按 Ctrl+C 停止服务${NC}"
    echo ""

    # 尝试打开浏览器
    if command -v xdg-open &> /dev/null; then
        xdg-open "http://127.0.0.1:8020/" 2>/dev/null || true
    elif command -v open &> /dev/null; then
        open "http://127.0.0.1:8020/" 2>/dev/null || true
    fi

    # 等待用户停止
    trap "echo ''; echo '正在停止服务...'; kill $PID 2>/dev/null; exit 0" INT TERM
    wait $PID
else
    echo -e "${RED}❌ 服务启动超时（等待超过 $MAX_WAIT 秒）${NC}"
    echo ""
    echo -e "${YELLOW}可能的原因:${NC}"
    echo "  1. 前端构建时间过长（Node.js 依赖安装）"
    echo "  2. 服务器响应慢"
    echo "  3. 端口被占用"
    echo ""
    echo -e "${YELLOW}建议:${NC}"
    echo "  检查进程是否仍在运行: ps aux | grep python"
    echo "  尝试访问: http://localhost:8020/"
    echo ""

    # 询问是否终止进程
    read -p "是否终止进程？(y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        kill $PID 2>/dev/null
        echo "进程已终止"
    else
        echo "进程继续运行（PID: $PID）"
    fi

    exit 1
fi
