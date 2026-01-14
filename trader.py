from py_clob_client.client import ClobClient
from py_clob_client.constants import Polygon
from config import PRIVATE_KEY, RPC_URL, API_KEY, API_SECRET, API_PASSPHRASE
import logging

logger = logging.getLogger(__name__)

client = ClobClient(
    host="https://clob.polymarket.com",
    key=PRIVATE_KEY,
    chain_id=Polygon.CHAIN_ID,
)

if API_KEY and API_SECRET and API_PASSPHRASE:
    client.set_api_creds({
        "api_key": API_KEY,
        "api_secret": API_SECRET,
        "api_passphrase": API_PASSPHRASE
    })

def execute_trade(token_id, side, price, usd_amount):
    try:
        # 带滑点保护的价格
        adj_price = price * (1.012 if side == "BUY" else 0.988)
        size_shares = usd_amount / adj_price

        order = client.create_limit_order(
            token_id=token_id,
            side=side,
            price=adj_price,
            size=size_shares
        )
        response = client.post_order(order)
        logger.info(f"Order placed: {response}")
    except Exception as e:
        logger.error(f"Trade failed: {e}")
