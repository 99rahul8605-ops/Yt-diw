import os
import logging
import asyncio
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List
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

# Store user states
user_states: Dict[int, Dict] = {}
waiting_for_cookies: Dict[int, bool] = {}

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
            "/cookies_help - Cookies troubleshooting\n"
            "/status - Check bot status\n"
            "/cancel - Cancel current operation\n"
        )
        
        await update.message.reply_text(welcome_message, parse_mode=ParseMode.MARKDOWN)
        
        # Check if cookies are configured
        user_id = update.effective_user.id
        cookie_status = self.cookie_manager.get_cookies_status(user_id)
        
        if not cookie_status['has_cookies']:
            cookies_note = (
                "\n⚠️ **Note:** You haven't configured cookies yet.\n"
                "Some videos may require cookies to download.\n"
                "Use /update_cookies to add cookies file."
            )
            await update.message.reply_text(cookies_note, parse_mode=ParseMode.MARKDOWN)

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
        user_id = update.effective_user.id
        waiting_for_cookies[user_id] = True
        
        instructions = (
            "🍪 **Update YouTube Cookies**\n\n"
            "**Why cookies?**\n"
            "• Download age-restricted videos\n"
            "• Avoid 'Sign in to confirm you're not a bot' errors\n"
            "• Access private/unlisted videos\n\n"
            "**How to get cookies:**\n"
            "1. Install 'Get cookies.txt' browser extension\n"
            "2. Login to YouTube in your browser\n"
            "3. Go to any YouTube video\n"
            "4. Click the extension and export cookies\n"
            "5. Send the cookies.txt file to this bot\n\n"
            "**Privacy:** Your cookies are stored securely and only used for downloading.\n\n"
            "👇 **Now send me your cookies.txt file:**\n"
            "(or send /cancel to cancel)"
        )
        
        # Check current cookie status
        cookie_status = self.cookie_manager.get_cookies_status(user_id)
        
        if cookie_status['has_cookies']:
            instructions += f"\n\n📊 **Current Status:**\n{cookie_status['message']}"
        
        await update.message.reply_text(instructions, parse_mode=ParseMode.MARKDOWN)

    async def cookies_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Detailed help for cookies troubleshooting."""
        help_text = (
            "🔧 **Cookies Troubleshooting Guide**\n\n"
            "**Common Issues & Solutions:**\n\n"
            "1. **'Sign in to confirm you're not a bot' error**\n"
            "   • Update your cookies using /update_cookies\n"
            "   • Make sure you're logged into YouTube in browser\n"
            "   • Export cookies while on youtube.com\n\n"
            "2. **Age-restricted videos not downloading**\n"
            "   • Cookies must contain login information\n"
            "   • Re-export cookies after fresh login\n"
            "   • Use Chrome for best results\n\n"
            "3. **How to export cookies (Chrome):**\n"
            "   a. Install 'Get cookies.txt' extension\n"
            "   b. Login to youtube.com\n"
            "   c. Click the extension icon\n"
            "   d. Click 'Export' button\n"
            "   e. Send the file to bot\n\n"
            "4. **Still having issues?**\n"
            "   • Try clearing browser cookies and re-login\n"
            "   • Use Incognito mode for clean cookies\n"
            "   • Contact support if problem persists\n"
        )
        
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel the current operation."""
        user_id = update.effective_user.id
        
        if user_id in waiting_for_cookies:
            del waiting_for_cookies[user_id]
            await update.message.reply_text("✅ Cookie update cancelled.")
        elif user_id in user_states:
            del user_states[user_id]
            await update.message.reply_text("✅ Operation cancelled.")
        else:
            await update.message.reply_text("ℹ️ No active operation to cancel.")

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle all document uploads - both cookies and bulk files."""
        user_id = update.effective_user.id
        document = update.message.document
        file_name = document.file_name.lower()
        
        # Check if user is waiting for cookies
        if user_id in waiting_for_cookies and waiting_for_cookies[user_id]:
            # Handle as cookies file
            await self.handle_cookies_file(update, context)
            return
        
        # Check if it's a .txt file (for bulk download)
        if file_name.endswith('.txt'):
            # Check if it might be a cookies file
            if file_name == 'cookies.txt':
                await update.message.reply_text(
                    "📄 This looks like a cookies file.\n"
                    "If you want to update cookies, use /update_cookies first.\n"
                    "If this is a file with YouTube links, please rename it to something else."
                )
                return
            
            # Handle as bulk download file
            await self.handle_bulk_file(update, context)
            return
        
        # If not .txt file
        await update.message.reply_text(
            "❌ Unsupported file type.\n"
            "Please send:\n"
            "• A .txt file with YouTube links for bulk download\n"
            "• A cookies.txt file (use /update_cookies first)"
        )

    async def handle_cookies_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle cookies.txt file upload."""
        user_id = update.effective_user.id
        
        try:
            # Get the document
            document = update.message.document
            
            # Check if it's a text file
            if not document.file_name.endswith('.txt'):
                await update.message.reply_text(
                    "❌ Please send a .txt file.\n"
                    "The file should be named 'cookies.txt'"
                )
                return
            
            # Send processing message
            status_msg = await update.message.reply_text("🔍 Processing cookies file...")
            
            # Download the file
            file = await context.bot.get_file(document.file_id)
            temp_path = TEMP_DIR / f"cookies_{user_id}_{datetime.now().timestamp()}.txt"
            await file.download_to_drive(temp_path)
            
            # Update cookies
            result = self.cookie_manager.update_cookies(temp_path, user_id)
            
            if result['success']:
                # Verify cookies work
                await status_msg.edit_text("✅ Cookies saved! Verifying...")
                
                verification = await self.downloader.verify_cookies(user_id)
                
                if verification:
                    final_message = (
                        f"{result['message']}\n\n"
                        f"🔍 **Verification:** ✅ Working!\n"
                        f"You can now download all types of videos."
                    )
                else:
                    final_message = (
                        f"{result['message']}\n\n"
                        f"⚠️ **Note:** Cookies saved but may need refresh.\n"
                        "Try downloading a video to test."
                    )
                
                # Clear waiting state
                if user_id in waiting_for_cookies:
                    del waiting_for_cookies[user_id]
            else:
                final_message = result['message']
            
            await status_msg.edit_text(final_message, parse_mode=ParseMode.MARKDOWN)
            
            # Cleanup
            temp_path.unlink(missing_ok=True)
            
        except Exception as e:
            logger.error(f"Error updating cookies: {e}")
            await update.message.reply_text(
                "❌ Error processing cookies file.\n"
                "Please ensure you're sending a valid cookies.txt file."
            )
            
            # Clear waiting state on error
            if user_id in waiting_for_cookies:
                del waiting_for_cookies[user_id]

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
            invalid_urls = []
            
            for url in urls:
                if self.downloader.is_youtube_url(url):
                    valid_urls.append(url)
                else:
                    invalid_urls.append(url)
                    
            if not valid_urls:
                await update.message.reply_text(
                    "❌ No valid YouTube URLs found in the file.\n"
                    "Please make sure each line contains a valid YouTube URL."
                )
                temp_path.unlink()
                return
                
            # Show summary
            summary = (
                f"📁 **Bulk Download Detected**\n\n"
                f"📊 **Files found:** {len(urls)} lines\n"
                f"✅ **Valid YouTube URLs:** {len(valid_urls)}\n"
            )
            
            if invalid_urls:
                summary += f"❌ **Invalid URLs:** {len(invalid_urls)}\n"
                if len(invalid_urls) <= 5:
                    summary += "\nInvalid URLs:\n"
                    for url in invalid_urls[:5]:
                        summary += f"• {url[:50]}...\n"
            
            # Ask for resolution
            keyboard = [
                [
                    InlineKeyboardButton("360p", callback_data=f"bulk_res:18_{len(valid_urls)}"),
                    InlineKeyboardButton("480p", callback_data=f"bulk_res:135_{len(valid_urls)}"),
                ],
                [
                    InlineKeyboardButton("720p", callback_data=f"bulk_res:22_{len(valid_urls)}"),
                    InlineKeyboardButton("1080p", callback_data=f"bulk_res:137_{len(valid_urls)}"),
                ],
                [
                    InlineKeyboardButton("Best Quality", callback_data=f"bulk_res:best_{len(valid_urls)}"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            summary += f"\n👇 **Select resolution for {len(valid_urls)} videos:**"
            
            # Store bulk info
            user_states[user_id] = {
                'bulk_urls': valid_urls,
                'current_index': 0,
                'total_count': len(valid_urls),
                'invalid_urls': invalid_urls
            }
            
            await update.message.reply_text(
                summary,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Cleanup
            temp_path.unlink()
            
        except Exception as e:
            logger.error(f"Error handling bulk file: {e}")
            await update.message.reply_text(
                f"❌ Error processing bulk file:\n{str(e)[:200]}"
            )

    async def handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages containing YouTube URLs."""
        text = update.message.text.strip()
        user_id = update.effective_user.id
        
        # Check if it's a YouTube URL
        if not self.downloader.is_youtube_url(text):
            await update.message.reply_text(
                "❌ Please send a valid YouTube URL.\n"
                "Example: https://www.youtube.com/watch?v=dQw4w9WgXcQ"
            )
            return
            
        # Get video info
        status_msg = await update.message.reply_text("🔍 Fetching video information...")
        
        try:
            video_info = await self.downloader.get_video_info(text, user_id)
            
            if not video_info:
                await status_msg.edit_text(
                    "❌ Failed to fetch video information.\n"
                    "Possible reasons:\n"
                    "• Video is private/restricted\n"
                    "• Need updated cookies (use /update_cookies)\n"
                    "• Network error"
                )
                return
                
            # Store video info for this user
            user_states[user_id] = {
                'video_url': text,
                'video_info': video_info,
                'status_message': status_msg
            }
            
            # Create resolution buttons
            keyboard = []
            formats_added = set()
            
            for format_info in video_info['formats']:
                format_id = format_info['format_id']
                if format_id not in formats_added:
                    button_text = f"{format_info['resolution']} ({format_info['ext']})"
                    
                    # Add file size if available
                    if format_info.get('filesize'):
                        size_mb = format_info['filesize'] / (1024 * 1024)
                        button_text += f" [{size_mb:.1f}MB]"
                    
                    callback_data = f"res:{format_info['format_id']}"
                    keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
                    formats_added.add(format_id)
            
            # Add best quality option
            keyboard.append([InlineKeyboardButton("🌟 Best Quality Available", callback_data="res:best")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Send video info with thumbnail
            caption = (
                f"🎬 **{video_info['title']}**\n\n"
                f"📊 **Duration:** {video_info['duration_string']}\n"
                f"👁️ **Views:** {video_info['view_count']:,}\n"
                f"👤 **Channel:** {video_info['channel']}\n"
                f"📅 **Upload Date:** {video_info['upload_date']}\n\n"
                f"👇 **Select Resolution:**"
            )
            
            # Send thumbnail if available
            if video_info.get('thumbnail'):
                try:
                    await update.message.reply_photo(
                        photo=video_info['thumbnail'],
                        caption=caption,
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=reply_markup
                    )
                except:
                    await update.message.reply_text(
                        caption,
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
            await status_msg.edit_text(
                f"❌ Error fetching video information:\n{str(e)[:200]}"
            )

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
            parts = callback_data.split(':')[1].split('_')
            format_id = parts[0]
            video_count = int(parts[1]) if len(parts) > 1 else 0
            
            await self.process_bulk_download(query, user_id, format_id, video_count)

    async def download_and_send_video(self, query, video_url, format_id, user_id, video_info):
        """Download and send a single video."""
        try:
            # Update status
            status_msg = await query.message.reply_text(
                f"⏬ **Starting download...**\n"
                f"🎬 **{video_info['title'][:50]}...**\n"
                f"🎯 **Quality:** {format_id if format_id != 'best' else 'Best Available'}"
            )
            
            # Create progress handler
            progress_msg = await query.message.reply_text(
                f"📥 **Downloading:** {video_info['title'][:50]}...\n"
                f"📊 **Progress:** 0%\n"
                f"🔄 **Status:** Preparing..."
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
                await progress_msg.edit_text(
                    f"❌ **Download failed**\n"
                    f"**Error:** {download_result.get('error', 'Unknown error')}"
                )
                await status_msg.delete()
                return
                
            # Upload to Telegram
            await progress_msg.edit_text(
                f"✅ **Download Complete!**\n"
                f"📤 **Now Uploading to Telegram...**\n"
                f"📦 **Size:** {download_result['file_size_mb']:.1f} MB\n"
                f"⏳ **Progress:** 0%"
            )
            
            # Create caption
            caption = (
                f"🎬 **{video_info['title']}**\n"
                f"📊 **Quality:** {download_result.get('resolution_display', download_result['resolution'])}\n"
                f"📦 **Size:** {download_result['file_size_mb']:.1f} MB\n"
                f"⏱️ **Duration:** {video_info['duration_string']}\n"
                f"👤 **Channel:** {video_info['channel']}\n\n"
                f"✅ Downloaded via @YouTubeDownloaderBot"
            )
            
            # Send video with progress tracking
            try:
                with open(download_result['filepath'], 'rb') as video_file:
                    # Start upload
                    await query.message.reply_video(
                        video=InputFile(
                            video_file, 
                            filename=download_result['filename']
                        ),
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
            except Exception as e:
                logger.error(f"Error uploading video: {e}")
                await query.message.reply_text(
                    f"✅ **Download Complete!**\n"
                    f"📦 **Size:** {download_result['file_size_mb']:.1f} MB\n\n"
                    f"❌ **Upload failed:** {str(e)[:100]}\n"
                    f"The file was downloaded but couldn't be sent to Telegram."
                )
            
            # Cleanup
            await progress_msg.delete()
            await status_msg.delete()
            
            # Remove downloaded file
            Path(download_result['filepath']).unlink(missing_ok=True)
            
            # Clear user state
            if user_id in user_states:
                del user_states[user_id]
            
        except Exception as e:
            logger.error(f"Error in download_and_send_video: {e}")
            await query.message.reply_text(
                f"❌ **Error processing video:**\n{str(e)[:200]}"
            )

    async def process_bulk_download(self, query, user_id, format_id, video_count):
        """Process bulk download queue."""
        if user_id not in user_states:
            await query.edit_message_text("❌ Session expired. Please send the file again.")
            return
            
        bulk_info = user_states[user_id]
        urls = bulk_info['bulk_urls']
        
        await query.edit_message_text(
            f"📁 **Bulk Download Started**\n\n"
            f"📊 **Total Videos:** {len(urls)}\n"
            f"🎯 **Quality:** {format_id if format_id != 'best' else 'Best Available'}\n"
            f"⏳ **Processing...**"
        )
        
        success_count = 0
        failed_count = 0
        failed_videos = []
        
        for i, url in enumerate(urls, 1):
            try:
                # Status message
                status_msg = await query.message.reply_text(
                    f"🔄 **Processing {i}/{len(urls)}**\n"
                    f"📥 Getting video info..."
                )
                
                # Get video info
                video_info = await self.downloader.get_video_info(url, user_id)
                
                if not video_info:
                    await status_msg.edit_text(
                        f"❌ **Failed {i}/{len(urls)}**\n"
                        f"Could not get video info"
                    )
                    failed_count += 1
                    failed_videos.append(f"{url} - Info not found")
                    await asyncio.sleep(2)
                    continue
                
                await status_msg.edit_text(
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
                    try:
                        with open(download_result['filepath'], 'rb') as video_file:
                            await query.message.reply_video(
                                video=InputFile(video_file),
                                caption=f"🎬 {video_info['title'][:100]}",
                                supports_streaming=True
                            )
                        success_count += 1
                        
                        await status_msg.edit_text(
                            f"✅ **Completed {i}/{len(urls)}**\n"
                            f"🎬 **{video_info['title'][:50]}...**"
                        )
                        
                    except Exception as e:
                        await status_msg.edit_text(
                            f"⚠️ **Downloaded but upload failed {i}/{len(urls)}**\n"
                            f"🎬 **{video_info['title'][:50]}...**\n"
                            f"Error: {str(e)[:100]}"
                        )
                        failed_count += 1
                        failed_videos.append(f"{video_info['title']} - Upload failed")
                    
                    # Cleanup
                    Path(download_result['filepath']).unlink(missing_ok=True)
                else:
                    await status_msg.edit_text(
                        f"❌ **Failed {i}/{len(urls)}**\n"
                        f"🎬 **{video_info['title'][:50]}...**\n"
                        f"Error: {download_result.get('error', 'Unknown')[:100]}"
                    )
                    failed_count += 1
                    failed_videos.append(f"{video_info['title']} - {download_result.get('error', 'Unknown')}")
                
                # Delay between downloads
                await asyncio.sleep(3)
                
            except Exception as e:
                logger.error(f"Error in bulk download item {i}: {e}")
                failed_count += 1
                failed_videos.append(f"URL {i} - {str(e)[:100]}")
                
                if 'status_msg' in locals():
                    await status_msg.edit_text(
                        f"❌ **Error {i}/{len(urls)}**\n"
                        f"Exception: {str(e)[:100]}"
                    )
        
        # Final report
        report = (
            f"✅ **Bulk Download Complete!**\n\n"
            f"📊 **Results:**\n"
            f"✅ Successful: {success_count}\n"
            f"❌ Failed: {failed_count}\n"
            f"📁 Total: {len(urls)}\n"
        )
        
        if failed_videos and len(failed_videos) <= 10:
            report += "\n❌ **Failed videos:**\n"
            for failed in failed_videos[:10]:
                report += f"• {failed[:80]}...\n"
        elif failed_videos:
            report += f"\n❌ **Failed videos:** {len(failed_videos)} (too many to list)\n"
        
        await query.message.reply_text(report, parse_mode=ParseMode.MARKDOWN)
        
        # Cleanup user state
        if user_id in user_states:
            del user_states[user_id]

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show bot status."""
        user_id = update.effective_user.id
        
        # Get cookies status
        cookie_status = self.cookie_manager.get_cookies_status(user_id)
        
        # Get disk space info
        try:
            import shutil
            total, used, free = shutil.disk_usage("/")
            disk_info = f"{free // (2**30)}GB free"
        except:
            disk_info = "Unknown"
        
        status = (
            "🤖 **Bot Status**\n\n"
            "✅ **Operational**\n"
            f"👤 **Your ID:** {user_id}\n"
            f"🍪 **Cookies:** {cookie_status['message']}\n"
            f"💾 **Storage:** {disk_info}\n"
            f"⚡ **Version:** 2.1.0\n\n"
            f"🔄 **Last Update:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"🏠 **Host:** Render"
        )
        await update.message.reply_text(status, parse_mode=ParseMode.MARKDOWN)

    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle errors."""
        logger.error(f"Update {update} caused error {context.error}")
        
        if update and update.effective_message:
            try:
                error_msg = str(context.error)[:200]
                await update.effective_message.reply_text(
                    f"❌ An error occurred:\n`{error_msg}`\n\n"
                    "Please try again or contact support.",
                    parse_mode=ParseMode.MARKDOWN
                )
            except:
                pass

def main():
    """Start the bot."""
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable not set")
    
    bot = YouTubeDownloadBot()
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("help", bot.help_command))
    application.add_handler(CommandHandler("update_cookies", bot.update_cookies))
    application.add_handler(CommandHandler("cookies_help", bot.cookies_help))
    application.add_handler(CommandHandler("status", bot.status_command))
    application.add_handler(CommandHandler("cancel", bot.cancel))
    
    # Handle documents (both cookies and bulk files)
    application.add_handler(MessageHandler(
        filters.Document.ALL & filters.ChatType.PRIVATE,
        bot.handle_document
    ))
    
    # Handle YouTube URLs
    application.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND,
        bot.handle_text_message
    ))
    
    # Handle inline keyboard buttons
    application.add_handler(CallbackQueryHandler(bot.handle_resolution_selection))
    
    # Error handler
    application.add_error_handler(bot.error_handler)
    
    # Start the bot
    print("🤖 Bot is starting...")
    print(f"📁 Temp directory: {TEMP_DIR}")
    print(f"🍪 Cookies directory: {COOKIES_DIR}")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()