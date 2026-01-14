import os
from dotenv import load_dotenv

load_dotenv()

PRIVATE_KEY = os.getenv("PRIVATE_KEY")
RPC_URL = os.getenv("RPC_URL")
TARGET_WALLETS = [addr.strip().lower() for addr in os.getenv("TARGET_WALLETS", "").split(",") if addr.strip()]
MULTIPLIER = float(os.getenv("TRADE_MULTIPLIER", 0.35))
MAX_POS_USD = float(os.getenv("MAX_POSITION_USD", 150))
MIN_TRADE_USD = float(os.getenv("MIN_TRADE_USD", 20))
PAPER_MODE = os.getenv("PAPER_MODE", "true").lower() == "true"

# 后续可把生成的 API creds 存这里
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
API_PASSPHRASE = os.getenv("API_PASSPHRASE")
