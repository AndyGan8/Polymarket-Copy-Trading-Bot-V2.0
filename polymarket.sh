#!/bin/bash

# Polymarket 跟单机器人 V2.0 一键部署脚本（自动安装依赖 + 启动 screen）
# 作者：Andy甘 (@mingfei2022)
# 项目仓库：https://github.com/AndyGan8/Polymarket-Copy-Trading-Bot-V2.0

BOT_REPO_URL="https://raw.githubusercontent.com/AndyGan8/Polymarket-Copy-Trading-Bot-V2.0/main/bot.py"
BOT_DIR="$HOME/polymarket-bot-v2"
PYTHON_CMD="python3"
SCREEN_NAME="polymarket-v2"

echo "===== Polymarket 跟单机器人 V2.0 一键部署 ====="
echo "本脚本会自动安装必要依赖（requests、python-dotenv、py-clob-client）"
echo ""

# 1. 安装 screen（如果没有）
if ! command -v screen &> /dev/null; then
    echo "未检测到 screen，正在安装..."
    sudo apt update -y && sudo apt install -y screen
    [ $? -ne 0 ] && { echo "安装 screen 失败，请手动：sudo apt install screen"; exit 1; }
fi

# 2. 创建目录并下载 bot.py
mkdir -p "$BOT_DIR"
cd "$BOT_DIR" || exit 1
echo "目录: $BOT_DIR"

wget -O bot.py "$BOT_REPO_URL"
[ $? -ne 0 ] && { echo "下载 bot.py 失败"; exit 1; }
echo "已下载 bot.py"

sed -i 's/\r$//' bot.py
echo "已处理兼容性"

chmod +x bot.py
echo "已赋予权限"

# 3. 自动安装核心依赖
echo "自动检查并安装依赖..."
DEPENDENCIES="requests python-dotenv py-clob-client"

for pkg in $DEPENDENCIES; do
    if python3 -c "import $pkg" 2>/dev/null; then
        echo "✅ $pkg 已安装"
    else
        echo "安装 $pkg..."
        pip3 install $pkg || pip3 install $pkg --break-system-packages
        if [ $? -ne 0 ]; then
            echo "❌ 安装 $pkg 失败"
            echo "请手动在虚拟环境中安装："
            echo "  python3 -m venv venv"
            echo "  source venv/bin/activate"
            echo "  pip install $pkg"
            exit 1
        fi
    fi
done

echo "✅ 所有核心依赖安装完成！"

# 4. 自动清理旧会话
echo "自动清理旧 $SCREEN_NAME 会话..."
screen -ls | grep "$SCREEN_NAME" | awk '{print $1}' | while read session; do
    kill "${session%%.*}" 2>/dev/null
done
screen -wipe
echo "旧会话已清理"

# 5. 启动 screen 并自动进入
echo "启动并进入 screen 会话 $SCREEN_NAME..."
screen -S "$SCREEN_NAME" $PYTHON_CMD bot.py

echo ""
echo "部署完成！已自动进入 screen 会话"
echo "首次操作："
echo "1. 进入后选2配置私钥、目标地址（用 burner 钱包！）"
echo "2. 选3启动监控（PAPER_MODE=true 先测试）"
echo ""
echo "管理命令："
echo "脱离后台 : Ctrl+A 然后 D"
echo "重新进入 : screen -r $SCREEN_NAME"
echo "日志      : tail -f $BOT_DIR/bot.log"
echo ""
echo "安全提醒：私钥必须用全新小额 burner 钱包！先模拟测试几天"
echo "项目地址：https://github.com/AndyGan8/Polymarket-Copy-Trading-Bot-V2.0"

exit 0
