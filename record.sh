#!/bin/bash
# 小红书直播录制工具 - 便捷启动脚本
# 用法: ./record.sh <直播链接> [选项]

cd "$(dirname "$0")"

# 自动查找 Python 3（优先环境变量，其次 PATH，最后常见路径）
find_python() {
    if [ -n "$PYTHON_BIN" ] && [ -x "$PYTHON_BIN" ]; then
        echo "$PYTHON_BIN"
        return
    fi
    for cmd in python3 python; do
        local p=$(command -v "$cmd" 2>/dev/null)
        if [ -n "$p" ]; then
            echo "$p"
            return
        fi
    done
    for path in \
        /Users/cc/.workbuddy/binaries/python/envs/default/bin/python3 \
        /usr/local/bin/python3 \
        /opt/homebrew/bin/python3; do
        if [ -x "$path" ]; then
            echo "$path"
            return
        fi
    done
    echo ""
}

PYTHON=$(find_python)
SCRIPT="$(pwd)/recorder.py"

if [ -z "$PYTHON" ]; then
    echo "❌ 未找到 Python 3，请安装或设置 PYTHON_BIN 环境变量"
    exit 1
fi

if [ $# -eq 0 ]; then
    echo "小红书直播录制工具 — 跟随信号自动录制"
    echo ""
    echo "用法:"
    echo "  ./record.sh <直播链接>                       # 跟随信号：直播开始即录，结束即停"
    echo "  ./record.sh <直播链接> --headless            # 无头模式"
    echo "  ./record.sh <直播链接> --loop                # 直播结束后继续等待重新开播"
    echo "  ./record.sh <直播链接> --schedule schedule.json  # 按时间表监测，省电模式"
    echo "  ./record.sh --manual <流地址>                # 手动输入流地址录制"
    echo "  ./record.sh --clean                         # 清理浏览器缓存"
    echo ""
    echo "示例:"
    echo "  ./record.sh https://xhslink.com/m/xxx"
    echo "  ./record.sh https://xhslink.com/m/xxx --headless --loop --schedule schedule.json"
    exit 0
fi

exec "$PYTHON" "$SCRIPT" "$@"
