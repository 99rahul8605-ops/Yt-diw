import asyncio
import re
import json
import random
import time
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any, Tuple
import yt_dlp
from datetime import datetime
import logging
import os

logger = logging.getLogger(__name__)

class YouTubeDownloader:
    def __init__(self, cookie_manager):
        self.cookie_manager = cookie_manager
        self.temp_dir = Path("temp")
        self.temp_dir.mkdir(exist_ok=True)
        
        # Enhanced user agents
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        ]
        
        # Rate limiting
        self.last_request_time = 0
        self.min_request_interval = 1
    
    def is_youtube_url(self, url: str) -> bool:
        """STEP 1: Validate YouTube URL"""
        patterns = [
            r'^(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+$',
            r'^https?://youtu\.be/[a-zA-Z0-9_-]+',
            r'^https?://www\.youtube\.com/shorts/[a-zA-Z0-9_-]+',
        ]
        return any(re.match(pattern, url, re.IGNORECASE) for pattern in patterns)
    
    async def get_video_info(self, url: str, user_id: int) -> Optional[Dict]:
        """STEP 2: Fetch video information"""
        self._rate_limit()
        
        ydl_opts = self._get_ydl_opts(user_id, extract_flat=False)
        
        try:
            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(
                None,
                lambda: self._extract_info_with_retry(url, ydl_opts)
            )
            
            if not info:
                return None
            
            # Get available formats
            formats = []
            seen_formats = set()
            
            for f in info.get('formats', []):
                if f.get('vcodec') != 'none':  # Has video
                    height = f.get('height', 0)
                    if height:
                        resolution = f"{height}p"
                    else:
                        resolution = "unknown"
                    
                    fps = f.get('fps')
                    if fps:
                        resolution += f"@{int(fps)}fps"
                    
                    has_audio = f.get('acodec') != 'none'
                    format_id = f.get('format_id', 'unknown')
                    
                    if format_id in seen_formats:
                        continue
                    
                    seen_formats.add(format_id)
                    
                    format_info = {
                        'format_id': format_id,
                        'resolution': resolution,
                        'resolution_display': f"{resolution}{' + Audio' if has_audio else ' (Video only)'}",
                        'ext': f.get('ext', 'mp4'),
                        'filesize': f.get('filesize'),
                        'vcodec': f.get('vcodec', 'unknown'),
                        'acodec': f.get('acodec', 'none'),
                        'has_audio': has_audio,
                    }
                    
                    formats.append(format_info)
            
            # Sort by resolution
            def get_height(format_info):
                res = format_info['resolution'].split('p')[0]
                try:
                    return int(res)
                except:
                    return 0
            
            formats.sort(key=get_height, reverse=True)
            
            # Get best thumbnail
            thumbnail = info.get('thumbnail')
            if not thumbnail:
                thumbnails = info.get('thumbnails', [])
                if thumbnails:
                    thumbnails.sort(key=lambda x: x.get('height', 0), reverse=True)
                    thumbnail = thumbnails[0].get('url')
            
            return {
                'title': info.get('title', 'Unknown Title'),
                'duration': info.get('duration', 0),
                'duration_string': self._format_duration(info.get('duration', 0)),
                'view_count': info.get('view_count', 0),
                'upload_date': self._format_date(info.get('upload_date', '')),
                'thumbnail': thumbnail,
                'channel': info.get('channel', 'Unknown Channel'),
                'description': info.get('description', '')[:200] + '...',
                'formats': formats[:8],
                'webpage_url': info.get('webpage_url', url),
                'age_limit': info.get('age_limit', 0),
                'is_live': info.get('is_live', False),
            }
                
        except Exception as e:
            logger.error(f"Error getting video info: {e}")
            return None
    
    # NEW METHOD: IMPLEMENT 8-STEP PROCESS
    async def download_video_mp4(self, url: str, user_id: int, 
                                 progress_callback: Optional[Callable] = None) -> Dict:
        """
        IMPLEMENT 8-STEP PROCESS for MP4 download
        Returns: Dict with 'success', 'filepath', 'filename', 'file_size_mb', etc.
        """
        try:
            # STEP 1: Validate URL
            if not self.is_youtube_url(url):
                return {
                    'success': False,
                    'error': 'Invalid YouTube URL'
                }
            
            # STEP 2: Get video info
            video_info = await self.get_video_info(url, user_id)
            if not video_info:
                return {
                    'success': False,
                    'error': 'Could not fetch video information'
                }
            
            # Sanitize title for filename
            title = self._sanitize_filename(video_info['title'])
            
            # STEP 3 & 4: Download with quality selection
            # Format: bestvideo(height<=720) + bestaudio, fallback = best
            format_str = 'bestvideo[height<=720]+bestaudio/best'
            
            # Create temp files
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            temp_base = self.temp_dir / f"{timestamp}_{title}"
            temp_video = str(temp_base) + "_video.%(ext)s"
            temp_output = str(temp_base) + "_output.mp4"
            temp_thumbnail = str(temp_base) + "_thumb.jpg"
            
            # Get cookies path
            cookies_path = self.cookie_manager.get_cookies_path(user_id)
            
            # Build yt-dlp command
            cmd = [
                'yt-dlp',
                '-f', format_str,
                '--output', temp_video,
                '--merge-output-format', 'mp4',
                '--no-playlist',
                '--no-warnings',
                '--quiet',
            ]
            
            # Add cookies if available
            if cookies_path and cookies_path.exists():
                cmd.extend(['--cookies', str(cookies_path)])
            
            cmd.append(url)
            
            # Download video
            logger.info(f"Downloading video: {title}")
            
            if progress_callback:
                # For progress updates
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                # Process output for progress
                while True:
                    line = await process.stdout.readline()
                    if not line:
                        break
                    # Parse progress from line
                    # (You can enhance this with proper progress parsing)
                    
                await process.wait()
            else:
                process = await asyncio.create_subprocess_exec(*cmd)
                await process.wait()
            
            # Find downloaded file
            downloaded_file = None
            for ext in ['.mp4', '.mkv', '.webm']:
                test_file = str(temp_base) + f"_video{ext}"
                if os.path.exists(test_file):
                    downloaded_file = test_file
                    break
            
            if not downloaded_file:
                return {
                    'success': False,
                    'error': 'Downloaded file not found'
                }
            
            # STEP 5: Rename to output file
            os.rename(downloaded_file, temp_output)
            
            # STEP 6: Generate thumbnail
            thumbnail_result = await self._generate_thumbnail(temp_output, temp_thumbnail)
            
            # Get file info
            file_size = os.path.getsize(temp_output)
            
            return {
                'success': True,
                'filepath': temp_output,
                'filename': f"{title}.mp4",
                'title': video_info['title'],
                'file_size': file_size,
                'file_size_mb': file_size / (1024 * 1024),
                'duration': video_info['duration'],
                'thumbnail_path': temp_thumbnail if thumbnail_result else None,
                'width': 1280,  # Default, can be extracted from video
                'height': 720,   # Default, can be extracted from video
                'resolution': '720p (or best)',
                'resolution_display': '720p or best available',
            }
            
        except Exception as e:
            logger.error(f"Error in 8-step process: {e}")
            return {
                'success': False,
                'error': str(e)[:200]
            }
    
    async def _generate_thumbnail(self, video_path: str, thumbnail_path: str) -> bool:
        """STEP 6: Generate thumbnail at 10 seconds"""
        try:
            cmd = [
                'ffmpeg',
                '-ss', '00:00:10',
                '-i', video_path,
                '-vframes', '1',
                '-q:v', '2',
                '-loglevel', 'error',
                thumbnail_path,
                '-y'
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.wait()
            
            return os.path.exists(thumbnail_path)
        except Exception as e:
            logger.warning(f"Thumbnail generation failed: {e}")
            return False
    
    def _sanitize_filename(self, title: str) -> str:
        """Sanitize filename"""
        # Remove invalid characters
        sanitized = re.sub(r'[<>:"/\\|?*]', '', title)
        sanitized = re.sub(r'\s+', ' ', sanitized)
        return sanitized.strip()[:100]
    
    def _get_ydl_opts(self, user_id: int, extract_flat: bool = False) -> Dict:
        """Get yt-dlp options with cookies"""
        self._rate_limit()
        
        cookies_path = self.cookie_manager.get_cookies_path(user_id)
        
        opts = {
            'quiet': True,
            'no_warnings': False,
            'ignoreerrors': True,
            'no_color': True,
            'extract_flat': extract_flat,
            'http_headers': {
                'User-Agent': random.choice(self.user_agents),
            },
            'retries': 3,
            'fragment_retries': 3,
            'sleep_interval': 2,
        }
        
        if cookies_path and cookies_path.exists():
            opts['cookiefile'] = str(cookies_path)
        
        return opts
    
    def _rate_limit(self):
        """Rate limiting"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        if time_since_last < self.min_request_interval:
            sleep_time = self.min_request_interval - time_since_last
            if sleep_time > 0.1:
                time.sleep(sleep_time)
        
        self.last_request_time = time.time()
    
    def _extract_info_with_retry(self, url: str, ydl_opts: Dict, max_attempts: int = 2):
        """Extract info with retry"""
        for attempt in range(max_attempts):
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if info:
                        return info
                    time.sleep(2)
            except Exception as e:
                logger.error(f"Attempt {attempt + 1} failed: {e}")
                time.sleep(3)
        return None
    
    def _format_duration(self, seconds: int) -> str:
        """Format duration"""
        if not seconds:
            return "0:00"
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes}:{secs:02d}"
    
    def _format_date(self, date_str: str) -> str:
        """Format date"""
        if not date_str or len(date_str) != 8:
            return "Unknown"
        try:
            year = date_str[:4]
            month = date_str[4:6]
            day = date_str[6:8]
            return f"{day}/{month}/{year}"
        except:
            return date_str
    
    async def verify_cookies(self, user_id: int) -> bool:
        """Verify cookies"""
        test_url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
        try:
            info = await self.get_video_info(test_url, user_id)
            return info is not None
        except:
            return False