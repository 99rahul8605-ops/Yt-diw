import asyncio
from typing import Dict, Any
from telegram import Message

class ProgressHandler:
    def __init__(self):
        self.emoji_cycle = ['🔄', '⚡', '📥', '🚀', '💾', '🌀']
        self.emoji_index = 0
    
    def _escape_markdown(self, text: str) -> str:
        """Escape special characters for MarkdownV2."""
        special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        for char in special_chars:
            text = text.replace(char, f'\\{char}')
        return text
    
    async def update_download_progress(self, message: Message, title: str, progress_data: Dict[str, Any]):
        """Update download progress message."""
        try:
            self.emoji_index = (self.emoji_index + 1) % len(self.emoji_cycle)
            emoji_char = self.emoji_cycle[self.emoji_index]
            
            # Format progress bar
            percentage = progress_data.get('percentage', 0)
            progress_bar = self._create_progress_bar(percentage)
            
            # Format ETA
            eta_str = self._format_eta(progress_data.get('eta_seconds', 0))
            
            # Format speed
            speed = progress_data.get('speed_mb', 0)
            if speed > 1:
                speed_str = f"{speed:.1f} MB/s"
            elif speed > 0:
                speed_str = f"{speed*1024:.0f} KB/s"
            else:
                speed_str = "Calculating..."
            
            # Escape title for Markdown
            safe_title = self._escape_markdown(title[:40])
            
            # Create status message
            status_text = (
                f"{emoji_char} *Downloading:* {safe_title}\\.\\.\\.\n\n"
                f"{progress_bar} *{percentage:.1f}%*\n\n"
                f"📊 *Progress:* {progress_data.get('downloaded_mb', 0):.1f} MB / "
                f"{progress_data.get('total_mb', 0):.1f} MB\n"
                f"⚡ *Speed:* {speed_str}\n"
                f"⏱️ *ETA:* {eta_str}\n"
                f"📁 *Status:* Downloading\\.\\.\\."
            )
            
            await message.edit_text(status_text, parse_mode="MarkdownV2")
            
        except Exception as e:
            # Don't crash if message edit fails
            pass
    
    def _create_progress_bar(self, percentage: float, length: int = 10) -> str:
        """Create a text-based progress bar."""
        filled = int(length * percentage / 100)
        empty = length - filled
        
        # Create progress bar with different characters
        filled_char = '█'
        empty_char = '░'
        current_char = '▶' if filled < length else '█'
        
        if filled < length:
            bar = filled_char * max(0, filled - 1) + current_char + empty_char * max(0, empty - 1)
        else:
            bar = filled_char * filled
        
        return f"[{bar}]"
    
    def _format_eta(self, seconds: int) -> str:
        """Format ETA seconds to readable string."""
        if seconds <= 0:
            return "Calculating..."
        
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        
        if hours > 0:
            return f"{hours}h {minutes}m {secs}s"
        elif minutes > 0:
            return f"{minutes}m {secs}s"
        else:
            return f"{secs}s"
    
    async def update_upload_progress(self, message: Message, current: int, total: int):
        """Update upload progress message."""
        try:
            percentage = (current / total) * 100 if total > 0 else 0
            progress_bar = self._create_progress_bar(percentage)
            
            status_text = (
                f"📤 *Uploading to Telegram*\n\n"
                f"{progress_bar} *{percentage:.1f}%*\n\n"
                f"📊 *Progress:* {current/(1024*1024):.1f} MB / {total/(1024*1024):.1f} MB\n"
                f"⏱️ *Status:* Uploading\\.\\.\\."
            )
            
            await message.edit_text(status_text, parse_mode="MarkdownV2")
            
        except Exception:
            pass
