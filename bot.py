import os
import sys
import subprocess
import time
import json
import logging
import requests
from datetime import datetime
from dotenv import load_dotenv, set_key
from web3 import AsyncWeb3, Web3  # 添加同步 Web3 用于 keccak
from web3.providers.persistent import WebSocketProvider
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs
from py_clob_client.order_builder.constants import BUY, SELL
import asyncio

# ==================== 依赖列表 ====================
REQUIREMENTS = [
    "py-clob-client>=0.34.0",
    "websocket-client>=1.8.0",
    "python-dotenv>=1.0.0",
    "web3>=7.0.0",
    "requests>=2.28.0"
]

# ==================== 日志配置 ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-5s | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", mode='a')
    ]
)
logger = logging.getLogger(__name__)

# ==================== 常量 ====================
ENV_FILE = ".env"
CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID = 137

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

# ==================== 主菜单 ====================
def show_menu():
    print("\n===== Polymarket 跟单机器人（VPS简易版） =====")
    print("1. 检查环境并自动安装依赖")
    print("2. 配置密钥、RPC、跟单地址等（首次必做）")
    print("3. 启动跟单机器人（只跟输入地址）")
    print("4. 查看当前配置")
    print("5. 查看监听状态和跟单情况")
    print("6. 退出")
    return input("\n请输入选项 (1-6): ").strip()

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
                logger.info("依赖安装完成！")
                print("依赖安装完成，请重新运行脚本或继续操作。")
            except Exception as e:
                logger.error(f"安装失败: {e}\n请手动运行: pip install {' '.join(missing)}")
        else:
            logger.warning("请手动安装依赖后再继续。")
    else:
        logger.info("所有必要依赖已安装 ✓")
        print("所有依赖已就位，无需安装。")

# ==================== 选项2：配置引导 ====================
def setup_config():
    if not os.path.exists(ENV_FILE):
        open(ENV_FILE, 'a').close()

    load_dotenv(ENV_FILE)

    while True:
        print("\n=== 配置选单（选项2） ====")
        print("1. 填写/修改 必须参数（私钥、目标地址）")
        print("2. 填写/修改 可选参数（跟单比例、金额限制、模拟模式）")
        print("3. 返回主选单")
        sub_choice = input("\n请选择 (1-3): ").strip()

        if sub_choice == "3":
            break

        if sub_choice == "1":
            must_have = [
                ("PRIVATE_KEY", "你的钱包私钥（全新burner钱包）"),
                ("TARGET_WALLETS", "跟单目标地址（逗号分隔）")
            ]
            for key, desc in must_have:
                current = os.getenv(key, "未设置")
                print(f"\n当前 {key}: {current[:10] + '...' if current != '未设置' else current}")
                value = input(f"{key} - {desc}\n输入新值: ").strip()
                if value:
                    set_key(ENV_FILE, key, value)
                    os.environ[key] = value

        elif sub_choice == "2":
            current = os.getenv("RPC_WSS_LIST", "未设置")
            print(f"\n当前 RPC wss 列表: {current}")
            print("输入多个 wss 地址，用逗号分隔（留空使用默认）")
            value = input("新 RPC_WSS_LIST: ").strip()
            if value:
                set_key(ENV_FILE, "RPC_WSS_LIST", value)
                os.environ["RPC_WSS_LIST"] = value

        elif sub_choice == "3":
            # 可选参数逻辑（保持原样）
            pass

def view_config():
    load_dotenv(ENV_FILE)
    print("\n当前配置：")
    keys = ["PRIVATE_KEY", "RPC_WSS_LIST", "TARGET_WALLETS", "TRADE_MULTIPLIER", "MAX_POSITION_USD", "MIN_TRADE_USD", "PAPER_MODE"]
    for k in keys:
        v = os.getenv(k, "未设置")
        print(f"{k}: {v}")

def view_wallet_info():
    load_dotenv(ENV_FILE)
    print("\n=== 监听状态和跟单情况 ===\n")

    try:
        with open("bot.log", "r", encoding="utf-8") as f:
            last_lines = f.readlines()[-100:]
            log_tail = ''.join(last_lines)

            if "启动链上 OrderFilled 监听" in log_tail:
                print("监听状态: 已启动")
            else:
                print("监听状态: 未启动")

            if "WebSocket 连接成功" in log_tail:
                print("WebSocket 连接: 正常")
            else:
                print("WebSocket 连接: 未连接或失败")

            print(f"监听目标地址: {os.getenv('TARGET_WALLETS', '未设置')}")

            if "链上检测到目标" in log_tail:
                print("最近活动: 有成交记录")
            else:
                print("最近活动: 暂无成交")

            print("\n最近跟单情况：")
            found = False
            for line in last_lines:
                if "检测到目标" in line or "准备跟单" in line:
                    print(line.strip())
                    found = True
            if not found:
                print("暂无跟单记录")

    except Exception as e:
        print(f"读取失败: {e}")

    print("\n查看完成！按回车返回...")
    input()

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
        return True
    except Exception as e:
        logger.error(f"生成失败: {e}")
        return False

# ==================== 轮询式监听函数（已修复 Web3.keccak 导入） ====================
async def poll_order_filled(w3: AsyncWeb3, contract_address, target_set, client, last_block):
    contract = w3.eth.contract(address=contract_address, abi=ORDER_FILLED_ABI)
    processed_hashes = set()

    while True:
        try:
            current_block = await w3.eth.block_number
            if current_block > last_block:
                logs = await w3.eth.get_logs({
                    'fromBlock': last_block + 1,
                    'toBlock': current_block,
                    'address': contract_address,
                    'topics': [Web3.keccak(text="OrderFilled(bytes32,address,address,uint256,uint256,uint256,uint256,uint256)").hex()]
                })

                for log in logs:
                    event = contract.events.OrderFilled().process_log(log)
                    await handle_event(event, target_set, client)  # 调用处理函数

                last_block = current_block
            await asyncio.sleep(5)  # 每5秒轮询一次
        except Exception as e:
            logger.error(f"轮询异常 ({contract_address}): {e}")
            await asyncio.sleep(10)

async def handle_event(event, target_set, client):
    order_hash = event['args']['orderHash'].hex()
    if order_hash in processed_hashes:
        return
    processed_hashes.add(order_hash)

    maker = event['args']['maker'].lower()
    taker = event['args']['taker'].lower()

    if maker in target_set or taker in target_set:
        wallet = maker if maker in target_set else taker
        ts = datetime.now()  # 简化

        maker_asset = event['args']['makerAssetId']
        taker_asset = event['args']['takerAssetId']
        maker_amt = event['args']['makerAmountFilled'] / 1e6
        taker_amt = event['args']['takerAmountFilled'] / 1e6

        if maker_asset == 0:
            side = BUY
            price = maker_amt / taker_amt if taker_amt > 0 else 0
            usd_value = maker_amt
            pos_id = taker_asset
        else:
            side = SELL
            price = taker_amt / maker_amt if maker_amt > 0 else 0
            usd_value = taker_amt
            pos_id = maker_asset

        if pos_id not in TOKEN_MAP:
            logger.warning(f"未知 position_id {pos_id}")
            return

        info = TOKEN_MAP[pos_id]
        token_id = info['token_id']
        outcome = info['outcome']
        market = info['market_question']

        logger.info(f"检测到目标 {wallet} 成交！时间: {ts} | 市场: {market} | {outcome} | "
                    f"方向: {side} | 价格: {price:.4f} | USD: {usd_value:.2f}")

        multiplier = float(os.getenv("TRADE_MULTIPLIER", 0.35))
        copy_usd = usd_value * multiplier
        if copy_usd < float(os.getenv("MIN_TRADE_USD", 20)) or copy_usd > float(os.getenv("MAX_POSITION_USD", 150)):
            logger.warning(f"金额 {copy_usd:.2f} 不符合条件")
            return

        size = copy_usd / price if price > 0 else 0

        mode = "模拟" if os.getenv("PAPER_MODE", "true") == "true" else "真实"
        logger.info(f"[{mode}] 准备跟单: {side} {size:.2f} @ {price:.4f} ({token_id})")

        if mode == "真实":
            try:
                slippage = float(os.getenv("SLIPPAGE_TOLERANCE", 0.02))
                adj_price = price * (1 + slippage) if side == BUY else price * (1 - slippage)

                order_args = OrderArgs(token_id=token_id, price=adj_price, size=size, side=side)
                signed = client.create_order(order_args)
                resp = client.post_order(signed)
                logger.info(f"下单成功！ID: {resp.get('id')}")
            except Exception as e:
                logger.error(f"下单失败: {e}")

# ==================== 异步监控主函数 ====================
async def monitor_target_trades_async(client):
    load_dotenv(ENV_FILE)
    target_wallets = [addr.strip().lower() for addr in os.getenv("TARGET_WALLETS", "").split(",") if addr.strip()]
    if not target_wallets:
        logger.warning("未配置 TARGET_WALLETS")
        return

    target_set = set(target_wallets)
    logger.info(f"启动链上 OrderFilled 监听，目标: {', '.join(target_wallets)}")

    rpc_url = os.getenv("RPC_URL")
    if not rpc_url.startswith("wss://"):
        logger.error(f"RPC_URL 必须以 wss:// 开头！当前: {rpc_url}")
        return

    try:
        async with AsyncWeb3(WebSocketProvider(rpc_url)) as w3:
            if not await w3.is_connected():
                logger.error("WebSocket 连接失败")
                return

            logger.info("WebSocket 连接成功，开始轮询监听...")

            current_block = await w3.eth.block_number - 10  # 从最近10块开始

            tasks = [
                poll_order_filled(w3, CTF_EXCHANGE, target_set, client, current_block),
                poll_order_filled(w3, NEGRISK_EXCHANGE, target_set, client, current_block)
            ]
            await asyncio.gather(*tasks)
    except Exception as e:
        logger.critical(f"监控启动失败: {e}")

# ==================== 主程序 ====================
def main():
    print("\n===== Polymarket 跟单机器人 V2.0 =====")
    print("欢迎使用！请选择操作：")

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

            client = ClobClient(CLOB_HOST, key=os.getenv("PRIVATE_KEY"), chain_id=CHAIN_ID)
            if not ensure_api_creds(client):
                continue

            logger.info("启动跟单监控（链上事件监听）...")
            asyncio.run(monitor_target_trades_async(client))

        elif choice == "4":
            view_config()

        elif choice == "5":
            view_wallet_info()

        elif choice == "6":
            logger.info("退出程序")
            sys.exit(0)

        else:
            print("无效选项，请输入1-6")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("用户中断，程序退出")
    except Exception as e:
        logger.critical(f"严重错误: {e}", exc_info=True)
