# ws_client.py (更新：添加最近交易缓存，用于快速匹配)
import json
import threading
import time
import logging
from websocket import WebSocketApp
from config import *

logger = logging.getLogger(__name__)

class MarketWS:
    def __init__(self, on_trade_callback):
        self.url = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
        self.on_trade_callback = on_trade_callback
        self.ws = None
        self.monitored_tokens = []
        self.last_trade_times = {}  # token_id: last_trade_timestamp，用于匹配验证

    def set_monitored_tokens(self, tokens):
        self.monitored_tokens = tokens

    def on_open(self, ws):
        logger.info(f"WS connected. Subscribing to {len(self.monitored_tokens)} markets...")
        if self.monitored_tokens:
            sub_msg = {
                "assets_ids": self.monitored_tokens,
                "type": "market"
            }
            ws.send(json.dumps(sub_msg))
        threading.Thread(target=self._heartbeat, daemon=True).start()

    def on_message(self, ws, message):
        try:
            data = json.loads(message)
            if data.get("event_type") == "last_trade_price":
                token_id = data.get("token_id")
                price = float(data.get("price", 0))
                size = float(data.get("size", 0))
                usd_value = size * price
                timestamp = int(time.time() * 1000)  # 近似

                if usd_value >= MIN_TRADE_USD:
                    self.last_trade_times[token_id] = timestamp
                    logger.info(f"Potential trade: {token_id} | ${usd_value:.2f} @ {price:.4f}")
                    self.on_trade_callback(token_id, usd_value, price, True)  # 假设buy，实际可从book delta判断
        except Exception as e:
            logger.error(f"WS message error: {e}")

    def _heartbeat(self):
        while True:
            if self.ws and self.ws.sock and self.ws.sock.connected:
                self.ws.send(json.dumps({"type": "ping"}))
            time.sleep(25)

    def run(self):
        self.ws = WebSocketApp(
            self.url,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=lambda ws, err: logger.error(f"WS error: {err}"),
            on_close=lambda ws, code, msg: (logger.warning("WS closed, reconnecting..."), time.sleep(5), self.run())
        )
        self.ws.run_forever(ping_interval=0)
