import os
import sys
import subprocess
import time
import json
import logging
import requests
from datetime import datetime
from dotenv import load_dotenv, set_key
from web3 import AsyncWeb3, Web3
from web3.providers.persistent import WebSocketProvider  # v7+ 正确导入
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs
from py_clob_client.order_builder.constants import BUY, SELL
import asyncio

# 日志配置
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
CHAIN_ID = 137
GAMMA_MARKETS_URL = "https://gamma-api.polymarket.com/markets?active=true&limit=1000"

NATIVE_USDC_ADDRESS_LOWER = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"

USDC_ABI = [
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"}
]

CTF_EXCHANGE = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
NEGRISK_EXCHANGE = "0xC5d563A36AE78145C45a50134d48A1215220f80a"

ORDER_FILLED_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "orderHash", "type": "bytes32"},
            {"indexed": True, "name": "maker", "type": "address"},
            {"indexed": True, "name": "taker", "type": "address"},
            {"indexed": False, "name": "makerAssetId", "type": "uint256"},
            {"indexed": False, "name": "takerAssetId", "type": "uint256"},
            {"indexed": False, "name": "makerAmountFilled", "type": "uint256"},
            {"indexed": False, "name": "takerAmountFilled", "type": "uint256"},
            {"indexed": False, "name": "fee", "type": "uint256"}
        ],
        "name": "OrderFilled",
        "type": "event"
    }
]

TOKEN_MAP = {}

def load_market_mappings():
    global TOKEN_MAP
    logger.info("加载 Polymarket 市场映射...")
    try:
        response = requests.get(GAMMA_MARKETS_URL)
        markets = response.json()
        count = 0
        for market in markets:
            clob_token_ids = market.get('clobTokenIds', [])
            tokens = market.get('tokens', [])
            for i, token_id_str in enumerate(clob_token_ids):
                try:
                    position_id = int(token_id_str)
                except ValueError:
                    continue
                if i < len(tokens):
                    token = tokens[i]
                    TOKEN_MAP[position_id] = {
                        'token_id': token_id_str,
                        'market_question': market['question'],
                        'outcome': token['outcome'],
                        'decimals': 6
                    }
                    count += 1
        logger.info(f"加载了 {count} 个映射")
    except Exception as e:
        logger.error(f"加载失败: {e}")

def show_menu():
    print("\n===== Polymarket 跟单机器人（VPS简易版） =====")
    print("1. 检查环境并自动安装依赖")
    print("2. 配置密钥、RPC、跟单地址等（首次必做）")
    print("3. 启动跟单机器人（只跟输入地址）")
    print("4. 查看当前配置")
    print("5. 查看钱包余额、持仓及跟单历史")
    print("6. 退出")
    return input("\n请输入选项 (1-6): ").strip()

def check_and_install_dependencies():
    # ... (你的原函数，省略以节省空间，复制原有即可)
    logger.info("检查依赖...")  # 占位，实际用你完整代码

def setup_config():
    if not os.path.exists(ENV_FILE):
        open(ENV_FILE, 'a').close()

    load_dotenv(ENV_FILE)

    while True:
        print("\n=== 配置选单（选项2） ===")
        print("1. 填写/修改 必须参数（私钥、RPC、目标地址）")
        print("2. 填写/修改 可选参数")
        print("3. 返回主选单")
        sub_choice = input("\n请选择 (1-3): ").strip()

        if sub_choice == "3":
            break

        if sub_choice == "1":
            must_have = [
                ("PRIVATE_KEY", "你的钱包私钥"),
                ("RPC_URL", "wss://polygon-mainnet.g.alchemy.com/v2/YOUR_KEY"),
                ("TARGET_WALLETS", "目标地址，逗号分隔")
            ]
            for key, desc in must_have:
                current = os.getenv(key, "未设置")
                print(f"当前 {key}: {current[:10] + '...' if current != '未设置' else current}")
                value = input(f"{key} - {desc}\n输入新值: ").strip()
                if value:
                    set_key(ENV_FILE, key, value)
                    os.environ[key] = value
                    print(f"{key} 已更新")

        elif sub_choice == "2":
            # 可选参数逻辑（复制你的原代码）
            pass

def view_config():
    # ... (复制你的原函数)

def view_wallet_info():
    # ... (复制你的原函数)

def ensure_api_creds(client):
    # ... (复制你的原函数)

async def subscribe_to_order_filled(w3: AsyncWeb3, contract_address, target_wallets_set, client):
    # ... (你的异步订阅逻辑，保持不变)

async def monitor_target_trades_async(client):
    # ... (你的异步监控主函数，保持不变)

def main():
    print("\n===== Polymarket 跟单机器人 V2.0 =====")

    while True:
        choice = show_menu()

        if choice == "1":
            check_and_install_dependencies()

        elif choice == "2":
            setup_config()

        elif choice == "3":
            if not os.path.exists(ENV_FILE):
                logger.error("请先配置 .env")
                continue

            load_dotenv(ENV_FILE)

            client = ClobClient(CLOB_HOST, key=os.getenv("PRIVATE_KEY"), chain_id=CHAIN_ID)
            if not ensure_api_creds(client):
                continue

            load_market_mappings()

            logger.info("启动跟单监控...")
            asyncio.run(monitor_target_trades_async(client))

        elif choice == "4":
            view_config()

        elif choice == "5":
            view_wallet_info()

        elif choice == "6":
            sys.exit(0)

        else:
            print("无效选项")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("用户中断")
    except Exception as e:
        logger.critical(f"严重错误: {e}", exc_info=True)
