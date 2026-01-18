#!/usr/bin/env python3
import asyncio
import aiohttp
import json
import os
import base58
from datetime import datetime
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from loguru import logger
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import Transaction
from solana.rpc.async_api import AsyncClient

BOT_TOKEN = "7901758242:AAGx7wzUi0o_bVMmZz8UYITdVSQe0BaDGVA"  # TUO
CONFIG_FILE = "config/trading.json"
JUPITER_QUOTE = "https://104.18.43.103/v6/quote"  # IP + SSL bypass
JUPITER_SWAP = "https://104.18.43.103/v6/swap"

logger.add("logs/bot.log", rotation="1 day")
config = {}
wallet = None
trading_active = False
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
client = None

async def load_config():
    global config, wallet, client
    try:
        os.makedirs("config", exist_ok=True)
        os.makedirs("logs", exist_ok=True)
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
        else:
            config = {"rpc": "https://api.mainnet-beta.solana.com", "slippage": 0.5, "wallet_private_key": ""}
            with open(CONFIG_FILE, 'w') as f:
                json.dump(config, f)
        private_key_str = config.get("wallet_private_key", "")
        if private_key_str:
            keypair_bytes = base58.b58decode(private_key_str)
            wallet = Keypair.from_bytes(keypair_bytes)
            logger.info(f"✅ Wallet: {wallet.pubkey()}")
        client = AsyncClient(config["rpc"])
    except Exception as e:
        logger.error(f"Config error: {e}")

async def get_quote(input_mint, output_mint, amount):
connector = aiohttp.TCPConnector(ssl=False)
    timeout = aiohttp.ClientTimeout(total=30)
    try:
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            params = {
                "inputMint": input_mint,
                "outputMint": output_mint,
                "amount": amount,
                "slippageBps": int(config["slippage"] * 100)
            }
            async with session.get(JUPITER_QUOTE, params=params) as resp:
                resp.raise_for_status()
                return await resp.json()
    except Exception as e:
        logger.error(f"Quote error: {e}")
        raise

async def execute_swap(user_amount_sol):
    try:
        amount_lamports = int(user_amount_sol * 10**9)
        quote = await get_quote("So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", amount_lamports)
        swap_req = {"quoteResponse": quote, "userPublicKey": str(wallet.pubkey()), "wrapAndUnwrapSol": True}
        connector = aiohttp.TCPConnector(ssl=False)
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            async with session.post(JUPITER_SWAP, json=swap_req) as resp:
                resp.raise_for_status()
                swap_data = await resp.json()
                swap_tx_b58 = swap_data["swapTransaction"]
                swap_tx = base58.b58decode(swap_tx_b58)
                tx = Transaction.deserialize(swap_tx)
                tx.sign(wallet)
                result = await client.send_transaction(tx)
                tx_sig = result.value
                logger.info(f"✅ Swap TX: https://solscan.io/tx/{tx_sig}")
                return f"✅ SWAP {user_amount_sol} SOL → USDC!\nTX: https://solscan.io/tx/{tx_sig}"
    except Exception as e:
        logger.error(f"Swap error: {e}")
        return f"❌ Swap failed: {str(e)[:100]}"

@dp.message(Command("start"))
async def start_handler(message: Message):
    await message.answer("🚀 LasveTraderBot v6.1 JUPITER SWAPPER IP+SSL!\n/status /startbot /buy")

@dp.message(Command("status"))
async def status_handler(message: Message):
    status = "ATTIVO" if trading_active else "FERMATO"
    wallet_info = f"Wallet: {wallet.pubkey()}" if wallet else "No wallet"
    await message.answer(f"{wallet_info}\nTrading: {status}")

@dp.message(Command("startbot"))
async def start_bot(message: Message):
    global trading_active
    trading_active = True
    await message.answer("✅ Trading ATTIVO")

@dp.message(Command("stopbot"))
async def stop_bot(message: Message):
    global trading_active
    trading_active = False
    await message.answer("🛑 Trading FERMATO")

@dp.message(Command("buy"))
async def buy_handler(message: Message):
    if not trading_active:
        await message.answer("❌ Trading FERMATO. /startbot")
        return
    if not wallet:
        await message.answer("❌ Aggiungi wallet_private_key in config/trading.json")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="0.01 SOL → USDC", callback_data="buy_0.01")],
        [InlineKeyboardButton(text="0.05 SOL → USDC", callback_data="buy_0.05")]
    ])
    await message.answer("💰 Seleziona:", reply_markup=keyboard)

@dp.callback_query(lambda c: c.data.startswith("buy_"))
async def process_buy(callback: CallbackQuery):
    amount = float(callback.data.split("_")[1])
    await callback.message.edit_text("⏳ Swappando...")
    result = await execute_swap(amount)
    await callback.message.edit_text(result)
    await callback.answer()

async def main():
    await load_config()
    logger.info("🚀 LasveTraderBot v6.1 READY")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
