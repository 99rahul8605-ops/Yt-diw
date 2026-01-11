import os
import re
import logging
import asyncio
import tempfile
import shutil
from pathlib import Path
from typing import List, Optional
from datetime import datetime

import yt_dlp
from telegram import Update, InputFile, Document, Video
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)
from telegram.constants import ChatAction

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot states
SELECTING_QUALITY = 1

# Configuration
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB Telegram limit
SUPPORTED_DOMAINS = ['youtube.com', 'youtu.be', 'youtube-nocookie.com']

class YouTubeDownloaderBot:
    def __init__(self, token: str):
        self.token = token
        self.temp_dir = Path("temp_downloads")
        self.temp_dir.mkdir(exist_ok=True)
        
        # yt-dlp configuration
        self.ydl_opts = {
            'quiet': False,
            'no_warnings': False,
            'extract_flat': False,
            'force_generic_extractor': False,
            'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]',
            'merge_output_format': 'mp4',
            'outtmpl': str(self.temp_dir / '%(title)s.%(ext)s'),
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }],
            'ffmpeg_location': shutil.which('ffmpeg'),
            'progress_hooks': [self.progress_hook],
        }
        
        # Optional: Use aria2c for faster downloads
        if shutil.which('aria2c'):
            self.ydl_opts['external_downloader'] = 'aria2c'
            self.ydl_opts['external_downloader_args'] = ['-x16', '-s16', '-k1M']
    
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
        youtube_regex = r'^(https?://)?(www\.)?(youtube\.com|youtu\.?be)/.+$'
        return bool(re.match(youtube_regex, url))
    
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
            if line and not line.startswith('#'):  # Skip empty lines and comments
                urls.append(line)
        return [url for url in urls if self.is_valid_youtube_url(url)]
    
    async def get_video_info(self, url: str) -> dict:
        """Get video information using yt-dlp"""
        try:
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                info = ydl.extract_info(url, download=False)
                
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
                
                # Get thumbnail
                thumbnail = info.get('thumbnail', '')
                
                # Get best format for automatic selection
                best_format = self.get_best_format(formats)
                
                return {
                    'title': info.get('title', 'Unknown'),
                    'duration': info.get('duration', 0),
                    'formats': formats,
                    'best_format': best_format,
                    'thumbnail': thumbnail,
                    'channel': info.get('channel', 'Unknown'),
                    'upload_date': info.get('upload_date', ''),
                    'view_count': info.get('view_count', 0),
                }
        except Exception as e:
            logger.error(f"Error getting video info: {e}")
            return None
    
    def get_best_format(self, formats: List[dict]) -> dict:
        """Select the best format based on our criteria"""
        # Filter for formats with video
        video_formats = [f for f in formats if f.get('vcodec') != 'none']
        
        # Try to find 720p or lower
        target_formats = [f for f in video_formats if f.get('height', 0) <= 720]
        
        if target_formats:
            # Sort by height descending, then by filesize if available
            target_formats.sort(
                key=lambda x: (x.get('height', 0), x.get('filesize', 0) or 0),
                reverse=True
            )
            return target_formats[0]
        
        # Fallback to best available
        if video_formats:
            video_formats.sort(
                key=lambda x: (x.get('height', 0), x.get('filesize', 0) or 0),
                reverse=True
            )
            return video_formats[0]
        
        return {}
    
    async def download_video(self, url: str, format_id: str = None) -> Optional[Path]:
        """Download video using yt-dlp"""
        temp_file = None
        try:
            # Create temporary directory for this download
            download_dir = self.temp_dir / datetime.now().strftime("%Y%m%d_%H%M%S")
            download_dir.mkdir(exist_ok=True)
            
            # Configure yt-dlp options
            ydl_opts = self.ydl_opts.copy()
            ydl_opts['outtmpl'] = str(download_dir / '%(title)s.%(ext)s')
            
            if format_id:
                ydl_opts['format'] = format_id
            else:
                # Use our quality selection logic
                ydl_opts['format'] = 'bestvideo[height<=720]+bestaudio/best[height<=720]'
            
            logger.info(f"Downloading {url} with format {format_id or 'auto'}")
            
            # Download video
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await asyncio.to_thread(ydl.extract_info, url, download=True)
                
                if info:
                    # Get the downloaded file
                    files = list(download_dir.glob("*"))
                    if files:
                        temp_file = files[0]
                        logger.info(f"Downloaded: {temp_file.name} ({temp_file.stat().st_size / 1024 / 1024:.2f} MB)")
                        
                        # Check file size
                        if temp_file.stat().st_size > MAX_FILE_SIZE:
                            logger.warning(f"File too large: {temp_file.stat().st_size}")
                            return None
                        
                        return temp_file
            
            return None
            
        except Exception as e:
            logger.error(f"Download error: {e}")
            if temp_file and temp_file.exists():
                temp_file.unlink()
            return None
    
    async def generate_thumbnail(self, video_path: Path) -> Optional[Path]:
        """Generate thumbnail from video"""
        try:
            if not shutil.which('ffmpeg'):
                logger.warning("FFmpeg not found, skipping thumbnail generation")
                return None
            
            thumbnail_path = video_path.with_suffix('.jpg')
            
            # Use ffmpeg to extract thumbnail at 10 seconds
            cmd = [
                'ffmpeg',
                '-ss', '00:00:10',
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
                logger.info(f"Generated thumbnail: {thumbnail_path}")
                return thumbnail_path
            else:
                logger.error(f"FFmpeg error: {stderr.decode()}")
                return None
                
        except Exception as e:
            logger.error(f"Thumbnail generation error: {e}")
            return None
    
    async def cleanup(self, *paths):
        """Clean up temporary files"""
        for path in paths:
            if path and path.exists():
                try:
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                    logger.info(f"Cleaned up: {path}")
                except Exception as e:
                    logger.error(f"Cleanup error for {path}: {e}")
    
    async def handle_single_url(self, update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
        """Handle single YouTube URL"""
        chat_id = update.effective_chat.id
        
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
                f"📹 **{info['title']}**\n\n"
                f"👤 Channel: {info['channel']}\n"
                f"⏱ Duration: {duration_min}:{duration_sec:02d}\n"
                f"👁 Views: {info['view_count']:,}\n"
                f"📅 Uploaded: {info['upload_date']}\n\n"
                f"📥 Preparing download..."
            )
            
            await message.edit_text(info_text, parse_mode='Markdown')
            
            # Download video
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO)
            video_file = await self.download_video(url, info['best_format'].get('format_id'))
            
            if not video_file:
                await message.edit_text("❌ Failed to download video.")
                return
            
            # Generate thumbnail
            thumbnail = await self.generate_thumbnail(video_file)
            
            # Send video
            try:
                with open(video_file, 'rb') as f:
                    await context.bot.send_video(
                        chat_id=chat_id,
                        video=InputFile(f, filename=video_file.name),
                        caption=f"✅ {info['title']}",
                        thumbnail=open(thumbnail, 'rb') if thumbnail else None,
                        supports_streaming=True
                    )
                await message.edit_text(f"✅ Successfully sent: {info['title']}")
                
            except Exception as send_error:
                logger.error(f"Failed to send as video: {send_error}")
                
                # Try sending as document
                try:
                    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_DOCUMENT)
                    with open(video_file, 'rb') as f:
                        await context.bot.send_document(
                            chat_id=chat_id,
                            document=InputFile(f, filename=video_file.name),
                            caption=f"📁 {info['title']}"
                        )
                    await message.edit_text(f"📁 Sent as document: {info['title']}")
                except Exception as doc_error:
                    logger.error(f"Failed to send as document: {doc_error}")
                    await message.edit_text("❌ Failed to send video. File might be too large.")
            
            # Cleanup
            await self.cleanup(video_file, thumbnail, video_file.parent)
            
        except Exception as e:
            logger.error(f"Error processing URL: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")
    
    async def handle_batch_urls(self, update: Update, context: ContextTypes.DEFAULT_TYPE, urls: List[str]):
        """Handle multiple URLs"""
        chat_id = update.effective_chat.id
        total = len(urls)
        
        message = await update.message.reply_text(f"📚 Processing {total} videos...")
        
        successful = 0
        failed = 0
        
        for i, url in enumerate(urls, 1):
            try:
                await message.edit_text(
                    f"📥 Downloading video {i}/{total}\n"
                    f"✅ Successful: {successful} | ❌ Failed: {failed}"
                )
                
                # Get video info
                info = await self.get_video_info(url)
                if not info:
                    failed += 1
                    continue
                
                # Download video
                video_file = await self.download_video(url)
                if not video_file:
                    failed += 1
                    continue
                
                # Send video
                try:
                    with open(video_file, 'rb') as f:
                        await context.bot.send_video(
                            chat_id=chat_id,
                            video=InputFile(f, filename=video_file.name),
                            caption=f"{info['title']} ({i}/{total})",
                            supports_streaming=True
                        )
                    successful += 1
                    
                except Exception:
                    # Try as document
                    try:
                        with open(video_file, 'rb') as f:
                            await context.bot.send_document(
                                chat_id=chat_id,
                                document=InputFile(f, filename=video_file.name),
                                caption=f"{info['title']} ({i}/{total})"
                            )
                        successful += 1
                    except Exception:
                        failed += 1
                
                # Cleanup
                if video_file and video_file.exists():
                    video_file.unlink()
                if video_file.parent.exists():
                    video_file.parent.rmdir()
                    
                # Rate limiting to avoid hitting Telegram limits
                await asyncio.sleep(2)
                
            except Exception as e:
                logger.error(f"Error processing URL {url}: {e}")
                failed += 1
        
        await message.edit_text(
            f"✅ Batch processing complete!\n\n"
            f"📊 Results:\n"
            f"• Total: {total}\n"
            f"• ✅ Successful: {successful}\n"
            f"• ❌ Failed: {failed}"
        )
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        welcome_text = (
            "🎬 **YouTube Video Downloader Bot**\n\n"
            "Send me a YouTube link to download it as MP4!\n\n"
            "📌 **Features:**\n"
            "• Download videos up to 720p\n"
            "• Support for playlists\n"
            "• Batch download from text files\n"
            "• Automatic format selection\n\n"
            "📎 **How to use:**\n"
            "1. Send a YouTube URL\n"
            "2. Or send a .txt file with multiple URLs\n"
            "3. Wait for the download to complete\n\n"
            "⚠️ **Note:** Videos larger than 50MB will be sent as documents."
        )
        await update.message.reply_text(welcome_text, parse_mode='Markdown')
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        help_text = (
            "🆘 **Help Guide**\n\n"
            "**Commands:**\n"
            "/start - Start the bot\n"
            "/help - Show this help message\n"
            "/about - About this bot\n\n"
            "**Supported URLs:**\n"
            "• youtube.com/watch?v=...\n"
            "• youtu.be/...\n"
            "• youtube.com/playlist?list=...\n\n"
            "**Text File Format:**\n"
            "Create a .txt file with one URL per line:\n"
            "```\n"
            "https://youtube.com/watch?v=abc123\n"
            "https://youtu.be/xyz789\n"
            "```\n"
            "Then send the file to download all videos."
        )
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def about(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /about command"""
        about_text = (
            "🤖 **About This Bot**\n\n"
            "**YouTube Video Downloader**\n"
            "Version: 1.0.0\n\n"
            "**Powered by:**\n"
            "• yt-dlp - YouTube video downloader\n"
            "• FFmpeg - Video processing\n"
            "• python-telegram-bot - Bot framework\n\n"
            "**Features:**\n"
            "• High-quality downloads (up to 720p)\n"
            "• Fast parallel downloads\n"
            "• Automatic format selection\n"
            "• Batch processing\n"
            "• Thumbnail generation\n\n"
            "⚠️ **Disclaimer:**\n"
            "Download only videos you have permission to download.\n"
            "Respect copyright laws."
        )
        await update.message.reply_text(about_text, parse_mode='Markdown')
    
    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages containing YouTube URLs"""
        text = update.message.text
        
        # Extract URLs from text
        urls = self.extract_urls_from_text(text)
        
        if not urls:
            await update.message.reply_text(
                "❌ No valid YouTube URLs found.\n"
                "Please send a valid YouTube link."
            )
            return
        
        if len(urls) == 1:
            await self.handle_single_url(update, context, urls[0])
        else:
            await self.handle_batch_urls(update, context, urls)
    
    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle document messages (text files with URLs)"""
        document = update.message.document
        
        # Check if it's a text file
        if not document.file_name.lower().endswith('.txt'):
            await update.message.reply_text("❌ Please send a .txt file containing YouTube URLs.")
            return
        
        # Download the file
        file = await document.get_file()
        temp_path = self.temp_dir / f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        await file.download_to_drive(temp_path)
        
        # Read and process URLs
        with open(temp_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        urls = self.extract_urls_from_file(content)
        
        if not urls:
            await update.message.reply_text("❌ No valid YouTube URLs found in the file.")
            temp_path.unlink()
            return
        
        await update.message.reply_text(f"📚 Found {len(urls)} valid URLs. Starting batch download...")
        await self.handle_batch_urls(update, context, urls)
        
        # Cleanup
        temp_path.unlink()
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle errors"""
        logger.error(f"Update {update} caused error {context.error}")
        
        try:
            await update.message.reply_text(
                "❌ An error occurred. Please try again later.\n"
                f"Error: {str(context.error)}"
            )
        except:
            pass

async def main():
    """Start the bot"""
    # Get bot token from environment variable
    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    if not BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN environment variable not set!")
        print("Please set it: export TELEGRAM_BOT_TOKEN='your_token_here'")
        return
    
    # Create bot instance
    bot = YouTubeDownloaderBot(BOT_TOKEN)
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("help", bot.help_command))
    application.add_handler(CommandHandler("about", bot.about))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_text))
    application.add_handler(MessageHandler(filters.Document.ALL, bot.handle_document))
    
    # Add error handler
    application.add_error_handler(bot.error_handler)
    
    # Start the bot
    print("🤖 Bot is starting...")
    print("📌 Commands: /start, /help, /about")
    print("📌 Send YouTube links or .txt files with multiple links")
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    # Keep running
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 Shutting down bot...")
        await application.stop()

if __name__ == "__main__":
    asyncio.run(main())