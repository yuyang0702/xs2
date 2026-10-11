# 前端构建指南

## 问题说明

DeterminFlow 启动时报错 `subprocess.CalledProcessError: Command '['npm.cmd', 'run', 'build']' returned non-zero exit status 2.`

**原因**: 前端构建失败，但这不应该阻止后端 API 启动。

## 解决方案

### 方案 1: 手动构建前端（推荐）

打开 **PowerShell** 或 **CMD**：

```powershell
# 进入前端目录
cd C:\xs2\DeterminFlow\web

# 安装依赖（首次或 package.json 更新后）
npm install

# 构建前端
npm run build
```

**预期输出**:
```
> determinflow-web@0.1.0 build
> tsc -b && vite build

vite v5.x.x building for production...
✓ xxx modules transformed.
dist/index.html                   x.xx kB
dist/assets/index-xxxxx.js       xxx.xx kB
✓ built in xxxs
```

构建成功后，再运行启动脚本：

```powershell
cd C:\xs2\DeterminFlow
.\start_determinflow.bat
```

### 方案 2: 仅启动后端 API（无 Web 界面）

如果前端构建持续失败，可以只启动后端：

```powershell
cd C:\xs2\DeterminFlow
.\.venv\Scripts\python.exe run.py
```

修改后的 `run.py` 会跳过前端构建，直接启动后端服务。

访问：
- API 文档: http://localhost:8020/docs
- 健康检查: http://localhost:8020/health （如果已实现）

### 方案 3: 开发模式（前后端分离）

如果需要开发前端，可以分别启动：

**终端 1 - 后端**:
```powershell
cd C:\xs2\DeterminFlow
.\.venv\Scripts\python.exe run.py
```

**终端 2 - 前端开发服务器**:
```powershell
cd C:\xs2\DeterminFlow\web
npm run dev
```

这样前端会在 `http://localhost:5173` 运行，并代理 API 请求到后端。

## 常见前端构建问题

### 问题 1: "node" 不是内部或外部命令

**原因**: Node.js 未安装或未添加到 PATH

**解决**:
1. 下载并安装 Node.js: https://nodejs.org/ （LTS 版本）
2. 重启 PowerShell/CMD
3. 验证: `node --version` 和 `npm --version`

### 问题 2: npm install 失败

**可能原因**:
- 网络问题（npm 源访问慢）
- 权限问题
- 磁盘空间不足

**解决**:

```powershell
# 使用国内镜像（淘宝源）
npm config set registry https://registry.npmmirror.com

# 清理缓存重试
npm cache clean --force
npm install
```

### 问题 3: TypeScript 编译错误

**解决**:

```powershell
# 查看详细错误
cd C:\xs2\DeterminFlow\web
npm run build -- --mode development

# 如果是依赖问题，重新安装
rm -rf node_modules package-lock.json
npm install
```

### 问题 4: Vite 构建失败

**检查**:
- `web/src` 目录是否存在
- `web/package.json` 是否完整
- `web/vite.config.ts` 是否正确

## 跳过前端构建启动

修改后的 `run.py` 已经优化：

✅ **改进前**: 前端构建失败会导致整个服务无法启动  
✅ **改进后**: 前端构建失败会警告，但后端仍会启动

**行为**:
1. 如果 `web/dist` 已存在 → 跳过构建，直接启动
2. 如果 `web/dist` 不存在 → 尝试构建
3. 如果构建失败 → 显示警告，但继续启动后端

## 验证前端是否正常

构建成功后，访问：

```
http://localhost:8020/
```

应该能看到 DeterminFlow 的 Web 界面。

如果看到 404 或空白页面：
1. 检查 `web/dist/` 目录是否存在且有文件
2. 检查浏览器控制台是否有错误
3. 检查后端日志: `logs/2026-xx-xx-web.log`

## 完整的启动流程

### 首次启动

```powershell
# 1. 进入项目目录
cd C:\xs2\DeterminFlow

# 2. 激活虚拟环境（可选，脚本会自动处理）
.\.venv\Scripts\Activate.ps1

# 3. 安装 Python 依赖
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 4. 手动构建前端
cd web
npm install
npm run build
cd ..

# 5. 启动服务
.\start_determinflow.bat
```

### 日常启动

```powershell
cd C:\xs2\DeterminFlow
.\start_determinflow.bat
```

如果前端已构建，会直接启动；如果前端有更新，会尝试重新构建。

## 环境要求

| 组件 | 版本要求 | 检查命令 |
|------|---------|----------|
| Python | 3.11+ | `python --version` |
| Node.js | 18+ | `node --version` |
| npm | 9+ | `npm --version` |
| Git | 任意 | `git --version` |

## 获取帮助

如果问题仍未解决：

1. 查看详细日志: `logs/startup_*.log`
2. 查看后端日志: `logs/2026-xx-xx-web.log`
3. 检查前端构建输出
4. 参考: [STARTUP_TROUBLESHOOTING.md](./STARTUP_TROUBLESHOOTING.md)

## 快速命令参考

```powershell
# 检查环境
python --version
node --version
npm --version

# 安装 Python 依赖
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 构建前端
cd web && npm install && npm run build && cd ..

# 直接启动（查看输出）
.\.venv\Scripts\python.exe run.py

# 使用脚本启动
.\start_determinflow.bat

# 查看日志
Get-Content logs\startup_*.log -Tail 50
Get-Content logs\2026-*-web.log -Tail 50
```

## 总结

**现在启动逻辑**:
1. ✅ 检查前端是否已构建
2. ✅ 如果已构建 → 跳过，直接启动后端
3. ✅ 如果未构建 → 尝试构建
4. ✅ 如果构建失败 → 警告但仍启动后端
5. ✅ 后端 API 总是可以启动

**推荐工作流**:
- **生产/日常使用**: 手动构建前端一次，后续直接启动
- **前端开发**: 使用 `npm run dev` 开发模式
- **纯后端开发**: 忽略前端，直接用 API

---

**最后更新**: 2026-10-11
