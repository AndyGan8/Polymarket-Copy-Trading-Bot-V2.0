import os
import sys
import subprocess
import time
import json
import logging
import requests
from datetime import datetime
from dotenv import load_dotenv, set_key
from web3 import Web3
from py_clob_client.client import ClobClient
from py_clob_client.constants import Polygon
from websocket import WebSocketApp

# 日志配置 - 输出到终端 + 文件
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-5s | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", mode='a')
    ]
)
logger = logging.getLogger(__name__)

# 常量
ENV_FILE = ".env"
CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID = Polygon.CHAIN_ID
WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
GAMMA_MARKETS_URL = "https://gamma-api.polymarket.com/markets"

REQUIREMENTS = [
    "py-clob-client>=0.9.0",
    "websocket-client>=1.8.0",
    "python-dotenv>=1.0.0",
    "web3>=6.0.0",
    "requests>=2.28.0"
]

HOT_MARKETS_LIMIT = 80
HOT_TOKEN_LIMIT = 150

# ==================== 菜单 ====================
def show_menu():
    print("\n===== Polymarket 跟单机器人（VPS简易版） =====")
    print("1. 检查环境并自动安装依赖")
    print("2. 配置密钥、RPC、跟单地址等（首次必做）")
    print("3. 启动机器人（自动获取热门市场 + 跟单）")
    print("4. 查看当前配置")
    print("5. 退出")
    return input("\n请输入选项 (1-5): ").strip()

# ==================== 选项1：检查&安装依赖 ====================
def check_and_install_dependencies():
    logger.info("检查 Python 环境与依赖...")
    try:
        import pkg_resources
        installed = {pkg.key: pkg.version for pkg in pkg_resources.working_set}
    except:
        result = subprocess.run(["pip", "list", "--format=freeze"], capture_output=True, text=True)
        installed = dict(line.split('==') for line in result.stdout.splitlines() if '==' in line)

    missing = [req for req in REQUIREMENTS if req.split('>=')[0].strip().lower() not in installed]

    if missing:
        logger.info(f"缺少依赖: {', '.join(missing)}")
        if input("是否自动安装缺失依赖？(y/n): ").strip().lower() == 'y':
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing)
                logger.info("依赖安装完成！请重新运行脚本。")
            except Exception as e:
                logger.error(f"安装失败: {e}\n请手动运行: pip install {' '.join(missing)}")
        else:
            logger.warning("请手动安装依赖后再继续。")
    else:
        logger.info("所有必要依赖已安装 ✓")

# ==================== 选项2：配置引导 ====================
def setup_config():
    if not os.path.exists(ENV_FILE):
        open(ENV_FILE, 'a').close()

    load_dotenv(ENV_FILE)

    must_have = {
        "PRIVATE_KEY": "你的钱包私钥（0x开头，burner钱包推荐）",
        "RPC_URL": "Polygon RPC（如 Alchemy: https://polygon-mainnet.g.alchemy.com/v2/你的key）",
        "TARGET_WALLETS": "跟单目标地址（多个用逗号分隔）"
    }

    for key, desc in must_have.items():
        if not os.getenv(key):
            value = input(f"{key} ({desc}): ").strip()
            if not value:
                logger.error(f"{key} 不能为空！")
                return False
            set_key(ENV_FILE, key, value)
            os.environ[key] = value

    # 可选参数
    optionals = {
        "TRADE_MULTIPLIER": ("跟单比例", "0.35"),
        "MAX_POSITION_USD": ("单笔最大美元", "150"),
        "MIN_TRADE_USD": ("最小跟单金额", "20"),
        "PAPER_MODE": ("模拟模式(true/false)", "true")
    }

    for key, (desc, default) in optionals.items():
        current = os.getenv(key)
        if not current:
            value = input(f"{key} - {desc} (默认 {default}): ").strip() or default
            set_key(ENV_FILE, key, value)

    logger.info("配置已保存到 .env")
    return True

# ==================== 选项4：查看配置 ====================
def view_config():
    load_dotenv(ENV_FILE)
    print("\n当前配置概览：")
    keys = ["PRIVATE_KEY", "RPC_URL", "TARGET_WALLETS", "TRADE_MULTIPLIER",
            "MAX_POSITION_USD", "MIN_TRADE_USD", "PAPER_MODE"]
    for k in keys:
        v = os.getenv(k, "未设置")
        if k == "PRIVATE_KEY" and v != "未设置":
            v = v[:6] + "..." + v[-4:]
        print(f"{k:18}: {v}")

# ==================== 获取热门 token_ids ====================
def fetch_hot_token_ids():
    try:
        params = {
            "active": "true",
            "closed": "false",
            "limit": HOT_MARKETS_LIMIT,
            "order": "volume24hr",
            "ascending": "false"
        }
        r = requests.get(GAMMA_MARKETS_URL, params=params, timeout=12)
        r.raise_for_status()
        markets = r.json()

        tokens = set()
        for m in markets:
            for t in m.get("tokens", []):
                if "token_id" in t:
                    tokens.add(t["token_id"])

        token_list = list(tokens)[:HOT_TOKEN_LIMIT]
        logger.info(f"获取到 {len(token_list)} 个热门 token_id")
        return token_list
    except Exception as e:
        logger.error(f"获取热门市场失败: {e}")
        return []

# ==================== API Credentials 处理 ====================
def ensure_api_creds(client):
    load_dotenv(ENV_FILE)
    if all(os.getenv(k) for k in ["API_KEY", "API_SECRET", "API_PASSPHRASE"]):
        client.set_api_creds({
            "api_key": os.getenv("API_KEY"),
            "api_secret": os.getenv("API_SECRET"),
            "api_passphrase": os.getenv("API_PASSPHRASE")
        })
        return True

    logger.info("正在生成 Polymarket API Credentials（只需一次）...")
    try:
        creds = client.create_or_derive_api_creds()
        set_key(ENV_FILE, "API_KEY", creds.api_key)
        set_key(ENV_FILE, "API_SECRET", creds.api_secret)
        set_key(ENV_FILE, "API_PASSPHRASE", creds.api_passphrase)
        logger.info("API Credentials 已自动保存到 .env")
        return True
    except Exception as e:
        logger.error(f"生成失败: {e}\n请检查私钥/RPC是否正确")
        return False

# ==================== 简易 WebSocket 监控 ====================
class SimpleWSMonitor:
    def __init__(self, token_ids, config):
        self.token_ids = token_ids
        self.config = config
        self.ws = None

    def on_open(self, ws):
        logger.info(f"WebSocket 已连接，订阅 {len(self.token_ids)} 个市场...")
        if self.token_ids:
            ws.send(json.dumps({"assets_ids": self.token_ids, "type": "market"}))

    def on_message(self, ws, message):
        try:
            data = json.loads(message)
            if data.get("event_type") == "last_trade_price":
                token = data.get("token_id")
                price = float(data.get("price", 0))
                size = float(data.get("size", 0))
                usd = size * price

                if usd >= self.config["min_trade_usd"]:
                    side = "BUY" if price < 0.5 else "SELL"  # 极简判断（实际可优化）
                    copy_usd = usd * self.config["multiplier"]
                    if copy_usd <= self.config["max_pos_usd"]:
                        mode = "模拟" if self.config["paper_mode"] else "真实"
                        logger.info(f"[{mode}] 检测到交易 → {side} ${copy_usd:.2f} @ {price:.4f} ({token})")
        except:
            pass

    def run(self):
        self.ws = WebSocketApp(
            WS_URL,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=lambda ws, err: logger.error(f"WS错误: {err}"),
            on_close=lambda ws, c, m: (logger.warning("WS断开，5秒后重连..."), time.sleep(5), self.run())
        )
        self.ws.run_forever(ping_interval=25)

# ==================== 主程序 ====================
def main():
    while True:
        choice = show_menu()

        if choice == "1":
            check_and_install_dependencies()

        elif choice == "2":
            setup_config()

        elif choice == "3":
            if not os.path.exists(ENV_FILE):
                logger.error("请先运行选项 2 配置 .env")
                continue

            load_dotenv(ENV_FILE)
            config = {
                "multiplier": float(os.getenv("TRADE_MULTIPLIER", 0.35)),
                "max_pos_usd": float(os.getenv("MAX_POSITION_USD", 150)),
                "min_trade_usd": float(os.getenv("MIN_TRADE_USD", 20)),
                "paper_mode": os.getenv("PAPER_MODE", "true").lower() == "true"
            }

            w3 = Web3(Web3.HTTPProvider(os.getenv("RPC_URL")))
            if not w3.is_connected():
                logger.error("RPC连接失败，请检查 RPC_URL")
                continue

            client = ClobClient(CLOB_HOST, key=os.getenv("PRIVATE_KEY"), chain_id=CHAIN_ID)
            if not ensure_api_creds(client):
                continue

            token_ids = fetch_hot_token_ids()
            if not token_ids:
                logger.warning("未获取到热门市场，使用默认示例")
                token_ids = ["示例token_id1", "示例token_id2"]  # 占位

            logger.info("启动 WebSocket 监控...")
            monitor = SimpleWSMonitor(token_ids, config)
            monitor.run()

        elif choice == "4":
            view_config()

        elif choice == "5":
            logger.info("退出程序")
            sys.exit(0)

        else:
            print("无效选项，请输入1-5")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("用户中断，程序退出")
    except Exception as e:
        logger.critical(f"严重错误: {e}", exc_info=True)
