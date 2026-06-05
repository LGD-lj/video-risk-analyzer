# 🎬 视频风险点分析系统 V1

上传行车记录视频，AI 自动识别驾驶风险点，生成 Word 报告和截图。

## 功能概览

- 📤 **网页上传** — 支持 MP4/MOV/AVI/MKV/WebM，最大 2GB
- 🔍 **智能识别** — 视觉模型逐帧分析，检测 10 种驾驶风险类型
- 📊 **Word 报告** — 自动生成包含截图、风险等级、描述的完整报告
- 📦 **截图打包** — 所有风险点截图一键下载 ZIP
- 🧹 **自动清理** — 超过 24 小时的上传文件和临时数据自动删除

### 支持的风险类型

| 风险类型 | 说明 |
|---------|------|
| 🚧 施工 | 路面施工、围挡、施工标志 |
| ⚠️ 限高 | 限高杆、限高标志、低矮桥梁/隧道 |
| 🟠 锥桶 | 路锥、警示桶、隔离桩 |
| ↔️ 窄路 | 车道变窄、道路收窄 |
| 🚪 闸口 | 收费站、检查站、出入口闸机 |
| 🚶 行人 | 行人横穿、路边行人 |
| 🚲 非机动车 | 自行车、电动车、三轮车 |
| 🚛 货车遮挡 | 前方大货车遮挡视线 |
| 🅿️ 停车占道 | 路边违章停车占用行车道 |
| 🌉 低净空 | 桥梁/隧道高度不足 |

## 环境要求

| 软件 | 最低版本 | 说明 |
|------|---------|------|
| Python | 3.10+ | 编程语言运行环境 |
| FFmpeg | 4.0+ | 视频信息读取，需包含 ffprobe |
| pip | 最新 | Python 包管理器 |

### 安装 FFmpeg（Windows）

```bash
# 方式一：winget（推荐，Windows 11 自带）
winget install ffmpeg

# 方式二：手动下载
# 1. 访问 https://ffmpeg.org/download.html
# 2. 下载 Windows 版本
# 3. 解压后将 bin 目录添加到系统 PATH 环境变量
```

## 快速开始

### 1. 克隆/下载项目

```bash
cd video-risk-analyzer
```

### 2. 配置 API Key

```bash
# 复制配置模板
copy .env.example .env

# 用记事本编辑 .env，填入两个 API Key
notepad .env
```

需要配置的 Key：

```ini
# 视觉模型 — 用于分析视频帧中的风险
VISION_API_KEY=sk-your-openai-api-key

# DeepSeek — 用于润色风险描述、生成报告
DEEPSEEK_API_KEY=sk-your-deepseek-api-key
```

> 💡 **视觉模型说明**：默认使用 OpenAI GPT-4o，也支持任何 OpenAI 兼容接口（如 DeepSeek 视觉模型、通义千问 VL 等）。只需修改 `VISION_BASE_URL` 和 `VISION_MODEL`。

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 一键启动

```bash
# Windows 双击运行
run.bat

# 或手动命令行启动
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### 5. 打开浏览器

```
http://127.0.0.1:8000
```

上传视频 → 等待分析 → 下载报告和截图。

## 处理流程

```
用户上传视频
    ↓
ffprobe 读取视频信息（分辨率、帧率、时长）
    ↓
OpenCV 每隔 5 秒抽一帧（可配置）
    ↓
视觉模型逐帧分析 → 返回 JSON（has_risk, risk_types, severity, description）
    ↓
风险去重（30 秒内同类风险合并）
    ↓
按严重程度筛选 5-10 个最终风险点
    ↓
保存风险点截图
    ↓
DeepSeek 统一润色描述
    ↓
python-docx 生成 Word 报告
    ↓
打包 screenshots.zip
    ↓
网页显示下载链接
```

## 项目结构

```
video-risk-analyzer/
├── app/
│   ├── main.py              # FastAPI 入口，路由定义
│   ├── config.py            # 读取 .env 配置
│   ├── models.py            # Pydantic 数据模型
│   ├── video_utils.py       # 视频校验、抽帧、截图
│   ├── vision_provider.py   # 视觉模型接口（可替换 provider）
│   ├── llm_provider.py      # DeepSeek 文本总结
│   ├── risk_analyzer.py     # 风险分析主逻辑
│   ├── report_generator.py  # Word 报告生成
│   └── cleanup.py           # 24 小时自动清理
├── web/
│   └── index.html           # 前端上传页面
├── data/jobs/               # 任务数据目录（自动创建）
│   └── {job_id}/
│       ├── video.mp4        # 上传的视频
│       ├── frames/          # 抽取的帧
│       ├── screenshots/     # 风险点截图
│       ├── 风险分析报告.docx
│       └── screenshots.zip
├── requirements.txt
├── .env.example
├── run.bat                  # Windows 一键启动
└── README.md
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 前端页面 |
| GET | `/api/health` | 健康检查 |
| POST | `/api/upload` | 上传视频（multipart/form-data） |
| GET | `/api/status/{job_id}` | 查询任务状态和进度 |
| GET | `/api/download/{job_id}/report` | 下载 Word 报告 |
| GET | `/api/download/{job_id}/screenshots` | 下载截图 ZIP |
| POST | `/api/cleanup` | 手动触发清理 |

## 配置说明

所有配置项见 `.env.example`：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `FRAME_INTERVAL_SECONDS` | 5 | 抽帧间隔（秒），越小分析越细致但越慢 |
| `DEDUP_INTERVAL_SECONDS` | 30 | 风险去重最小间隔（秒） |
| `MAX_RISK_POINTS` | 10 | 最终报告中最多风险点数量 |
| `MIN_RISK_POINTS` | 5 | 最终报告中至少风险点数量 |
| `CLEANUP_HOURS` | 24 | 自动清理超过多少小时的任务数据 |
| `MAX_UPLOAD_SIZE_MB` | 2000 | 最大上传文件大小（MB） |

## 替换视觉模型

如需使用其他视觉模型（如 DeepSeek VL、通义千问 VL），只需修改 `.env`：

```ini
# 示例：使用 DeepSeek 视觉模型
VISION_PROVIDER=openai
VISION_API_KEY=sk-your-deepseek-key
VISION_BASE_URL=https://api.deepseek.com
VISION_MODEL=deepseek-chat

# 示例：使用阿里通义千问 VL
VISION_PROVIDER=openai
VISION_API_KEY=sk-your-qwen-key
VISION_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
VISION_MODEL=qwen-vl-max
```

只要目标 API 兼容 OpenAI Chat Completions 格式，都可以直接使用。

## 常见问题

### Q: 分析很慢怎么办？
- 增大 `FRAME_INTERVAL_SECONDS`（如改为 10 秒抽一帧）
- 使用更快的视觉模型
- 缩短视频时长

### Q: 提示 "缺少必要配置"？
- 检查 `.env` 文件中 `VISION_API_KEY` 和 `DEEPSEEK_API_KEY` 是否已填写
- 确保 `.env` 文件位于项目根目录

### Q: 找不到 ffprobe？
- 确认已安装 FFmpeg 且 `ffprobe` 在系统 PATH 中
- 打开新命令行窗口运行 `ffprobe -version` 测试

### Q: 如何查看历史任务？
- V1 版本不提供历史列表，直接访问 `http://127.0.0.1:8000/api/status/{job_id}` 查看
- 后续版本会加入任务历史页面

## 后续计划（V2+）

- [ ] 支持同时分析多个视频
- [ ] 任务历史列表和搜索
- [ ] 风险点可视化标注（视频上画框）
- [ ] 支持更多视觉模型 provider（Qwen VL、Gemini 等）
- [ ] Docker 一键部署
- [ ] 公网访问支持（添加登录鉴权）
