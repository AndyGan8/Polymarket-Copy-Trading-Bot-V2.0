#!/bin/bash

# Polymarket 跟单机器人 V2.0 一键部署脚本（screen + 自动清理旧会话 + 依赖自动安装）
# 作者：Andy甘 (@mingfei2022)
# 项目仓库：https://github.com/AndyGan8/Polymarket-Copy-Trading-Bot-V2.0
# 使用：wget -O polymarket.sh https://raw.githubusercontent.com/AndyGan8/Polymarket-Copy-Trading-Bot-V2.0/main/polymarket.sh && chmod +x polymarket.sh && ./polymarket.sh

# 配置变量
BOT_REPO_URL="https://raw.githubusercontent.com/AndyGan8/Polymarket-Copy-Trading-Bot-V2.0/main/bot.py"
BOT_DIR="$HOME/polymarket-bot-v2"
BOT_FILE="$BOT_DIR/bot.py"
PYTHON_CMD="python3"
SCREEN_NAME="polymarket-v2"

# 所需依赖包
REQUIRED_PACKAGES="py-clob-client websocket-client python-dotenv requests web3"

echo "===== Polymarket 跟单机器人 V2.0 一键部署（优化版） ====="
echo "作者：Andy甘 (@mingfei2022)"
echo "仓库：https://github.com/AndyGan8/Polymarket-Copy-Trading-Bot-V2.0"
echo ""

# 检查 Python 版本（需 3.8+）
PY_VERSION=$($PYTHON_CMD -V 2>&1 | grep -oP '\d+\.\d+')
if (( $(echo "$PY_VERSION < 3.8" | bc -l) )); then
    echo "错误：Python 版本过低 ($PY_VERSION)，需 3.8+"
    echo "请升级 Python 或使用 python3.10 等命令"
    exit 1
fi

# 设置 pip 清华镜像加速
echo "设置 pip 使用清华镜像加速..."
$PYTHON_CMD -m pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple || true

# 自动检查并安装所有依赖
echo "检查并安装 Python 依赖..."
for pkg in $REQUIRED_PACKAGES; do
    if ! $PYTHON_CMD -c "import $pkg" 2>/dev/null; then
        echo "缺少 $pkg，正在自动安装..."
        $PYTHON_CMD -m pip install $pkg
        [ $? -ne 0 ] && { echo "安装 $pkg 失败，请手动：$PYTHON_CMD -m pip install $pkg"; exit 1; }
        echo "$pkg 已安装"
    else
        echo "$pkg 已安装"
    fi
done

# 安装 screen（如果没有）
if ! command -v screen &> /dev/null; then
    echo "未检测到 screen，正在安装..."
    sudo apt update -y && sudo apt install -y screen
    [ $? -ne 0 ] && { echo "安装 screen 失败，请手动：sudo apt install screen"; exit 1; }
fi

# 创建目录
mkdir -p "$BOT_DIR"
cd "$BOT_DIR" || exit 1
echo "目录: $BOT_DIR"

# 下载 bot.py
wget -O bot.py "$BOT_REPO_URL"
[ $? -ne 0 ] && { echo "下载失败"; exit 1; }
echo "已下载 bot.py"

# 处理换行符
sed -i 's/\r$//' bot.py
echo "已处理兼容性"

# 赋予权限
chmod +x bot.py
echo "已赋予权限"

# 自动清理所有同名旧 screen 会话
echo "自动清理旧 $SCREEN_NAME 会话..."
screen -ls | grep "$SCREEN_NAME" | awk '{print $1}' | while read session; do
    kill "${session%%.*}" 2>/dev/null
done
screen -wipe
echo "旧会话已清理"

# 使用 screen 启动
echo "启动 screen 会话 $SCREEN_NAME..."
screen -dmS "$SCREEN_NAME" $PYTHON_CMD bot.py

# 检查是否启动成功
sleep 2
if screen -list | grep -q "$SCREEN_NAME"; then
    echo ""
    echo "===== 部署完成！机器人已在 screen 后台运行 ====="
    echo "会话名: $SCREEN_NAME"
    echo ""
    echo "管理命令："
    echo "进入会话   : screen -r $SCREEN_NAME"
    echo "脱离会话   : Ctrl+A 然后 D"
    echo "查看会话   : screen -ls"
    echo "停止机器人 : 进入会话后 Ctrl+C，然后 exit"
    echo ""
    echo "首次操作："
    echo "1. screen -r $SCREEN_NAME 进入"
    echo "2. 选2配置私钥、RPC、目标地址（必须用 burner 小额钱包！）"
    echo "3. 选3启动监控（先 PAPER_MODE=true 测试）"
    echo "4. Ctrl+A D 脱离后台"
    echo ""
    echo "日志：tail -f $BOT_DIR/bot.log"
    echo "安全提醒：私钥必须用全新小额 burner 钱包！先模拟测试几天"
    echo "祝顺利～ @mingfei2022"
else
    echo "警告：screen 启动失败，fallback 到 nohup 方式..."
    nohup $PYTHON_CMD bot.py > bot.log 2>&1 &
    echo "已使用 nohup 后台启动，查看日志：tail -f $BOT_DIR/bot.log"
    echo "进程ID: $!"
fi

echo ""
echo "项目地址：https://github.com/AndyGan8/Polymarket-Copy-Trading-Bot-V2.0"
echo "如有问题，欢迎反馈！"

exit 0
