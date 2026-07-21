# 机器人智能集群调度系统

本仓库包含 FastAPI 控制后端、PostgreSQL、Redis，以及 PM/O&M 两个 React 应用。机器人本体、ROS、SLAM、导航、固件和 Gazebo world 不在本仓库实现；真机或外部仿真桥通过受鉴权的 HTTP 网关接入。

PostgreSQL 是业务数据唯一事实来源。启动过程不会生成账号、项目、设备、地图、任务、摄像头、点云或遥测数据。

## 两种运行方式

本机开发和完整部署是两条独立流程，不要混用。

### 本机开发

```powershell
py -3.10 manager\manager.py init-env
py -3.10 manager\manager.py doctor
py -3.10 manager\manager.py start all
py -3.10 manager\manager.py status
```

也可双击 `manager/start_manager.bat` 使用桌面管理器。开发服务只监听本机：后端 `8000`、PM `5173`、O&M `5174`。停止命令：

```powershell
py -3.10 manager\manager.py stop all
```

### 局域网完整部署

推荐先在开发机生成发布包：

```powershell
py -3.10 manager\deploy.py package
py -3.10 manager\deploy.py package --offline
```

普通包较小，目标机使用 Docker 在线构建；离线包包含五个运行镜像，目标机不需要连接镜像仓库。将 `release/` 中的 ZIP 复制到目标机并解压，以管理员身份运行根目录 `install.cmd`。目标机只需要已启动的 Docker Desktop，不需要安装 Python、Node.js、pnpm 或 PostgreSQL。安装器自动校验文件、生成独立随机密钥、加载或构建镜像、启动服务并检查健康状态；`manage.cmd` 提供状态、启动、重启、停止和日志入口。

正式版本通过 GitHub 标签自动发布。`VERSION` 使用 SemVer，推送对应的 `vX.Y.Z` 标签后，GitHub Actions 会发布精确版本 GHCR 镜像、联网注册表包和完整离线包。部署包状态统一保存在 `C:\ProgramData\RobotsSystem`，所以新版本可以解压到新目录升级，不会覆盖密钥或业务数据。完整流程见 [版本发布与升级](docs/版本发布与升级.md)。

需要直接从源码部署时，先生成独立随机密钥：

```powershell
py -3.10 manager\deploy.py init
py -3.10 manager\deploy.py doctor
py -3.10 manager\deploy.py up
py -3.10 manager\deploy.py status
```

默认地址：后端 `8000`、PM `8080`、O&M `8081`。源码命令部署使用 `deploy/.env`；发布包部署使用 `C:\ProgramData\RobotsSystem\deploy.env`。两者都只保存在部署机，禁止提交。停止部署会保留 PostgreSQL、Redis 和备份卷：

```powershell
py -3.10 manager\deploy.py down
```

完整的升级、备份、恢复、日志和故障排查流程见 [部署与运维手册](docs/部署与运维手册.md)。设备接口见 [设备网关协议](docs/DEVICE_GATEWAY_API.md)。

## 首次项目初始化

首次打开 PM 或 O&M 页面时，使用部署机 `C:\ProgramData\RobotsSystem\deploy.env`（源码命令部署为 `deploy/.env`，开发模式为 `backend/.env`）中的 `INITIAL_SETUP_TOKEN`，填写真实项目资料并创建 PM/O&M 账号。初始化只允许执行一次，不会创建默认账号或演示项目。

## 验证

```powershell
cd backend
pytest -q
python -m compileall -q app
alembic check

cd ..\frontend
pnpm build
```

## 文档

- [开发进度](docs/开发进度.md)
- [使用手册](docs/使用手册.md)
- [部署与运维手册](docs/部署与运维手册.md)
- [本机项目阶段报告](docs/本机项目阶段报告.md)
- [设备开发与接入规范](docs/设备开发与接入规范.md)
- [设备网关协议](docs/DEVICE_GATEWAY_API.md)
- [版本发布与升级](docs/版本发布与升级.md)
