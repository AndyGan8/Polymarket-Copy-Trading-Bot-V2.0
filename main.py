# main.py (更新：添加自动获取热门市场)
import logging
import time
import requests
from py_clob_client.client import ClobClient
from config import *
from ws_client import MarketWS
from copy_engine import process_potential_trade

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')

def get_hot_markets(limit=50):
    try:
        url = "https://gamma-api.polymarket.com/markets?active=true&closed=false&limit={}&order=volume24Hours.desc".format(limit)
        response = requests.get(url)
        markets = response.json()
        token_ids = []
        for market in markets:
            for token in market.get('tokens', []):
                token_ids.append(token['token_id'])
        logger.info(f"Fetched {len(token_ids)} hot token_ids")
        return list(set(token_ids))  # 去重
    except Exception as e:
        logger.error(f"Failed to fetch hot markets: {e}")
        return []

def main():
    logger.info("Polymarket Copy Bot starting...")

    clob_client = ClobClient(host="https://clob.polymarket.com", key=PRIVATE_KEY, chain_id=137)

    if not API_KEY:
        try:
            creds = clob_client.create_or_derive_api_creds()
            logger.warning("\n=== 新生成的 API Credentials ===\n请手动添加到 .env：\n"
                           f"API_KEY={creds.api_key}\nAPI_SECRET={creds.api_secret}\n"
                           f"API_PASSPHRASE={creds.api_passphrase}\n然后重启\n")
            exit(0)
        except Exception as e:
            logger.error(f"生成 creds 失败: {e}")

    # 自动获取热门市场 token_ids
    monitored_tokens = get_hot_markets(100)  # 获取前100热门

    if not monitored_tokens:
        logger.error("No hot markets fetched, exiting.")
        exit(1)

    ws = MarketWS(on_trade_callback=process_potential_trade)
    ws.set_monitored_tokens(monitored_tokens)
    ws.run()

if __name__ == "__main__":
    main()
