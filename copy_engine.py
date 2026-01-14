import logging
from config import MULTIPLIER, MAX_POS_USD, PAPER_MODE, MIN_TRADE_USD
from trader import execute_trade

logger = logging.getLogger(__name__)

def process_potential_trade(token_id, usd_size, price, is_buy=True):
    if usd_size < MIN_TRADE_USD:
        return

    copy_usd = usd_size * MULTIPLIER
    if copy_usd > MAX_POS_USD:
        logger.warning(f"Position too large: ${copy_usd:.2f} > max ${MAX_POS_USD}")
        return

    side = "BUY" if is_buy else "SELL"
    logger.info(f"Copy trigger: {side} ${copy_usd:.2f} of {token_id}")

    if PAPER_MODE:
        logger.info("[PAPER] Simulated copy trade executed")
    else:
        execute_trade(token_id, side, price, copy_usd)
