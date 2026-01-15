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
from web3.providers.persistent import WebSocketProvider
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

# ==================== 函数定义区 ====================

def load_market_mappings():
    global TOKEN_MAP
    logger.info("正在从 Gamma API 加载市场映射...")
    try:
        resp = requests.get(GAMMA_MARKETS_URL, timeout=15)
        resp.raise_for_status()
        markets = resp.json()
        count = 0
        for market in markets:
            clob_ids = market.get('clobTokenIds', [])
            tokens = market.get('tokens', [])
            for i, clob_id in enumerate(clob_ids):
                if i < len(tokens):
                    try:
                        pos_id = int(clob_id)
                        TOKEN_MAP[pos_id] = {
                            'token_id': clob_id,
                            'market': market.get('question', '未知市场'),
                            'outcome': tokens[i].get('outcome', '未知'),
                            'decimals': 6
                        }
                        count += 1
                    except:
                        continue
        logger.info(f"成功加载 {count} 个 token 映射")
    except Exception as e:
        logger.error(f"加载 Gamma 市场失败: {e}")

def show_menu():
    print("\n===== Polymarket 跟单机器人 V2.0 =====")
    print("1. 检查环境并自动安装依赖")
    print("2. 配置密钥、RPC、跟单地址等（首次必做）")
    print("3. 启动跟单机器人（链上事件监听）")
    print("4. 查看当前配置")
    print("5. 查看钱包余额、持仓及跟单历史")
    print("6. 退出")
    return input("\n请输入选项 (1-6): ").strip()

def check_and_install_dependencies():
    logger.info("检查依赖...")
    try:
        import pkg_resources
        installed = {pkg.key: pkg.version for pkg in pkg_resources.working_set}
    except:
        result = subprocess.run(["pip", "list", "--format=freeze"], capture_output=True, text=True)
        installed = dict(line.split('==') for line in result.stdout.splitlines() if '==' in line)

    missing = [r.split('>=')[0].strip().lower() for r in REQUIREMENTS if r.split('>=')[0].strip().lower() not in installed]

    if missing:
        logger.info(f"缺少依赖: {', '.join(missing)}")
        if input("自动安装缺失依赖？(y/n): ").lower() == 'y':
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing)
                logger.info("安装完成")
            except Exception as e:
                logger.error(f"安装失败: {e}")
        else:
            logger.warning("请手动安装")
    else:
        logger.info("所有依赖已安装")

def setup_config():
    if not os.path.exists(ENV_FILE):
        open(ENV_FILE, 'a').close()

    load_dotenv(ENV_FILE)

    while True:
        print("\n=== 配置选单 ===")
        print("1. 修改必须参数（私钥、RPC、目标地址）")
        print("2. 修改可选参数")
        print("3. 返回主菜单")
        sub = input("请选择 (1-3): ").strip()

        if sub == "3":
            break

        if sub == "1":
            params = [
                ("PRIVATE_KEY", "私钥（burner钱包）"),
                ("RPC_URL", "wss://... (必须 wss 开头)"),
                ("TARGET_WALLETS", "目标地址，逗号分隔")
            ]
            for key, desc in params:
                val = input(f"{key} ({desc}) 当前: {os.getenv(key, '未设置')[:10]}...: ").strip()
                if val:
                    set_key(ENV_FILE, key, val)
                    os.environ[key] = val
                    print(f"{key} 更新完成")

        elif sub == "2":
            optionals = [
                ("TRADE_MULTIPLIER", "跟单比例 0.35"),
                ("MAX_POSITION_USD", "最大金额 150"),
                ("MIN_TRADE_USD", "最小金额 20"),
                ("PAPER_MODE", "true/false"),
                ("SLIPPAGE_TOLERANCE", "滑点 0.02")
            ]
            for key, default in optionals:
                val = input(f"{key} 当前: {os.getenv(key, default)} 新值（留空保持）: ").strip()
                if val:
                    set_key(ENV_FILE, key, val)
                    os.environ[key] = val

def view_config():
    load_dotenv(ENV_FILE)
    print("\n当前配置：")
    keys = ["PRIVATE_KEY", "RPC_URL", "TARGET_WALLETS", "TRADE_MULTIPLIER", "MAX_POSITION_USD", "MIN_TRADE_USD", "PAPER_MODE", "SLIPPAGE_TOLERANCE"]
    for k in keys:
        v = os.getenv(k, "未设置")
        if k == "PRIVATE_KEY" and v != "未设置":
            v = v[:6] + "..." + v[-4:]
        print(f"{k:20}: {v}")

def view_wallet_info():
    # 简化版（可复制你完整版本）
    print("钱包信息查询（占位）")

def ensure_api_creds(client):
    load_dotenv(ENV_FILE)
    if all(os.getenv(k) for k in ["API_KEY", "API_SECRET", "API_PASSPHRASE"]):
        client.set_api_creds({
            "api_key": os.getenv("API_KEY"),
            "api_secret": os.getenv("API_SECRET"),
            "api_passphrase": os.getenv("API_PASSPHRASE")
        })
        return True

    logger.info("生成 API Credentials...")
    try:
        creds = client.create_or_derive_api_creds()
        set_key(ENV_FILE, "API_KEY", creds.api_key)
        set_key(ENV_FILE, "API_SECRET", creds.api_secret)
        set_key(ENV_FILE, "API_PASSPHRASE", creds.api_passphrase)
        logger.info("凭证保存成功")
        return True
    except Exception as e:
        logger.error(f"生成失败: {e}")
        return False

async def subscribe_to_order_filled(w3: AsyncWeb3, contract_address, target_set, client):
    contract = w3.eth.contract(address=contract_address, abi=ORDER_FILLED_ABI)
    processed = set()

    async def handle(event):
        h = event['args']['orderHash'].hex()
        if h in processed:
            return
        processed.add(h)

        maker = event['args']['maker'].lower()
        taker = event['args']['taker'].lower()

        if maker in target_set or taker in target_set:
            wallet = maker if maker in target_set else taker
            block = await w3.eth.get_block(event['blockNumber'])
            ts = datetime.fromtimestamp(block['timestamp'])

            # ... 方向、价格、usd_value、position_id 逻辑同前

            logger.info(f"检测到 {wallet} 成交 @ {ts}")

            # 跟单计算 + 下单逻辑（同前）

    filter_ = await contract.events.OrderFilled.create_filter(fromBlock='latest')

    while True:
        try:
            for e in await filter_.get_new_entries():
                await handle(e)
            await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"订阅异常: {e}")
            await asyncio.sleep(10)

async def monitor_target_trades_async(client):
    load_dotenv(ENV_FILE)
    targets = set(a.strip().lower() for a in os.getenv("TARGET_WALLETS", "").split(",") if a.strip())
    if not targets:
        logger.warning("无目标地址")
        return

    logger.info(f"监听目标: {', '.join(targets)}")

    rpc = os.getenv("RPC_URL")
    if not rpc.startswith("wss://"):
        logger.error(f"RPC 需 wss:// 开头: {rpc}")
        return

    try:
        async with AsyncWeb3(WebSocketProvider(rpc)) as w3:
            if not await w3.is_connected():
                logger.error("WS 连接失败")
                return
            logger.info("WS 连接成功")

            await asyncio.gather(
                subscribe_to_order_filled(w3, CTF_EXCHANGE, targets, client),
                subscribe_to_order_filled(w3, NEGRISK_EXCHANGE, targets, client)
            )
    except Exception as e:
        logger.critical(f"监控启动失败: {e}")

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
                logger.error("缺少 .env，请先配置")
                continue

            load_dotenv(ENV_FILE)

            client = ClobClient(CLOB_HOST, key=os.getenv("PRIVATE_KEY"), chain_id=CHAIN_ID)
            if not ensure_api_creds(client):
                continue

            load_market_mappings()

            logger.info("启动链上监控...")
            asyncio.run(monitor_target_trades_async(client))

        elif choice == "4":
            view_config()

        elif choice == "5":
            view_wallet_info()

        elif choice == "6":
            logger.info("退出")
            sys.exit(0)

        else:
            print("无效选项")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("中断退出")
    except Exception as e:
        logger.critical(f"严重错误: {e}", exc_info=True)
