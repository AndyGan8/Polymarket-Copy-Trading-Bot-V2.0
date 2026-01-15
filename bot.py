import os
import sys
import time
import json
import logging
import requests
from datetime import datetime
from dotenv import load_dotenv, set_key
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, CancelOrderParams
from py_clob_client.order_builder.constants import BUY, SELL
from py_clob_client.constants import POLYGON
import asyncio

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

# ==================== 主菜单 ====================
def show_menu():
    print("\n" + "="*60)
    print(" " * 15 + "Polymarket 跟单机器人 (简化版)")
    print("="*60)
    print("1. 检查环境并安装依赖")
    print("2. 配置钱包和跟单地址")
    print("3. 启动跟单机器人")
    print("4. 测试API连接")
    print("5. 查看状态")
    print("6. 退出")
    return input("\n请输入选项 (1-6): ").strip()

# ==================== 安装依赖 ====================
def install_dependencies():
    print("\n安装必要依赖...")
    requirements = [
        "py-clob-client>=0.34.0",
        "python-dotenv>=1.0.0",
        "requests>=2.28.0"
    ]
    
    try:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install"] + requirements)
        print("✅ 依赖安装完成！")
    except Exception as e:
        print(f"❌ 安装失败: {e}")
        print("请手动运行: pip install py-clob-client python-dotenv requests")

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
        ("MIN_TRADE_USD", "最小交易金额USD (默认10)", "10"),
        ("MAX_TRADE_USD", "最大交易金额USD (默认100)", "100"),
        ("PAPER_MODE", "模拟模式 (true/false，默认true)", "true"),
        ("CHECK_INTERVAL", "检查间隔秒数 (默认10)", "10")
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

# ==================== API测试 ====================
def test_api_connection(client):
    print("\n" + "="*60)
    print("测试API连接")
    print("="*60)
    
    try:
        # 测试获取余额
        print("测试获取余额...")
        balances = client.get_balance()
        print(f"✅ 余额获取成功")
        for token, balance in balances.items():
            if float(balance) > 0:
                print(f"  {token}: {balance}")
        
        # 测试获取订单簿
        print("\n测试获取市场信息...")
        # 获取一个活跃的市场作为测试
        markets = client.get_markets()
        if markets:
            print(f"✅ 发现 {len(markets)} 个市场")
            for i, market in enumerate(markets[:3]):
                print(f"  {i+1}. {market.get('question', '未知市场')[:50]}...")
        else:
            print("⚠️  未获取到市场信息")
        
        print("\n✅ API连接测试通过！")
        return True
        
    except Exception as e:
        print(f"❌ API测试失败: {e}")
        return False

# ==================== 核心跟单逻辑 ====================
class CopyTrader:
    def __init__(self, client, target_wallets):
        self.client = client
        self.target_wallets = [addr.lower().strip() for addr in target_wallets]
        self.processed_orders = set()
        self.last_check_time = 0
        
        # 加载配置
        self.trade_multiplier = float(os.getenv("TRADE_MULTIPLIER", "0.5"))
        self.min_trade_usd = float(os.getenv("MIN_TRADE_USD", "10"))
        self.max_trade_usd = float(os.getenv("MAX_TRADE_USD", "100"))
        self.paper_mode = os.getenv("PAPER_MODE", "true").lower() == "true"
        self.check_interval = int(os.getenv("CHECK_INTERVAL", "10"))
        
        logger.info(f"跟单机器人初始化完成")
        logger.info(f"目标地址: {self.target_wallets}")
        logger.info(f"跟单比例: {self.trade_multiplier}")
        logger.info(f"模拟模式: {self.paper_mode}")
    
    async def get_recent_trades(self, wallet_address, limit=10):
        """获取指定钱包的最新交易"""
        try:
            # 这里需要根据Polymarket API调整
            # 目前是示例代码
            trades = []
            
            # 示例：获取钱包的订单历史
            orders = self.client.get_orders(wallet=wallet_address, limit=limit)
            
            for order in orders:
                if order.get('status') == 'FILLED':
                    trades.append({
                        'market': order.get('market'),
                        'side': order.get('side'),
                        'price': float(order.get('price', 0)),
                        'size': float(order.get('size', 0)),
                        'timestamp': order.get('created_at'),
                        'order_id': order.get('id')
                    })
            
            return trades
            
        except Exception as e:
            logger.error(f"获取交易历史失败 {wallet_address}: {e}")
            return []
    
    async def get_market_info(self, market_id):
        """获取市场信息"""
        try:
            # 获取市场详情
            market = self.client.get_market(market_id)
            return market
        except Exception as e:
            logger.error(f"获取市场信息失败 {market_id}: {e}")
            return None
    
    async def place_order(self, market_id, side, price, size):
        """下单"""
        if self.paper_mode:
            logger.info(f"[模拟] 下单: {side} {market_id[:10]}... {size}份 @ {price}")
            return {"id": "paper_trade", "status": "SIMULATED"}
        
        try:
            order_args = OrderArgs(
                token_id=market_id,
                price=price,
                size=size,
                side=side
            )
            
            # 创建并提交订单
            signed_order = self.client.create_order(order_args)
            response = self.client.post_order(signed_order)
            
            logger.info(f"✅ 下单成功: {response.get('id')}")
            return response
            
        except Exception as e:
            logger.error(f"❌ 下单失败: {e}")
            return None
    
    async def monitor_and_copy(self):
        """监控并跟单"""
        logger.info("🚀 开始监控并跟单...")
        
        while True:
            try:
                current_time = time.time()
                
                # 检查每个目标钱包
                for wallet in self.target_wallets:
                    logger.debug(f"检查钱包: {wallet[:10]}...")
                    
                    # 获取最近交易
                    recent_trades = await self.get_recent_trades(wallet, limit=5)
                    
                    for trade in recent_trades:
                        trade_key = f"{wallet}_{trade['order_id']}"
                        
                        # 检查是否已处理
                        if trade_key in self.processed_orders:
                            continue
                        
                        # 记录新交易
                        self.processed_orders.add(trade_key)
                        
                        # 解析交易信息
                        market_id = trade['market']
                        side = trade['side']
                        price = trade['price']
                        original_size = trade['size']
                        
                        # 计算跟单大小
                        copy_size = original_size * self.trade_multiplier
                        usd_value = copy_size * price
                        
                        # 检查金额限制
                        if usd_value < self.min_trade_usd:
                            logger.info(f"💰 金额 {usd_value:.2f} USD 小于最小限制，跳过")
                            continue
                        
                        if usd_value > self.max_trade_usd:
                            logger.info(f"💰 金额 {usd_value:.2f} USD 大于最大限制，跳过")
                            continue
                        
                        # 获取市场信息
                        market_info = await self.get_market_info(market_id)
                        market_name = market_info.get('question', '未知市场') if market_info else '未知市场'
                        
                        logger.info(f"📊 检测到新交易:")
                        logger.info(f"  钱包: {wallet[:10]}...")
                        logger.info(f"  市场: {market_name[:50]}...")
                        logger.info(f"  方向: {side}")
                        logger.info(f"  价格: {price:.4f}")
                        logger.info(f"  大小: {original_size:.2f} -> {copy_size:.2f}")
                        
                        # 执行跟单
                        await self.place_order(market_id, side, price, copy_size)
                
                # 等待下次检查
                await asyncio.sleep(self.check_interval)
                
            except KeyboardInterrupt:
                logger.info("用户中断监控")
                break
            except Exception as e:
                logger.error(f"监控出错: {e}")
                await asyncio.sleep(5)

# ==================== 主程序 ====================
def main():
    print("\n" + "="*60)
    print(" " * 15 + "Polymarket 跟单机器人")
    print("="*60)
    print("注意: 请使用全新的 burner 钱包进行测试！")
    print("="*60)
    
    while True:
        choice = show_menu()
        
        if choice == "1":
            install_dependencies()
        
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
                # 初始化客户端
                print("初始化客户端...")
                client = ClobClient(CLOB_HOST, key=private_key, chain_id=CHAIN_ID)
                
                # 生成API凭证
                print("生成API凭证...")
                creds = client.create_or_derive_api_creds()
                set_key(ENV_FILE, "API_KEY", creds.api_key)
                set_key(ENV_FILE, "API_SECRET", creds.api_secret)
                set_key(ENV_FILE, "API_PASSPHRASE", creds.api_passphrase)
                
                # 初始化跟单机器人
                targets = [addr.strip() for addr in target_wallets.split(",")]
                trader = CopyTrader(client, targets)
                
                # 启动监控
                print("\n" + "="*60)
                print("跟单机器人启动中...")
                print("按 Ctrl+C 停止")
                print("="*60)
                
                asyncio.run(trader.monitor_and_copy())
                
            except Exception as e:
                print(f"❌ 启动失败: {e}")
                import traceback
                traceback.print_exc()
        
        elif choice == "4":
            load_dotenv(ENV_FILE)
            
            private_key = os.getenv("PRIVATE_KEY", "")
            if not private_key:
                print("❌ 请先配置私钥！")
                continue
            
            try:
                client = ClobClient(CLOB_HOST, key=private_key, chain_id=CHAIN_ID)
                test_api_connection(client)
            except Exception as e:
                print(f"❌ 测试失败: {e}")
        
        elif choice == "5":
            # 查看状态
            load_dotenv(ENV_FILE)
            
            print("\n当前配置:")
            print(f"私钥: {os.getenv('PRIVATE_KEY', '未设置')[:20]}...")
            print(f"跟单地址: {os.getenv('TARGET_WALLETS', '未设置')}")
            print(f"跟单比例: {os.getenv('TRADE_MULTIPLIER', '0.5')}")
            print(f"模拟模式: {os.getenv('PAPER_MODE', 'true')}")
            
            # 检查日志文件
            if os.path.exists("bot.log"):
                print("\n最近日志:")
                try:
                    with open("bot.log", "r") as f:
                        lines = f.readlines()[-10:]
                        for line in lines:
                            print(line.strip())
                except:
                    print("无法读取日志")
        
        elif choice == "6":
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
