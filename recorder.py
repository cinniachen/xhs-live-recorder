#!/usr/bin/env python3
"""
小红书直播录制工具
输入直播链接，自动跟随信号录制：直播开始即录，直播结束即停

用法:
  python3 recorder.py <直播链接>                        # 跟随信号自动录制
  python3 recorder.py <直播链接> --headless              # 无头模式
  python3 recorder.py <直播链接> --loop                  # 直播结束后继续等待重新开播
  python3 recorder.py --manual <m3u8或flv地址>           # 手动输入流地址录制
  python3 recorder.py --clean                            # 清理浏览器缓存

工作流程:
  1. 持续监测直播链接，等待直播开始
  2. 检测到直播信号 → 自动提取流地址 → ffmpeg 开始录制
  3. 直播结束（信号消失）→ ffmpeg 自动退出 → 保存文件
  4. 默认退出；加 --loop 则回到第 1 步继续等重新开播

快捷键:
  Ctrl+C  停止录制并退出
"""

import os
import sys
import signal
import subprocess
import time
import re
import argparse
from pathlib import Path
from datetime import datetime

# === 路径配置 ===
SCRIPT_DIR = Path(__file__).parent.resolve()
RECORDINGS_DIR = SCRIPT_DIR / "recordings"
NODE_SCRIPT = SCRIPT_DIR / "stream_extractor.js"
CHROME_PROFILE = SCRIPT_DIR / ".chrome-profile"

# === 依赖路径（自动检测，可通过环境变量覆盖）===
def find_executable(name, env_var=None, hints=None):
    """查找可执行文件路径：环境变量 > hints > PATH"""
    import shutil
    if env_var and os.environ.get(env_var):
        return os.environ[env_var]
    if hints:
        for h in hints:
            if os.path.isfile(h) and os.access(h, os.X_OK):
                return h
    found = shutil.which(name)
    if found:
        return found
    return None

NODE_BIN = find_executable(
    'node', 'NODE_BIN',
    ['/Users/cc/.workbuddy/binaries/node/versions/22.22.2/bin/node']
)
NODE_PATH = os.environ.get(
    'NODE_PATH',
    '/Users/cc/.workbuddy/binaries/node/workspace/node_modules'
)
FFMPEG_BIN = find_executable(
    'ffmpeg', 'FFMPEG_BIN',
    ['/usr/local/ffmpeg/bin/ffmpeg', '/opt/homebrew/bin/ffmpeg']
)

# === 颜色输出 ===
class Color:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    END = '\033[0m'

def cprint(text, color='', end='\n'):
    print(f"{color}{text}{Color.END}", end=end, flush=True)

# === 工具函数 ===
def ensure_dirs():
    """确保目录存在"""
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

def generate_filename():
    """生成录制文件名（先录 .ts，再转 .mp4）"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"xhs_live_{timestamp}"

def extract_stream_url(live_url, headless=False, timeout=30):
    """
    调用 Node.js 脚本提取流地址
    返回: (stream_url, error_message)
    """
    if not NODE_SCRIPT.exists():
        return None, f"流地址提取脚本不存在: {NODE_SCRIPT}"

    cmd = [
        NODE_BIN,
        str(NODE_SCRIPT),
        live_url,
    ]
    if headless:
        cmd.append("--headless")
    cmd.extend(["--timeout", str(timeout)])

    env = os.environ.copy()
    env["NODE_PATH"] = NODE_PATH

    cprint("\n🔍 正在提取直播流地址...", Color.CYAN)
    cprint(f"   直播链接: {live_url}", Color.BLUE)
    cprint(f"   模式: {'无头' if headless else '有窗口（首次使用请登录）'}", Color.BLUE)
    cprint("")

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
        )

        stream_url = None
        stderr_lines = []

        # 实时读取输出
        while True:
            stdout_line = process.stdout.readline()
            stderr_line = process.stderr.readline()

            if stdout_line:
                line = stdout_line.strip()
                if line and not line.startswith('['):
                    stream_url = line
                # 打印 stderr 信息
            if stderr_line:
                stderr_lines.append(stderr_line.strip())
                # 打印进度信息
                msg = stderr_line.strip()
                if msg.startswith('[INFO]'):
                    cprint(f"  {msg}", Color.BLUE)
                elif msg.startswith('[FOUND]'):
                    cprint(f"  ✅ {msg}", Color.GREEN)
                elif msg.startswith('[WARN]'):
                    cprint(f"  ⚠️  {msg}", Color.YELLOW)
                elif msg.startswith('[ERROR]'):
                    cprint(f"  ❌ {msg}", Color.RED)
                elif msg.startswith('[SUCCESS]'):
                    cprint(f"  🎉 {msg}", Color.GREEN)
                elif msg.startswith('['):
                    cprint(f"  {msg}", Color.YELLOW)

            if process.poll() is not None:
                # 读取剩余输出
                remaining_stdout = process.stdout.read()
                remaining_stderr = process.stderr.read()
                if remaining_stdout:
                    for line in remaining_stdout.strip().split('\n'):
                        line = line.strip()
                        if line and not line.startswith('['):
                            stream_url = line
                if remaining_stderr:
                    for line in remaining_stderr.strip().split('\n'):
                        msg = line.strip()
                        if msg.startswith('[INFO]'):
                            cprint(f"  {msg}", Color.BLUE)
                        elif msg.startswith('[FOUND]'):
                            cprint(f"  ✅ {msg}", Color.GREEN)
                        elif msg.startswith('[WARN]'):
                            cprint(f"  ⚠️  {msg}", Color.YELLOW)
                        elif msg.startswith('[ERROR]'):
                            cprint(f"  ❌ {msg}", Color.RED)
                        elif msg.startswith('[SUCCESS]'):
                            cprint(f"  🎉 {msg}", Color.GREEN)
                        elif msg.startswith('['):
                            cprint(f"  {msg}", Color.YELLOW)
                break

            if stream_url:
                # 找到流地址后终止 Node 进程
                process.terminate()
                try:
                    process.wait(timeout=5)
                except:
                    process.kill()
                break

        if stream_url:
            return stream_url, None
        else:
            return None, "未能提取到流地址，请检查直播链接是否有效，或尝试在浏览器中先登录小红书"

    except FileNotFoundError:
        return None, f"Node.js 未找到: {NODE_BIN}"
    except Exception as e:
        return None, f"提取流地址时出错: {e}"


def record_stream(stream_url, output_base, live_url=None, headless=False):
    """
    使用 ffmpeg 录制流媒体
    关键技术：
    1. 先录到 .ts 文件（MPEG-TS 格式，不怕中断，随时可播）
    2. 录完后再转成 .mp4（写 moov 原子，QuickTime 兼容）
    3. 文件增长看门狗：60秒文件不增长 → 判定断流 → 杀 ffmpeg → 返回 "stalled"

    信号跟随逻辑：直播结束 → ffmpeg 检测到流断开自行退出 → 自动保存文件
    断流保护：文件停止增长 → 看门狗触发 → 返回 "stalled" 让主循环重抓流地址

    返回: (file_path, status)
      status = "ended"    直播自然结束
      status = "stopped"  用户手动停止
      status = "stalled"  断流，文件停止增长（主循环应重抓流地址继续录）
      status = "failed"   录制失败
    """
    ts_file = output_base.with_suffix('.ts')
    mp4_file = output_base.with_suffix('.mp4')

    cprint(f"\n🎬 检测到直播信号，开始录制...", Color.CYAN)
    cprint(f"   流地址: {stream_url[:80]}...", Color.BLUE)
    cprint(f"   临时文件: {ts_file.name} (TS格式，防中断)", Color.BLUE)
    cprint(f"   直播结束后自动停止，或按 Ctrl+C 手动停止\n", Color.BLUE)

    # ffmpeg 参数
    cmd = [
        FFMPEG_BIN,
        '-y',
        '-i', stream_url,
        '-c:v', 'libx264',
        '-preset', 'veryfast',
        '-crf', '23',
        '-c:a', 'copy',
        '-f', 'mpegts',
        '-timeout', '30000000',
        '-reconnect', '1',
        '-reconnect_streamed', '1',
        '-reconnect_delay_max', '10',
        str(ts_file),
    ]

    process = None
    start_time = time.time()
    stop_requested = False
    stalled = False

    # === 文件增长看门狗 ===
    WATCHDOG_INTERVAL = 15    # 每 15 秒检查一次文件大小
    WATCHDOG_STALL_LIMIT = 60 # 60 秒文件不增长 → 判定断流
    last_size = 0
    last_growth_time = time.time()
    last_check_time = time.time()

    def request_stop():
        """请求停止录制 - 通过向 ffmpeg stdin 写 'q' 触发优雅退出"""
        nonlocal stop_requested
        if stop_requested:
            return
        stop_requested = True
        cprint("\n\n⏹  正在停止录制（请等待 3-5 秒让 ffmpeg 写完文件）...", Color.YELLOW)
        if process and process.poll() is None:
            try:
                process.stdin.write('q\n')
                process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass

    def signal_handler(sig, frame):
        if not stop_requested:
            request_stop()
        else:
            cprint("\n\n⏹  强制停止...", Color.RED)
            if process and process.poll() is None:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    try:
                        process.kill()
                    except:
                        pass
            sys.exit(1)

    signal.signal(signal.SIGINT, signal_handler)

    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        preexec_fn=os.setsid,
    )

    # 实时显示 ffmpeg 进度 + 文件增长看门狗
    stream_ended = False
    while True:
        if process.poll() is not None:
            remaining = process.stderr.read()
            stream_ended = True
            break

        line = process.stderr.readline()
        now = time.time()

        # === 看门狗：定期检查文件增长 ===
        if now - last_check_time >= WATCHDOG_INTERVAL:
            last_check_time = now
            current_size = ts_file.stat().st_size if ts_file.exists() else 0
            if current_size > last_size:
                last_size = current_size
                last_growth_time = now
            else:
                # 文件没增长
                stall_duration = now - last_growth_time
                if stall_duration >= WATCHDOG_STALL_LIMIT:
                    cprint(f"\n\n⚠️  看门狗：文件已 {int(stall_duration)} 秒未增长，判定断流！", Color.RED)
                    cprint(f"   将杀掉 ffmpeg，重新抓取流地址继续录制", Color.YELLOW)
                    stalled = True
                    # 强制杀 ffmpeg
                    try:
                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    except (OSError, ProcessLookupError):
                        try:
                            process.kill()
                        except:
                            pass
                    break
                else:
                    cprint(f"\n  ⚠️  文件已 {int(stall_duration)} 秒未增长，等待恢复...", Color.YELLOW)

        if not line:
            time.sleep(0.1)
            continue

        line = line.strip()
        time_match = re.search(r'time=(\d{2}:\d{2}:\d{2}\.\d{2})', line)
        if time_match:
            elapsed_str = time_match.group(1)
            elapsed = time.time() - start_time
            file_size = ts_file.stat().st_size if ts_file.exists() else 0
            size_mb = file_size / (1024 * 1024)
            speed_match = re.search(r'speed=\s*([\d.]+)x', line)
            speed = speed_match.group(1) if speed_match else '?'

            sys.stdout.write(
                f"\r  ⏱  已录制: {elapsed_str}  |  "
                f"📦 {size_mb:.1f} MB  |  "
                f"⚡ {speed}x    "
            )
            sys.stdout.flush()
        elif 'error' in line.lower() or 'invalid' in line.lower():
            if 'Connection refused' in line or 'End of file' in line:
                pass
            else:
                cprint(f"\n  ⚠️  {line}", Color.YELLOW)

    # 确保进程完全退出
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        cprint(f"\n  ⚠️  ffmpeg 进程未响应，强制结束", Color.YELLOW)
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except:
            pass

    # 确定返回状态
    if stalled:
        status = "stalled"
    elif stop_requested:
        status = "stopped"
    elif stream_ended:
        status = "ended"
    else:
        status = "failed"

    # 检查 TS 文件结果
    elapsed = time.time() - start_time
    if not (ts_file.exists() and ts_file.stat().st_size > 1024):
        cprint(f"\n\n❌ 录制失败", Color.RED)
        cprint(f"   可能原因: 直播已结束、流地址失效、网络问题", Color.RED)
        return None, "failed"

    ts_size_mb = ts_file.stat().st_size / (1024 * 1024)

    if status == "stalled":
        cprint(f"\n📦 断流保护：保存当前片段 ({ts_size_mb:.1f} MB)，准备重新抓取流地址", Color.YELLOW)
        # 断流时先不转 mp4，保留 ts 文件，主循环会继续录制新片段
        return ts_file, "stalled"

    if status == "ended" and not stop_requested:
        cprint(f"\n\n✅ 直播已结束，录制完成！", Color.GREEN)
    else:
        cprint(f"\n\n✅ 录制完成！", Color.GREEN)
    cprint(f"   TS 文件: {ts_file.name} ({ts_size_mb:.1f} MB)", Color.GREEN)
    cprint(f"   时长: {int(elapsed // 60)}分{int(elapsed % 60)}秒", Color.GREEN)

    # TS → MP4 转换（remux，不重新编码，速度快）
    cprint(f"\n📦 正在转换为 MP4 格式...", Color.CYAN)
    remux_cmd = [
        FFMPEG_BIN,
        '-y',
        '-i', str(ts_file),
        '-c', 'copy',
        '-bsf:a', 'aac_adtstoasc',
        '-movflags', '+faststart',
        str(mp4_file),
    ]

    try:
        result = subprocess.run(remux_cmd, capture_output=True, text=True, timeout=300)
        if mp4_file.exists() and mp4_file.stat().st_size > 1024:
            mp4_size_mb = mp4_file.stat().st_size / (1024 * 1024)
            cprint(f"✅ 转换完成！", Color.GREEN)
            cprint(f"   MP4 文件: {mp4_file.name} ({mp4_size_mb:.1f} MB)", Color.GREEN)
            cprint(f"   可以用 QuickTime / VLC / IINA 播放", Color.GREEN)
            ts_file.unlink()
            cprint(f"   已清理临时 TS 文件", Color.BLUE)
            return mp4_file, status
        else:
            cprint(f"⚠️  MP4 转换失败，但 TS 文件仍可用", Color.YELLOW)
            cprint(f"   TS 文件: {ts_file}", Color.YELLOW)
            return ts_file, status
    except subprocess.TimeoutExpired:
        cprint(f"⚠️  MP4 转换超时，但 TS 文件仍可用", Color.YELLOW)
        return ts_file, status
    except Exception as e:
        cprint(f"⚠️  MP4 转换出错: {e}", Color.YELLOW)
        return ts_file, status


def clean_profile():
    """清理浏览器缓存"""
    import shutil
    if CHROME_PROFILE.exists():
        cprint("清理浏览器缓存...", Color.YELLOW)
        shutil.rmtree(CHROME_PROFILE)
        cprint("✅ 缓存已清理", Color.GREEN)
    else:
        cprint("没有需要清理的缓存", Color.BLUE)


import json

def load_schedule(schedule_file):
    """
    加载时间表配置
    返回: list of (start_datetime, end_datetime, note, url)
    url 可能为空字符串，表示使用命令行传入的默认链接
    """
    if not schedule_file.exists():
        cprint(f"❌ 时间表文件不存在: {schedule_file}", Color.RED)
        sys.exit(1)

    try:
        with open(schedule_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        cprint(f"❌ 时间表 JSON 格式错误: {e}", Color.RED)
        sys.exit(1)

    windows = []
    for w in data.get('windows', []):
        try:
            start = datetime.strptime(w['start'], '%Y-%m-%d %H:%M')
            end = datetime.strptime(w['end'], '%Y-%m-%d %H:%M')
            url = w.get('url', '').strip()
            windows.append((start, end, w.get('note', ''), url))
        except (KeyError, ValueError) as e:
            cprint(f"❌ 时间表项格式错误: {w} ({e})", Color.RED)
            sys.exit(1)

    # 按开始时间排序
    windows.sort(key=lambda x: x[0])
    return windows


def get_current_window(now, windows):
    """判断当前时间是否在某个时间窗口内"""
    for start, end, note, url in windows:
        if start <= now <= end:
            return (start, end, note, url)
    return None


def get_next_window(now, windows):
    """找到下一个还没开始的时间窗口"""
    for start, end, note, url in windows:
        if start > now:
            return (start, end, note, url)
    return None


def sleep_until(target_time, reason=""):
    """
    睡眠到目标时间，期间显示倒计时
    资源消耗极低：不启动 Chrome、不联网
    """
    now = datetime.now()
    if target_time <= now:
        return

    if reason:
        cprint(f"\n💤 {reason}", Color.BLUE)
        cprint(f"   下次唤醒: {target_time.strftime('%Y-%m-%d %H:%M:%S')}", Color.BLUE)
        cprint(f"   当前时间: {now.strftime('%Y-%m-%d %H:%M:%S')}", Color.BLUE)

    while True:
        now = datetime.now()
        remaining = (target_time - now).total_seconds()
        if remaining <= 0:
            break

        # 显示倒计时
        days = int(remaining // 86400)
        hours = int((remaining % 86400) // 3600)
        minutes = int((remaining % 3600) // 60)
        seconds = int(remaining % 60)

        if days > 0:
            countdown = f"{days}天{hours}小时{minutes}分{seconds}秒"
        elif hours > 0:
            countdown = f"{hours}小时{minutes}分{seconds}秒"
        elif minutes > 0:
            countdown = f"{minutes}分{seconds}秒"
        else:
            countdown = f"{seconds}秒"

        sys.stdout.write(f"\r  💤 距离下次监测还有: {countdown}    ")
        sys.stdout.flush()

        # 睡眠策略：每 60 秒醒一次刷新显示
        if remaining > 60:
            time.sleep(60)
        else:
            time.sleep(1)

    cprint(f"\n  ⏰ 时间到，开始监测直播信号", Color.GREEN)


def wait_for_stream(live_url, headless=False, timeout=30, schedule_windows=None):
    """
    监测直播链接直到检测到信号

    schedule_windows: 时间表窗口列表 [(start, end, note, url), ...]
        - 如果提供：只在窗口内监测，窗口外深度睡眠（不启动 Chrome、不联网）
        - 每个窗口可有独立的 url，为空则用 live_url（命令行传入的默认链接）
        - 如果为 None：持续监测（每次间隔 30 秒）
    """
    check_interval = 30  # 每次检测间隔30秒
    attempt = 0

    def get_active_url(window):
        """从时间窗口获取本次监测该用的链接"""
        if window and window[3]:  # window = (start, end, note, url)
            return window[3]
        return live_url

    # 第一次进入：检查时间表
    if schedule_windows:
        now = datetime.now()
        # 如果所有时间窗口都已过期，提示并退出
        next_w = get_next_window(now, schedule_windows)
        if not next_w:
            last_end = schedule_windows[-1][1]
            cprint(f"\n📅 时间表已全部结束", Color.YELLOW)
            cprint(f"   最后一场: {last_end.strftime('%Y-%m-%d %H:%M')}", Color.BLUE)
            cprint(f"   当前时间: {now.strftime('%Y-%m-%d %H:%M')}", Color.BLUE)
            sys.exit(0)
        # 如果当前不在窗口内，先睡到下一个窗口开始
        if not get_current_window(now, schedule_windows):
            start, end, note, url = next_w
            sleep_until(
                start,
                f"当前不在直播时间表内（{note}），进入省电模式"
            )

    while True:
        # 每次循环都检查时间表
        current_w = None
        if schedule_windows:
            now = datetime.now()
            current_w = get_current_window(now, schedule_windows)
            if not current_w:
                # 不在窗口内，进入省电模式
                next_w = get_next_window(now, schedule_windows)
                if not next_w:
                    # 所有窗口都过了，退出
                    cprint(f"\n📅 所有直播时间已结束，自动退出", Color.YELLOW)
                    sys.exit(0)
                start, end, note, url = next_w
                sleep_until(start, f"直播时间表外，省电模式（{note} 开始时唤醒）")
                continue  # 唤醒后回到循环顶部

        # 确定本次监测用的链接：时间表里的 url 优先，没有就用命令行默认链接
        active_url = get_active_url(current_w)

        attempt += 1
        now_str = datetime.now().strftime("%H:%M:%S")
        cprint(f"\n📡 [{now_str}] 第 {attempt} 次检测直播信号...", Color.CYAN)

        stream_url, error = extract_stream_url(
            active_url,
            headless=headless,
            timeout=timeout
        )

        if stream_url:
            cprint(f"\n🎬 检测到直播信号！", Color.GREEN)
            return stream_url, None

        # 没检测到信号，等待后重试
        cprint(f"   ⏳ 未检测到直播信号，{check_interval} 秒后重试...", Color.YELLOW)
        cprint(f"   （直播可能还没开始，工具会持续等待）", Color.BLUE)

        # 倒计时等待
        for i in range(check_interval, 0, -1):
            sys.stdout.write(f"\r   等待中... {i}s   ")
            sys.stdout.flush()
            time.sleep(1)
        sys.stdout.write("\r" + " " * 30 + "\r")
        sys.stdout.flush()


def merge_segments(segments, base_output):
    """
    合并多个录制片段（.ts 或 .mp4）为一个文件
    使用 ffmpeg concat demuxer，不重新编码，速度快
    """
    if not segments:
        return None

    if len(segments) == 1:
        return segments[0]

    # 创建 concat 列表文件
    list_file = base_output.with_suffix('.txt')
    with open(list_file, 'w') as f:
        for seg in segments:
            # ffmpeg concat 需要绝对路径，单引号包裹
            f.write(f"file '{seg.resolve()}'\n")

    # 合并后的输出文件
    merged_mp4 = base_output.with_suffix('.mp4')

    # 先合并为 ts（concat 对 ts 兼容性最好），再转 mp4
    merged_ts = base_output.with_name(base_output.stem + '_merged.ts')
    concat_cmd = [
        FFMPEG_BIN,
        '-y',
        '-f', 'concat',
        '-safe', '0',
        '-i', str(list_file),
        '-c', 'copy',
        str(merged_ts),
    ]

    try:
        result = subprocess.run(concat_cmd, capture_output=True, text=True, timeout=600)
        if not (merged_ts.exists() and merged_ts.stat().st_size > 1024):
            cprint(f"⚠️  合并失败", Color.YELLOW)
            list_file.unlink(missing_ok=True)
            return None

        # ts → mp4
        remux_cmd = [
            FFMPEG_BIN,
            '-y',
            '-i', str(merged_ts),
            '-c', 'copy',
            '-bsf:a', 'aac_adtstoasc',
            '-movflags', '+faststart',
            str(merged_mp4),
        ]
        result = subprocess.run(remux_cmd, capture_output=True, text=True, timeout=300)

        if merged_mp4.exists() and merged_mp4.stat().st_size > 1024:
            # 清理临时文件
            merged_ts.unlink()
            list_file.unlink()
            # 删除各片段
            for seg in segments:
                seg.unlink(missing_ok=True)
            return merged_mp4
        else:
            # mp4 转换失败，保留合并后的 ts
            cprint(f"⚠️  MP4 转换失败，保留合并后的 TS 文件", Color.YELLOW)
            list_file.unlink(missing_ok=True)
            return merged_ts
    except Exception as e:
        cprint(f"⚠️  合并出错: {e}", Color.YELLOW)
        list_file.unlink(missing_ok=True)
        return None


def main():
    parser = argparse.ArgumentParser(
        description='小红书直播录制工具 — 跟随信号自动录制',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  # 跟随信号录制（直播开始即录，结束即停）
  python3 recorder.py https://xhslink.com/m/xxx

  # 无头模式
  python3 recorder.py https://xhslink.com/m/xxx --headless

  # 直播结束后继续等待重新开播（循环模式）
  python3 recorder.py https://xhslink.com/m/xxx --loop

  # 手动模式（直接给流地址）
  python3 recorder.py --manual https://xxx.com/live.m3u8
        '''
    )
    parser.add_argument('url', nargs='?', help='小红书直播链接或流地址')
    parser.add_argument('--headless', action='store_true', help='无头模式（不显示浏览器窗口）')
    parser.add_argument('--manual', action='store_true', help='手动模式：直接输入流地址录制')
    parser.add_argument('--timeout', type=int, default=30, help='流地址提取超时时间（秒）')
    parser.add_argument('--clean', action='store_true', help='清理浏览器缓存')
    parser.add_argument('--loop', action='store_true', help='循环模式：直播结束后继续等待重新开播')
    parser.add_argument('--schedule', type=str, default=None, help='时间表文件路径（JSON），指定直播时段以节省资源')

    args = parser.parse_args()

    ensure_dirs()

    # 清理缓存
    if args.clean:
        clean_profile()
        return

    # 需要提供 URL
    if not args.url:
        parser.print_help()
        sys.exit(1)

    cprint("=" * 50, Color.HEADER)
    cprint("  📹 小红书直播录制工具", Color.HEADER + Color.BOLD)
    cprint("  跟随信号模式：直播开始即录，结束即停", Color.HEADER)
    cprint("=" * 50, Color.HEADER)

    # 加载时间表（可选）
    schedule_windows = None
    if args.schedule:
        schedule_file = Path(args.schedule)
        schedule_windows = load_schedule(schedule_file)
        cprint(f"\n📅 已加载时间表: {len(schedule_windows)} 个时段", Color.CYAN)
        for i, (start, end, note, url) in enumerate(schedule_windows, 1):
            url_display = f"  🔗 {url[:40]}..." if url else "  🔗 (用默认链接)"
            cprint(f"   {i}. {start.strftime('%m-%d %H:%M')} ~ {end.strftime('%H:%M')}  {note}{url_display}", Color.BLUE)
        cprint(f"   工具将在时段内监测，时段外省电睡眠", Color.BLUE)
        cprint(f"   每个时段可单独指定链接（编辑 schedule.json 的 url 字段）", Color.BLUE)

    # 手动模式 —— 直接录制，不监测信号
    if args.manual:
        stream_url = args.url
        cprint(f"\n🔧 手动模式：直接录制流地址", Color.CYAN)
        output_file = RECORDINGS_DIR / generate_filename()
        record_stream(stream_url, output_file)
        return

    # 信号跟随模式
    cprint(f"\n👀 信号跟随模式已启动", Color.CYAN)
    cprint(f"   链接: {args.url}", Color.BLUE)
    if args.loop:
        cprint(f"   模式: 循环（直播结束后继续等待重新开播）", Color.BLUE)
    else:
        cprint(f"   模式: 单次（直播结束后退出）", Color.BLUE)
    cprint(f"   断流保护：60秒文件不增长 → 自动重抓流地址继续录", Color.GREEN)

    # 记录所有录制片段（断流可能产生多个片段）
    all_segments = []
    segment_index = 0
    base_output = RECORDINGS_DIR / generate_filename()

    while True:
        # 1. 等待直播信号
        stream_url, error = wait_for_stream(
            args.url,
            headless=args.headless,
            timeout=args.timeout,
            schedule_windows=schedule_windows
        )

        if not stream_url:
            cprint(f"\n❌ {error}", Color.RED)
            break

        # 2. 录制（支持断流自动续录）
        while True:
            if segment_index == 0:
                output_file = base_output
            else:
                output_file = base_output.with_name(
                    base_output.stem + f"_seg{segment_index + 1}"
                )

            cprint(f"\n🎥 录制片段 {segment_index + 1}", Color.HEADER + Color.BOLD)
            result_file, status = record_stream(
                stream_url, output_file,
                live_url=args.url, headless=args.headless
            )

            if result_file:
                all_segments.append(result_file)

            if status == "stalled":
                # 断流了，重新抓取流地址继续录
                segment_index += 1
                cprint(f"\n🔄 断流恢复：重新抓取流地址...", Color.CYAN)
                cprint(f"   等待 15 秒后重试...", Color.BLUE)
                time.sleep(15)

                # 重新抓取流地址（用原始直播链接，不是旧的流地址）
                active_url = args.url
                if schedule_windows:
                    now = datetime.now()
                    current_w = get_current_window(now, schedule_windows)
                    if current_w and current_w[3]:
                        active_url = current_w[3]
                    elif not current_w:
                        cprint(f"\n📅 已不在直播时间表内，停止录制", Color.YELLOW)
                        break

                stream_url, error = extract_stream_url(
                    active_url, headless=args.headless, timeout=30
                )
                if stream_url:
                    cprint(f"\n✅ 重新抓取流地址成功，继续录制", Color.GREEN)
                    continue  # 回到内层 while，用新流地址继续录
                else:
                    cprint(f"\n⚠️  重新抓取流地址失败：{error}", Color.YELLOW)
                    cprint(f"   30 秒后再次尝试...", Color.BLUE)
                    time.sleep(30)
                    stream_url, error = extract_stream_url(
                        active_url, headless=args.headless, timeout=30
                    )
                    if stream_url:
                        cprint(f"\n✅ 第二次重抓成功，继续录制", Color.GREEN)
                        continue
                    else:
                        cprint(f"\n❌ 两次重抓流地址均失败，结束录制", Color.RED)
                        break
            else:
                # 录制正常结束（直播结束或用户停止）
                break

        # 3. 合并多个片段（如果有断流产生多段）
        if len(all_segments) > 1:
            cprint(f"\n📦 检测到 {len(all_segments)} 个录制片段，正在合并...", Color.CYAN)
            merged_file = merge_segments(all_segments, base_output)
            if merged_file:
                cprint(f"✅ 合并完成: {merged_file.name}", Color.GREEN)
            else:
                cprint(f"⚠️  合并失败，保留各片段文件", Color.YELLOW)
        elif len(all_segments) == 1:
            cprint(f"\n📦 录制文件: {all_segments[0].name}", Color.GREEN)

        # 4. 直播结束后的处理
        if not args.loop:
            cprint(f"\n👋 直播已结束，录制完成，退出", Color.GREEN)
            break

        cprint(f"\n🔄 循环模式：等待重新开播...", Color.CYAN)
        time.sleep(10)


if __name__ == '__main__':
    main()
