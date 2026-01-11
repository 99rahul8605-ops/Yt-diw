import os
import logging
import asyncio
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, InputFile
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes
)
from telegram.constants import ParseMode

from utils.youtube_downloader import YouTubeDownloader
from utils.cookie_manager import CookieManager
from utils.progress_handler import ProgressHandler

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
MAX_FILE_SIZE = 2000 * 1024 * 1024  # 2GB Telegram limit
TEMP_DIR = Path("temp")
COOKIES_DIR = Path("cookies")

# Ensure directories exist
TEMP_DIR.mkdir(exist_ok=True)
COOKIES_DIR.mkdir(exist_ok=True)

# Conversation states
CHOOSING_RESOLUTION, PROCESSING_BULK, UPLOADING = range(3)

# Store user states
user_states: Dict[int, Dict] = {}

class YouTubeDownloadBot:
    def __init__(self):
        self.cookie_manager = CookieManager(COOKIES_DIR)
        self.downloader = YouTubeDownloader(self.cookie_manager)
        self.progress_handler = ProgressHandler()
        
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send a welcome message when /start is issued."""
        user = update.effective_user
        welcome_message = (
            f"🎬 Welcome {user.first_name} to YouTube Downloader Bot!\n\n"
            "📥 **Features:**\n"
            "• Download individual YouTube videos\n"
            "• Bulk download via .txt file\n"
            "• Multiple resolution options\n"
            "• Update YouTube cookies\n"
            "• Real-time progress tracking\n\n"
            "📝 **How to use:**\n"
            "1. Send a YouTube link directly\n"
            "2. Or send a .txt file with multiple links\n"
            "3. Use /update_cookies to add cookies file\n"
            "4. Use /help for more info\n\n"
            "🔧 **Commands:**\n"
            "/start - Start the bot\n"
            "/help - Show help message\n"
            "/update_cookies - Update YouTube cookies\n"
            "/status - Check bot status\n"
        )
        
        await update.message.reply_text(welcome_message, parse_mode=ParseMode.MARKDOWN)
        
        # Send bot capabilities
        capabilities = (
            "🚀 **Ready to download!**\n\n"
            "👇 **Send me:**\n"
            "• A YouTube URL to download single video\n"
            "• A .txt file with multiple URLs (one per line)\n"
            "• A cookies.txt file to update cookies\n"
        )
        await update.message.reply_text(capabilities, parse_mode=ParseMode.MARKDOWN)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send a help message."""
        help_text = (
            "🤖 **YouTube Downloader Bot Help**\n\n"
            "📥 **Download Single Video:**\n"
            "1. Send any YouTube URL\n"
            "2. Choose resolution from buttons\n"
            "3. Wait for download & upload\n\n"
            "📁 **Bulk Download:**\n"
            "1. Send a .txt file containing YouTube URLs\n"
            "2. Each URL should be on a new line\n"
            "3. Choose resolution for all videos\n"
            "4. Bot will process each video\n\n"
            "🍪 **Update Cookies:**\n"
            "1. Use /update_cookies command\n"
            "2. Send cookies.txt file\n"
            "3. Cookies help with age-restricted videos\n\n"
            "⚡ **Progress Tracking:**\n"
            "• 🔄 Downloading... shows download progress\n"
            "• 📤 Uploading... shows upload progress\n"
            "• ✅ Complete when finished\n\n"
            "⚠️ **Limitations:**\n"
            "• Max file size: 2GB (Telegram limit)\n"
            "• Supported formats: MP4, WebM\n"
            "• Keep cookies updated for best results\n"
        )
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

    async def update_cookies(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Initiate cookie update process."""
        await update.message.reply_text(
            "🍪 **Update YouTube Cookies**\n\n"
            "Please send me a cookies.txt file.\n"
            "This helps download age-restricted or private videos.\n\n"
            "⚠️ Note: Your cookies are stored securely and only used for downloading."
        )

    async def handle_cookies_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle cookies.txt file upload."""
        user_id = update.effective_user.id
        
        try:
            # Get the document
            document = update.message.document
            
            if document.file_name != 'cookies.txt':
                await update.message.reply_text("❌ Please send a file named 'cookies.txt'")
                return
                
            # Download the file
            file = await context.bot.get_file(document.file_id)
            temp_path = TEMP_DIR / f"cookies_{user_id}.txt"
            await file.download_to_drive(temp_path)
            
            # Update cookies
            success = self.cookie_manager.update_cookies(temp_path, user_id)
            
            if success:
                await update.message.reply_text(
                    "✅ Cookies updated successfully!\n"
                    "You can now download age-restricted videos."
                )
            else:
                await update.message.reply_text("❌ Failed to update cookies. Please check the file format.")
                
            # Cleanup
            temp_path.unlink(missing_ok=True)
            
        except Exception as e:
            logger.error(f"Error updating cookies: {e}")
            await update.message.reply_text("❌ Error processing cookies file.")

    async def handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages containing YouTube URLs."""
        text = update.message.text.strip()
        user_id = update.effective_user.id
        
        # Check if it's a YouTube URL
        if not self.downloader.is_youtube_url(text):
            await update.message.reply_text("❌ Please send a valid YouTube URL")
            return
            
        # Get video info
        status_msg = await update.message.reply_text("🔍 Fetching video information...")
        
        try:
            video_info = await self.downloader.get_video_info(text, user_id)
            
            if not video_info:
                await status_msg.edit_text("❌ Failed to fetch video information")
                return
                
            # Store video info for this user
            user_states[user_id] = {
                'video_url': text,
                'video_info': video_info,
                'status_message': status_msg
            }
            
            # Create resolution buttons
            keyboard = []
            for format_info in video_info['formats']:
                button_text = f"{format_info['resolution']} ({format_info['ext']})"
                callback_data = f"res:{format_info['format_id']}"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Send video info with thumbnail
            caption = (
                f"🎬 **{video_info['title']}**\n\n"
                f"📊 **Duration:** {video_info['duration_string']}\n"
                f"👁️ **Views:** {video_info['view_count']:,}\n"
                f"👍 **Likes:** {video_info['like_count']:,}\n"
                f"📅 **Upload Date:** {video_info['upload_date']}\n\n"
                f"👇 **Select Resolution:**"
            )
            
            # Send thumbnail if available
            if video_info.get('thumbnail'):
                await update.message.reply_photo(
                    photo=video_info['thumbnail'],
                    caption=caption,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup
                )
            else:
                await update.message.reply_text(
                    caption,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup
                )
                
            await status_msg.delete()
            
        except Exception as e:
            logger.error(f"Error getting video info: {e}")
            await status_msg.edit_text("❌ Error fetching video information")

    async def handle_bulk_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle bulk download via .txt file."""
        user_id = update.effective_user.id
        
        try:
            document = update.message.document
            
            if not document.file_name.endswith('.txt'):
                await update.message.reply_text("❌ Please send a .txt file")
                return
                
            # Download the file
            file = await context.bot.get_file(document.file_id)
            temp_path = TEMP_DIR / f"bulk_{user_id}.txt"
            await file.download_to_drive(temp_path)
            
            # Read URLs
            with open(temp_path, 'r') as f:
                urls = [line.strip() for line in f if line.strip()]
                
            if not urls:
                await update.message.reply_text("❌ No valid URLs found in file")
                temp_path.unlink()
                return
                
            # Validate URLs
            valid_urls = []
            for url in urls:
                if self.downloader.is_youtube_url(url):
                    valid_urls.append(url)
                    
            if not valid_urls:
                await update.message.reply_text("❌ No valid YouTube URLs found")
                temp_path.unlink()
                return
                
            # Store bulk info
            user_states[user_id] = {
                'bulk_urls': valid_urls,
                'current_index': 0,
                'total_count': len(valid_urls)
            }
            
            # Ask for resolution
            keyboard = [
                [
                    InlineKeyboardButton("360p", callback_data="bulk_res:18"),
                    InlineKeyboardButton("480p", callback_data="bulk_res:135"),
                ],
                [
                    InlineKeyboardButton("720p", callback_data="bulk_res:22"),
                    InlineKeyboardButton("1080p", callback_data="bulk_res:137"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"📁 **Bulk Download Detected**\n\n"
                f"📊 **Files found:** {len(valid_urls)} videos\n"
                f"👇 **Select resolution for all videos:**",
                reply_markup=reply_markup
            )
            
            # Cleanup
            temp_path.unlink()
            
        except Exception as e:
            logger.error(f"Error handling bulk file: {e}")
            await update.message.reply_text("❌ Error processing bulk file")

    async def handle_resolution_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle resolution selection from inline keyboard."""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        callback_data = query.data
        
        if callback_data.startswith('res:'):
            # Single video download
            format_id = callback_data.split(':')[1]
            
            if user_id not in user_states:
                await query.edit_message_text("❌ Session expired. Please send the URL again.")
                return
                
            video_info = user_states[user_id]['video_info']
            video_url = user_states[user_id]['video_url']
            
            # Download the video
            await self.download_and_send_video(
                query, video_url, format_id, user_id, video_info
            )
            
        elif callback_data.startswith('bulk_res:'):
            # Bulk download
            format_id = callback_data.split(':')[1]
            await self.process_bulk_download(query, user_id, format_id)

    async def download_and_send_video(self, query, video_url, format_id, user_id, video_info):
        """Download and send a single video."""
        try:
            # Update status
            status_msg = await query.message.reply_text("⏬ Starting download...")
            
            # Create progress handler
            progress_msg = await query.message.reply_text(
                f"📥 **Downloading:** {video_info['title']}\n"
                f"📊 **Resolution:** {format_id}\n"
                f"⏳ **Progress:** 0%\n"
                f"🔄 **Status:** Starting..."
            )
            
            # Download with progress
            download_result = await self.downloader.download_video(
                video_url,
                format_id,
                user_id,
                lambda p: self.progress_handler.update_download_progress(
                    progress_msg, video_info['title'], p
                )
            )
            
            if not download_result['success']:
                await progress_msg.edit_text(f"❌ Download failed: {download_result.get('error', 'Unknown error')}")
                return
                
            # Upload to Telegram
            await progress_msg.edit_text(
                f"✅ **Download Complete!**\n"
                f"📤 **Now Uploading to Telegram...**\n"
                f"⏳ **Progress:** 0%"
            )
            
            # Send video with thumbnail
            caption = (
                f"🎬 **{video_info['title']}**\n"
                f"📊 **Resolution:** {download_result['resolution']}\n"
                f"📦 **Size:** {download_result['file_size_mb']:.2f} MB\n"
                f"⏱️ **Duration:** {video_info['duration_string']}\n\n"
                f"✅ Downloaded via @YouTubeDownloaderBot"
            )
            
            # Send video
            with open(download_result['filepath'], 'rb') as video_file:
                await query.message.reply_video(
                    video=InputFile(video_file, filename=download_result['filename']),
                    caption=caption,
                    parse_mode=ParseMode.MARKDOWN,
                    duration=video_info['duration'],
                    width=download_result.get('width', 1280),
                    height=download_result.get('height', 720),
                    supports_streaming=True,
                    read_timeout=300,
                    write_timeout=300,
                    connect_timeout=300,
                    pool_timeout=300
                )
            
            # Cleanup
            await progress_msg.delete()
            await status_msg.delete()
            
            # Remove downloaded file
            Path(download_result['filepath']).unlink(missing_ok=True)
            
        except Exception as e:
            logger.error(f"Error in download_and_send_video: {e}")
            await query.message.reply_text(f"❌ Error: {str(e)}")

    async def process_bulk_download(self, query, user_id, format_id):
        """Process bulk download queue."""
        if user_id not in user_states:
            await query.edit_message_text("❌ Session expired.")
            return
            
        bulk_info = user_states[user_id]
        urls = bulk_info['bulk_urls']
        
        await query.edit_message_text(
            f"📁 **Bulk Download Started**\n\n"
            f"📊 **Total Videos:** {len(urls)}\n"
            f"🎯 **Resolution:** {format_id}\n"
            f"⏳ **Processing...**"
        )
        
        success_count = 0
        failed_count = 0
        
        for i, url in enumerate(urls, 1):
            try:
                # Get video info
                video_info = await self.downloader.get_video_info(url, user_id)
                
                if not video_info:
                    failed_count += 1
                    continue
                    
                # Status message
                status_msg = await query.message.reply_text(
                    f"🔄 **Processing {i}/{len(urls)}**\n"
                    f"🎬 **{video_info['title'][:50]}...**\n"
                    f"📥 Downloading..."
                )
                
                # Download
                download_result = await self.downloader.download_video(
                    url,
                    format_id,
                    user_id,
                    lambda p: None  # Simplified progress for bulk
                )
                
                if download_result['success']:
                    # Send video
                    with open(download_result['filepath'], 'rb') as video_file:
                        await query.message.reply_video(
                            video=InputFile(video_file),
                            caption=f"🎬 {video_info['title']}",
                            supports_streaming=True
                        )
                    success_count += 1
                    
                    # Cleanup
                    Path(download_result['filepath']).unlink(missing_ok=True)
                else:
                    failed_count += 1
                    
                await status_msg.delete()
                
            except Exception as e:
                logger.error(f"Error in bulk download item {i}: {e}")
                failed_count += 1
                
            # Delay between downloads
            await asyncio.sleep(2)
        
        # Final report
        await query.message.reply_text(
            f"✅ **Bulk Download Complete!**\n\n"
            f"📊 **Results:**\n"
            f"✅ Successful: {success_count}\n"
            f"❌ Failed: {failed_count}\n"
            f"📁 Total: {len(urls)}"
        )
        
        # Cleanup user state
        if user_id in user_states:
            del user_states[user_id]

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show bot status."""
        status = (
            "🤖 **Bot Status**\n\n"
            "✅ **Operational**\n"
            "📊 **Active Users:** {}\n"
            "💾 **Storage:** Ready\n"
            "🍪 **Cookies:** {}\n"
            "⚡ **Version:** 2.0.0\n\n"
            "🔄 **Last Update:** {}\n"
            "🏠 **Host:** Render"
        ).format(
            len(user_states),
            "✅ Configured" if self.cookie_manager.has_cookies() else "❌ Not configured",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        await update.message.reply_text(status, parse_mode=ParseMode.MARKDOWN)

    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle errors."""
        logger.error(f"Update {update} caused error {context.error}")
        
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "❌ An error occurred. Please try again or contact support."
            )

def main():
    """Start the bot."""
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable not set")
    
    bot = YouTubeDownloadBot()
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("help", bot.help_command))
    application.add_handler(CommandHandler("update_cookies", bot.update_cookies))
    application.add_handler(CommandHandler("status", bot.status_command))
    
    # Handle cookies file
    application.add_handler(MessageHandler(
        filters.Document.ALL & filters.ChatType.PRIVATE,
        bot.handle_cookies_file
    ))
    
    # Handle YouTube URLs
    application.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND,
        bot.handle_text_message
    ))
    
    # Handle bulk files
    application.add_handler(MessageHandler(
        filters.Document.FileExtension("txt") & filters.ChatType.PRIVATE,
        bot.handle_bulk_file
    ))
    
    # Handle inline keyboard buttons
    application.add_handler(CallbackQueryHandler(bot.handle_resolution_selection))
    
    # Error handler
    application.add_error_handler(bot.error_handler)
    
    # Start the bot
    print("🤖 Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()