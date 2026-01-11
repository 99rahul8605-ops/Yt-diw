import os
import re
import logging
import asyncio
import tempfile
import shutil
import json
import aiohttp
from pathlib import Path
from typing import List, Optional, Dict
from datetime import datetime
from urllib.parse import urlparse

import yt_dlp
from telegram import Update, InputFile, Message
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ChatAction
from telegram.error import NetworkError, TelegramError

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class YouTubeDownloaderBot:
    def __init__(self, token: str):
        self.token = token
        self.temp_dir = Path("temp_downloads")
        self.temp_dir.mkdir(exist_ok=True)
        
        # User agents to rotate to avoid detection
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
        ]
        
        # Configure yt-dlp with anti-bot measures
        self.ydl_opts = {
            'quiet': False,
            'no_warnings': False,
            'extract_flat': False,
            'force_generic_extractor': False,
            'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]',
            'merge_output_format': 'mp4',
            'outtmpl': str(self.temp_dir / '%(title).100s.%(ext)s'),
            'ffmpeg_location': shutil.which('ffmpeg'),
            'progress_hooks': [self.progress_hook],
            
            # Anti-bot configuration
            'verbose': True,
            'ignoreerrors': True,
            'no_check_certificate': True,
            'prefer_insecure': False,
            'user_agent': self.user_agents[0],
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web'],
                    'player_skip': ['configs', 'webpage'],
                }
            },
            'postprocessor_args': {
                'ffmpeg': ['-hide_banner', '-loglevel', 'warning']
            },
            'http_headers': {
                'User-Agent': self.user_agents[0],
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Cache-Control': 'max-age=0',
            },
            
            # Retry configuration
            'retries': 10,
            'fragment_retries': 10,
            'skip_unavailable_fragments': True,
            'keep_fragments': False,
            'concurrent_fragment_downloads': 4,
            
            # Throttling to avoid rate limiting
            'sleep_interval_requests': 1,
            'sleep_interval': 5,
            'max_sleep_interval': 30,
            'sleep_interval_subtitles': 1,
        }
        
        # Optional: Use aria2c for faster downloads
        if shutil.which('aria2c'):
            self.ydl_opts['external_downloader'] = 'aria2c'
            self.ydl_opts['external_downloader_args'] = [
                '--max-connection-per-server=16',
                '--split=16',
                '--min-split-size=1M',
                '--max-tries=20',
                '--retry-wait=5',
                '--timeout=30',
            ]
        
        # Load cookies if available
        cookies_file = Path('cookies.txt')
        if cookies_file.exists():
            self.ydl_opts['cookiefile'] = str(cookies_file)
            logger.info("Using cookies from cookies.txt")
    
    def progress_hook(self, d):
        """Callback for download progress"""
        if d['status'] == 'downloading':
            percent = d.get('_percent_str', '0%').strip()
            speed = d.get('_speed_str', 'N/A')
            eta = d.get('_eta_str', 'N/A')
            logger.info(f"Downloading: {percent} at {speed}, ETA: {eta}")
    
    def sanitize_filename(self, filename: str) -> str:
        """Remove invalid characters from filename"""
        # Remove invalid filename characters
        filename = re.sub(r'[<>:"/\\|?*]', '', filename)
        # Limit length
        if len(filename) > 100:
            filename = filename[:97] + "..."
        return filename.strip()
    
    def is_valid_youtube_url(self, url: str) -> bool:
        """Validate YouTube URL"""
        youtube_patterns = [
            r'(https?://)?(www\.)?youtube\.com/watch\?v=[\w-]+',
            r'(https?://)?(www\.)?youtube\.com/embed/[\w-]+',
            r'(https?://)?(www\.)?youtu\.be/[\w-]+',
            r'(https?://)?(www\.)?youtube\.com/playlist\?list=[\w-]+',
            r'(https?://)?(www\.)?youtube\.com/shorts/[\w-]+',
        ]
        
        for pattern in youtube_patterns:
            if re.match(pattern, url):
                return True
        return False
    
    def extract_urls_from_text(self, text: str) -> List[str]:
        """Extract URLs from text message"""
        url_pattern = r'https?://[^\s]+'
        urls = re.findall(url_pattern, text)
        return [url for url in urls if self.is_valid_youtube_url(url)]
    
    def extract_urls_from_file(self, file_content: str) -> List[str]:
        """Extract URLs from text file"""
        lines = file_content.strip().split('\n')
        urls = []
        for line in lines:
            line = line.strip()
            if line and not line.startswith('#'):
                urls.append(line)
        return [url for url in urls if self.is_valid_youtube_url(url)]
    
    async def get_video_info(self, url: str) -> Optional[Dict]:
        """Get video information using yt-dlp with retries"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Rotate user agent for each attempt
                current_agent = self.user_agents[attempt % len(self.user_agents)]
                ydl_opts = self.ydl_opts.copy()
                ydl_opts['http_headers']['User-Agent'] = current_agent
                ydl_opts['user_agent'] = current_agent
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = await asyncio.to_thread(ydl.extract_info, url, download=False)
                    
                    if not info:
                        continue
                    
                    # Get available formats
                    formats = []
                    if 'formats' in info:
                        for fmt in info['formats']:
                            if fmt.get('ext') in ['mp4', 'webm', 'mkv']:
                                formats.append({
                                    'format_id': fmt['format_id'],
                                    'height': fmt.get('height', 0),
                                    'width': fmt.get('width', 0),
                                    'ext': fmt.get('ext', ''),
                                    'filesize': fmt.get('filesize'),
                                    'format_note': fmt.get('format_note', ''),
                                    'vcodec': fmt.get('vcodec', ''),
                                    'acodec': fmt.get('acodec', ''),
                                })
                    
                    # Sanitize title
                    title = info.get('title', 'Unknown')
                    title = self.sanitize_filename(title)
                    
                    return {
                        'title': title,
                        'duration': info.get('duration', 0),
                        'formats': formats,
                        'thumbnail': info.get('thumbnail', ''),
                        'channel': info.get('channel', 'Unknown'),
                        'upload_date': info.get('upload_date', ''),
                        'view_count': info.get('view_count', 0),
                        'webpage_url': info.get('webpage_url', url),
                    }
                    
            except yt_dlp.utils.DownloadError as e:
                if "Sign in to confirm you're not a bot" in str(e):
                    logger.error(f"Bot detection triggered on attempt {attempt + 1}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(5)  # Wait before retry
                        continue
                    else:
                        raise Exception("YouTube is requiring sign-in. Try using cookies.txt file.")
                else:
                    raise
            except Exception as e:
                logger.error(f"Error getting video info (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)
                    continue
                else:
                    return None
        
        return None
    
    async def download_video(self, url: str) -> Optional[Path]:
        """Download video using yt-dlp with improved error handling"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Create temporary directory for this download
                download_dir = self.temp_dir / datetime.now().strftime("%Y%m%d_%H%M%S")
                download_dir.mkdir(exist_ok=True)
                
                # Configure yt-dlp options for this attempt
                current_agent = self.user_agents[attempt % len(self.user_agents)]
                ydl_opts = self.ydl_opts.copy()
                ydl_opts['outtmpl'] = str(download_dir / '%(title).100s.%(ext)s')
                ydl_opts['http_headers']['User-Agent'] = current_agent
                ydl_opts['user_agent'] = current_agent
                
                # Try different format selections
                if attempt == 0:
                    # First try: 720p or lower
                    ydl_opts['format'] = 'bestvideo[height<=720]+bestaudio/best[height<=720]'
                elif attempt == 1:
                    # Second try: Best available
                    ydl_opts['format'] = 'best'
                else:
                    # Third try: Any format
                    ydl_opts['format'] = 'bestvideo+bestaudio/best'
                
                logger.info(f"Download attempt {attempt + 1} for {url}")
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = await asyncio.to_thread(ydl.download, [url])
                    
                    # Find downloaded file
                    files = list(download_dir.glob("*"))
                    if files:
                        downloaded_file = files[0]
                        file_size = downloaded_file.stat().st_size
                        
                        if file_size > 0:
                            logger.info(f"Downloaded: {downloaded_file.name} ({file_size / 1024 / 1024:.2f} MB)")
                            return downloaded_file
                        else:
                            logger.warning(f"Empty file downloaded: {downloaded_file}")
                            downloaded_file.unlink()
                
                if attempt < max_retries - 1:
                    await asyncio.sleep(5)
                    continue
                    
            except yt_dlp.utils.DownloadError as e:
                error_msg = str(e)
                logger.error(f"Download error (attempt {attempt + 1}): {error_msg}")
                
                if "Sign in" in error_msg or "bot" in error_msg.lower():
                    if attempt < max_retries - 1:
                        logger.info("Bot detection triggered, waiting before retry...")
                        await asyncio.sleep(10)
                        continue
                    else:
                        raise Exception("YouTube is blocking downloads. Try using cookies.txt file.")
                
                if attempt < max_retries - 1:
                    await asyncio.sleep(3)
                    continue
                    
            except Exception as e:
                logger.error(f"Unexpected error (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(3)
                    continue
        
        return None
    
    async def generate_thumbnail(self, video_path: Path) -> Optional[Path]:
        """Generate thumbnail from video"""
        try:
            if not shutil.which('ffmpeg'):
                logger.warning("FFmpeg not found, skipping thumbnail generation")
                return None
            
            thumbnail_path = video_path.with_suffix('.jpg')
            
            # Try multiple time positions for thumbnail
            time_positions = ['00:00:05', '00:00:10', '00:00:30']
            
            for position in time_positions:
                cmd = [
                    'ffmpeg',
                    '-ss', position,
                    '-i', str(video_path),
                    '-vframes', '1',
                    '-q:v', '2',
                    '-y',
                    str(thumbnail_path)
                ]
                
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await process.communicate()
                
                if process.returncode == 0 and thumbnail_path.exists():
                    if thumbnail_path.stat().st_size > 0:
                        logger.info(f"Generated thumbnail at {position}")
                        return thumbnail_path
                    else:
                        thumbnail_path.unlink()
            
            return None
            
        except Exception as e:
            logger.error(f"Thumbnail generation error: {e}")
            return None
    
    async def cleanup(self, *paths):
        """Clean up temporary files"""
        for path in paths:
            if path and isinstance(path, Path) and path.exists():
                try:
                    if path.is_dir():
                        shutil.rmtree(path, ignore_errors=True)
                    else:
                        path.unlink(missing_ok=True)
                    logger.debug(f"Cleaned up: {path}")
                except Exception as e:
                    logger.error(f"Cleanup error for {path}: {e}")
    
    async def handle_single_url(self, update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
        """Handle single YouTube URL"""
        chat_id = update.effective_chat.id
        message = None
        
        try:
            # Send initial message
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            message = await update.message.reply_text("🔍 Fetching video information...")
            
            # Get video info
            info = await self.get_video_info(url)
            if not info:
                await message.edit_text("❌ Could not fetch video information. Please check the URL.")
                return
            
            # Show video info
            duration_min = info['duration'] // 60
            duration_sec = info['duration'] % 60
            info_text = (
                f"📹 **{info['title'][:100]}**\n\n"
                f"👤 Channel: {info['channel']}\n"
                f"⏱ Duration: {duration_min}:{duration_sec:02d}\n"
                f"📥 Starting download..."
            )
            
            await message.edit_text(info_text, parse_mode='Markdown')
            
            # Download video
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO)
            await message.edit_text("📥 Downloading video...")
            
            video_file = await self.download_video(url)
            
            if not video_file:
                await message.edit_text("❌ Failed to download video. YouTube might be blocking the request.")
                return
            
            # Check file size
            file_size = video_file.stat().st_size
            if file_size == 0:
                await message.edit_text("❌ Downloaded file is empty.")
                await self.cleanup(video_file, video_file.parent)
                return
            
            # Generate thumbnail
            await message.edit_text("🖼️ Generating thumbnail...")
            thumbnail = await self.generate_thumbnail(video_file)
            
            # Send video
            await message.edit_text("📤 Sending video...")
            
            try:
                with open(video_file, 'rb') as f:
                    # Try to send as video first
                    if file_size <= 50 * 1024 * 1024:  # 50MB limit
                        await context.bot.send_video(
                            chat_id=chat_id,
                            video=InputFile(f, filename=f"{info['title'][:50]}.mp4"),
                            caption=f"✅ {info['title'][:100]}",
                            thumbnail=open(thumbnail, 'rb') if thumbnail else None,
                            supports_streaming=True,
                            read_timeout=60,
                            write_timeout=60,
                            connect_timeout=60,
                        )
                    else:
                        # Send as document for large files
                        await context.bot.send_document(
                            chat_id=chat_id,
                            document=InputFile(f, filename=f"{info['title'][:50]}.mp4"),
                            caption=f"📁 {info['title'][:100]}",
                            read_timeout=60,
                            write_timeout=60,
                            connect_timeout=60,
                        )
                
                await message.edit_text(f"✅ Successfully sent!")
                
            except TelegramError as e:
                logger.error(f"Telegram error while sending: {e}")
                await message.edit_text(f"❌ Error sending file: {str(e)}")
            
            # Cleanup
            await self.cleanup(video_file, thumbnail, video_file.parent)
            
        except Exception as e:
            logger.error(f"Error processing URL: {e}", exc_info=True)
            error_msg = str(e)
            
            if "Sign in" in error_msg or "bot" in error_msg:
                help_text = (
                    "❌ **YouTube Bot Detection Triggered**\n\n"
                    "YouTube is requiring sign-in to download this video.\n\n"
                    "**Solutions:**\n"
                    "1. Try again later\n"
                    "2. Use a cookies.txt file (export from browser)\n"
                    "3. Try a different video"
                )
            else:
                help_text = f"❌ Error: {error_msg}"
            
            if message:
                await message.edit_text(help_text, parse_mode='Markdown')
            else:
                await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        welcome_text = (
            "🎬 **YouTube Video Downloader Bot**\n\n"
            "Send me a YouTube link to download it as MP4!\n\n"
            "📌 **Features:**\n"
            "• Download videos up to 720p\n"
            "• Support for playlists\n"
            "• Automatic format selection\n\n"
            "📎 **How to use:**\n"
            "1. Send a YouTube URL\n"
            "2. Wait for the download\n\n"
            "⚠️ **Note:** Some videos may be blocked by YouTube.\n"
            "If you get bot detection errors, try using a cookies.txt file.\n\n"
            "**Commands:**\n"
            "/start - Start the bot\n"
            "/help - Show help\n"
            "/status - Bot status"
        )
        await update.message.reply_text(welcome_text, parse_mode='Markdown')
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        help_text = (
            "🆘 **Help Guide**\n\n"
            "**How to download videos:**\n"
            "1. Send any YouTube URL\n"
            "2. Wait for processing\n"
            "3. Receive the video\n\n"
            "**Supported URLs:**\n"
            "• youtube.com/watch?v=...\n"
            "• youtu.be/...\n"
            "• youtube.com/shorts/...\n\n"
            "**Bot Detection Issues:**\n"
            "If you see 'Sign in to confirm you're not a bot':\n"
            "1. Export cookies from your browser\n"
            "2. Save as cookies.txt\n"
            "3. Send to the bot\n\n"
            "**Need more help?** Contact the bot administrator."
        )
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command"""
        # Check dependencies
        ffmpeg_available = shutil.which('ffmpeg') is not None
        yt_dlp_version = yt_dlp.version.__version__
        
        # Check temp directory
        temp_files = len(list(self.temp_dir.glob("*"))) if self.temp_dir.exists() else 0
        
        status_text = (
            "📊 **Bot Status**\n\n"
            f"• **yt-dlp Version:** {yt_dlp_version}\n"
            f"• **FFmpeg Available:** {'✅' if ffmpeg_available else '❌'}\n"
            f"• **Temp Files:** {temp_files}\n"
            f"• **User Agents:** {len(self.user_agents)}\n"
            f"• **Cookies:** {'✅ Loaded' if 'cookiefile' in self.ydl_opts else '❌ Not loaded'}\n\n"
            "**Bot is operational!** 🚀"
        )
        await update.message.reply_text(status_text, parse_mode='Markdown')
    
    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages containing YouTube URLs"""
        text = update.message.text
        
        # Check if it's a command
        if text.startswith('/'):
            return
        
        # Extract URLs from text
        urls = self.extract_urls_from_text(text)
        
        if not urls:
            await update.message.reply_text(
                "❌ No valid YouTube URLs found.\n"
                "Please send a valid YouTube link."
            )
            return
        
        # Process each URL
        for url in urls:
            await self.handle_single_url(update, context, url)
    
    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle document messages"""
        document = update.message.document
        
        # Check if it's cookies.txt
        if document.file_name == 'cookies.txt':
            try:
                # Download cookies file
                file = await document.get_file()
                cookies_path = Path('cookies.txt')
                await file.download_to_drive(cookies_path)
                
                # Update yt-dlp options
                self.ydl_opts['cookiefile'] = str(cookies_path)
                
                await update.message.reply_text(
                    "✅ Cookies file loaded successfully!\n"
                    "This should help with bot detection issues."
                )
            except Exception as e:
                await update.message.reply_text(f"❌ Error loading cookies: {e}")
            return
        
        # Check if it's a text file with URLs
        if document.file_name.endswith('.txt'):
            try:
                file = await document.get_file()
                temp_path = Path(f"temp_{document.file_name}")
                await file.download_to_drive(temp_path)
                
                with open(temp_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                urls = self.extract_urls_from_file(content)
                temp_path.unlink()
                
                if not urls:
                    await update.message.reply_text("❌ No valid YouTube URLs found in the file.")
                    return
                
                await update.message.reply_text(f"📚 Found {len(urls)} URLs. Processing...")
                
                for url in urls[:5]:  # Limit to 5 URLs per batch
                    await self.handle_single_url(update, context, url)
                    await asyncio.sleep(2)  # Rate limiting
                
            except Exception as e:
                await update.message.reply_text(f"❌ Error processing file: {e}")
            return
        
        await update.message.reply_text(
            "❌ Unsupported file type.\n"
            "Supported files:\n"
            "• cookies.txt - For authentication\n"
            "• *.txt - With YouTube URLs (one per line)"
        )
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle errors"""
        logger.error(f"Update {update} caused error {context.error}", exc_info=True)
        
        try:
            error_msg = str(context.error)
            
            if "Connection refused" in error_msg or "port" in error_msg.lower():
                # Don't send error message for port issues
                return
            
            await update.message.reply_text(
                "❌ An error occurred.\n"
                "Please try again later or contact support."
            )
        except:
            pass

async def main():
    """Start the bot"""
    # Get bot token from environment variable
    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    
    if not BOT_TOKEN:
        # Try to get from file (for local development)
        try:
            with open('.env', 'r') as f:
                for line in f:
                    if line.startswith('TELEGRAM_BOT_TOKEN='):
                        BOT_TOKEN = line.strip().split('=', 1)[1]
                        break
        except:
            pass
    
    if not BOT_TOKEN:
        print("❌ Error: TELEGRAM_BOT_TOKEN not found!")
        print("Please set it as environment variable or in .env file")
        return
    
    # Check if running on Render
    IS_RENDER = os.getenv('RENDER', 'false').lower() == 'true'
    
    # Create bot instance
    bot = YouTubeDownloaderBot(BOT_TOKEN)
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("help", bot.help_command))
    application.add_handler(CommandHandler("status", bot.status))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_text))
    application.add_handler(MessageHandler(filters.Document.ALL, bot.handle_document))
    
    # Add error handler
    application.add_error_handler(bot.error_handler)
    
    print("🤖 Bot is starting...")
    print(f"📡 Mode: {'Render' if IS_RENDER else 'Local'}")
    print("📌 Commands: /start, /help, /status")
    
    if IS_RENDER:
        # On Render, we need to handle webhook or use long polling with keep-alive
        print("⚠️ Running on Render - using webhook setup")
        
        # Get Render external URL
        RENDER_EXTERNAL_URL = os.getenv('RENDER_EXTERNAL_URL')
        if RENDER_EXTERNAL_URL:
            # Set webhook for Render
            await application.bot.set_webhook(
                url=f"{RENDER_EXTERNAL_URL}/{BOT_TOKEN}",
                drop_pending_updates=True
            )
            print(f"✅ Webhook set to: {RENDER_EXTERNAL_URL}")
        else:
            print("⚠️ RENDER_EXTERNAL_URL not set, using polling")
        
        # Start polling with specific parameters for Render
        await application.initialize()
        await application.start()
        
        try:
            await application.updater.start_polling(
                poll_interval=1.0,
                timeout=10,
                read_timeout=10,
                write_timeout=10,
                connect_timeout=10,
                pool_timeout=10,
            )
        except Exception as e:
            print(f"❌ Polling error: {e}")
            print("Trying alternative approach...")
            
            # Alternative: Keep the bot running with periodic updates
            while True:
                try:
                    await asyncio.sleep(1)
                except KeyboardInterrupt:
                    break
        
        # Keep the bot running
        await asyncio.Event().wait()
        
    else:
        # Local development - use polling
        print("🏠 Running locally - using polling")
        await application.run_polling(
            poll_interval=1.0,
            timeout=30,
            read_timeout=30,
            write_timeout=30,
            connect_timeout=30,
            pool_timeout=30,
            drop_pending_updates=True
        )

if __name__ == "__main__":
    # Create temp directory if it doesn't exist
    Path("temp_downloads").mkdir(exist_ok=True)
    
    # Run the bot
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bot stopped by user")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()