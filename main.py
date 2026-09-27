import asyncio
import logging
import signal
import sys

from src.core.config import config
from src.core.database import db
from src.clients.discord_client import DiscordClient
from src.clients.telegram_client import TelegramClient
from src.services.mirror_service import MirrorService
from src.services.digest_service import digest_service

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
# Silence voice warnings since announcement bots do not require voice dependencies
logging.getLogger("discord.client").setLevel(logging.ERROR)

logger = logging.getLogger("DiscordTelegramMirror")

def main():
    # Validate environment variables before connecting
    config.validate(exit_on_error=True)

    telegram_client = TelegramClient(config.telegram_bot_token)
    discord_client = DiscordClient()
    mirror_service = MirrorService(discord_client, telegram_client, db)
    
    discord_client.set_mirror_service(mirror_service)
    digest_service.set_telegram_client(telegram_client)

    def handle_shutdown(signum, frame):
        logger.info("Shutdown signal received. Shutting down gracefully...")
        if discord_client.is_closed():
            return
        try:
            loop = discord_client.loop
            if loop and loop.is_running():
                loop.create_task(discord_client.close())
            else:
                asyncio.create_task(discord_client.close())
        except Exception as e:
            logger.warning(f"Error scheduling bot shutdown: {e}")

    signal.signal(signal.SIGINT, handle_shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handle_shutdown)

    logger.info("Starting Discord to Telegram Announcement Bot...")
    try:
        discord_client.run(config.discord_bot_token, log_handler=None)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.critical(f"Bot crashed with error: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
