#!/bin/bash

# Polymarket 跟单机器人 V2.0 一键部署脚本（只下载 + 启动 screen，不自动安装依赖）
# 作者：Andy甘 (@mingfei2022)
# 项目仓库：https://github.com/AndyGan8/Polymarket-Copy-Trading-Bot-V2.0
# 使用：wget -O polymarket.sh https://raw.githubusercontent.com/AndyGan8/Polymarket-Copy-Trading-Bot-V2.0/main/polymarket.sh && chmod +x polymarket.sh && ./polymarket.sh

BOT_REPO_URL="https://raw.githubusercontent.com/AndyGan8/Polymarket-Copy-Trading-Bot-V2.0/main/bot.py"
BOT_DIR="$HOME/polymarket-bot-v2"
PYTHON_CMD="python3"
SCREEN_NAME="polymarket-v2"

echo "===== Polymarket 跟单机器人 V2.0 一键部署 ====="
echo "注意：依赖将在 bot.py 菜单选项1手动检查/安装"
echo ""

# 安装 screen（如果没有）
if ! command -v screen &> /dev/null; then
    echo "未检测到 screen，正在安装..."
    sudo apt update -y && sudo apt install -y screen
    [ $? -ne 0 ] && { echo "安装 screen 失败，请手动：sudo apt install screen"; exit 1; }
fi

# 创建目录并下载 bot.py
mkdir -p "$BOT_DIR"
cd "$BOT_DIR" || exit 1
echo "目录: $BOT_DIR"

wget -O bot.py "$BOT_REPO_URL"
[ $? -ne 0 ] && { echo "下载失败"; exit 1; }
echo "已下载 bot.py"

sed -i 's/\r$//' bot.py
echo "已处理兼容性"

chmod +x bot.py
echo "已赋予权限"

# 自动清理旧会话
echo "自动清理旧 $SCREEN_NAME 会话..."
screen -ls | grep "$SCREEN_NAME" | awk '{print $1}' | while read session; do
    kill "${session%%.*}" 2>/dev/null
done
screen -wipe
echo "旧会话已清理"

# 启动 screen 并自动进入
echo "启动并进入 screen 会话 $SCREEN_NAME..."
screen -S "$SCREEN_NAME" $PYTHON_CMD bot.py

echo ""
echo "部署完成！已自动进入 screen 会话"
echo "首次操作："
echo "1. 进入后选1检查并安装依赖（必须先做！）"
echo "2. 选2配置私钥、RPC、目标地址（用 burner 钱包！）"
echo "3. 选3启动监控（PAPER_MODE=true 先测试）"
echo ""
echo "管理命令："
echo "脱离后台 : Ctrl+A 然后 D"
echo "重新进入 : screen -r $SCREEN_NAME"
echo "日志      : tail -f $BOT_DIR/bot.log"
echo ""
echo "安全提醒：私钥必须用全新小额 burner 钱包！先模拟测试几天"
echo "项目地址：https://github.com/AndyGan8/Polymarket-Copy-Trading-Bot-V2.0"

exit 0
