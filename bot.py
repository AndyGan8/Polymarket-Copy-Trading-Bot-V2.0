import os
import time
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
from web3 import Web3
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds
from py_clob_client.constants import Polygon
from py_clob_client.order_builder.constants import BUY, SELL

# ==================== 配置日志 ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-5s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ==================== 加载配置 ====================
load_dotenv()

PRIVATE_KEY = os.getenv("PRIVATE_KEY")
if not PRIVATE_KEY:
    raise ValueError("请在 .env 文件中设置 PRIVATE_KEY")

RPC_URL = os.getenv("RPC_URL", "https://polygon-rpc.com")
TARGET_WALLET = os.getenv("TARGET_WALLET", "").lower()
if not TARGET_WALLET.startswith("0x") or len(TARGET_WALLET) != 42:
    raise ValueError("TARGET_WALLET 格式错误")

# 参数读取（带默认值与类型转换）
try:
    MULTIPLIER = float(os.getenv("TRADE_MULTIPLIER", 0.3))
    MAX_POS_USD = float(os.getenv("MAX_POSITION_USD", 100))
    MAX_DAILY_LOSS = float(os.getenv("MAX_DAILY_LOSS_USD", 200))
    SLIPPAGE = float(os.getenv("SLIPPAGE_TOLERANCE", 0.025))
    PAPER_MODE = os.getenv("PAPER_MODE", "true").lower() == "true"
    MIN_TRADE_USD = float(os.getenv("MIN_TRADE_SIZE_USD", 10))
except ValueError as e:
    logger.error(f"环境变量格式错误: {e}")
    exit(1)

# ==================== 初始化 ====================
w3 = Web3(Web3.HTTPProvider(RPC_URL))
if not w3.is_connected():
    raise ConnectionError("无法连接到 Polygon RPC")

client = ClobClient(
    host="https://clob.polymarket.com",
    key=PRIVATE_KEY,
    chain_id=Polygon.CHAIN_ID,
    signature_type=1,  # 目前 Polymarket 主要用 EIP-712
    funder=os.getenv("FUNDER_ADDRESS")  # 如使用代理钱包可填
)

account = w3.eth.account.from_key(PRIVATE_KEY)
logger.info(f"机器人启动 | 钱包: {account.address[:8]}... | 跟单目标: {TARGET_WALLET[:8]}... | 比例: {MULTIPLIER}")

last_checked_time = int(time.time()) - 300  # 先回溯5分钟
daily_loss = 0.0
today = datetime.utcnow().date()

# ==================== 核心跟单逻辑 ====================
def should_copy_trade(size_usd):
    if size_usd < MIN_TRADE_USD:
        return False
    if size_usd * MULTIPLIER > MAX_POS_USD:
        logger.warning(f"单笔超过最大限额，跳过: {size_usd:.2f} → {size_usd*MULTIPLIER:.2f}")
        return False
    if daily_loss <= -MAX_DAILY_LOSS:
        logger.error("当日亏损已达上限，机器人已停止！")
        return False
    return True

def main_loop():
    global last_checked_time, daily_loss, today
    
    while True:
        try:
            now = datetime.utcnow()
            if now.date() != today:
                daily_loss = 0
                today = now.date()
                logger.info("========== 新的一天，亏损重置为 0 ==========")

            # 这里是简化的实现方式：实际生产建议使用 websocket + subgraph
            # 当前使用最简单 polling 方式（对 RPC 压力较小）
            # 建议：每 8~15 秒查一次即可
            
            # 待实现：从 Polymarket subgraph 或 explorer 获取目标地址最近交易
            # 此处为占位逻辑，实际需要接入 subgraph 或 alchemy asset transfer API
            
            logger.info("轮询中...（示例占位）")
            
            # 模拟发现一笔交易（实际需要替换为真实数据源）
            # 假设发现目标开了多单，金额约 $500
            discovered_trade = {
                "token_id": "1234567890123456789012345678901234567890",
                "side": "BUY",
                "size_usd": 480.0,
                "price": 0.65
            }
            
            if discovered_trade and discovered_trade["size_usd"] >= MIN_TRADE_USD:
                copy_size = discovered_trade["size_usd"] * MULTIPLIER
                if should_copy_trade(discovered_trade["size_usd"]):
                    side = BUY if discovered_trade["side"] == "BUY" else SELL
                    
                    logger.info(f"发现可跟单交易！金额:${discovered_trade['size_usd']:.1f} → 准备跟单 ${copy_size:.2f}")
                    
                    if not PAPER_MODE:
                        try:
                            # 实际下单（这里是伪代码，需根据真实 token_id 和价格调整）
                            order = client.create_and_post_order(
                                token_id=discovered_trade["token_id"],
                                side=side,
                                price=discovered_trade["price"],
                                size=copy_size,
                                post_only=False,
                                slippage=SLIPPAGE
                            )
                            logger.info(f"下单成功！订单ID: {order.get('id')}")
                        except Exception as e:
                            logger.error(f"下单失败: {e}")
                    else:
                        logger.info(f"[模拟模式] 成功下单: {discovered_trade['side']} {copy_size:.2f} @ {discovered_trade['price']}")

            time.sleep(12)  # 建议 8~15 秒轮询一次

        except Exception as e:
            logger.error(f"主循环异常: {e}", exc_info=True)
            time.sleep(30)  # 出错后等待更久

if __name__ == "__main__":
    logger.info("===== Polymarket 跟单机器人启动 =====")
    try:
        main_loop()
    except KeyboardInterrupt:
        logger.info("用户手动停止机器人，再见~")
    except Exception as e:
        logger.critical(f"严重错误，机器人退出: {e}", exc_info=True)
