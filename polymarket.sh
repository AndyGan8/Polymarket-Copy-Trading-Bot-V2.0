#!/bin/bash

# Polymarket 跟单机器人 V2.0 一键部署脚本（screen 后台版）
# 作者：Andy甘 (基于用户需求定制)
# 使用方法：直接运行此脚本

# 配置变量（可修改）
BOT_REPO_URL="https://raw.githubusercontent.com/AndyGan8/Polymarket-Copy-Trading-Bot-V2.0/main/bot.py"
BOT_DIR="$HOME/polymarket-bot-v2"
BOT_FILE="$BOT_DIR/bot.py"
PYTHON_CMD="python3"  # 或 python，根据你的系统
SCREEN_NAME="polymarket-v2"  # screen 会话名，可自定义

echo "===== Polymarket 跟单机器人 V2.0 一键部署（screen 版） ====="
echo "仓库：https://github.com/AndyGan8/Polymarket-Copy-Trading-Bot-V2.0"
echo ""

# 步骤1：检查并安装 screen
if ! command -v screen &> /dev/null; then
    echo "未检测到 screen，正在自动安装（需要 sudo 权限）..."
    sudo apt update -y && sudo apt install screen -y
    if [ $? -ne 0 ]; then
        echo "安装 screen 失败，请手动运行：sudo apt install screen"
        exit 1
    fi
    echo "screen 已安装"
fi

# 步骤2：创建专用目录
mkdir -p "$BOT_DIR"
cd "$BOT_DIR" || exit 1
echo "已进入目录: $BOT_DIR"

# 步骤3：下载 bot.py
wget -O bot.py "$BOT_REPO_URL"
if [ $? -ne 0 ]; then
    echo "下载 bot.py 失败，请检查网络或仓库 URL"
    exit 1
fi
echo "已下载 bot.py"

# 步骤4：去除 Windows 换行符（兼容 GitHub Raw）
sed -i 's/\r$//' bot.py
echo "已处理换行符兼容性"

# 步骤5：赋予执行权限
chmod +x bot.py
echo "已赋予执行权限"

# 步骤6：检查是否已有同名 screen
if screen -list | grep -q "$SCREEN_NAME"; then
    echo "警告：已存在名为 $SCREEN_NAME 的 screen 会话"
    echo "1. 强制启动新会话（旧会话保留）"
    echo "2. 退出"
    read -p "请选择 (1/2): " choice
    if [ "$choice" != "1" ]; then
        echo "部署取消"
        exit 0
    fi
fi

# 步骤7：使用 screen 后台启动
screen -dmS "$SCREEN_NAME" $PYTHON_CMD bot.py

echo ""
echo "===== 部署完成！机器人已在 screen 后台运行 ====="
echo "会话名称: $SCREEN_NAME"
echo ""
echo "常用 screen 命令："
echo "1. 查看所有会话                  : screen -ls"
echo "2. 进入会话查看/操作菜单         : screen -r $SCREEN_NAME"
echo "   （进入后可看到实时日志，按 Ctrl+A 然后 D 脱离后台）"
echo "3. 脱离会话（不停止机器人）      : Ctrl+A 然后 D"
echo "4. 停止机器人并结束会话          : 进入会话后 Ctrl+C，然后 exit"
echo "   或直接杀进程：kill \$(pgrep -f bot.py)"
echo ""
echo "首次使用步骤（进入 screen 后）："
echo "1. 选 1：检查并自动安装依赖"
echo "2. 选 2：配置私钥、RPC、目标地址等（强烈建议用 burner 小额钱包！）"
echo "3. 选 3：启动监控（PAPER_MODE=true 先模拟测试）"
echo "4. Ctrl+A D 脱离后台，让它持续运行"
echo ""
echo "日志文件（如果有输出）：$BOT_DIR/bot.log"
echo "查看实时日志：tail -f $BOT_DIR/bot.log"
echo ""
echo "安全提醒："
echo "- 私钥必须用全新小额 burner 钱包！"
echo "- 先 PAPER_MODE=true 测试几天，确认无误再开真单"
echo "- VPS 安全：定期更新系统、用强密码、关闭 root 登录"
echo ""
echo "祝运行顺利！如需优化，欢迎反馈～ @mingfei2022"
echo "项目地址：https://github.com/AndyGan8/Polymarket-Copy-Trading-Bot-V2.0"

exit 0
