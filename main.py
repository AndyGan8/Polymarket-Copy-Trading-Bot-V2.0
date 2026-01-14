import logging
import time
from py_clob_client.client import ClobClient
from config import *
from ws_client import MarketWS
from copy_engine import process_potential_trade

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')

def main():
    logger.info("Polymarket Copy Bot starting...")

    client = ClobClient(host="https://clob.polymarket.com", key=PRIVATE_KEY, chain_id=137)

    # 自动生成/使用 API creds（只需一次）
    if not API_KEY:
        try:
            creds = client.create_or_derive_api_creds()
            logger.warning("\n=== 新生成的 API Credentials ===\n请手动添加到 .env：\n"
                           f"API_KEY={creds.api_key}\nAPI_SECRET={creds.api_secret}\n"
                           f"API_PASSPHRASE={creds.api_passphrase}\n然后重启\n")
            exit(0)
        except Exception as e:
            logger.error(f"生成 creds 失败: {e}")

    # 示例：获取热门市场 token_id（实际应动态获取）
    # markets = client.get_markets()  # 然后筛选你关心的
    monitored = ["示例tokenid1", "示例tokenid2"]  # ← 替换成真实 token ids

    ws = MarketWS(on_trade_callback=process_potential_trade)
    ws.set_monitored_tokens(monitored)
    ws.run()

if __name__ == "__main__":
    main()
