# Bilibili 视频总结技能

把 Bilibili、b23.tv、YouTube 视频整理成本地中文 Markdown 总结。

## 安装

有两种常见方式：

1. 在 Codex 里用 `skill-installer` 安装这个仓库。
2. 手动把整个目录放到 `$CODEX_HOME/skills/bilibili-video-summary`。

装完后重启 Codex，让新技能生效。

如果你要手动安装依赖：

```powershell
python -m pip install -r requirements.txt
```

## 使用

直接给视频链接即可，技能会自动生成本地 `.md` 文件。

也可以手动运行脚本：

```powershell
python scripts\summarize.py --url "视频链接" --include-transcript --output "$env:TEMP\video_summary.json"
```

## 工作流

1. 先提取视频元数据。
2. 优先读取字幕或现成转写。
3. 没有字幕时，尝试播放器字幕。
4. 还没有的话，转音频做本地转写。
5. 输出中文 Markdown，总结和详细内容都会写入。

## 输出

- 视频信息
- 摘要
- 详细内容
- 可复用要点

## 适用范围

- Bilibili 视频
- b23.tv 链接
- YouTube 视频

## 说明

- 默认输出中文
- 没有可用字幕时不会假装看过视频
- 音频转写依赖 `faster-whisper`
