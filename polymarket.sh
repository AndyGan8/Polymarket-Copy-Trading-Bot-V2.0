#!/bin/bash

# Polymarket 跟单机器人 V2.0 一键部署脚本（自动进入 screen + 跳过依赖检查）
# 作者：Andy甘 (@mingfei2022)
# 项目仓库：https://github.com/AndyGan8/Polymarket-Copy-Trading-Bot-V2.0

BOT_REPO_URL="https://raw.githubusercontent.com/AndyGan8/Polymarket-Copy-Trading-Bot-V2.0/main/bot.py"
BOT_DIR="$HOME/polymarket-bot-v2"
PYTHON_CMD="python3"
SCREEN_NAME="polymarket-v2"

REQUIRED_PACKAGES="py-clob-client websocket-client python-dotenv requests web3"

echo "===== Polymarket 跟单机器人 V2.0 一键部署 ====="
echo ""

# 设置 pip 镜像加速
$PYTHON_CMD -m pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple || true

# 自动检查并安装依赖（已安装跳过）
echo "检查依赖（已安装的跳过）..."
for pkg in $REQUIRED_PACKAGES; do
    if $PYTHON_CMD -c "import $pkg" 2>/dev/null; then
        echo "$pkg 已安装，跳过..."
    else
        echo "缺少 $pkg，正在安装..."
        $PYTHON_CMD -m pip install $pkg || { echo "安装失败"; exit 1; }
    fi
done

# 安装 screen
command -v screen >/dev/null 2>&1 || sudo apt update -y && sudo apt install -y screen

# 创建目录并下载
mkdir -p "$BOT_DIR"
cd "$BOT_DIR" || exit 1
wget -O bot.py "$BOT_REPO_URL" || exit 1
sed -i 's/\r$//' bot.py
chmod +x bot.py

# 清理旧会话
screen -ls | grep "$SCREEN_NAME" | awk '{print $1}' | while read s; do kill "${s%%.*}" 2>/dev/null; done
screen -wipe

# 启动并自动进入 screen 会话
echo "启动并进入 screen 会话 $SCREEN_NAME..."
screen -S "$SCREEN_NAME" $PYTHON_CMD bot.py

# 如果 screen 失败，fallback nohup
if [ $? -ne 0 ]; then
    echo "screen 启动失败，使用 nohup 后台运行..."
    nohup $PYTHON_CMD bot.py > bot.log 2>&1 &
    echo "日志: tail -f $BOT_DIR/bot.log"
fi

echo ""
echo "首次进入后：直接选2配置私钥（用 burner 钱包！），选3启动（PAPER_MODE=true 测试）"
echo "项目地址：https://github.com/AndyGan8/Polymarket-Copy-Trading-Bot-V2.0"
echo "安全第一，先模拟测试！"

exit 0
