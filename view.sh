#!/bin/bash
# 启动本地服务查看文章（支持同步按钮）
# 访问：http://localhost:8082/viewer.html

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR" || exit 1

PORT="${PORT:-8082}"
URL="http://localhost:$PORT/viewer.html"

echo "🌐 启动服务：$URL"
echo "🔄 同步接口：POST http://localhost:$PORT/api/sync"
echo "📖 本机可直接访问：$URL"
echo "🛑 停止服务：Ctrl+C"
echo ""

# 如果同端口上的本项目服务已经在运行，直接提示访问地址，避免重复启动时报端口占用。
if command -v curl >/dev/null 2>&1; then
  if curl -fsS "http://127.0.0.1:$PORT/api/sync/status" >/dev/null 2>&1 || \
     curl -fsS "http://localhost:$PORT/api/sync/status" >/dev/null 2>&1; then
    echo "✅ 查看服务已在运行：$URL"
    if command -v open >/dev/null 2>&1; then
      open "$URL"
    fi
    exit 0
  fi
fi

# 如果端口被其他进程占用，直接提示换端口，避免 server.py 再抛端口占用异常。
if command -v lsof >/dev/null 2>&1 && lsof -ti "tcp:$PORT" >/dev/null 2>&1; then
  echo "❌ 端口 $PORT 已被占用，但不是当前查看服务。"
  echo "   可以换端口启动：PORT=8083 ./view.sh"
  exit 1
fi



# 前台启动服务
PORT="$PORT" "$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/server.py"
