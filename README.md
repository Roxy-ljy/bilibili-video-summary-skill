# Bilibili 视频总结技能

这是一个给 Bilibili、b23.tv 和 YouTube 视频做本地 Markdown 总结的技能。

## 能做什么

- 提取视频元数据
- 优先读取字幕或转写
- 没有可用字幕时，自动走音频转写
- 输出本地 `.md` 文件

## 输出内容

- 视频信息
- 摘要
- 详细内容
- 可复用要点

## 使用方式

在 Codex 里直接给视频链接即可，技能会按本地工作流生成总结文件。

如果你手动运行脚本，可在技能目录下执行：

```powershell
python scripts\summarize.py --url "视频链接" --include-transcript --output "$env:TEMP\video_summary.json"
```

## 依赖

```powershell
python -m pip install -r requirements.txt
```

## 说明

- 有字幕时优先用字幕
- 没有字幕时会尝试音频转写
- 输出默认用中文
