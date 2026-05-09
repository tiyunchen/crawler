#!/bin/bash
# 定时任务包装脚本：切到项目目录 + 用 .venv 的 python + 开启无头模式 + 按天切分日志
# 被 launchd/cron 调用

PROJECT_DIR="/Users/cty/Documents/pythonStuty/browser-use"
PYTHON="$PROJECT_DIR/.venv/bin/python"
SCRIPT="$PROJECT_DIR/toutiao_crawler.py"

LOG_DIR="$PROJECT_DIR/output_toutiao/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/cron_$(date +%Y%m%d).log"

cd "$PROJECT_DIR" || exit 1

# 设置环境：无头模式、让 Playwright 找到系统 Chrome
export HEADLESS=1
export PATH="/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin:$PATH"

# 全部输出追加到日志文件
exec >> "$LOG_FILE" 2>&1

echo ""
echo "================================================================"
echo "🕐 $(date '+%Y-%m-%d %H:%M:%S') 开始执行定时抓取"
echo "================================================================"

"$PYTHON" "$SCRIPT"
EXIT_CODE=$?

echo ""
echo "✅ $(date '+%Y-%m-%d %H:%M:%S') 执行结束（exit=${EXIT_CODE}）"

exit "${EXIT_CODE}"
