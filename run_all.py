import asyncio
import sys
import os

# Add the current directory to sys.path so app and core can be resolved
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

async def start_telegram():
    try:
        from bot.bot import main as tg_main
        print("Starting Telegram Bot task...")
        await tg_main()
    except Exception as e:
        print(f"Telegram Bot error: {e}")
        import traceback
        traceback.print_exc()

async def start_discord():
    try:
        from discord_bot.bot import main as ds_main
        print("Starting Discord Bot task...")
        await ds_main()
    except Exception as e:
        print(f"Discord Bot error: {e}")
        import traceback
        traceback.print_exc()

async def main():
    # Gather both tasks
    await asyncio.gather(
        start_telegram(),
        start_discord()
    )

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Stopped by user.")
