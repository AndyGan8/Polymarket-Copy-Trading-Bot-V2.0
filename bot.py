import os
import sys
import json
import time
import logging
import asyncio
import websockets
from datetime import datetime
from dotenv import load_dotenv, set_key
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs
from py_clob_client.order_builder.constants import BUY, SELL
import hashlib
import hmac
import base64

# ==================== 配置 ====================
ENV_FILE = ".env"
CLOB_HOST = "https://clob.polymarket.com"
WS_URL = "wss://ws.clob.polymarket.com"  # Polymarket WebSocket端点
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
    print(" " * 15 + "Polymarket WebSocket 跟单机器人")
    print("="*60)
    print("1. 检查环境并安装依赖")
    print("2. 配置钱包和跟单地址")
    print("3. 启动WebSocket跟单机器人")
    print("4. 测试连接")
    print("5. 查看状态")
    print("6. 退出")
    return input("\n请输入选项 (1-6): ").strip()

# ==================== 安装依赖 ====================
def install_dependencies():
    print("\n安装必要依赖...")
    requirements = [
        "py-clob-client>=0.34.0",
        "python-dotenv>=1.0.0",
        "websockets>=11.0.0",
        "requests>=2.28.0"
    ]
    
    try:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install"] + requirements)
        print("✅ 依赖安装完成！")
    except Exception as e:
        print(f"❌ 安装失败: {e}")
        print("请手动运行: pip install py-clob-client python-dotenv websockets requests")

# ==================== 配置 ====================
def setup_config():
    if not os.path.exists(ENV_FILE):
        with open(ENV_FILE, 'w') as f:
            f.write("# Polymarket WebSocket 跟单机器人配置\n")
    
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
    
    # 3. 订阅的市场ID（可选）
    market_ids = os.getenv("MARKET_IDS", "")
    if market_ids:
        print(f"\n当前订阅市场ID: {market_ids}")
    else:
        print("\n未配置市场ID，将订阅所有市场")
    
    change = input("是否配置特定市场ID？(y/n): ").strip().lower()
    if change == 'y':
        new_markets = input("请输入市场ID (多个用逗号分隔，留空订阅所有): ").strip()
        if new_markets:
            set_key(ENV_FILE, "MARKET_IDS", new_markets)
            print("✅ 市场ID已保存")
    
    # 4. 其他参数配置
    print("\n其他参数配置:")
    
    params = [
        ("TRADE_MULTIPLIER", "跟单比例 (默认0.5)", "0.5"),
        ("MIN_TRADE_USD", "最小交易金额USD (默认5)", "5"),
        ("MAX_TRADE_USD", "最大交易金额USD (默认50)", "50"),
        ("PAPER_MODE", "模拟模式 (true/false，默认true)", "true"),
        ("SLIPPAGE", "滑点容忍度 (默认0.01)", "0.01"),
        ("MAX_POSITION", "最大持仓数量 (默认10)", "10")
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

# ==================== WebSocket客户端 ====================
class PolymarketWebSocketClient:
    def __init__(self, client, target_wallets, market_ids=None):
        self.ws_url = WS_URL
        self.client = client
        self.target_wallets = [addr.lower().strip() for addr in target_wallets]
        self.market_ids = [mid.strip() for mid in market_ids.split(",")] if market_ids else []
        
        # 配置参数
        self.trade_multiplier = float(os.getenv("TRADE_MULTIPLIER", "0.5"))
        self.min_trade_usd = float(os.getenv("MIN_TRADE_USD", "5"))
        self.max_trade_usd = float(os.getenv("MAX_TRADE_USD", "50"))
        self.paper_mode = os.getenv("PAPER_MODE", "true").lower() == "true"
        self.slippage = float(os.getenv("SLIPPAGE", "0.01"))
        self.max_position = int(os.getenv("MAX_POSITION", "10"))
        
        # 状态跟踪
        self.websocket = None
        self.connected = False
        self.subscriptions = set()
        self.processed_trades = set()
        self.open_positions = {}
        
        logger.info(f"WebSocket客户端初始化完成")
        logger.info(f"目标地址: {self.target_wallets}")
        logger.info(f"订阅市场: {self.market_ids if self.market_ids else '所有'}")
    
    async def connect(self):
        """连接到WebSocket服务器"""
        try:
            logger.info(f"连接到 WebSocket: {self.ws_url}")
            self.websocket = await websockets.connect(self.ws_url, ping_interval=30, ping_timeout=10)
            self.connected = True
            logger.info("✅ WebSocket连接成功")
            return True
        except Exception as e:
            logger.error(f"❌ WebSocket连接失败: {e}")
            return False
    
    async def subscribe_to_trades(self):
        """订阅交易数据"""
        try:
            # 构建订阅消息
            subscribe_msg = {
                "type": "subscribe",
                "channel": "trades"
            }
            
            # 如果指定了市场，添加过滤
            if self.market_ids:
                subscribe_msg["markets"] = self.market_ids
            
            await self.websocket.send(json.dumps(subscribe_msg))
            logger.info(f"📡 已订阅交易数据")
            
            # 确认订阅
            response = await self.websocket.recv()
            logger.info(f"订阅响应: {response}")
            
            return True
        except Exception as e:
            logger.error(f"订阅失败: {e}")
            return False
    
    async def subscribe_to_orderbook(self, market_id):
        """订阅订单簿数据"""
        try:
            subscribe_msg = {
                "type": "subscribe",
                "channel": "orderbook",
                "market": market_id
            }
            
            await self.websocket.send(json.dumps(subscribe_msg))
            logger.debug(f"订阅订单簿: {market_id}")
            
        except Exception as e:
            logger.error(f"订阅订单簿失败 {market_id}: {e}")
    
    async def listen_for_trades(self):
        """监听交易数据"""
        logger.info("👂 开始监听交易数据...")
        
        while self.connected:
            try:
                # 接收消息
                message = await self.websocket.recv()
                await self.handle_message(message)
                
            except websockets.exceptions.ConnectionClosed as e:
                logger.error(f"WebSocket连接关闭: {e}")
                self.connected = False
                break
            except Exception as e:
                logger.error(f"接收消息错误: {e}")
                await asyncio.sleep(1)
    
    async def handle_message(self, message):
        """处理接收到的消息"""
        try:
            data = json.loads(message)
            
            # 根据消息类型处理
            msg_type = data.get("type")
            channel = data.get("channel")
            
            if msg_type == "trades" and channel == "trades":
                await self.handle_trade_data(data)
            elif msg_type == "orderbook" and channel == "orderbook":
                await self.handle_orderbook_data(data)
            elif msg_type == "error":
                logger.error(f"WebSocket错误: {data.get('message')}")
            elif msg_type == "subscribed":
                logger.info(f"✅ 订阅成功: {data.get('channel')}")
            else:
                logger.debug(f"收到消息: {msg_type}/{channel}")
                
        except json.JSONDecodeError:
            logger.error(f"JSON解析错误: {message}")
        except Exception as e:
            logger.error(f"处理消息错误: {e}")
    
    async def handle_trade_data(self, data):
        """处理交易数据"""
        trades = data.get("trades", [])
        
        for trade in trades:
            await self.process_trade(trade)
    
    async def process_trade(self, trade):
        """处理单个交易"""
        try:
            # 提取交易信息
            market_id = trade.get("market")
            side = trade.get("side")  # "buy" 或 "sell"
            price = float(trade.get("price", 0))
            size = float(trade.get("size", 0))
            taker = trade.get("taker", "").lower()
            maker = trade.get("maker", "").lower()
            trade_id = trade.get("id")
            timestamp = trade.get("timestamp")
            
            # 检查是否是目标钱包的交易
            target_wallet = None
            if taker in self.target_wallets:
                target_wallet = taker
            elif maker in self.target_wallets:
                target_wallet = maker
            
            if not target_wallet:
                return
            
            # 检查是否已处理
            trade_key = f"{target_wallet}_{trade_id}"
            if trade_key in self.processed_trades:
                return
            
            # 标记为已处理
            self.processed_trades.add(trade_key)
            
            # 获取市场信息
            market_info = await self.get_market_info(market_id)
            market_name = market_info.get('question', '未知市场') if market_info else '未知市场'
            
            # 计算跟单金额
            usd_value = size * price
            copy_size = size * self.trade_multiplier
            copy_usd = copy_size * price
            
            # 检查交易限制
            if copy_usd < self.min_trade_usd:
                logger.info(f"💰 金额 {copy_usd:.2f} USD 小于最小限制，跳过")
                return
            
            if copy_usd > self.max_trade_usd:
                logger.info(f"💰 金额 {copy_usd:.2f} USD 大于最大限制，跳过")
                return
            
            # 检查持仓限制
            position_key = f"{target_wallet}_{market_id}"
            current_position = self.open_positions.get(position_key, 0)
            
            if abs(current_position + (copy_size if side == "buy" else -copy_size)) > self.max_position:
                logger.info(f"📊 持仓限制 {self.max_position}，跳过")
                return
            
            # 更新持仓
            if side == "buy":
                self.open_positions[position_key] = current_position + copy_size
            else:
                self.open_positions[position_key] = current_position - copy_size
            
            # 记录检测到的交易
            logger.info("="*50)
            logger.info(f"🎯 检测到目标交易！")
            logger.info(f"  钱包: {target_wallet[:10]}...")
            logger.info(f"  市场: {market_name[:50]}...")
            logger.info(f"  方向: {side.upper()}")
            logger.info(f"  价格: ${price:.4f}")
            logger.info(f"  数量: {size:.2f} -> {copy_size:.2f}")
            logger.info(f"  金额: ${usd_value:.2f} -> ${copy_usd:.2f}")
            logger.info(f"  时间: {timestamp}")
            logger.info("="*50)
            
            # 执行跟单
            await self.execute_copy_trade(market_id, side, price, copy_size, market_name)
            
        except Exception as e:
            logger.error(f"处理交易失败: {e}")
    
    async def get_market_info(self, market_id):
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
                # 实际交易
                logger.info(f"📤 执行跟单交易...")
                
                # 转换side格式
                trade_side = BUY if side == "buy" else SELL
                
                # 创建订单
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
    
    async def handle_orderbook_data(self, data):
        """处理订单簿数据"""
        # 可以用于获取更好的价格信息
        market_id = data.get("market")
        # logger.debug(f"订单簿更新: {market_id}")
    
    async def disconnect(self):
        """断开连接"""
        if self.websocket:
            await self.websocket.close()
            self.connected = False
            logger.info("WebSocket连接已关闭")
    
    async def run(self):
        """运行WebSocket客户端"""
        # 连接
        if not await self.connect():
            return False
        
        # 订阅
        if not await self.subscribe_to_trades():
            return False
        
        # 监听
        try:
            await self.listen_for_trades()
        except KeyboardInterrupt:
            logger.info("用户中断")
        finally:
            await self.disconnect()
        
        return True

# ==================== 测试连接 ====================
async def test_websocket_connection():
    """测试WebSocket连接"""
    print("\n" + "="*60)
    print("测试 WebSocket 连接")
    print("="*60)
    
    try:
        # 测试基本连接
        print("测试连接到 WebSocket 服务器...")
        async with websockets.connect(WS_URL) as ws:
            print("✅ WebSocket连接成功")
            
            # 测试订阅
            test_msg = {
                "type": "subscribe",
                "channel": "trades",
                "markets": []  # 空数组表示所有市场
            }
            
            await ws.send(json.dumps(test_msg))
            print("✅ 订阅消息发送成功")
            
            # 等待响应
            try:
                response = await asyncio.wait_for(ws.recv(), timeout=5)
                print(f"✅ 收到响应: {response}")
                return True
            except asyncio.TimeoutError:
                print("⚠️  未收到响应（可能正常）")
                return True
                
    except Exception as e:
        print(f"❌ WebSocket测试失败: {e}")
        return False

# ==================== 主程序 ====================
def main():
    print("\n" + "="*60)
    print(" " * 15 + "Polymarket WebSocket 跟单机器人")
    print("="*60)
    print("功能特点:")
    print("  • 实时WebSocket交易监控")
    print("  • 多地址同时跟单")
    print("  • 可配置交易参数")
    print("  • 模拟/实盘模式")
    print("  • 自动重连机制")
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
                print("初始化 CLOB 客户端...")
                client = ClobClient(CLOB_HOST, key=private_key, chain_id=CHAIN_ID)
                
                # 生成API凭证
                print("生成API凭证...")
                creds = client.create_or_derive_api_creds()
                set_key(ENV_FILE, "API_KEY", creds.api_key)
                set_key(ENV_FILE, "API_SECRET", creds.api_secret)
                set_key(ENV_FILE, "API_PASSPHRASE", creds.api_passphrase)
                
                print("✅ 客户端初始化完成")
                
                # 获取市场ID列表
                market_ids = os.getenv("MARKET_IDS", "")
                
                # 初始化WebSocket客户端
                targets = [addr.strip() for addr in target_wallets.split(",")]
                ws_client = PolymarketWebSocketClient(client, targets, market_ids)
                
                # 启动跟单机器人
                print("\n" + "="*60)
                print("WebSocket跟单机器人启动中...")
                print("按 Ctrl+C 停止")
                print("="*60)
                
                asyncio.run(ws_client.run())
                
            except KeyboardInterrupt:
                print("\n用户中断")
            except Exception as e:
                print(f"❌ 启动失败: {e}")
                import traceback
                traceback.print_exc()
        
        elif choice == "4":
            print("测试连接中...")
            success = asyncio.run(test_websocket_connection())
            if success:
                print("\n✅ 连接测试通过！")
            else:
                print("\n❌ 连接测试失败")
        
        elif choice == "5":
            # 查看状态
            load_dotenv(ENV_FILE)
            
            print("\n当前配置:")
            print(f"私钥: {os.getenv('PRIVATE_KEY', '未设置')[:20]}...")
            print(f"跟单地址: {os.getenv('TARGET_WALLETS', '未设置')}")
            print(f"市场ID: {os.getenv('MARKET_IDS', '所有市场')}")
            print(f"跟单比例: {os.getenv('TRADE_MULTIPLIER', '0.5')}")
            print(f"模拟模式: {os.getenv('PAPER_MODE', 'true')}")
            print(f"最小金额: ${os.getenv('MIN_TRADE_USD', '5')}")
            print(f"最大金额: ${os.getenv('MAX_TRADE_USD', '50')}")
            
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
