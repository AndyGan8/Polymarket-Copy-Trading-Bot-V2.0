import os
import sys
import subprocess
import time
import json
import logging
import requests
from datetime import datetime
from dotenv import load_dotenv, set_key
from web3 import AsyncWeb3
from web3.providers.persistent import WebSocketProvider  # web3.py v7+ 正确导入
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs
from py_clob_client.order_builder.constants import BUY, SELL
import asyncio

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
CHAIN_ID = 137  # Polygon Mainnet chain ID
GAMMA_MARKETS_URL = "https://gamma-api.polymarket.com/markets?active=true&limit=1000"

NATIVE_USDC_ADDRESS_LOWER = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"

USDC_ABI = [
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"}
]

REQUIREMENTS = [
    "py-clob-client>=0.34.0",
    "websocket-client>=1.8.0",
    "python-dotenv>=1.0.0",
    "web3>=7.0.0",          # 强制要求 v7+
    "requests>=2.28.0"
]

# 合约地址
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

# 全局映射：position_id (int) -> token_info
TOKEN_MAP = {}

# ==================== 加载 Gamma 市场映射 ====================
def load_market_mappings():
    global TOKEN_MAP
    logger.info("加载 Polymarket 市场映射（positionId → token_id）...")
    try:
        response = requests.get(GAMMA_MARKETS_URL)
        markets = response.json()
        count = 0
        for market in markets:
            clob_token_ids = market.get('clobTokenIds', [])
            tokens = market.get('tokens', [])
            for i, token_id_str in enumerate(clob_token_ids):
                try:
                    position_id = int(token_id_str)  # clobTokenIds 通常是字符串数字
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
        logger.info(f"成功加载 {count} 个 token 映射")
    except Exception as e:
        logger.error(f"加载市场失败: {e}（跟单仍可运行，但日志缺少市场名称）")

# ==================== 主菜单（保持不变） ====================
def show_menu():
    print("\n===== Polymarket 跟单机器人（VPS简易版） =====")
    print("1. 检查环境并自动安装依赖")
    print("2. 配置密钥、RPC、跟单地址等（首次必做）")
    print("3. 启动跟单机器人（只跟输入地址）")
    print("4. 查看当前配置")
    print("5. 查看钱包余额、持仓及跟单历史")
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

# ==================== 选项2、4、5、ensure_api_creds 函数（保持不变） ====================
# （这里省略与之前相同的代码，复制你原有版本即可）

# ==================== 异步订阅函数 ====================
async def subscribe_to_order_filled(w3: AsyncWeb3, contract_address, target_wallets_set, client):
    contract = w3.eth.contract(address=contract_address, abi=ORDER_FILLED_ABI)
    
    processed_hashes = set()
    
    async def handle_event(event):
        order_hash = event['args']['orderHash'].hex()
        if order_hash in processed_hashes:
            return
        processed_hashes.add(order_hash)
        
        maker = event['args']['maker'].lower()
        taker = event['args']['taker'].lower()
        
        involved = {maker, taker}
        matched_targets = involved & target_wallets_set
        
        if matched_targets:
            wallet = list(matched_targets)[0]
            try:
                block = await w3.eth.get_block(event['blockNumber'])
                timestamp = datetime.fromtimestamp(block['timestamp'])
            except Exception as e:
                logger.error(f"获取区块失败: {e}")
                timestamp = datetime.now()
            
            maker_asset_id = event['args']['makerAssetId']
            taker_asset_id = event['args']['takerAssetId']
            maker_amount = event['args']['makerAmountFilled'] / 1e6
            taker_amount = event['args']['takerAmountFilled'] / 1e6
            
            if maker_asset_id == 0:
                side = BUY
                price = maker_amount / taker_amount if taker_amount > 0 else 0
                usd_value = maker_amount
                position_id = taker_asset_id
            else:
                side = SELL
                price = taker_amount / maker_amount if maker_amount > 0 else 0
                usd_value = taker_amount
                position_id = maker_asset_id
            
            if position_id not in TOKEN_MAP:
                logger.warning(f"未知 position_id: {position_id}，跳过跟单")
                return
            
            token_info = TOKEN_MAP[position_id]
            token_id = token_info['token_id']
            outcome = token_info['outcome']
            market_question = token_info['market_question']
            
            logger.info(f"链上检测到目标 {wallet} 成交！ 时间: {timestamp} | 市场: {market_question} | Outcome: {outcome} | "
                        f"方向: {side} | 价格: {price:.4f} | USD价值约: {usd_value:.2f}")
            
            multiplier = float(os.getenv("TRADE_MULTIPLIER", 0.35))
            copy_usd = usd_value * multiplier
            max_usd = float(os.getenv("MAX_POSITION_USD", 150))
            min_usd = float(os.getenv("MIN_TRADE_USD", 20))
            
            if copy_usd > max_usd or copy_usd < min_usd:
                logger.warning(f"金额过滤: {copy_usd:.2f} USD 不符合条件")
                return
            
            size = copy_usd / price if price > 0 else 0
            
            mode = "模拟" if os.getenv("PAPER_MODE", "true") == "true" else "真实"
            logger.info(f"[{mode}] 准备跟单: {side} {size:.2f} 份额 @ {price:.4f} ({token_id}, {outcome}) | USD: {copy_usd:.2f}")
            
            if mode == "真实":
                try:
                    slippage = float(os.getenv("SLIPPAGE_TOLERANCE", 0.02))
                    adjusted_price = price * (1 + slippage) if side == BUY else price * (1 - slippage)
                    
                    order_args = OrderArgs(
                        token_id=token_id,
                        price=adjusted_price,
                        size=size,
                        side=side,
                    )
                    signed_order = client.create_order(order_args)
                    order_response = client.post_order(signed_order)
                    logger.info(f"下单成功！订单ID: {order_response.get('id')} | 响应: {order_response}")
                except Exception as e:
                    logger.error(f"下单失败: {e}")

    event_filter = await contract.events.OrderFilled.create_filter(fromBlock='latest')
    
    while True:
        try:
            new_entries = await event_filter.get_new_entries()
            for event in new_entries:
                await handle_event(event)
            await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"订阅异常 ({contract_address}): {e}")
            await asyncio.sleep(10)

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
        logger.error(f"RPC_URL 必须是 wss:// 开头！当前: {rpc_url}")
        logger.error("请修改 .env 为 Alchemy/Infura wss 端点")
        return

    try:
        async with AsyncWeb3(WebSocketProvider(rpc_url)) as w3:
            if not await w3.is_connected():
                logger.error("WebSocket 连接失败，请检查 RPC_URL 和网络")
                return

            logger.info("WebSocket 连接成功，开始监听 OrderFilled 事件...")

            tasks = [
                subscribe_to_order_filled(w3, CTF_EXCHANGE, target_set, client),
                subscribe_to_order_filled(w3, NEGRISK_EXCHANGE, target_set, client)
            ]
            await asyncio.gather(*tasks)
    except Exception as e:
        logger.critical(f"WebSocket 启动失败: {e}")

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

            w3_http = Web3(Web3.HTTPProvider(os.getenv("RPC_URL").replace("wss", "https")))
            if not w3_http.is_connected():
                logger.error("HTTP RPC 连接失败，请检查 RPC_URL")
                continue

            client = ClobClient(CLOB_HOST, key=os.getenv("PRIVATE_KEY"), chain_id=CHAIN_ID)
            if not ensure_api_creds(client):
                continue

            load_market_mappings()

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
