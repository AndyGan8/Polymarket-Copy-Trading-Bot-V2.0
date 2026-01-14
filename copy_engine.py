# copy_engine.py (更新：添加fills验证逻辑)
import logging
from datetime import datetime, timedelta
from config import *
from trader import client, execute_trade
from py_clob_client.clob_types import TradeParams

logger = logging.getLogger(__name__)

# 风险管理全局变量
daily_loss = 0.0
last_reset_date = datetime.utcnow().date()
open_positions = {}  # token_id: {'size': float, 'entry_price': float}

def reset_daily_loss():
    global daily_loss, last_reset_date
    now = datetime.utcnow().date()
    if now != last_reset_date:
        daily_loss = 0.0
        last_reset_date = now
        logger.info("Daily loss reset to 0")

def update_pnl(token_id, trade_size, trade_price, is_buy):
    global daily_loss
    if token_id in open_positions:
        pos = open_positions[token_id]
        if (pos['size'] > 0 and not is_buy) or (pos['size'] < 0 and is_buy):  # 平仓方向
            pnl = (trade_price - pos['entry_price']) * abs(trade_size) if is_buy else (pos['entry_price'] - trade_price) * abs(trade_size)
            daily_loss += min(0, pnl)  # 只累加亏损
            del open_positions[token_id]
        else:  # 加仓
            new_size = pos['size'] + (trade_size if is_buy else -trade_size)
            pos['entry_price'] = (pos['entry_price'] * abs(pos['size']) + trade_price * abs(trade_size)) / abs(new_size)
            pos['size'] = new_size
    else:
        open_positions[token_id] = {'size': trade_size if is_buy else -trade_size, 'entry_price': trade_price}

def is_from_target(token_id, expected_price, expected_size):
    try:
        # 使用 get_trades 获取最近1条trade，检查是否匹配目标地址
        params = TradeParams(
            maker_address=TARGET_WALLETS[0] if TARGET_WALLETS else None,  # 假设单目标，多目标循环检查
            market=token_id,  # market通常是condition_id，但这里用token_id试
            limit=1
        )
        recent_trades = client.get_trades(params)
        if recent_trades:
            latest = recent_trades[0]
            if latest.get('maker') in TARGET_WALLETS or latest.get('taker') in TARGET_WALLETS:
                # 检查是否匹配WS检测的price/size（近似）
                if abs(float(latest['price']) - expected_price) < 0.001 and abs(float(latest['size']) - expected_size) < 0.1:
                    return True, latest['side'] == 'BUY'
    except Exception as e:
        logger.error(f"Fill verification failed: {e}")
    return False, True  # 默认不跟

def process_potential_trade(token_id, usd_size, price, is_buy=True):
    reset_daily_loss()
    if daily_loss <= -MAX_DAILY_LOSS_USD:
        logger.error("Daily loss limit reached! Stopping trades.")
        return

    is_target_trade, actual_buy = is_from_target(token_id, price, usd_size / price)
    if not is_target_trade:
        logger.info(f"Trade not from target wallet, skipping: {token_id}")
        return

    copy_usd = usd_size * MULTIPLIER
    if copy_usd > MAX_POS_USD or copy_usd < MIN_TRADE_USD:
        logger.warning(f"Invalid copy size: ${copy_usd:.2f}")
        return

    side = "BUY" if actual_buy else "SELL"
    logger.info(f"Verified target trade! Copying: {side} ${copy_usd:.2f} of {token_id}")

    if PAPER_MODE:
        logger.info("[PAPER] Simulated copy trade executed")
        update_pnl(token_id, copy_usd / price, price, actual_buy)  # 模拟PNL
    else:
        execute_trade(token_id, side, price, copy_usd)
        update_pnl(token_id, copy_usd / price, price, actual_buy)
