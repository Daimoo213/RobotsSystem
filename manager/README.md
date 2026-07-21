# 项目管理工具

本目录提供两套边界清晰的工具：

- `manager.py`：本机开发管理器，运行本机 Python/Vite 与 Docker 中的 PostgreSQL/Redis。
- `deploy.py`：完整容器部署控制器，运行后端、PM、O&M、PostgreSQL 和 Redis。

## 本机开发管理器

双击 `start_manager.bat`，或执行：

```powershell
py -3.10 manager\manager.py gui
```

命令行操作：

```powershell
py -3.10 manager\manager.py init-env
py -3.10 manager\manager.py doctor
py -3.10 manager\manager.py start all
py -3.10 manager\manager.py status
py -3.10 manager\manager.py logs backend --follow
py -3.10 manager\manager.py stop all
```

`init-env` 只替换缺失、占位、过弱或重复的本地密钥，不打印值，也不会更改已经合格的密钥。管理器会在迁移前等待 PostgreSQL/Redis 健康，按基础设施、后端、PM、O&M 顺序启动；任一步失败都会停止后续启动。

管理器记录进程创建时间、可执行路径和命令行，停止前重新核验，避免 PID 被系统复用后误杀其他程序。外部端口占用默认只报告，不接管。

运行状态和日志位于 `manager/runtime/`。日志在服务下一次启动前达到 5 MiB 时轮转；长期运行时应使用完整容器部署的 Docker 日志策略。

## 完整部署控制器

生成可复制到其他 Windows 电脑的发布包：

```powershell
py -3.10 manager\deploy.py package
py -3.10 manager\deploy.py package --offline
```

也可以双击 `build_release.bat` 生成离线包。发布包不会包含 `.env`、账号、数据库、备份、日志、缓存或前端构建目录。目标机解压后运行 `install.cmd`，日常操作运行 `manage.cmd`；目标机不要求安装 Python。

正式发布由 `VERSION` 与 Git 标签共同控制：

```powershell
py -3.10 manager\deploy.py package --registry-prefix ghcr.io/<owner>/robots-system
py -3.10 manager\deploy.py package --offline
```

上面的 `<owner>` 需要替换为小写 GitHub 用户或组织名。GitHub Actions 会自动传入正确路径，通常不需要人工执行。发布包安装的持久状态位于 `C:\ProgramData\RobotsSystem`。

```powershell
py -3.10 manager\deploy.py init
py -3.10 manager\deploy.py doctor
py -3.10 manager\deploy.py up
py -3.10 manager\deploy.py status
py -3.10 manager\deploy.py logs backend --follow
py -3.10 manager\deploy.py down
```

其他管理命令：

```powershell
py -3.10 manager\deploy.py backup
py -3.10 manager\deploy.py restore deploy\backups\<file>.dump --confirm RESTORE
py -3.10 manager\deploy.py restart backend
```

`up` 在已有部署数据库运行时会先导出主机备份，再构建和升级。`restore` 会先停止应用服务，恢复失败时保持停止状态供排查。`down` 不删除数据卷；工具故意不提供自动删除卷的命令。
