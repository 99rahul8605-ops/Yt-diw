"""
Configuration settings for YouTube Downloader Bot
"""

import os
from pathlib import Path

# Directories
BASE_DIR = Path(__file__).parent.parent
TEMP_DIR = BASE_DIR / "temp"
COOKIES_DIR = BASE_DIR / "cookies"
LOGS_DIR = BASE_DIR / "logs"

# Ensure directories exist
for directory in [TEMP_DIR, COOKIES_DIR, LOGS_DIR]:
    directory.mkdir(exist_ok=True)

# YouTube settings
YTDL_OPTIONS = {
    # Rate limiting
    'min_request_interval': 5,  # Minimum seconds between requests
    
    # Retry settings
    'max_retries': 3,
    'retry_delay': 5,
    
    # Format preferences
    'preferred_formats': ['mp4', 'webm'],
    'preferred_qualities': ['720p', '480p', '360p'],
    
    # Size limits
    'max_file_size_mb': 2000,  # 2GB Telegram limit
    'max_duration_seconds': 7200,  # 2 hours
    
    # Proxy settings (optional)
    'use_proxy': False,
    'proxy_url': None,
}

# Bot settings
BOT_SETTINGS = {
    'max_concurrent_downloads': 2,
    'download_timeout': 1800,  # 30 minutes
    'upload_timeout': 600,  # 10 minutes
    
    # Cleanup
    'cleanup_interval_hours': 24,
    'max_temp_files': 50,
}

# Logging settings
LOGGING_CONFIG = {
    'level': 'INFO',
    'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    'file': LOGS_DIR / 'bot.log',
    'max_size_mb': 10,
    'backup_count': 5,
}
