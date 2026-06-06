# 视频风险点分析系统 — 公网访问指南

## 本机使用（本地模式）

双击 `run_local.bat`，访问 `http://127.0.0.1:8000`。

此模式仅本机可用，不需要口令，不需要 Cloudflare Tunnel。

## 公网临时访问（Quick Tunnel）

### 1. 配置 .env

编辑 `.env`，设置：

```ini
PUBLIC_ACCESS_ENABLED=true
UPLOAD_TOKEN=你的口令（至少 6 位，告诉同事）
```

### 2. 安装 cloudflared

如果尚未安装：

1. 下载 Windows 版: https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe
2. 放到本项目目录下，重命名为 `cloudflared.exe`
3. 或放到 `C:\Windows\System32\` 目录下

### 3. 启动

双击 `run_public_quick.bat`。

启动后会显示一个 `https://xxx.trycloudflare.com` 格式的临时链接。

把这个链接发给同事即可。

**注意**：Quick Tunnel 链接每次重启都可能变化。

## 公网稳定访问（稳定域名 Tunnel）

需要有 Cloudflare 账号和一个域名。

### 1. 安装并登录 cloudflared

```cmd
cloudflared tunnel login
```

### 2. 创建 Tunnel

```cmd
cloudflared tunnel create video-risk-analyzer
```

### 3. 配置 DNS

在 Cloudflare 控制台中添加 CNAME 记录：
- 名称: `video-risk.yourdomain.com`
- 目标: `<tunnel-id>.cfargotunnel.com`

### 4. 创建 config.yml

在本项目目录下创建 `config.yml`：

```yaml
tunnel: <tunnel-id>
credentials-file: C:\Users\<用户名>\.cloudflared\<tunnel-id>.json

ingress:
  - hostname: video-risk.yourdomain.com
    service: http://localhost:8000
  - service: http_status:404
```

### 5. 启动

双击 `run_public_stable.bat` 或在命令行运行：

```cmd
cloudflared tunnel run video-risk-analyzer
```

## 一键公网启动

配置好 `.env` 后，双击 `start_public.bat` 即可：

1. 自动检查 `.env` 配置（PUBLIC_ACCESS_ENABLED、UPLOAD_TOKEN、API Key）
2. 自动安装依赖
3. 启动 FastAPI 本地服务
4. 启动 Cloudflare Quick Tunnel
5. 显示本地地址和公网访问链接

## 给同事使用

1. 你的电脑必须开机，且运行了 `run_public_quick.bat` 或 `run_public_stable.bat`
2. 同事打开公网链接
3. 输入你设置的口令
4. 上传视频 → 等待分析 → 下载结果

## 文件保留和清理

- 结果文件（Word、ZIP、JSON）默认保留 **24 小时**
- 失败任务保留 **1 小时**
- 原始上传视频和临时帧**处理完成后立即删除**
- 可修改 `.env` 中的 `RESULT_KEEP_HOURS` 调整保留时间

## 安全注意事项

1. **不要泄露 `.env` 文件**，里面包含 API Key
2. **不要泄露上传口令**，仅告诉可信同事
3. **电脑关机后同事无法访问**
4. Quick Tunnel 链接是公开的，但需要口令才能上传
5. 公网模式下所有 API 都需要口令验证
6. 不要在公网环境打印或展示 API Key

## ⚠️ 重要提醒

### 电脑关机后服务不可用

本系统运行在你的电脑上。如果电脑关机、休眠、断网，公网链接立即失效，同事无法访问。需要保持电脑开机、联网、Tunnel 运行中。

### Quick Tunnel 链接重启后变化

每次运行 `start_public.bat` 或重启 Tunnel，公网链接都会变化（如 `https://xxx.trycloudflare.com` 中的 xxx 会变）。需要把新链接发给同事。

### 如需固定链接

配置 **稳定域名 Tunnel**（见上方"公网稳定访问"章节）：
1. 注册 Cloudflare 账号
2. 拥有一个域名（如 `yourdomain.com`）
3. 创建命名 Tunnel 并绑定域名
4. 链接如 `https://video-risk.yourdomain.com` 将永久不变

## 常见问题

### 127.0.0.1 只能自己访问

正确。127.0.0.1 是本地回环地址，只有本机能访问。要让同事访问，必须启动 Cloudflare Tunnel。

### 公网访问必须启动 Cloudflare Tunnel

是的。不启动 Tunnel，同事无法从外网访问你的电脑。

### 电脑关机后同事无法访问

是的。你的电脑必须开机且运行了 Tunnel。

### Quick Tunnel 链接每次可能变化

是的。每次重启 Tunnel，链接会变化。如果链接经常变化不方便，请配置稳定域名 Tunnel。

### 视频越长处理越慢

视频越长抽帧越多、API 调用越多、费用越高。
- 30 秒视频约 1-3 分钟处理
- 5 分钟视频约 3-10 分钟处理
- 10 分钟视频约 10-30 分钟处理

### 不要泄露上传口令

上传口令相当于密码。只告诉需要使用的同事，不要在公开渠道传播。
