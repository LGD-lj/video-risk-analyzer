---
name: video-risk-maintenance
description: 用于维护 video-risk-analyzer 项目，约束 Claude 不重写项目、不乱杀进程、不连续执行大量命令，并保护 .env 和上传数据。
---

# video-risk-analyzer 项目维护 Skill

## 基本原则

维护当前项目时：
- 不要重写整个项目。
- 不要改页面样式，除非用户明确要求。
- 不要执行 taskkill，除非用户明确同意。
- 不要停止正在运行的 FastAPI 服务，除非需要重启且用户同意。
- 不要运行大视频测试，除非用户明确同意。
- 不要读取、展示、打印、提交 .env 内容。
- 不要把 API Key 输出到聊天、日志或报告中。
- 不要提交 data/、上传视频、临时帧、报告结果到 git。

## 单步执行原则

每执行一个命令后，先停下来汇报：

1. 执行了什么命令
2. 是否成功
3. 关键输出
4. 是否有报错
5. 下一步准备做什么

不要一次性连续执行很多命令。

如果命令超过 2 分钟无输出，停止等待并说明卡在哪里。

## 修改代码前

先说明：
- 要修改哪个文件
- 为什么修改
- 预计影响什么功能
- 是否会影响已经跑通的上传、下载、Word、ZIP 主流程

## 测试原则

优先使用：
- 10-30 秒小视频
- Mock 模式
- 快速测试模式

只有用户明确要求时，才运行：
- 10 分钟真实道路视频
- full 正式分析模式
- 真实 AI 大量调用

## 版本保存

重大功能跑通后必须建议保存版本：

- v1 mock flow works
- v2 mock enhanced flow works
- v3 dashscope deepseek real ai works
- v4 risk filtering tuned

提交时不要提交：
- .env
- data/
- 上传视频
- 临时帧
- 生成报告
