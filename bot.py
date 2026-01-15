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

# ==================== 依赖列表（必须定义在这里！） ====================
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

# ==================== 函数定义 ====================

def load_market_mappings():
    global TOKEN_MAP
    logger.info("从 Gamma API 加载市场映射...")
    try:
        resp = requests.get(GAMMA_MARKETS_URL, timeout=15)
        resp.raise_for_status()
        markets = resp.json()
        count = 0
        for market in markets:
            clob_ids = market.get('clobTokenIds', [])
            tokens = market.get('tokens', [])
            for i, clob_id in enumerate(clob_ids):
                try:
                    pos_id = int(clob_id)
                    if i < len(tokens):
                        token = tokens[i]
                        TOKEN_MAP[pos_id] = {
                            'token_id': clob_id,
                            'market': market.get('question', '未知市场'),
                            'outcome': token.get('outcome', '未知'),
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
    logger.info("检查 Python 环境与依赖...")
    try:
        import pkg_resources
        installed = {pkg.key: pkg.version for pkg in pkg_resources.working_set}
    except:
        result = subprocess.run(["pip", "list", "--format=freeze"], capture_output=True, text=True)
        installed = dict(line.split('==') for line in result.stdout.splitlines() if '==' in line)

    missing = []
    for req in REQUIREMENTS:
        pkg_name = req.split('>=')[0].strip().lower()
        if pkg_name not in installed:
            missing.append(req)

    if missing:
        logger.info(f"缺少依赖: {', '.join(missing)}")
        if input("是否自动安装缺失依赖？(y/n): ").strip().lower() == 'y':
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing)
                logger.info("依赖安装完成！")
                print("依赖安装完成，请重新运行脚本。")
            except Exception as e:
                logger.error(f"安装失败: {e}\n请手动运行: pip install {' '.join(missing)}")
        else:
            logger.warning("请手动安装依赖后再继续。")
    else:
        logger.info("所有必要依赖已安装 ✓")
        print("所有依赖已就位，无需安装。")

def setup_config():
    if not os.path.exists(ENV_FILE):
        open(ENV_FILE, 'a').close()

    load_dotenv(ENV_FILE)

    while True:
        print("\n=== 配置选单（选项2） ===")
        print("1. 填写/修改 必须参数（私钥、RPC、目标地址）")
        print("2. 填写/修改 可选参数（跟单比例、金额限制、模拟模式）")
        print("3. 返回主选单")
        sub_choice = input("\n请选择 (1-3): ").strip()

        if sub_choice == "3":
            logger.info("返回主选单")
            print("已返回主菜单，请继续选择...")
            break

        if sub_choice == "1":
            must_have = [
                ("PRIVATE_KEY", "你的钱包私钥（全新burner钱包，0x开头）"),
                ("RPC_URL", "Polygon RPC（如 wss://polygon-mainnet.g.alchemy.com/v2/YOUR_KEY）"),
                ("TARGET_WALLETS", "跟单目标地址（多个用逗号分隔，只跟这些地址）")
            ]
            for key, desc in must_have:
                current = os.getenv(key, "未设置")
                print(f"\n当前 {key}: {current[:10] + '...' if current != '未设置' else current}")
                while True:
                    value = input(f"{key} - {desc}\n输入新值（必须填写，不能留空）: ").strip()
                    if value:
                        set_key(ENV_FILE, key, value)
                        os.environ[key] = value
                        print(f"{key} 已更新为 {value[:10] + '...' if key == 'PRIVATE_KEY' else value}")
                        break
                    else:
                        print("错误：必须参数不能为空，请重新输入！")

        elif sub_choice == "2":
            optionals = [
                ("TRADE_MULTIPLIER", "跟单比例（例如 0.35，建议0.1~0.5）", "0.35"),
                ("MAX_POSITION_USD", "单笔最大跟单金额（美元，建议50~200）", "150"),
                ("MIN_TRADE_USD", "目标交易最小金额（建议10~50）", "20"),
                ("PAPER_MODE", "模拟模式（true/false，先用true测试）", "true"),
                ("SLIPPAGE_TOLERANCE", "滑点容忍度（例如 0.02 = 2%）", "0.02")
            ]
            for key, desc, default in optionals:
                current = os.getenv(key, default)
                print(f"\n当前 {key}: {current}")
                value = input(f"{key} - {desc}\n输入新值（留空保持 {current}，继续下一个）: ").strip()
                if value:
                    if key == "PAPER_MODE" and value.lower() not in ["true", "false"]:
                        print("错误：只能输入 true 或 false")
                        continue
                    try:
                        if key in ["TRADE_MULTIPLIER", "MAX_POSITION_USD", "MIN_TRADE_USD", "SLIPPAGE_TOLERANCE"]:
                            float(value)
                    except ValueError:
                        print("错误：请输入有效数字")
                        continue
                    set_key(ENV_FILE, key, value)
                    os.environ[key] = value
                    print(f"{key} 已更新！")
                else:
                    print(f"{key} 保持原值，继续下一个...")

        else:
            print("无效选择，请输入1-3")

    print("配置完成，已返回主菜单，请继续选择...")

def view_config():
    load_dotenv(ENV_FILE)
    print("\n当前配置概览：")
    keys = ["PRIVATE_KEY", "RPC_URL", "TARGET_WALLETS", "TRADE_MULTIPLIER",
            "MAX_POSITION_USD", "MIN_TRADE_USD", "PAPER_MODE", "SLIPPAGE_TOLERANCE"]
    for k in keys:
        v = os.getenv(k, "未设置")
        if k == "PRIVATE_KEY" and v != "未设置":
            v = v[:6] + "..." + v[-4:]
        print(f"{k:18}: {v}")

    print("\n配置查看完成！已返回主菜单，请继续选择...")

def view_wallet_info():
    load_dotenv(ENV_FILE)
    private_key = os.getenv("PRIVATE_KEY")
    rpc_url = os.getenv("RPC_URL")

    if not private_key or not rpc_url:
        print("请先在选项2配置 PRIVATE_KEY 和 RPC_URL！")
        input("按回车返回主菜单...")
        return

    try:
        w3 = Web3(Web3.HTTPProvider(rpc_url.replace("wss", "https")))
        if not w3.is_connected():
            print("RPC连接失败，请检查 RPC_URL")
            input("按回车返回主菜单...")
            return

        account = w3.eth.account.from_key(private_key)
        address = account.address
        print(f"\n钱包地址: {address}")

        balance_wei = w3.eth.get_balance(address)
        balance_pol = w3.from_wei(balance_wei, 'ether')
        print(f"当前 POL 余额: {balance_pol:.4f} POL")

        native_usdc_checksum = w3.to_checksum_address(NATIVE_USDC_ADDRESS_LOWER)
        native_usdc_contract = w3.eth.contract(address=native_usdc_checksum, abi=USDC_ABI)
        balance_native_wei = native_usdc_contract.functions.balanceOf(address).call()
        decimals_native = native_usdc_contract.functions.decimals().call()
        balance_native = balance_native_wei / (10 ** decimals_native)
        print(f"当前 USDC 余额 (native): {balance_native:.2f} USDC")

        print("\n查看完成！按回车返回主菜单...")
        input()

    except Exception as e:
        print(f"查询失败: {e}")
        input("按回车返回主菜单...")

def ensure_api_creds(client):
    load_dotenv(ENV_FILE)
    if all(os.getenv(k) for k in ["API_KEY", "API_SECRET", "API_PASSPHRASE"]):
        client.set_api_creds({
            "api_key": os.getenv("API_KEY"),
            "api_secret": os.getenv("API_SECRET"),
            "api_passphrase": os.getenv("API_PASSPHRASE")
        })
        return True

    logger.info("正在生成 Polymarket API Credentials...")
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

# ==================== 异步订阅函数（占位，可扩展为完整跟单逻辑） ====================
async def subscribe_to_order_filled(w3: AsyncWeb3, contract_address, target_set, client):
    logger.info(f"开始订阅 {contract_address} 的 OrderFilled 事件...")
    # 这里添加完整事件过滤、下单逻辑（从你之前的版本复制）
    # 示例占位：持续监听 1 小时
    await asyncio.sleep(3600)

async def monitor_target_trades_async(client):
    load_dotenv(ENV_FILE)
    targets = set(a.strip().lower() for a in os.getenv("TARGET_WALLETS", "").split(",") if a.strip())
    if not targets:
        logger.warning("未配置 TARGET_WALLETS")
        return

    logger.info(f"启动链上监听，目标地址: {', '.join(targets)}")

    rpc = os.getenv("RPC_URL")
    if not rpc.startswith("wss://"):
        logger.error(f"RPC_URL 必须以 wss:// 开头！当前: {rpc}")
        return

    try:
        async with AsyncWeb3(WebSocketProvider(rpc)) as w3:
            if not await w3.is_connected():
                logger.error("WebSocket 连接失败，请检查 RPC_URL")
                return

            logger.info("WebSocket 连接成功，开始监听 OrderFilled 事件...")

            tasks = [
                subscribe_to_order_filled(w3, CTF_EXCHANGE, targets, client),
                subscribe_to_order_filled(w3, NEGRISK_EXCHANGE, targets, client)
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
