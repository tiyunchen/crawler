#!/bin/bash
# 启动本地服务查看文章（支持同步按钮）
# 访问：http://localhost:8000/viewer.html

PROJECT_DIR="/Users/cty/Documents/pythonStuty/browser-use"
cd "$PROJECT_DIR" || exit 1

PORT=8000
URL="http://localhost:$PORT/viewer.html"

echo "🌐 启动服务：$URL"
echo "🔄 同步接口：POST http://localhost:$PORT/api/sync"
echo "📖 正在打开浏览器..."
echo "🛑 停止服务：Ctrl+C"
echo ""

# 后台打开浏览器
(sleep 1 && open "$URL") &

# 前台启动服务
"$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/server.py"
