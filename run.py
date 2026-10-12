"""DeterminFlow development entry point.

Production uses the Gunicorn command declared by the Docker image.
"""
import os
import sys
from pathlib import Path

# 将项目根目录加入 sys.path
sys.path.insert(0, str(Path(__file__).parent))

npm_cmd = "npm.cmd" if os.name == "nt" else "npm"


def _check_nodejs_available():
    """检查 Node.js 是否可用"""
    import subprocess
    try:
        # 尝试多个可能的 node 命令
        node_cmds = ["node", "node.exe", "nodejs"]
        for cmd in node_cmds:
            try:
                result = subprocess.run(
                    [cmd, "--version"],
                    capture_output=True,
                    timeout=5
                )
                if result.returncode == 0:
                    return True
            except:
                continue
        return False
    except:
        return False


def _build_frontend_if_needed():
    """检测前端源码是否比 dist 更新，如果是则自动构建。"""
    import subprocess, os

    root = Path(__file__).parent
    web_dir = root / "web"
    src_dir = web_dir / "src"
    dist_dir = web_dir / "dist"

    if not src_dir.exists():
        return  # 没有前端源码，跳过

    # 如果 dist 存在且有内容，跳过构建
    if dist_dir.exists() and (dist_dir / "index.html").exists():
        print("  ✅ 前端已构建，跳过")
        return

    print("  📦 检测前端环境...")

    # 检查 Node.js 是否可用
    if not _check_nodejs_available():
        print("  ⚠️  Node.js 未安装或不在 PATH 中")
        print("  ℹ️  前端功能将不可用（仅后端API模式）")
        print("  ℹ️  如需完整功能，请安装 Node.js: https://nodejs.org/")
        print("  ℹ️  安装后重新运行启动脚本\n")
        return

    # 检查 npm 是否可用
    try:
        result = subprocess.run(
            [npm_cmd, "--version"],
            capture_output=True,
            timeout=5
        )
        if result.returncode != 0:
            raise Exception("npm not available")
    except:
        print("  ⚠️  npm 不可用")
        print("  ℹ️  前端功能将不可用（仅后端API模式）\n")
        return

    print("  🔄 自动构建前端...")

    try:
        # 检查 node_modules 是否存在
        if not (web_dir / "node_modules").exists():
            print("  📦 安装前端依赖（首次运行可能需要几分钟）...")
            result = subprocess.run(
                [npm_cmd, "install"],
                cwd=str(web_dir),
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=600  # 10分钟超时
            )
            if result.returncode != 0:
                print(f"  ⚠️  前端依赖安装失败")
                stderr = result.stderr[:500] if result.stderr else ""
                if stderr:
                    print(f"  错误信息: {stderr}")
                print("  ℹ️  服务将以纯后端模式启动")
                print("  ℹ️  故障排除:")
                print("      1. 检查网络连接")
                print("      2. 尝试使用国内镜像: npm config set registry https://registry.npmmirror.com")
                print("      3. 手动执行: cd web && npm install\n")
                return

        print("  🔨 构建前端（可能需要1-2分钟）...")
        result = subprocess.run(
            [npm_cmd, "run", "build"],
            cwd=str(web_dir),
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=300  # 5分钟超时
        )

        if result.returncode == 0:
            print("  ✅ 前端构建完成\n")
        else:
            print(f"  ⚠️  前端构建失败，服务将以纯后端模式启动")
            stderr = result.stderr[:500] if result.stderr else ""
            if stderr:
                print(f"  错误信息: {stderr}")
            print("  ℹ️  手动构建: cd web && npm run build\n")

    except subprocess.TimeoutExpired:
        print(f"  ⚠️  前端构建超时")
        print("  ℹ️  服务将以纯后端模式启动")
        print("  ℹ️  可手动构建: cd web && npm install && npm run build\n")
    except Exception as e:
        print(f"  ⚠️  前端构建异常: {str(e)[:100]}")
        print("  ℹ️  服务将以纯后端模式启动\n")


def _check_and_install_plugins():
    """检查并自动安装必需的插件"""
    import subprocess
    import os

    root = Path(__file__).parent
    setup_plugins_script = root / "setup_plugins.py"

    if not setup_plugins_script.exists():
        return

    try:
        print("  📦 检查并安装必需的插件...")

        # 设置环境变量，确保 Python 使用 UTF-8
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'

        result = subprocess.run(
            [sys.executable, str(setup_plugins_script)],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding='utf-8',  # 明确指定 UTF-8 编码
            env=env,
        )

        if result.stdout:
            for line in result.stdout.strip().split("\n"):
                if line and line.strip():
                    print(f"    {line}")

        if result.returncode == 0:
            # 成功
            pass
        elif result.stderr:
            print(f"    ⚠️  插件检查提示: {result.stderr[:200]}")

    except Exception as e:
        print(f"    ⚠️  插件检查失败: {str(e)[:100]}")


def _check_humanware_engine():
    """检查 Humanware Engine 状态并提示"""
    root = Path(__file__).parent

    # 检查 Humanware Engine 是否存在
    humanware_path = root / "data" / "plugins" / "checkouts" / "xs2-novel-flywheel"

    # 查找实际的插件目录（因为有 hash 值）
    if humanware_path.exists():
        for checkout_dir in humanware_path.iterdir():
            if checkout_dir.is_dir():
                engine_path = checkout_dir / "resources" / "script-library" / "xs2" / "humanware_engine"
                if engine_path.exists():
                    # Humanware Engine 已安装
                    print("  ✨ Humanware Engine 已就绪")
                    print("     让你的小说更有人味！")

                    # 检查是否已初始化
                    meta_dir = root / "meta"
                    if meta_dir.exists():
                        voice_file = meta_dir / "character_voices.json"
                        if voice_file.exists():
                            print("     ✅ 系统已初始化")
                        else:
                            print("     ℹ️  首次使用？运行: python humanware_quickstart.py --action init")
                    else:
                        print("     ℹ️  首次使用？运行: python humanware_quickstart.py --action init")

                    print()
                    return

    # Humanware Engine 未找到，显示安装提示
    quickstart = root / "humanware_quickstart.py"
    demo = root / "humanware_demo.py"

    if quickstart.exists() and demo.exists():
        print("  ℹ️  Humanware Engine 工具已就绪")
        print("     查看效果: python humanware_demo.py")
        print("     快速启动: python humanware_quickstart.py --action init")
        print()

if __name__ == "__main__":
    import os
    import uvicorn
    from dotenv import load_dotenv

    load_dotenv()

    # Redirected Windows consoles otherwise use GBK, which cannot print the
    # startup symbols and can corrupt Chinese workflow diagnostics.
    for output_stream in (sys.stdout, sys.stderr):
        if hasattr(output_stream, "reconfigure"):
            output_stream.reconfigure(encoding="utf-8", errors="replace")

    _build_frontend_if_needed()
    _check_and_install_plugins()
    _check_humanware_engine()

    # 日志级别唯一入口：需要诊断日志时设置 LOG_LEVEL=DEBUG
    os.environ.setdefault("LOG_LEVEL", "INFO")

    from src.web_server import app

    host = os.getenv("WEB_HOST", "0.0.0.0")
    port = int(os.getenv("WEB_PORT", "8020"))

    print(f"\n  🚀 DeterminFlow")
    print(f"  http://localhost:{port}")
    print(f"  API docs: http://localhost:{port}/docs\n")

    # 并发限制：防止事件循环被过载（百级 Agent 并发时数千 coroutine 竞争）
    limit_concurrency = int(os.getenv("UVICORN_LIMIT_CONCURRENCY", "200"))
    backlog = int(os.getenv("UVICORN_BACKLOG", "2048"))

    uvicorn.run(
        "src.web_server:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
        limit_concurrency=limit_concurrency,
        backlog=backlog,
    )
