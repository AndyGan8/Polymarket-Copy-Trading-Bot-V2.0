#!/bin/bash

# Polymarket 跟单机器人 V2.0 一键部署脚本（自动 venv + 安装依赖 + screen）
# 作者：Andy甘 (@mingfei2022)
# 项目仓库：https://github.com/AndyGan8/Polymarket-Copy-Trading-Bot-V2.0

set -e  # 遇到错误立即退出

BOT_REPO_URL="https://raw.githubusercontent.com/AndyGan8/Polymarket-Copy-Trading-Bot-V2.0/main/bot.py"
BOT_DIR="$HOME/polymarket-bot-v2"
VENV_DIR="$BOT_DIR/venv"
PYTHON_CMD="$VENV_DIR/bin/python3"
PIP_CMD="$VENV_DIR/bin/pip"
SCREEN_NAME="polymarket-v2"

echo "===== Polymarket 跟单机器人 V2.0 一键部署 ====="
echo "自动创建 venv + 安装依赖 + 启动 screen"
echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# 1. 安装 screen 和 venv 工具（Ubuntu 22.04/24.04 兼容）
echo "安装 screen 和 python3-venv..."
sudo apt update -y
sudo apt install -y screen python3-venv python3-pip

# 2. 创建项目目录
mkdir -p "$BOT_DIR"
cd "$BOT_DIR" || exit 1
echo "工作目录: $BOT_DIR"

# 3. 创建虚拟环境（如果不存在）
if [ ! -d "$VENV_DIR" ]; then
    echo "创建虚拟环境..."
    python3 -m venv "$VENV_DIR"
fi

# 4. 激活 venv 并安装依赖
echo "激活 venv 并安装核心依赖..."
source "$VENV_DIR/bin/activate"
"$PIP_CMD" install --upgrade pip -q
"$PIP_CMD" install py-clob-client requests python-dotenv -q

echo "依赖安装完成："
"$PIP_CMD" list | grep -E 'py-clob-client|requests|python-dotenv'

# 5. 下载/更新 bot.py
echo "下载/更新 bot.py..."
wget -q -O bot.py "$BOT_REPO_URL"
chmod +x bot.py

# 6. 清理旧 screen 会话
echo "清理旧 screen 会话..."
screen -ls | grep "$SCREEN_NAME" | awk '{print $1}' | while read s; do
    kill "${s%%.*}" 2>/dev/null || true
done
screen -wipe

# 7. 启动 screen（用 venv 的 python）
echo "启动 screen 会话 $SCREEN_NAME..."
screen -S "$SCREEN_NAME" -d -m "$PYTHON_CMD" bot.py

# 8. 立即进入 screen（用户看到菜单）
echo "部署完成！进入 screen 会话..."
sleep 1
screen -r "$SCREEN_NAME"

echo ""
echo "已进入 screen 会话"
echo "首次操作："
echo "  - 选2 配置私钥（用全新 burner 钱包！）、目标地址"
echo "  - PAPER_MODE=true 先模拟测试几天"
echo ""
echo "管理命令："
echo "  脱离后台: Ctrl+A 然后 D"
echo "  重新进入: screen -r $SCREEN_NAME"
echo "  查看日志: tail -f $BOT_DIR/bot.log"
echo ""
echo "安全提醒：私钥必须全新小额 burner 钱包！先模拟测试几天"
echo "项目地址：https://github.com/AndyGan8/Polymarket-Copy-Trading-Bot-V2.0"

exit 0
