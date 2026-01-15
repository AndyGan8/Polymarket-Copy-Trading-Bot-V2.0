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
CHAIN_ID = 137  # Polygon Mainnet chain ID
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
            logger.info("返回主选单")
            print("已返回主菜单，请继续选择...")
            break

        if sub_choice == "1":
            must_have = [
                ("PRIVATE_KEY", "你的钱包私钥（全新burner钱包，0x开头）"),
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
                ("PAPER_MODE", "模拟模式（true/false，先用true测试）", "true")
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
                        if key in ["TRADE_MULTIPLIER", "MAX_POSITION_USD", "MIN_TRADE_USD"]:
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
    show_menu()

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

    print("\n配置查看完成！已返回主菜单，请继续选择...")
    show_menu()

# ==================== 选项5：查看监听状态和跟单情况 ====================
def view_wallet_info():
    load_dotenv(ENV_FILE)
    print("\n=== 监听状态和跟单情况 ===\n")

    try:
        with open("bot.log", "r") as f:
            lines = f.readlines()[-20:]
            found = False
            for line in lines:
                if "监控异常" in line or "监控" in line or "连接成功" in line or "检测到目标" in line:
                    print(line.strip())
                    found = True
            if not found:
                print("暂无监听记录（等待检测到交易后会显示）")
    except:
        print("无法读取日志文件（暂无监听记录）")

    print("\n查看完成！按回车返回主菜单...")
    input()

# ==================== 获取 API Credentials ====================
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

# ==================== 异步订阅函数 ====================
async def subscribe_to_order_filled(w3: AsyncWeb3, contract_address, target_wallets_set, client):
    contract = w3.eth.contract(address=contract_address, abi=ORDER_FILLED_ABI)
    
    processed_hashes = set()  # 防重处理
    
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
            block = await w3.eth.get_block(event['blockNumber'])
            timestamp = datetime.fromtimestamp(block['timestamp'])
            
            maker_asset_id = event['args']['makerAssetId']
            taker_asset_id = event['args']['takerAssetId']
            maker_amount = event['args']['makerAmountFilled'] / 1e6  # 假设 6 decimals
            taker_amount = event['args']['takerAmountFilled'] / 1e6
            
            # 判断方向和价格
            if maker_asset_id == 0:
                side = BUY  # maker 买 (USDC 换 token)
                price = maker_amount / taker_amount if taker_amount > 0 else 0
                usd_value = maker_amount
                position_id = taker_asset_id
            else:
                side = SELL  # maker 卖 (token 换 USDC)
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
            
            logger.info(f"链上检测到目标 {wallet} 成交！"
                        f" 时间: {timestamp} | 市场: {market_question} | Outcome: {outcome} | "
                        f"方向: {side} | 价格: {price:.4f} | USD价值约: {usd_value:.2f} | "
                        f"maker: {maker} | taker: {taker}")
            
            # 跟单计算
            multiplier = float(os.getenv("TRADE_MULTIPLIER", 0.35))
            copy_usd = usd_value * multiplier
            max_usd = float(os.getenv("MAX_POSITION_USD", 150))
            min_usd = float(os.getenv("MIN_TRADE_USD", 20))
            
            if copy_usd > max_usd or copy_usd < min_usd:
                logger.warning(f"金额过滤: {copy_usd:.2f} USD 不符合条件")
                return
            
            size = copy_usd / price  # 份额计算
            
            mode = "模拟" if os.getenv("PAPER_MODE", "true") == "true" else "真实"
            logger.info(f"[{mode}] 准备跟单: {side} {size:.2f} 份额 @ {price:.4f} ({token_id}, {outcome}) | USD: {copy_usd:.2f}")
            
            if mode == "真实":
                try:
                    # 滑点保护: 调整价格 ± slippage
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

    # 修复：移除 from_block 参数（默认从最新开始）
    event_filter = await contract.events.OrderFilled.create_filter()
    
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
    if not rpc_url.startswith("wss"):
        logger.warning("RPC_URL 应为 wss:// 以支持订阅，当前: {rpc_url}")

    try:
        async with AsyncWeb3(WebSocketProvider(rpc_url)) as w3:
            if not await w3.is_connected():
                logger.error("WebSocket RPC 连接失败，请检查 RPC_URL 支持 wss（推荐 Alchemy/Infura）")
                return

            logger.info("WebSocket 连接成功，开始监听...")
            logger.info("开始订阅 CTF Exchange OrderFilled 事件...")
            logger.info("开始订阅 NegRisk Exchange OrderFilled 事件...")

            tasks = [
                subscribe_to_order_filled(w3, CTF_EXCHANGE, target_set, client),
                subscribe_to_order_filled(w3, NEGRISK_EXCHANGE, target_set, client)
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
