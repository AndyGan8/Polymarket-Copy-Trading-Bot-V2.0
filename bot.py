import os
import sys
import subprocess
import time
import json
import logging
import requests
from datetime import datetime
from dotenv import load_dotenv, set_key
from web3 import AsyncWeb3, Web3
from web3.providers.persistent import WebSocketProvider
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs
from py_clob_client.order_builder.constants import BUY, SELL
import asyncio

# ==================== 依赖列表 ====================
REQUIREMENTS = [
    "py-clob-client>=0.34.0",
    "websocket-client>=1.8.0",
    "python-dotenv>=1.0.0",
    "web3>=7.0.0",
    "requests>=2.28.0"
]

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

# ==================== 常量 ====================
ENV_FILE = ".env"
CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID = 137

CTF_EXCHANGE = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
NEGRISK_EXCHANGE = "0xC5d563A36AE78145C45a50134d48A1215220f80a"

ORDER_FILLED_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "orderHash", "type": "bytes32"},
            {"indexed": True, "name": "maker", "type": "address"},
            {"indexed": True, "name": "taker", "type": "address"},
            {"indexed": False, "name": "makerAssetId", "type": "uint256"},
            {"indexed": False, "name": "takerAssetId", "type": "uint256"},
            {"indexed": False, "name": "makerAmountFilled", "type": "uint256"},
            {"indexed": False, "name": "takerAmountFilled", "type": "uint256"},
            {"indexed": False, "name": "fee", "type": "uint256"}
        ],
        "name": "OrderFilled",
        "type": "event"
    }
]

TOKEN_MAP = {}
processed_hashes = set()

# ==================== 主菜单 ====================
def show_menu():
    print("\n" + "="*60)
    print(" " * 15 + "Polymarket 跟单机器人 V2.2 (最终修复版)")
    print("="*60)
    print("1. 检查环境并自动安装依赖")
    print("2. 配置密钥、RPC、跟单地址等（首次必做）")
    print("3. 启动跟单机器人（只跟输入地址）")
    print("4. 查看当前配置")
    print("5. 查看监听状态和跟单情况")
    print("6. 退出")
    return input("\n请输入选项 (1-6): ").strip()

# ==================== 选项1：检查&安装依赖 ====================
def check_and_install_dependencies():
    logger.info("检查 Python 环境与依赖...")
    try:
        import pkg_resources
        installed = {pkg.key: pkg.version for pkg in pkg_resources.working_set}
    except:
        result = subprocess.run(["pip", "list", "--format=freeze"], capture_output=True, text=True)
        installed = dict(line.split('==') for line in result.stdout.splitlines() if '==' in line)

    missing = [req for req in REQUIREMENTS if req.split('>=')[0].strip().lower() not in installed]

    if missing:
        logger.info(f"缺少依赖: {', '.join(missing)}")
        if input("是否自动安装缺失依赖？(y/n): ").strip().lower() == 'y':
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing)
                logger.info("依赖安装完成！")
                print("依赖安装完成，请重新运行脚本或继续操作。")
            except Exception as e:
                logger.error(f"安装失败: {e}\n请手动运行: pip install {' '.join(missing)}")
        else:
            logger.warning("请手动安装依赖后再继续。")
    else:
        logger.info("所有必要依赖已安装 ✓")
        print("所有依赖已就位，无需安装。")

# ==================== 选项2：配置引导 ====================
def setup_config():
    if not os.path.exists(ENV_FILE):
        open(ENV_FILE, 'a').close()

    load_dotenv(ENV_FILE)

    while True:
        print("\n" + "="*50)
        print("配置选单")
        print("="*50)
        print("1. 填写/修改 必须参数（私钥、目标地址、RPC）")
        print("2. 填写/修改 可选参数（跟单比例、金额限制、模拟模式）")
        print("3. 返回主选单")
        sub_choice = input("\n请选择 (1-3): ").strip()

        if sub_choice == "3":
            break

        if sub_choice == "1":
            must_have = [
                ("PRIVATE_KEY", "你的钱包私钥（0x开头，64字符）"),
                ("TARGET_WALLETS", "跟单目标地址（逗号分隔，如: 0x123...,0x456...）"),
                ("RPC_URL", "Polygon WebSocket RPC（必须wss://开头）")
            ]
            for key, desc in must_have:
                current = os.getenv(key, "未设置")
                if key == "PRIVATE_KEY" and current != "未设置":
                    display = current[:10] + "..." + current[-10:] if len(current) > 20 else current
                else:
                    display = current
                print(f"\n当前 {key}: {display}")
                value = input(f"{desc}\n输入新值: ").strip()
                if value:
                    set_key(ENV_FILE, key, value)
                    os.environ[key] = value
                    print(f"{key} 已更新！")

        elif sub_choice == "2":
            optional_params = [
                ("TRADE_MULTIPLIER", "跟单比例（默认0.35，范围0.01-1.0）"),
                ("MAX_POSITION_USD", "最大单笔金额USD（默认150）"),
                ("MIN_TRADE_USD", "最小单笔金额USD（默认20）"),
                ("PAPER_MODE", "模拟模式（true/false，默认true）"),
                ("SLIPPAGE_TOLERANCE", "滑点容忍度（默认0.02，即2%）")
            ]
            
            for key, desc in optional_params:
                current = os.getenv(key)
                print(f"\n当前 {key}: {current if current else '未设置（使用默认值）'}")
                value = input(f"{desc}\n输入新值（留空保持默认）: ").strip()
                if value:
                    set_key(ENV_FILE, key, value)
                    os.environ[key] = value
                    print(f"{key} 已更新！")

        else:
            print("无效选项，请输入1-3")

def view_config():
    load_dotenv(ENV_FILE)
    print("\n" + "="*50)
    print("当前配置")
    print("="*50)
    keys = ["PRIVATE_KEY", "RPC_URL", "TARGET_WALLETS", "TRADE_MULTIPLIER", 
            "MAX_POSITION_USD", "MIN_TRADE_USD", "PAPER_MODE", "SLIPPAGE_TOLERANCE"]
    
    for k in keys:
        v = os.getenv(k, "未设置")
        if k == "PRIVATE_KEY" and v != "未设置":
            v = v[:10] + "..." + v[-10:] if len(v) > 20 else "****"
        elif k == "RPC_URL" and v != "未设置":
            v = v[:40] + "..." if len(v) > 40 else v
        print(f"{k:20}: {v}")

def view_wallet_info():
    load_dotenv(ENV_FILE)
    print("\n" + "="*50)
    print("监听状态和跟单情况")
    print("="*50)

    try:
        if not os.path.exists("bot.log"):
            print("日志文件不存在，暂无记录")
            print("\n按回车返回...")
            input()
            return
            
        with open("bot.log", "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        if not lines:
            print("日志文件为空")
            print("\n按回车返回...")
            input()
            return
            
        last_lines = lines[-50:]
        log_tail = ''.join(last_lines)
        
        # 分析状态
        status = "未启动"
        ws_status = "未连接"
        
        for line in lines[-20:]:
            if "启动跟单监控" in line and "成功" not in line:
                status = "启动中"
            elif "WebSocket 连接成功" in line:
                ws_status = "正常"
                status = "运行中"
            elif "开始轮询监听" in line:
                status = "运行中"
            elif "连接失败" in line or "断开" in line:
                ws_status = "失败"
        
        print(f"监听状态: {status}")
        print(f"WebSocket 连接: {ws_status}")
        
        targets = os.getenv("TARGET_WALLETS", "未设置")
        if targets != "未设置":
            target_list = targets.split(",")
            print(f"\n监听目标地址 ({len(target_list)}个):")
            for i, addr in enumerate(target_list[:3], 1):
                print(f"  {i}. {addr}")
            if len(target_list) > 3:
                print(f"  ... 还有 {len(target_list)-3} 个地址")
        
        print("\n最近活动：")
        recent_activity = []
        for line in lines[-100:]:
            if "检测到目标" in line or "准备跟单" in line or "下单成功" in line or "下单失败" in line:
                recent_activity.append(line.strip())
        
        if recent_activity:
            for i, activity in enumerate(recent_activity[-5:], 1):
                print(f"  {activity}")
            if len(recent_activity) > 5:
                print(f"  ... 还有 {len(recent_activity)-5} 条记录")
        else:
            print("  暂无活动记录")
        
        print(f"\n已处理事件哈希数: {len(processed_hashes)}")

    except Exception as e:
        print(f"读取失败: {e}")

    print("\n按回车返回主菜单...")
    input()

def ensure_api_creds(client):
    load_dotenv(ENV_FILE)
    if all(os.getenv(k) for k in ["API_KEY", "API_SECRET", "API_PASSPHRASE"]):
        client.set_api_creds({
            "api_key": os.getenv("API_KEY"),
            "api_secret": os.getenv("API_SECRET"),
            "api_passphrase": os.getenv("API_PASSPHRASE")
        })
        return True

    logger.info("生成 API Credentials...")
    try:
        creds = client.create_or_derive_api_creds()
        set_key(ENV_FILE, "API_KEY", creds.api_key)
        set_key(ENV_FILE, "API_SECRET", creds.api_secret)
        set_key(ENV_FILE, "API_PASSPHRASE", creds.api_passphrase)
        logger.info("API 凭证生成成功！")
        return True
    except Exception as e:
        logger.error(f"生成失败: {e}")
        return False

# ==================== 事件处理函数 ====================
async def handle_event(event, target_set, client):
    """处理 OrderFilled 事件"""
    try:
        order_hash = event['args']['orderHash'].hex() if hasattr(event['args']['orderHash'], 'hex') else event['args']['orderHash']
        
        if order_hash in processed_hashes:
            return
        
        processed_hashes.add(order_hash)

        maker = event['args']['maker'].lower()
        taker = event['args']['taker'].lower()

        if maker in target_set or taker in target_set:
            wallet = maker if maker in target_set else taker
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            maker_asset = event['args']['makerAssetId']
            taker_asset = event['args']['takerAssetId']
            maker_amt = event['args']['makerAmountFilled'] / 1e6
            taker_amt = event['args']['takerAmountFilled'] / 1e6

            if maker_asset == 0:
                side = BUY
                price = maker_amt / taker_amt if taker_amt > 0 else 0
                usd_value = maker_amt
                pos_id = taker_asset
            else:
                side = SELL
                price = taker_amt / maker_amt if maker_amt > 0 else 0
                usd_value = taker_amt
                pos_id = maker_asset

            logger.info(f"📊 检测到目标 {wallet[:10]}... 成交！")
            logger.info(f"  时间: {ts} | 方向: {side} | 价格: {price:.4f} | USD: {usd_value:.2f}")
            logger.info(f"  市场ID: {pos_id}")

            multiplier = float(os.getenv("TRADE_MULTIPLIER", "0.35"))
            copy_usd = usd_value * multiplier
            min_trade = float(os.getenv("MIN_TRADE_USD", "20"))
            max_trade = float(os.getenv("MAX_POSITION_USD", "150"))
            
            if copy_usd < min_trade:
                logger.warning(f"💰 金额 {copy_usd:.2f} USD 小于最小限制 {min_trade} USD，跳过")
                return
            if copy_usd > max_trade:
                logger.warning(f"💰 金额 {copy_usd:.2f} USD 大于最大限制 {max_trade} USD，跳过")
                return

            size = copy_usd / price if price > 0 else 0
            
            if size <= 0:
                logger.warning(f"⚠️  计算出的交易大小为0，跳过")
                return

            mode = "模拟" if os.getenv("PAPER_MODE", "true").lower() == "true" else "真实"
            logger.info(f"🎯 [{mode}] 准备跟单: {side} {size:.2f} 份 @ {price:.4f}")

            if mode == "真实":
                try:
                    slippage = float(os.getenv("SLIPPAGE_TOLERANCE", "0.02"))
                    adj_price = price * (1 + slippage) if side == BUY else price * (1 - slippage)
                    
                    # 这里需要实际的 token_id，暂时使用占位符
                    token_id = f"0x{pos_id:064x}"
                    
                    order_args = OrderArgs(
                        token_id=token_id, 
                        price=adj_price, 
                        size=size, 
                        side=side
                    )
                    signed = client.create_order(order_args)
                    resp = client.post_order(signed)
                    logger.info(f"✅ 下单成功！订单ID: {resp.get('id', '未知')}")
                except Exception as e:
                    logger.error(f"❌ 下单失败: {e}")
    except Exception as e:
        logger.error(f"处理事件时出错: {e}")

# ==================== 修复的轮询监听函数 ====================
async def poll_order_filled(w3: AsyncWeb3, contract_address, target_set, client, last_block):
    """轮询监听 OrderFilled 事件 - 修复十六进制前缀问题"""
    logger.info(f"🔍 开始监听合约 {contract_address[:10]}...")
    
    # 预计算事件签名
    event_signature = Web3.keccak(text="OrderFilled(bytes32,address,address,uint256,uint256,uint256,uint256,uint256)").hex()
    
    error_count = 0
    max_errors = 3
    
    while True:
        try:
            # 获取当前区块
            try:
                current_block = await w3.eth.block_number
            except Exception as e:
                logger.error(f"获取区块高度失败: {e}")
                await asyncio.sleep(5)
                continue
            
            if current_block <= last_block:
                await asyncio.sleep(2)
                continue
            
            # 计算查询范围（每次最多查询5个区块，避免限制）
            from_block = last_block + 1
            to_block = min(from_block + 5, current_block)
            
            # 如果范围太小，稍等一会儿
            if to_block <= from_block:
                await asyncio.sleep(2)
                continue
            
            logger.debug(f"📦 查询 {contract_address[:10]}... 区块 {from_block} 到 {to_block}")
            
            try:
                # 关键修复：使用 web3.py 的 to_hex 方法确保正确的十六进制格式
                from_block_hex = w3.to_hex(from_block)
                to_block_hex = w3.to_hex(to_block)
                
                # 方法1：使用正确的十六进制格式
                logs = await w3.eth.get_logs({
                    'address': Web3.to_checksum_address(contract_address),
                    'fromBlock': from_block_hex,  # 使用十六进制字符串
                    'toBlock': to_block_hex,      # 使用十六进制字符串
                    'topics': [event_signature]
                })
                
                if logs:
                    logger.info(f"🎉 在 {contract_address[:10]}... 发现 {len(logs)} 个新事件")
                    
                    # 处理日志
                    for log in logs:
                        try:
                            # 解析事件数据
                            event_data = {
                                'args': {
                                    'orderHash': log['topics'][1],
                                    'maker': '0x' + log['topics'][2].hex()[-40:],
                                    'taker': '0x' + log['topics'][3].hex()[-40:],
                                    'makerAssetId': int.from_bytes(log['data'][0:32], 'big'),
                                    'takerAssetId': int.from_bytes(log['data'][32:64], 'big'),
                                    'makerAmountFilled': int.from_bytes(log['data'][64:96], 'big'),
                                    'takerAmountFilled': int.from_bytes(log['data'][96:128], 'big'),
                                    'fee': int.from_bytes(log['data'][128:160], 'big')
                                }
                            }
                            
                            await handle_event(event_data, target_set, client)
                            
                        except Exception as e:
                            logger.error(f"解析日志失败: {e}")
                
                # 成功处理，重置错误计数
                error_count = 0
                last_block = to_block
                
            except Exception as e:
                error_count += 1
                error_msg = str(e)
                
                if "hex string without 0x prefix" in error_msg:
                    logger.warning(f"🔄 十六进制格式问题，尝试不同方法...")
                    
                    # 尝试不同方法
                    for method in range(3):
                        try:
                            if method == 0:
                                # 方法1：使用整数（让web3内部处理转换）
                                logs = await w3.eth.get_logs({
                                    'address': contract_address,
                                    'fromBlock': from_block,  # 整数
                                    'toBlock': to_block,      # 整数
                                    'topics': [event_signature]
                                })
                            elif method == 1:
                                # 方法2：使用'latest'
                                logs = await w3.eth.get_logs({
                                    'address': contract_address,
                                    'fromBlock': from_block,
                                    'toBlock': 'latest',
                                    'topics': [event_signature]
                                })
                            elif method == 2:
                                # 方法3：使用 web3.py 的 BlockNumber 对象
                                logs = await w3.eth.get_logs({
                                    'address': contract_address,
                                    'fromBlock': w3.eth.get_block(from_block).number,
                                    'toBlock': w3.eth.get_block(to_block).number,
                                    'topics': [event_signature]
                                })
                            
                            if logs:
                                logger.info(f"方法{method+1}查询到 {len(logs)} 个事件")
                            
                            for log in logs:
                                try:
                                    event_data = {
                                        'args': {
                                            'orderHash': log['topics'][1],
                                            'maker': '0x' + log['topics'][2].hex()[-40:],
                                            'taker': '0x' + log['topics'][3].hex()[-40:],
                                            'makerAssetId': int.from_bytes(log['data'][0:32], 'big'),
                                            'takerAssetId': int.from_bytes(log['data'][32:64], 'big'),
                                            'makerAmountFilled': int.from_bytes(log['data'][64:96], 'big'),
                                            'takerAmountFilled': int.from_bytes(log['data'][96:128], 'big'),
                                            'fee': int.from_bytes(log['data'][128:160], 'big')
                                        }
                                    }
                                    
                                    await handle_event(event_data, target_set, client)
                                    
                                except Exception as e:
                                    logger.error(f"解析日志失败: {e}")
                            
                            error_count = 0
                            last_block = to_block
                            break  # 方法成功，跳出循环
                            
                        except Exception as e2:
                            logger.debug(f"方法{method+1}失败: {e2}")
                            continue
                    
                    # 如果所有方法都失败
                    if error_count > 0:
                        logger.error(f"所有查询方法都失败了")
                
                elif "invalid block range" in error_msg.lower():
                    logger.warning(f"📏 区块范围无效，尝试单区块查询")
                    
                    # 只查询1个区块
                    try:
                        logs = await w3.eth.get_logs({
                            'address': contract_address,
                            'fromBlock': from_block,
                            'toBlock': from_block,
                            'topics': [event_signature]
                        })
                        
                        if logs:
                            logger.info(f"单区块查询到 {len(logs)} 个事件")
                        
                        for log in logs:
                            try:
                                event_data = {
                                    'args': {
                                        'orderHash': log['topics'][1],
                                        'maker': '0x' + log['topics'][2].hex()[-40:],
                                        'taker': '0x' + log['topics'][3].hex()[-40:],
                                        'makerAssetId': int.from_bytes(log['data'][0:32], 'big'),
                                        'takerAssetId': int.from_bytes(log['data'][32:64], 'big'),
                                        'makerAmountFilled': int.from_bytes(log['data'][64:96], 'big'),
                                        'takerAmountFilled': int.from_bytes(log['data'][96:128], 'big'),
                                        'fee': int.from_bytes(log['data'][128:160], 'big')
                                    }
                                }
                                
                                await handle_event(event_data, target_set, client)
                                
                            except Exception as e:
                                logger.error(f"解析日志失败: {e}")
                        
                        error_count = 0
                        last_block = from_block
                        
                    except Exception as e2:
                        logger.error(f"单区块查询失败: {e2}")
                else:
                    logger.error(f"查询日志失败: {error_msg}")
                
                # 如果连续失败，跳过这个区块范围
                if error_count >= max_errors:
                    logger.warning(f"⚠️  连续 {error_count} 次失败，跳过区块 {from_block}-{to_block}")
                    last_block = to_block
                    error_count = 0
            
            await asyncio.sleep(3)  # 每3秒轮询一次
            
        except asyncio.CancelledError:
            logger.info("监听任务被取消")
            break
        except Exception as e:
            logger.error(f"轮询主循环异常: {e}")
            await asyncio.sleep(5)

# ==================== 简化版本（如果上述方法仍有问题） ====================
async def poll_order_filled_simple(w3: AsyncWeb3, contract_address, target_set, client, last_block):
    """简化版本的轮询监听 - 避免复杂的参数转换"""
    logger.info(f"🔍 [简化版] 开始监听合约 {contract_address[:10]}...")
    
    # 预计算事件签名
    event_signature = Web3.keccak(text="OrderFilled(bytes32,address,address,uint256,uint256,uint256,uint256,uint256)").hex()
    
    # 创建合约对象用于解析事件
    contract = w3.eth.contract(address=Web3.to_checksum_address(contract_address), abi=ORDER_FILLED_ABI)
    
    while True:
        try:
            # 获取当前区块
            current_block = await w3.eth.block_number
            
            if current_block <= last_block:
                await asyncio.sleep(3)
                continue
            
            # 每次只查询1个区块，避免复杂参数问题
            query_block = last_block + 1
            
            if query_block > current_block:
                await asyncio.sleep(3)
                continue
            
            logger.debug(f"📦 查询 {contract_address[:10]}... 区块 {query_block}")
            
            try:
                # 使用最简单的方式查询
                logs = await contract.events.OrderFilled.get_logs(
                    fromBlock=query_block,
                    toBlock=query_block
                )
                
                if logs:
                    logger.info(f"🎉 在 {contract_address[:10]}... 发现 {len(logs)} 个新事件")
                    
                    for event in logs:
                        await handle_event(event, target_set, client)
                
                # 更新最后处理的区块
                last_block = query_block
                
            except Exception as e:
                logger.error(f"查询事件失败: {e}")
                
                # 尝试使用原始 get_logs
                try:
                    logs = await w3.eth.get_logs({
                        'address': contract_address,
                        'fromBlock': query_block,
                        'toBlock': query_block,
                        'topics': [event_signature]
                    })
                    
                    if logs:
                        logger.info(f"使用原始查询发现 {len(logs)} 个事件")
                        
                        for log in logs:
                            try:
                                event = contract.events.OrderFilled().process_log(log)
                                await handle_event(event, target_set, client)
                            except Exception as e2:
                                logger.error(f"处理原始日志失败: {e2}")
                    
                    last_block = query_block
                    
                except Exception as e2:
                    logger.error(f"原始查询也失败: {e2}")
                    
                    # 如果连续失败，直接跳到当前区块
                    if last_block < current_block - 10:
                        logger.warning(f"跳过 {current_block - last_block} 个区块")
                        last_block = current_block
            
            await asyncio.sleep(2)
            
        except asyncio.CancelledError:
            logger.info("监听任务被取消")
            break
        except Exception as e:
            logger.error(f"轮询异常: {e}")
            await asyncio.sleep(5)

# ==================== 异步监控主函数 ====================
async def monitor_target_trades_async(client):
    """主监控函数"""
    load_dotenv(ENV_FILE)
    
    # 检查必要配置
    required_configs = ["PRIVATE_KEY", "TARGET_WALLETS", "RPC_URL"]
    missing = [key for key in required_configs if not os.getenv(key)]
    
    if missing:
        logger.error(f"❌ 缺少必要配置: {', '.join(missing)}")
        logger.error("请先运行选项2进行配置")
        return
    
    target_wallets = [addr.strip().lower() for addr in os.getenv("TARGET_WALLETS", "").split(",") if addr.strip()]
    if not target_wallets:
        logger.error("❌ TARGET_WALLETS 配置为空")
        return
    
    rpc_url = os.getenv("RPC_URL", "").strip()
    if not rpc_url.startswith("wss://"):
        logger.error(f"❌ RPC_URL 必须以 wss:// 开头！当前: {rpc_url}")
        return
    
    target_set = set(target_wallets)
    logger.info("="*60)
    logger.info("🚀 启动跟单监控")
    logger.info(f"📡 RPC: {rpc_url[:50]}...")
    logger.info(f"🎯 目标地址 ({len(target_wallets)}个):")
    for i, addr in enumerate(target_wallets[:3], 1):
        logger.info(f"    {i}. {addr}")
    if len(target_wallets) > 3:
        logger.info(f"    ... 还有 {len(target_wallets)-3} 个地址")
    logger.info("="*60)
    
    try:
        # 创建 Web3 连接
        logger.info(f"🔗 连接至 RPC...")
        w3 = AsyncWeb3(WebSocketProvider(rpc_url))
        
        # 测试连接
        logger.info("🔄 测试连接...")
        connected = await w3.is_connected()
        
        if not connected:
            logger.error("❌ WebSocket 连接失败")
            return
        
        logger.info("✅ WebSocket 连接成功！")
        
        # 获取当前区块
        try:
            current_block = await w3.eth.block_number
            start_block = max(current_block - 50, 0)
            logger.info(f"📦 当前区块: {current_block}，从区块 {start_block} 开始监听")
        except Exception as e:
            logger.error(f"获取区块高度失败: {e}")
            start_block = 0
        
        # 询问使用哪个版本
        print("\n" + "="*60)
        print("选择监听模式:")
        print("1. 标准模式 (推荐，使用修复的查询方法)")
        print("2. 简化模式 (如果标准模式有问题)")
        print("="*60)
        
        mode_choice = input("请选择模式 (1/2): ").strip()
        
        # 创建监听任务
        logger.info("👂 开始监听事件...")
        
        if mode_choice == "2":
            logger.info("使用简化监听模式")
            tasks = [
                asyncio.create_task(poll_order_filled_simple(w3, CTF_EXCHANGE, target_set, client, start_block)),
                asyncio.create_task(poll_order_filled_simple(w3, NEGRISK_EXCHANGE, target_set, client, start_block))
            ]
        else:
            logger.info("使用标准监听模式")
            tasks = [
                asyncio.create_task(poll_order_filled(w3, CTF_EXCHANGE, target_set, client, start_block)),
                asyncio.create_task(poll_order_filled(w3, NEGRISK_EXCHANGE, target_set, client, start_block))
            ]
        
        # 等待所有任务完成
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("监控任务被取消")
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            logger.error(f"监控任务异常: {e}")
        
    except Exception as e:
        logger.critical(f"🚨 监控启动失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        logger.info("监控结束")

# ==================== 主程序 ====================
def main():
    print("\n" + "="*60)
    print(" " * 15 + "Polymarket 跟单机器人 V2.2 (最终修复版)")
    print("="*60)
    print("说明：")
    print("  1. 首次使用请先运行选项2配置必要参数")
    print("  2. 需要准备一个 burner 钱包和 Polygon RPC")
    print("  3. 支持同时跟单多个地址")
    print("  4. 提供两种监听模式解决十六进制前缀问题")
    print("="*60)
    
    while True:
        choice = show_menu()

        if choice == "1":
            check_and_install_dependencies()

        elif choice == "2":
            setup_config()

        elif choice == "3":
            # 检查配置文件是否存在
            if not os.path.exists(ENV_FILE):
                logger.error("❌ 配置文件 .env 不存在")
                print("请先运行选项2进行配置")
                continue
            
            load_dotenv(ENV_FILE)
            
            # 验证必要配置
            required = ["PRIVATE_KEY", "TARGET_WALLETS", "RPC_URL"]
            missing = [r for r in required if not os.getenv(r)]
            
            if missing:
                logger.error(f"❌ 缺少必要配置: {', '.join(missing)}")
                print("请先运行选项2进行配置")
                continue
            
            # 验证私钥格式
            private_key = os.getenv("PRIVATE_KEY", "")
            if not private_key.startswith("0x") or len(private_key) != 66:
                logger.error("❌ 私钥格式不正确，应为0x开头的64字符十六进制")
                continue
            
            # 验证RPC格式
            rpc_url = os.getenv("RPC_URL", "")
            if not rpc_url.startswith("wss://"):
                logger.error("❌ RPC_URL 必须是以 wss:// 开头的WebSocket地址")
                continue
            
            try:
                logger.info("初始化 CLOB 客户端...")
                client = ClobClient(CLOB_HOST, key=private_key, chain_id=CHAIN_ID)
                
                logger.info("检查/生成 API 凭证...")
                if not ensure_api_creds(client):
                    logger.error("API 凭证处理失败")
                    continue
                
                logger.info("✅ 所有配置检查通过！")
                
                # 启动监控
                print("\n" + "="*60)
                print("跟单机器人启动中...")
                print("按 Ctrl+C 停止")
                print("="*60)
                
                try:
                    asyncio.run(monitor_target_trades_async(client))
                except KeyboardInterrupt:
                    logger.info("用户中断监控")
                
            except Exception as e:
                logger.error(f"启动失败: {e}")

        elif choice == "4":
            view_config()

        elif choice == "5":
            view_wallet_info()

        elif choice == "6":
            logger.info("👋 退出程序")
            sys.exit(0)

        else:
            print("❌ 无效选项，请输入1-6")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n👋 用户中断，程序退出")
    except Exception as e:
        logger.critical(f"🚨 严重错误: {e}", exc_info=True)
