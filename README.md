# 📹 小红书直播录制工具

输入直播链接，自动提取流地址并录制保存为 MP4。支持信号跟随（直播开始即录、结束即停）、时间表省电模式、断流自动续录。

个人学习用途，纯本地运行，零 API 消耗。

## 功能特性

- **信号跟随录制** — 检测到直播信号自动开始录制，直播结束自动停止
- **断流看门狗** — 每 15 秒检查文件增长，60 秒无增长判定断流，自动杀掉 ffmpeg 并重新抓取流地址继续录
- **多片段自动合并** — 断流产生的多个 .ts 片段，录制结束后自动合并为一个 MP4
- **时间表省电模式** — 通过 `schedule.json` 定义直播时段，非直播时段深度睡眠（不启动 Chrome、不联网）
- **每场独立链接** — 小红书每场直播链接会变，时间表支持每个时段单独指定 URL
- **TS 格式防损坏** — 先录为 MPEG-TS（无 moov 原子，进程被杀也不损坏），再转 MP4（QuickTime 兼容）
- **H.264 实时转码** — 小红书直播用 HEVC(H.265)，QuickTime 不兼容，工具实时转码为 H.264
- **手动模式** — 自动提取失败时，可手动输入流地址直接录制
- **循环模式** — 直播结束后继续等待重新开播

## 依赖

| 依赖 | 用途 | 安装方式 |
|------|------|----------|
| [Python 3](https://www.python.org/) | 主程序 | `brew install python` |
| [Node.js](https://nodejs.org/) | 流地址提取 | `brew install node` |
| [puppeteer-core](https://pptr.dev/) | 浏览器自动化 | `npm install puppeteer-core` |
| [ffmpeg](https://ffmpeg.org/) | 视频录制与转码 | `brew install ffmpeg` |
| [Google Chrome](https://www.google.com/chrome/) | 打开直播页面 | 官网下载 |

## 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/cinniachen/xhs-live-recorder.git
cd xhs-live-recorder
```

### 2. 安装依赖

```bash
# macOS
brew install python node ffmpeg
npm install puppeteer-core

# 或手动安装各依赖后，设置路径
export NODE_PATH=$(npm root -g)
```

### 3. 首次使用（需要登录）

```bash
./record.sh "你的小红书直播链接"
```

首次运行会弹出 Chrome 窗口。如果直播需要登录，在弹出的浏览器中登录小红书账号。登录状态会保存在 `.chrome-profile/` 目录，下次无需重复登录。

### 4. 日常录制

```bash
# 跟随信号：直播开始即录，结束即停
./record.sh "https://xhslink.com/m/xxxxx"

# 无头模式（不弹窗口，后台静默录制）
./record.sh "https://xhslink.com/m/xxxxx" --headless

# 循环模式（直播结束后继续等待重新开播）
./record.sh "https://xhslink.com/m/xxxxx" --loop
```

## 使用方式

### 信号跟随模式（默认）

输入直播链接后，工具持续监测直播信号（每 30 秒一次）。检测到直播自动开始录制，直播结束自动停止。

```bash
./record.sh "https://xhslink.com/m/xxxxx"
```

### 时间表省电模式

适合多天赛程等固定时间表的场景。非直播时段不启动 Chrome、不联网，资源消耗极低。

```bash
# 编辑时间表
cp schedule.json schedule.json  # 修改为你自己的时间表

# 启动
./record.sh "默认链接" --schedule schedule.json
```

时间表格式（`schedule.json`）：

```json
{
  "windows": [
    {
      "start": "2026-07-20 08:30",
      "end": "2026-07-20 17:30",
      "note": "第一天",
      "url": "https://xhslink.com/m/xxxxx"
    },
    {
      "start": "2026-07-21 08:30",
      "end": "2026-07-21 17:30",
      "note": "第二天",
      "url": ""
    }
  ]
}
```

- 每个时段可单独指定 `url`，为空则使用命令行传入的默认链接
- 拿到新链接后，直接填到对应时段的 `url` 字段即可，不用改命令
- 非直播时段进入省电模式，显示倒计时

### 手动模式

自动提取流地址失败时，可手动获取流地址后直接录制：

```bash
# 手动获取流地址的方法：
# 1. Chrome 打开直播页面
# 2. 按 F12 打开开发者工具 → Network 标签
# 3. 在筛选框输入 m3u8 或 flv
# 4. 找到流地址，右键 → Copy URL

./record.sh --manual "https://xxx.com/live/stream.flv"
```

### 清理浏览器缓存

```bash
./record.sh --clean
```

## 命令行参数

| 参数 | 说明 |
|------|------|
| `<url>` | 小红书直播链接（或手动模式下的流地址） |
| `--headless` | 无头模式，不显示浏览器窗口 |
| `--loop` | 循环模式，直播结束后继续等待重新开播 |
| `--schedule <file>` | 时间表文件路径（JSON） |
| `--manual` | 手动模式，直接输入流地址录制 |
| `--timeout <sec>` | 流地址提取超时时间，默认 30 秒 |
| `--clean` | 清理浏览器缓存 |

## 录制控制

| 操作 | 说明 |
|------|------|
| `Ctrl + C` | 优雅停止录制（等待 ffmpeg 写完文件后退出） |
| `Ctrl + C` × 2 | 强制停止 |

录制文件自动保存在 `recordings/` 目录下，文件名格式为 `xhs_live_YYYYMMDD_HHMMSS.mp4`。

## 工作原理

```
小红书直播链接
      │
      ▼
 ┌─────────────────────────┐
 │  puppeteer + Chrome     │  打开直播页面
 │  拦截网络请求            │  提取 .m3u8 / .flv 流地址
 └────────────┬────────────┘
              │
              ▼
 ┌─────────────────────────┐
 │  ffmpeg 接收流地址       │  H.264 实时转码
 │  录制为 MPEG-TS 文件     │  AAC 音频直拷
 └────────────┬────────────┘
              │
              ▼
 ┌─────────────────────────┐
 │  文件增长看门狗          │  每 15 秒检查文件大小
 │  60 秒不增长 → 断流      │  杀 ffmpeg → 重抓流地址
 └────────────┬────────────┘
              │
              ▼
 ┌─────────────────────────┐
 │  直播结束 / 用户停止     │
 │  TS → MP4 转换           │  remux 不重新编码
 │  多片段自动合并          │  ffmpeg concat
 └─────────────────────────┘
```

## 文件结构

```
xhs-live-recorder/
├── recorder.py           # 主程序（Python）
├── stream_extractor.js   # 流地址提取器（Node.js + puppeteer）
├── record.sh             # 便捷启动脚本
├── schedule.json         # 时间表示例
├── recordings/           # 录制文件保存目录（自动创建）
├── .chrome-profile/      # Chrome 用户数据（保存登录状态，自动创建）
├── .gitignore
├── LICENSE
└── README.md
```

## 环境变量

如果依赖不在默认 PATH 中，可通过环境变量指定路径：

```bash
export PYTHON_BIN="/path/to/python3"
export NODE_BIN="/path/to/node"
export NODE_PATH="/path/to/node_modules"
export FFMPEG_BIN="/path/to/ffmpeg"
```

## 常见问题

**Q: 提示"未检测到流媒体地址"**

- 确认直播正在进行中
- 首次使用去掉 `--headless`，在浏览器窗口中登录小红书
- 登录成功后关闭浏览器，重新运行录制命令
- 如果仍失败，使用手动模式（`--manual`）

**Q: 录制的视频 QuickTime 打不开**

- 工具已自动将 HEVC 转码为 H.264 并转换为 MP4 格式
- 如果仍然打不开，可能是录制中途中断，尝试用 [VLC](https://www.videolan.org/) 或 [IINA](https://iina.io/) 打开

**Q: 录制中途断开**

- 工具内置断流看门狗：60 秒文件不增长会自动重抓流地址继续录
- 断流产生的多个片段会在录制结束后自动合并
- ffmpeg 也内置了断线重连机制（`-reconnect`）

**Q: 首次使用弹出浏览器但页面空白**

- 可能是 Chrome 版本不兼容，确保使用最新版 Chrome
- 尝试 `./record.sh --clean` 清理缓存后重试

**Q: 无头模式下提示需要登录**

- 无头模式无法手动登录，请先在有窗口模式下登录一次
- 登录状态保存在 `.chrome-profile/`，之后无头模式也能复用

## 声明

本工具仅供个人学习研究使用，请遵守小红书平台相关规定。

## License

[MIT](LICENSE)
