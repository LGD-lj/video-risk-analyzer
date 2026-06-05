# Video Risk Analysis Skill

## 技能说明
分析行车记录视频中的驾驶风险点。当用户提到"分析视频风险"、"道路风险分析"、"行车视频分析"时触发此技能。

## 触发条件
- 用户上传或提到 mp4/mov 视频文件
- 用户提到"风险点"、"risk"、"道路安全"等关键词
- 用户明确要求分析视频中的驾驶风险

## 使用方式
1. 确认视频文件路径
2. 使用本项目的 `app/risk_analyzer.py` 中的 `run_analysis` 函数
3. 如果需要交互，调用 API 或直接运行脚本

## 快速命令

### 分析单个视频
```bash
cd video-risk-analyzer
python -c "
from app.risk_analyzer import run_analysis
risk_points, report, zip_path = run_analysis(
    job_id='manual_test',
    video_path='path/to/video.mp4',
    job_dir='data/jobs/manual_test'
)
print(f'发现 {len(risk_points)} 个风险点')
print(f'报告: {report}')
print(f'截图: {zip_path}')
"
```

### 启动 Web 服务
```bash
cd video-risk-analyzer
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

## 配置检查
分析前确认 `.env` 中的 API Key 已配置：
- VISION_API_KEY: 视觉模型 API Key
- DEEPSEEK_API_KEY: DeepSeek API Key

## 输出文件
- `data/jobs/{job_id}/风险分析报告.docx` — Word 报告
- `data/jobs/{job_id}/screenshots.zip` — 截图打包
