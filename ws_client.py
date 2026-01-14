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
        self.monitored_tokens = []  # 稍后动态填充

    def set_monitored_tokens(self, tokens):
        self.monitored_tokens = tokens

    def on_open(self, ws):
        logger.info("WS connected. Subscribing markets...")
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
                usd_value = size * price  # 简化估算

                if usd_value >= MIN_TRADE_USD:
                    # 这里是触发点，实际项目中应结合 fills API 验证 maker/taker
                    logger.info(f"Trade detected: {token_id} | ${usd_value:.2f} @ {price:.4f}")
                    self.on_trade_callback(token_id, usd_value, price, is_buy=True)  # 方向需进一步判断
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
