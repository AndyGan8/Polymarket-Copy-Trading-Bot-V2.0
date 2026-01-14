#!/bin/bash

# Polymarket 跟单机器人 V2.0 一键部署脚本（screen 后台版 + 自动依赖检查&安装）
# 作者：Andy甘 (@mingfei2022)
# 项目仓库：https://github.com/AndyGan8/Polymarket-Copy-Trading-Bot-V2.0
# 使用：wget -O polymarket.sh https://raw.githubusercontent.com/AndyGan8/Polymarket-Copy-Trading-Bot-V2.0/main/polymarket.sh && chmod +x polymarket.sh && ./polymarket.sh

# 配置变量（可自定义）
BOT_REPO_URL="https://raw.githubusercontent.com/AndyGan8/Polymarket-Copy-Trading-Bot-V2.0/main/bot.py"
BOT_DIR="$HOME/polymarket-bot-v2"
BOT_FILE="$BOT_DIR/bot.py"
PYTHON_CMD="python3"
SCREEN_NAME="polymarket-v2"

# 所需依赖包列表
REQUIRED_PACKAGES="py-clob-client websocket-client python-dotenv requests web3"

echo "===== Polymarket 跟单机器人 V2.0 一键部署（screen + 自动依赖） ====="
echo "作者：Andy甘 (@mingfei2022)"
echo "仓库：https://github.com/AndyGan8/Polymarket-Copy-Trading-Bot-V2.0"
echo ""

# 步骤1：检查并安装 screen
if ! command -v screen &> /dev/null; then
    echo "未检测到 screen，正在安装（需要 sudo）..."
    sudo apt update -y && sudo apt install -y screen
    [ $? -ne 0 ] && { echo "安装 screen 失败，请手动: sudo apt install screen"; exit 1; }
    echo "screen 已安装"
fi

# 步骤2：检查并设置 pip 国内镜像（加速安装）
echo "设置 pip 使用清华镜像加速..."
pip3 config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple || true

# 步骤3：自动检查并安装所有 Python 依赖
echo "正在检查并自动安装依赖包..."
for pkg in $REQUIRED_PACKAGES; do
    if ! $PYTHON_CMD -c "import $pkg" 2>/dev/null; then
        echo "缺少 $pkg，正在自动安装..."
        $PYTHON_CMD -m pip install $pkg
        if [ $? -ne 0 ]; then
            echo "安装 $pkg 失败！请手动运行：$PYTHON_CMD -m pip install $pkg"
            exit 1
        fi
        echo "$pkg 安装成功"
    else
        echo "$pkg 已安装"
    fi
done

# 步骤4：创建专用目录
mkdir -p "$BOT_DIR"
cd "$BOT_DIR" || exit 1
echo "目录: $BOT_DIR"

# 步骤5：下载 bot.py
wget -O bot.py "$BOT_REPO_URL"
[ $? -ne 0 ] && { echo "下载失败"; exit 1; }
echo "已下载 bot.py"

# 步骤6：处理换行符
sed -i 's/\r$//' bot.py
echo "已处理兼容性"

# 步骤7：赋予权限
chmod +x bot.py
echo "已赋予权限"

# 步骤8：检查重复 screen
if screen -list | grep -q "$SCREEN_NAME"; then
    echo "警告：已存在 $SCREEN_NAME 会话"
    read -p "1.强制新启动  2.退出 (1/2): " choice
    [ "$choice" != "1" ] && { echo "取消"; exit 0; }
fi

# 步骤9：使用 screen 后台启动
screen -dmS "$SCREEN_NAME" $PYTHON_CMD bot.py

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
echo "2. 选2配置私钥、RPC、目标地址（用 burner 钱包！）"
echo "3. 选3启动监控（PAPER_MODE=true 先测试）"
echo "4. Ctrl+A D 脱离"
echo ""
echo "日志：tail -f $BOT_DIR/bot.log"
echo "安全提醒：必须用全新小额 burner 钱包！先模拟模式测试几天"
echo "祝顺利～ @mingfei2022"
echo "项目地址：https://github.com/AndyGan8/Polymarket-Copy-Trading-Bot-V2.0"

exit 0
