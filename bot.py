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
import requests

# ==================== 配置 ====================
ENV_FILE = ".env"
CLOB_HOST = "https://clob.polymarket.com"
# 可能的WebSocket地址（需要测试）
WS_URLS = [
    "wss://clob.polymarket.com/ws",  # 可能的WebSocket端点
    "wss://ws.clob.polymarket.com",
    "wss://api.polymarket.com/ws",
    "wss://api.polymarket.com/socket.io",
]
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
    print("4. 测试连接并查找正确的WebSocket地址")
    print("5. 查看状态")
    print("6. 退出")
    return input("\n请输入选项 (1-6): ").strip()

# ==================== 查找正确的WebSocket地址 ====================
async def find_websocket_url():
    """测试并找到可用的WebSocket地址"""
    print("\n正在查找可用的WebSocket地址...")
    
    for ws_url in WS_URLS:
        print(f"测试: {ws_url}")
        try:
            async with websockets.connect(ws_url, timeout=10) as ws:
                print(f"✅ 连接成功: {ws_url}")
                return ws_url
        except Exception as e:
            print(f"❌ 连接失败: {e}")
    
    # 如果预设地址都失败，尝试从API获取
    print("\n尝试从API获取WebSocket地址...")
    try:
        # 尝试获取服务器信息
        response = requests.get("https://clob.polymarket.com/info", timeout=10)
        if response.status_code == 200:
            data = response.json()
            if "websocket_url" in data:
                ws_url = data["websocket_url"]
                print(f"从API获取到WebSocket地址: {ws_url}")
                return ws_url
    except Exception as e:
        print(f"从API获取失败: {e}")
    
    return None

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
    
    # 3. WebSocket地址配置
    ws_url = os.getenv("WS_URL", "")
    if ws_url:
        print(f"\n当前WebSocket地址: {ws_url}")
    else:
        print("\n未配置WebSocket地址")
    
    change = input("是否手动配置WebSocket地址？(y/n): ").strip().lower()
    if change == 'y':
        new_ws = input("请输入WebSocket地址 (wss://开头): ").strip()
        if new_ws.startswith("wss://"):
            set_key(ENV_FILE, "WS_URL", new_ws)
            print("✅ WebSocket地址已保存")
        else:
            print("❌ WebSocket地址必须以wss://开头")
    
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
    def __init__(self, client, target_wallets, ws_url=None):
        self.client = client
        self.target_wallets = [addr.lower().strip() for addr in target_wallets]
        
        # 获取或使用配置的WebSocket地址
        if ws_url:
            self.ws_url = ws_url
        else:
            self.ws_url = os.getenv("WS_URL", "")
            if not self.ws_url:
                logger.warning("未配置WebSocket地址，将尝试自动查找")
        
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
        self.processed_trades = set()
        self.open_positions = {}
        
        logger.info(f"WebSocket客户端初始化完成")
        logger.info(f"目标地址: {self.target_wallets}")
        logger.info(f"WebSocket地址: {self.ws_url}")
    
    async def find_and_connect(self):
        """查找并连接到可用的WebSocket服务器"""
        # 如果已配置地址，先尝试它
        if self.ws_url:
            try:
                logger.info(f"尝试连接配置的地址: {self.ws_url}")
                self.websocket = await websockets.connect(self.ws_url, ping_interval=30, ping_timeout=10)
                self.connected = True
                logger.info(f"✅ 连接到 {self.ws_url}")
                return True
            except Exception as e:
                logger.warning(f"配置的地址连接失败: {e}")
        
        # 尝试其他可能的地址
        logger.info("尝试其他可能的WebSocket地址...")
        for ws_url in WS_URLS:
            try:
                logger.info(f"尝试: {ws_url}")
                self.websocket = await websockets.connect(ws_url, ping_interval=30, ping_timeout=10)
                self.connected = True
                self.ws_url = ws_url
                logger.info(f"✅ 成功连接到: {ws_url}")
                
                # 保存找到的地址
                set_key(ENV_FILE, "WS_URL", ws_url)
                logger.info(f"已保存WebSocket地址到配置")
                
                return True
            except Exception as e:
                logger.warning(f"连接失败 {ws_url}: {e}")
                continue
        
        logger.error("❌ 所有WebSocket地址都连接失败")
        return False
    
    async def subscribe_to_trades(self):
        """订阅交易数据"""
        try:
            # Polymarket可能使用不同的订阅格式
            # 尝试几种可能的格式
            
            # 格式1: 简单的subscribe消息
            subscribe_msg = {
                "type": "subscribe",
                "channel": "trades"
            }
            
            await self.websocket.send(json.dumps(subscribe_msg))
            logger.info("📡 尝试订阅格式1...")
            
            # 等待响应
            try:
                response = await asyncio.wait_for(self.websocket.recv(), timeout=3)
                logger.info(f"订阅响应: {response}")
                return True
            except asyncio.TimeoutError:
                logger.info("未收到响应，尝试其他格式...")
            
            # 格式2: 不同的消息结构
            subscribe_msg2 = {
                "event": "subscribe",
                "channel": "trades"
            }
            
            await self.websocket.send(json.dumps(subscribe_msg2))
            logger.info("📡 尝试订阅格式2...")
            
            # 格式3: 可能是socket.io格式
            subscribe_msg3 = '42["subscribe", {"channel": "trades"}]'
            await self.websocket.send(subscribe_msg3)
            logger.info("📡 尝试订阅格式3...")
            
            logger.info("✅ 订阅消息已发送")
            return True
            
        except Exception as e:
            logger.error(f"订阅失败: {e}")
            return False
    
    async def listen_for_trades(self):
        """监听交易数据"""
        logger.info("👂 开始监听交易数据...")
        logger.info("注意: 如果长时间没有数据，可能需要调整订阅格式")
        
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
            # 尝试解析为JSON
            try:
                data = json.loads(message)
                await self.handle_json_message(data)
            except json.JSONDecodeError:
                # 可能是其他格式
                await self.handle_raw_message(message)
                
        except Exception as e:
            logger.error(f"处理消息错误: {e}")
    
    async def handle_json_message(self, data):
        """处理JSON格式的消息"""
        # 根据消息类型处理
        msg_type = data.get("type") or data.get("event")
        channel = data.get("channel")
        
        if msg_type == "trades" or channel == "trades":
            trades = data.get("trades") or data.get("data") or []
            if isinstance(trades, list):
                for trade in trades:
                    await self.process_trade(trade)
            elif isinstance(trades, dict):
                await self.process_trade(trades)
        elif msg_type == "trade":
            await self.process_trade(data.get("data", data))
        elif msg_type == "error":
            logger.error(f"WebSocket错误: {data.get('message')}")
        elif msg_type == "subscribed":
            logger.info(f"✅ 订阅成功: {data.get('channel')}")
        else:
            # 记录未知消息格式用于调试
            logger.debug(f"收到消息: {json.dumps(data)[:100]}...")
    
    async def handle_raw_message(self, message):
        """处理原始格式的消息"""
        # 可能是socket.io格式或其他格式
        logger.debug(f"收到原始消息: {message[:100]}...")
        
        # 尝试解析socket.io格式
        if message.startswith('42'):
            try:
                # 解析socket.io格式: 42["event", data]
                import ast
                content = message[2:]  # 去掉'42'
                event_data = ast.literal_eval(content)
                
                if isinstance(event_data, list) and len(event_data) >= 2:
                    event_name = event_data[0]
                    event_payload = event_data[1]
                    
                    if event_name == "trade" or event_name == "trades":
                        await self.process_trade(event_payload)
                    elif event_name == "subscribed":
                        logger.info(f"✅ Socket.io订阅成功")
            except Exception as e:
                logger.debug(f"解析socket.io消息失败: {e}")
    
    async def process_trade(self, trade):
        """处理单个交易"""
        try:
            # 提取交易信息（适应不同格式）
            market_id = trade.get("market") or trade.get("marketId") or trade.get("token_id")
            side = trade.get("side")  # "buy" 或 "sell"
            price = float(trade.get("price", 0))
            size = float(trade.get("size", trade.get("amount", 0)))
            taker = trade.get("taker", "").lower()
            maker = trade.get("maker", "").lower()
            trade_id = trade.get("id") or trade.get("tradeId")
            timestamp = trade.get("timestamp") or trade.get("time")
            
            if not all([market_id, side, price > 0, size > 0]):
                # 不是有效的交易数据
                return
            
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
            if timestamp:
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
    
    async def run(self):
        """运行WebSocket客户端"""
        # 查找并连接
        if not await self.find_and_connect():
            logger.error("无法连接到任何WebSocket服务器")
            return False
        
        # 订阅
        logger.info("发送订阅请求...")
        await self.subscribe_to_trades()
        
        # 监听
        try:
            await self.listen_for_trades()
        except KeyboardInterrupt:
            logger.info("用户中断")
        finally:
            await self.disconnect()
        
        return True
    
    async def disconnect(self):
        """断开连接"""
        if self.websocket:
            await self.websocket.close()
            self.connected = False
            logger.info("WebSocket连接已关闭")

# ==================== 备用方案：REST API轮询 ====================
class RESTCopyTrader:
    """使用REST API轮询作为备用方案"""
    def __init__(self, client, target_wallets):
        self.client = client
        self.target_wallets = [addr.lower().strip() for addr in target_wallets]
        
        # 配置参数
        self.trade_multiplier = float(os.getenv("TRADE_MULTIPLIER", "0.5"))
        self.min_trade_usd = float(os.getenv("MIN_TRADE_USD", "5"))
        self.max_trade_usd = float(os.getenv("MAX_TRADE_USD", "50"))
        self.paper_mode = os.getenv("PAPER_MODE", "true").lower() == "true"
        self.slippage = float(os.getenv("SLIPPAGE", "0.01"))
        
        # 状态跟踪
        self.processed_trades = set()
        self.last_check = {}
        
        logger.info(f"REST API跟单机器人初始化")
        logger.info(f"目标地址: {self.target_wallets}")
    
    async def get_wallet_trades(self, wallet_address):
        """获取钱包的交易历史"""
        try:
            # 这里需要根据Polymarket API调整
            # 目前使用示例方式
            trades = []
            
            # 获取钱包的订单
            orders = self.client.get_orders(wallet=wallet_address, limit=20)
            
            for order in orders:
                if order.get('status') == 'FILLED':
                    trade_time = order.get('created_at')
                    if trade_time:
                        # 检查是否是新的交易
                        trade_key = f"{wallet_address}_{order.get('id')}"
                        if trade_key not in self.processed_trades:
                            trades.append({
                                'market': order.get('market'),
                                'side': order.get('side'),
                                'price': float(order.get('price', 0)),
                                'size': float(order.get('size', 0)),
                                'timestamp': trade_time,
                                'id': order.get('id')
                            })
            
            return trades
            
        except Exception as e:
            logger.error(f"获取交易失败 {wallet_address}: {e}")
            return []
    
    async def run(self):
        """运行REST API轮询"""
        logger.info("🚀 启动REST API跟单机器人")
        logger.info("📡 使用轮询方式（每30秒检查一次）")
        
        try:
            while True:
                for wallet in self.target_wallets:
                    logger.debug(f"检查钱包: {wallet[:10]}...")
                    
                    trades = await self.get_wallet_trades(wallet)
                    
                    for trade in trades:
                        await self.process_trade(wallet, trade)
                
                # 等待下次检查
                await asyncio.sleep(30)
                
        except KeyboardInterrupt:
            logger.info("用户中断")
        except Exception as e:
            logger.error(f"轮询出错: {e}")
    
    async def process_trade(self, wallet, trade):
        """处理交易"""
        try:
            trade_key = f"{wallet}_{trade['id']}"
            
            if trade_key in self.processed_trades:
                return
            
            self.processed_trades.add(trade_key)
            
            # 获取市场信息
            market_info = await self.get_market_info(trade['market'])
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
            
            logger.info("="*50)
            logger.info(f"🎯 检测到目标交易（轮询方式）")
            logger.info(f"  钱包: {wallet[:10]}...")
            logger.info(f"  市场: {market_name[:50]}...")
            logger.info(f"  方向: {side.upper()}")
            logger.info(f"  价格: ${price:.4f}")
            logger.info(f"  数量: {size:.2f} -> {copy_size:.2f}")
            logger.info(f"  时间: {trade['timestamp']}")
            logger.info("="*50)
            
            # 执行跟单
            await self.execute_copy_trade(trade['market'], side, price, copy_size, market_name)
            
        except Exception as e:
            logger.error(f"处理交易失败: {e}")
    
    async def get_market_info(self, market_id):
        """获取市场信息"""
        try:
            market = self.client.get_market(market_id)
            return market
        except Exception as e:
            logger.debug(f"获取市场信息失败 {market_id}: {e}")
            return None
    
    async def execute_copy_trade(self, market_id, side, price, size, market_name):
        """执行跟单交易"""
        try:
            adjusted_price = price * (1 + self.slippage) if side == "buy" else price * (1 - self.slippage)
            
            if self.paper_mode:
                logger.info(f"[模拟交易] {side.upper()} {market_name[:30]}...")
                logger.info(f"  数量: {size:.2f} @ ${adjusted_price:.4f}")
                return {"status": "simulated"}
            else:
                logger.info(f"📤 执行跟单交易...")
                
                trade_side = BUY if side == "buy" else SELL
                
                order_args = OrderArgs(
                    token_id=market_id,
                    price=adjusted_price,
                    size=size,
                    side=trade_side
                )
                
                signed_order = self.client.create_order(order_args)
                response = self.client.post_order(signed_order)
                
                if response and response.get("id"):
                    logger.info(f"✅ 跟单成功！订单ID: {response['id']}")
                    return response
                else:
                    logger.error(f"❌ 跟单失败")
                    return None
                    
        except Exception as e:
            logger.error(f"❌ 执行跟单失败: {e}")
            return None

# ==================== 主程序 ====================
def main():
    print("\n" + "="*60)
    print(" " * 15 + "Polymarket 跟单机器人 (多模式)")
    print("="*60)
    print("功能特点:")
    print("  • 自动查找WebSocket地址")
    print("  • WebSocket实时跟单（如果可用）")
    print("  • REST API轮询跟单（备用方案）")
    print("  • 多地址同时跟单")
    print("  • 模拟/实盘模式")
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
                
                # 选择模式
                print("\n" + "="*60)
                print("选择跟单模式:")
                print("1. WebSocket实时模式（推荐，如果可用）")
                print("2. REST API轮询模式（稳定，但有延迟）")
                print("="*60)
                
                mode = input("请选择模式 (1/2): ").strip()
                
                # 初始化跟单机器人
                targets = [addr.strip() for addr in target_wallets.split(",")]
                
                if mode == "1":
                    print("\n启动WebSocket跟单机器人...")
                    ws_client = PolymarketWebSocketClient(client, targets)
                    asyncio.run(ws_client.run())
                else:
                    print("\n启动REST API跟单机器人...")
                    rest_trader = RESTCopyTrader(client, targets)
                    asyncio.run(rest_trader.run())
                
            except KeyboardInterrupt:
                print("\n用户中断")
            except Exception as e:
                print(f"❌ 启动失败: {e}")
                import traceback
                traceback.print_exc()
        
        elif choice == "4":
            print("测试WebSocket连接...")
            ws_url = asyncio.run(find_websocket_url())
            
            if ws_url:
                print(f"\n✅ 找到可用的WebSocket地址: {ws_url}")
                
                # 保存到配置
                load_dotenv(ENV_FILE)
                set_key(ENV_FILE, "WS_URL", ws_url)
                print("已保存到配置文件中")
                
                # 测试连接
                print("\n测试详细连接...")
                try:
                    async def test_connection():
                        async with websockets.connect(ws_url, timeout=10) as ws:
                            print("✅ 连接成功")
                            
                            # 测试订阅
                            test_msg = json.dumps({"type": "subscribe", "channel": "trades"})
                            await ws.send(test_msg)
                            print("✅ 订阅消息已发送")
                            
                            # 尝试接收数据
                            try:
                                response = await asyncio.wait_for(ws.recv(), timeout=5)
                                print(f"✅ 收到响应: {response[:100]}...")
                            except asyncio.TimeoutError:
                                print("⚠️  未收到响应（可能正常）")
                    
                    asyncio.run(test_connection())
                except Exception as e:
                    print(f"❌ 详细测试失败: {e}")
            else:
                print("\n❌ 未找到可用的WebSocket地址")
                print("建议使用REST API轮询模式")
        
        elif choice == "5":
            # 查看状态
            load_dotenv(ENV_FILE)
            
            print("\n当前配置:")
            print(f"私钥: {os.getenv('PRIVATE_KEY', '未设置')[:20]}...")
            print(f"跟单地址: {os.getenv('TARGET_WALLETS', '未设置')}")
            print(f"WebSocket地址: {os.getenv('WS_URL', '未配置')}")
            print(f"跟单比例: {os.getenv('TRADE_MULTIPLIER', '0.5')}")
            print(f"模拟模式: {os.getenv('PAPER_MODE', 'true')}")
            
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
