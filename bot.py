import os
import sys
import json
import time
import logging
import asyncio
import requests
import subprocess
from datetime import datetime
from dotenv import load_dotenv, set_key
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs
from py_clob_client.order_builder.constants import BUY, SELL

# ==================== 配置 ====================
ENV_FILE = ".env"
CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID = 137

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

# ==================== 自动检查并安装依赖 ====================
def check_and_install_dependencies():
    """自动检测并安装缺失的依赖包"""
    print("\n" + "="*60)
    print("自动检查依赖...")
    print("="*60)
    
    requirements = {
        "requests": "requests>=2.28.0",
        "python-dotenv": "python-dotenv>=1.0.0",
        "py_clob_client": "py-clob-client>=0.34.0"
    }
    
    missing = []
    for pkg, req in requirements.items():
        try:
            __import__(pkg.replace("-", "_"))  # py-clob-client -> py_clob_client
            print(f"✅ {pkg} 已安装")
        except ImportError:
            missing.append(req)
            print(f"❌ {pkg} 缺失，将尝试自动安装...")
    
    if not missing:
        print("所有核心依赖已就绪！")
        return True
    
    print("\n开始自动安装缺失依赖...")
    try:
        # 优先尝试正常 pip install
        cmd = [sys.executable, "-m", "pip", "install"] + missing
        subprocess.check_call(cmd)
        print("✅ 自动安装成功！")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ 自动安装失败: {e}")
        print("尝试使用 --break-system-packages 强制安装（仅限全局环境）...")
        try:
            cmd.append("--break-system-packages")
            subprocess.check_call(cmd)
            print("✅ 强制安装成功！（注意：可能影响系统稳定性）")
            return True
        except Exception as force_e:
            print(f"❌ 强制安装也失败: {force_e}")
            print("\n强烈建议使用虚拟环境（venv）：")
            print("  python3 -m venv venv")
            print("  source venv/bin/activate")
            print("  pip install " + " ".join(missing))
            print("然后重新运行 python3 bot.py")
            sys.exit(1)

# ==================== 主菜单 ====================
def show_menu():
    print("\n" + "="*60)
    print(" " * 15 + "Polymarket 跟单机器人 (REST API 模式)")
    print("="*60)
    print("1. 手动检查并安装依赖")
    print("2. 配置钱包和跟单地址")
    print("3. 启动跟单机器人 (REST API 轮询)")
    print("4. 查看状态")
    print("5. 退出")
    return input("\n请输入选项 (1-5): ").strip()

# ==================== 手动安装依赖（菜单用） ====================
def install_dependencies():
    print("\n手动安装必要依赖...")
    requirements = [
        "py-clob-client>=0.34.0",
        "python-dotenv>=1.0.0",
        "requests>=2.28.0"
    ]
    
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install"] + requirements)
        print("✅ 依赖安装完成！")
    except Exception as e:
        print(f"❌ 安装失败: {e}")
        print("请尝试在虚拟环境中手动运行: pip install py-clob-client python-dotenv requests")

# ==================== 配置 ====================
def setup_config():
    if not os.path.exists(ENV_FILE):
        with open(ENV_FILE, 'w') as f:
            f.write("# Polymarket 跟单机器人配置\n")
    
    load_dotenv(ENV_FILE)
    
    print("\n" + "="*60)
    print("配置向导")
    print("="*60)
    
    # 1. 私钥配置
    private_key = os.getenv("PRIVATE_KEY", "")
    if private_key:
        print(f"当前私钥: {private_key[:10]}...{private_key[-10:]}")
    else:
        print("未配置私钥")
    
    change = input("是否修改私钥？(y/n): ").strip().lower()
    if change == 'y':
        new_key = input("请输入你的钱包私钥 (0x开头): ").strip()
        if new_key.startswith("0x") and len(new_key) == 66:
            set_key(ENV_FILE, "PRIVATE_KEY", new_key)
            print("✅ 私钥已保存")
        else:
            print("❌ 私钥格式错误！应为0x开头的64字符十六进制")
    
    # 2. 跟单地址配置
    target_wallets = os.getenv("TARGET_WALLETS", "")
    if target_wallets:
        print(f"\n当前跟单地址: {target_wallets}")
    else:
        print("\n未配置跟单地址")
    
    change = input("是否修改跟单地址？(y/n): ").strip().lower()
    if change == 'y':
        new_targets = input("请输入要跟单的地址 (多个用逗号分隔): ").strip()
        if new_targets:
            set_key(ENV_FILE, "TARGET_WALLETS", new_targets)
            print("✅ 跟单地址已保存")
    
    # 3. 其他参数配置
    print("\n其他参数配置:")
    
    params = [
        ("TRADE_MULTIPLIER", "跟单比例 (默认0.5)", "0.5"),
        ("MIN_TRADE_USD", "最小交易金额USD (默认5)", "5"),
        ("MAX_TRADE_USD", "最大交易金额USD (默认50)", "50"),
        ("PAPER_MODE", "模拟模式 (true/false，默认true)", "true"),
        ("SLIPPAGE", "滑点容忍度 (默认0.01)", "0.01"),
        ("MAX_POSITION", "最大持仓数量 (默认10)", "10"),
        ("POLL_INTERVAL", "轮询间隔秒 (默认30，避免rate limit)", "30")
    ]
    
    for key, desc, default in params:
        current = os.getenv(key, default)
        print(f"\n{desc}")
        print(f"当前值: {current}")
        new_val = input(f"输入新值 (回车保持当前): ").strip()
        if new_val:
            set_key(ENV_FILE, key, new_val)
            print(f"✅ {key} 已更新")
    
    print("\n✅ 配置完成！")

# ==================== Data API 跟踪器 ====================
class DataAPITracker:
    """使用官方 Data API 轮询任意钱包的持仓和交易变化"""
    BASE_URL = "https://data-api.polymarket.com"
    
    def __init__(self, target_wallets: list):
        self.targets = [addr.lower() for addr in target_wallets]
        self.last_positions = {addr: {} for addr in self.targets}  # {addr: {market_id: pos_info}}
        self.processed_trade_ids = {addr: set() for addr in self.targets}
        self.fetch_interval = int(os.getenv("POLL_INTERVAL", "30"))  # 秒
    
    def fetch_positions(self, address: str) -> list:
        """获取用户当前持仓"""
        url = f"{self.BASE_URL}/positions"
        params = {
            "user": address,
            "limit": 200,
            "sortBy": "TOKENS",
            "sortDirection": "DESC",
            "sizeThreshold": 0.01  # 过滤小仓位
        }
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"拉取 {address} 持仓失败: {e}")
            return []

    def fetch_recent_trades(self, address: str, limit=50) -> list:
        """获取最近交易记录（辅助检测新动作）"""
        url = f"{self.BASE_URL}/trades"
        params = {
            "user": address,
            "limit": limit,
            "sortBy": "TIMESTAMP",
            "sortDirection": "DESC"
        }
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"拉取 {address} 最近交易失败: {e}")
            return []

    async def detect_changes(self, process_trade_func):
        """检测变化并触发跟单（传入 process_trade 函数）"""
        async def fetch_for_addr(addr):
            # 优先用 positions 检测持仓变化
            current_pos_list = self.fetch_positions(addr)
            prev_pos = self.last_positions[addr]
            
            current_pos_dict = {}
            for pos in current_pos_list:
                market_id = pos.get("asset") or pos.get("token_id") or pos.get("conditionId")
                if not market_id:
                    continue
                current_pos_dict[market_id] = pos
                
                prev = prev_pos.get(market_id, {})
                curr_size = float(pos.get("size", 0))
                prev_size = float(prev.get("size", 0))
                
                if abs(curr_size - prev_size) > 0.01:  # 变化阈值
                    delta = curr_size - prev_size
                    if delta > 0:
                        side = "buy"
                        action = "加仓/开仓"
                    else:
                        side = "sell"
                        action = "减仓/平仓"
                    size_change = abs(delta)
                    price = float(pos.get("curPrice", pos.get("price", 0)))
                    
                    # 模拟 trade 对象
                    simulated_trade = {
                        "market": market_id,
                        "side": side,
                        "price": price,
                        "size": size_change,
                        "id": f"pos_change_{int(time.time())}",
                        "timestamp": datetime.utcnow().isoformat(),
                        "taker": addr,
                        "maker": ""
                    }
                    
                    logger.info(f"检测到{action}！{addr} {side.upper()} {size_change:.2f} shares in {market_id}")
                    await process_trade_func(addr, simulated_trade)
            
            self.last_positions[addr] = current_pos_dict
            
            # 辅助：检查新 trades
            trades = self.fetch_recent_trades(addr)
            for trade in trades:
                trade_id = trade.get("id")
                if trade_id not in self.processed_trade_ids[addr]:
                    self.processed_trade_ids[addr].add(trade_id)
                    
                    simulated_trade = {
                        "market": trade.get("market") or trade.get("conditionId"),
                        "side": trade.get("side", "buy").lower(),
                        "price": float(trade.get("price", 0)),
                        "size": float(trade.get("size", 0)),
                        "id": trade_id,
                        "timestamp": trade.get("timestamp"),
                        "taker": trade.get("taker", addr),
                        "maker": trade.get("maker", "")
                    }
                    
                    if simulated_trade["price"] > 0 and simulated_trade["size"] > 0:
                        logger.info(f"检测到新成交！{addr} {simulated_trade['side'].upper()} {simulated_trade['size']:.2f} @ ${simulated_trade['price']:.4f}")
                        await process_trade_func(addr, simulated_trade)

        # 并行拉取多地址
        await asyncio.gather(*(fetch_for_addr(addr) for addr in self.targets))

# ==================== REST跟单机器人 ====================
class RESTCopyTrader:
    """使用REST API轮询作为主方案"""
    def __init__(self, client, target_wallets):
        self.client = client
        self.target_wallets = [addr.lower().strip() for addr in target_wallets]
        
        # 配置参数
        self.trade_multiplier = float(os.getenv("TRADE_MULTIPLIER", "0.5"))
        self.min_trade_usd = float(os.getenv("MIN_TRADE_USD", "5"))
        self.max_trade_usd = float(os.getenv("MAX_TRADE_USD", "50"))
        self.paper_mode = os.getenv("PAPER_MODE", "true").lower() == "true"
        self.slippage = float(os.getenv("SLIPPAGE", "0.01"))
        self.max_position = int(os.getenv("MAX_POSITION", "10"))
        self.poll_interval = int(os.getenv("POLL_INTERVAL", "30"))
        
        # 状态跟踪
        self.processed_trades = set()
        self.open_positions = {}  # {market_id: size}
        
        # Tracker
        self.tracker = DataAPITracker(self.target_wallets)
        
        logger.info(f"REST API跟单机器人初始化")
        logger.info(f"目标地址: {self.target_wallets}")
        logger.info(f"轮询间隔: {self.poll_interval}秒")
    
    async def run(self):
        """运行REST API轮询"""
        logger.info("🚀 启动REST API跟单机器人")
        logger.info(f"模拟模式: {'开启' if self.paper_mode else '关闭'}")
        
        retry_delay = 5
        while True:
            try:
                await self.tracker.detect_changes(self.process_trade)
                await asyncio.sleep(self.poll_interval)
            except Exception as e:
                logger.error(f"轮询出错: {e}")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 300)  # 指数退避
    
    async def process_trade(self, wallet, trade):
        """处理交易"""
        try:
            trade_key = f"{wallet}_{trade['id']}"
            
            if trade_key in self.processed_trades:
                return
            
            self.processed_trades.add(trade_key)
            
            market_id = trade['market']
            # 获取市场信息
            market_info = self.get_market_info(market_id)
            market_name = market_info.get('question', '未知市场') if market_info else '未知市场'
            
            # 计算跟单
            price = trade['price']
            size = trade['size']
            side = trade['side']
            
            usd_value = size * price
            copy_size = size * self.trade_multiplier
            copy_usd = copy_size * price
            
            # 检查限制
            if copy_usd < self.min_trade_usd:
                logger.info(f"💰 金额 {copy_usd:.2f} USD 小于最小限制，跳过")
                return
            
            if copy_usd > self.max_trade_usd:
                logger.info(f"💰 金额 {copy_usd:.2f} USD 大于最大限制，跳过")
                return
            
            # 检查持仓限制
            position_key = market_id
            current_position = self.open_positions.get(position_key, 0)
            
            if abs(current_position + (copy_size if side == "buy" else -copy_size)) > self.max_position:
                logger.info(f"📊 持仓限制 {self.max_position}，跳过")
                return
            
            # 更新持仓 (模拟或真实)
            if side == "buy":
                self.open_positions[position_key] = current_position + copy_size
            else:
                self.open_positions[position_key] = current_position - copy_size
            
            logger.info("="*50)
            logger.info(f"🎯 检测到目标交易")
            logger.info(f"  钱包: {wallet[:10]}...")
            logger.info(f"  市场: {market_name[:50]}...")
            logger.info(f"  方向: {side.upper()}")
            logger.info(f"  价格: ${price:.4f}")
            logger.info(f"  数量: {size:.2f} -> {copy_size:.2f}")
            logger.info(f"  时间: {trade['timestamp']}")
            logger.info("="*50)
            
            # 执行跟单
            await self.execute_copy_trade(market_id, side, price, copy_size, market_name)
            
        except Exception as e:
            logger.error(f"处理交易失败: {e}")
    
    def get_market_info(self, market_id):
        """获取市场信息"""
        try:
            # 使用缓存避免频繁请求
            if not hasattr(self, '_market_cache'):
                self._market_cache = {}
            
            if market_id in self._market_cache:
                return self._market_cache[market_id]
            
            # 从API获取市场信息
            market = self.client.get_market(market_id)
            if market:
                self._market_cache[market_id] = market
            
            return market
        except Exception as e:
            logger.debug(f"获取市场信息失败 {market_id}: {e}")
            return None
    
    async def execute_copy_trade(self, market_id, side, price, size, market_name):
        """执行跟单交易"""
        try:
            # 计算调整后的价格（考虑滑点）
            adjusted_price = price * (1 + self.slippage) if side == "buy" else price * (1 - self.slippage)
            
            if self.paper_mode:
                # 模拟交易
                logger.info(f"[模拟交易] {side.upper()} {market_name[:30]}...")
                logger.info(f"  数量: {size:.2f} @ ${adjusted_price:.4f}")
                logger.info(f"  总价: ${size * adjusted_price:.2f}")
                return {"status": "simulated", "id": f"paper_{int(time.time())}"}
            else:
                # 检查深度，避免滑点太大
                book = self.client.get_order_book(market_id)
                if not book:
                    logger.warning("无法获取order book，跳过")
                    return
                
                # 实际交易
                logger.info(f"📤 执行跟单交易...")
                
                # 转换side格式
                trade_side = BUY if side == "buy" else SELL
                
                # 创建订单 (用limit order)
                order_args = OrderArgs(
                    token_id=market_id,
                    price=adjusted_price,
                    size=size,
                    side=trade_side
                )
                
                # 提交订单
                signed_order = self.client.create_order(order_args)
                response = self.client.post_order(signed_order)
                
                if response and response.get("id"):
                    logger.info(f"✅ 跟单成功！订单ID: {response['id']}")
                    return response
                else:
                    logger.error(f"❌ 跟单失败: {response}")
                    return None
                    
        except Exception as e:
            logger.error(f"❌ 执行跟单失败: {e}")
            return None

# ==================== 主程序 ====================
def main():
    print("\n" + "="*60)
    print(" " * 15 + "Polymarket 跟单机器人 (REST API 轮询模式)")
    print("="*60)
    print("正在自动检查依赖...")
    
    # 自动检查并安装
    if not check_and_install_dependencies():
        print("依赖安装失败，请手动解决后重试")
        sys.exit(1)
    
    print("依赖检查完成！进入主菜单...")
    
    while True:
        choice = show_menu()
        
        if choice == "1":
            install_dependencies()  # 手动触发
        elif choice == "2":
            setup_config()
        elif choice == "3":
            # 检查配置
            load_dotenv(ENV_FILE)
            
            private_key = os.getenv("PRIVATE_KEY", "")
            target_wallets = os.getenv("TARGET_WALLETS", "")
            
            if not private_key:
                print("❌ 请先配置私钥！")
                continue
            
            if not target_wallets:
                print("❌ 请先配置跟单地址！")
                continue
            
            try:
                print("初始化 CLOB 客户端...")
                
                # 创建 client
                client = ClobClient(
                    host=CLOB_HOST,
                    key=private_key,
                    chain_id=CHAIN_ID
                )
                
                # 确保有API creds
                api_key = os.getenv("API_KEY")
                api_secret = os.getenv("API_SECRET")
                api_passphrase = os.getenv("API_PASSPHRASE")
                
                if not all([api_key, api_secret, api_passphrase]):
                    print("未找到API凭证，正在生成...")
                    creds = client.create_or_derive_api_creds()
                    api_key = creds.api_key
                    api_secret = creds.api_secret
                    api_passphrase = creds.api_passphrase
                    set_key(ENV_FILE, "API_KEY", api_key)
                    set_key(ENV_FILE, "API_SECRET", api_secret)
                    set_key(ENV_FILE, "API_PASSPHRASE", api_passphrase)
                    print("✅ API凭证已生成并保存")
                else:
                    # 加载已有 creds
                    client.set_api_creds(
                        api_key=api_key,
                        api_secret=api_secret,
                        api_passphrase=api_passphrase
                    )
                    print("✅ 使用已有API凭证")
                
                targets = [addr.strip() for addr in target_wallets.split(",")]
                
                rest_trader = RESTCopyTrader(client, targets)
                asyncio.run(rest_trader.run())
                
            except KeyboardInterrupt:
                print("\n用户中断")
            except Exception as e:
                print(f"❌ 启动失败: {e}")
                import traceback
                traceback.print_exc()
        
        elif choice == "4":
            # 查看状态
            load_dotenv(ENV_FILE)
            
            print("\n当前配置:")
            print(f"私钥: {os.getenv('PRIVATE_KEY', '未设置')[:20]}...")
            print(f"跟单地址: {os.getenv('TARGET_WALLETS', '未设置')}")
            print(f"跟单比例: {os.getenv('TRADE_MULTIPLIER', '0.5')}")
            print(f"模拟模式: {os.getenv('PAPER_MODE', 'true')}")
            print(f"轮询间隔: {os.getenv('POLL_INTERVAL', '30')}秒")
            
            # 检查日志文件
            if os.path.exists("bot.log"):
                print("\n最近日志:")
                try:
                    with open("bot.log", "r") as f:
                        lines = f.readlines()[-5:]
                        for line in lines:
                            print(line.strip())
                except:
                    print("无法读取日志")
        
        elif choice == "5":
            print("退出程序")
            sys.exit(0)
        
        else:
            print("❌ 无效选项")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n程序已退出")
    except Exception as e:
        print(f"程序出错: {e}")
        import traceback
        traceback.print_exc()
