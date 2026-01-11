import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
TEMP_DIR = Path("temp")
COOKIES_DIR = Path("cookies")

# Ensure directories exist
TEMP_DIR.mkdir(exist_ok=True)
COOKIES_DIR.mkdir(exist_ok=True)

if __name__ == '__main__':
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable not set")
    
    logger.info("🚀 Starting YouTube Downloader Bot...")
    logger.info(f"📁 Temp directory: {TEMP_DIR}")
    logger.info(f"🍪 Cookies directory: {COOKIES_DIR}")
    
    # Import and run the bot
    from bot import main
    
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        raise
