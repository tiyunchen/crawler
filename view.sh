#!/bin/bash
# 启动本地静态服务查看文章
# 访问：http://localhost:8000/viewer.html

PROJECT_DIR="/Users/cty/Documents/pythonStuty/browser-use"
cd "$PROJECT_DIR" || exit 1

PORT=8000
URL="http://localhost:$PORT/viewer.html"

echo "🌐 启动静态服务：$URL"
echo "📖 正在打开浏览器..."
echo "🛑 停止服务：Ctrl+C"
echo ""

# 后台打开浏览器
(sleep 1 && open "$URL") &

# 前台启动 http 服务
python3 -m http.server $PORT
