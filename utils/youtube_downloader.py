import asyncio
import re
import json
import random
import time
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any
import yt_dlp
from datetime import datetime

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
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1',
        ]
        
    def is_youtube_url(self, url: str) -> bool:
        """Check if the URL is a valid YouTube URL."""
        patterns = [
            r'^(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+$',
            r'^https?://youtu\.be/[a-zA-Z0-9_-]+',
            r'^https?://www\.youtube\.com/shorts/[a-zA-Z0-9_-]+',
            r'^https?://www\.youtube\.com/embed/[a-zA-Z0-9_-]+',
            r'^https?://www\.youtube\.com/live/[a-zA-Z0-9_-]+',
        ]
        
        return any(re.match(pattern, url, re.IGNORECASE) for pattern in patterns)
    
    def _get_ydl_opts(self, user_id: int, extract_flat: bool = False) -> Dict:
        """Get YouTube DL options with enhanced configuration."""
        cookies_path = self.cookie_manager.get_cookies_path(user_id)
        
        opts = {
            'quiet': True,
            'no_warnings': False,
            'ignoreerrors': True,
            'no_color': True,
            'extract_flat': extract_flat,
            
            # Enhanced headers
            'http_headers': {
                'User-Agent': random.choice(self.user_agents),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Cache-Control': 'max-age=0',
            },
            
            # Retry configuration
            'retries': 15,
            'fragment_retries': 10,
            'skip_unavailable_fragments': True,
            'continuedl': True,
            
            # Throttling
            'sleep_interval': 2,
            'max_sleep_interval': 8,
            'sleep_interval_requests': 2,
            
            # Proxy (optional, uncomment if needed)
            # 'proxy': 'http://proxy:port',
        }
        
        # Add cookies if available
        if cookies_path and cookies_path.exists():
            opts['cookiefile'] = str(cookies_path)
            print(f"✅ Using cookies from: {cookies_path}")
        else:
            print("⚠️ No cookies found, some videos may not work")
        
        return opts
    
    async def get_video_info(self, url: str, user_id: int) -> Optional[Dict]:
        """Get video information including available formats."""
        loop = asyncio.get_event_loop()
        
        try:
            ydl_opts = self._get_ydl_opts(user_id, extract_flat=False)
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Extract info with retry logic
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        info = await loop.run_in_executor(
                            None, 
                            lambda: ydl.extract_info(url, download=False)
                        )
                        
                        if info:
                            break
                    except yt_dlp.utils.DownloadError as e:
                        if attempt == max_retries - 1:
                            print(f"Failed to get info after {max_retries} attempts: {e}")
                            return None
                        print(f"Attempt {attempt + 1} failed, retrying...")
                        await asyncio.sleep(2)
                
                if not info:
                    print(f"No info returned for {url}")
                    return None
                
                # Get available video formats
                formats = []
                seen_formats = set()
                
                for f in info.get('formats', []):
                    if f.get('vcodec') != 'none':  # Has video
                        # Create format identifier
                        resolution = f"{f.get('height', 'N/A')}p"
                        fps = f.get('fps')
                        if fps:
                            resolution += f"@{int(fps)}fps"
                        
                        # Check if audio is included
                        has_audio = f.get('acodec') != 'none'
                        audio_note = " + Audio" if has_audio else " (Video only)"
                        
                        format_id = f['format_id']
                        if format_id in seen_formats:
                            continue
                        
                        seen_formats.add(format_id)
                        
                        format_info = {
                            'format_id': format_id,
                            'resolution': resolution,
                            'resolution_display': f"{resolution}{audio_note}",
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
                    return int(res) if res.isdigit() else 0
                
                formats.sort(key=get_height, reverse=True)
                
                # Get best thumbnail
                thumbnail = info.get('thumbnail')
                if not thumbnail:
                    thumbnails = info.get('thumbnails', [])
                    if thumbnails:
                        # Get highest resolution thumbnail
                        thumbnails.sort(key=lambda x: x.get('height', 0), reverse=True)
                        thumbnail = thumbnails[0].get('url')
                
                return {
                    'title': info.get('title', 'Unknown Title'),
                    'duration': info.get('duration', 0),
                    'duration_string': self._format_duration(info.get('duration', 0)),
                    'view_count': info.get('view_count', 0),
                    'like_count': info.get('like_count', 0),
                    'upload_date': self._format_date(info.get('upload_date', '')),
                    'thumbnail': thumbnail,
                    'channel': info.get('channel', 'Unknown Channel'),
                    'description': info.get('description', '')[:200] + '...',
                    'formats': formats[:12],  # Limit to 12 formats
                    'webpage_url': info.get('webpage_url', url),
                    'age_limit': info.get('age_limit', 0),
                    'is_live': info.get('is_live', False),
                }
                
        except Exception as e:
            print(f"Error getting video info for {url}: {e}")
            return None
    
    async def download_video(self, url: str, format_id: str, user_id: int, 
                           progress_callback: Optional[Callable] = None) -> Dict:
        """Download video with specified format."""
        loop = asyncio.get_event_loop()
        
        # Create output template
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_template = str(self.temp_dir / f"{timestamp}_%(title).100s.%(ext)s")
        
        # Get base options
        ydl_opts = self._get_ydl_opts(user_id)
        
        # Handle format selection
        if format_id == 'best':
            ydl_opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
        else:
            # Try to find a format with video+audio for the given format_id
            ydl_opts['format'] = f'{format_id}+bestaudio/best'
        
        # Add download-specific options
        ydl_opts.update({
            'outtmpl': output_template,
            'merge_output_format': 'mp4',
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }],
            'concurrent_fragment_downloads': 3,
            'buffersize': 1024 * 1024 * 16,  # 16MB buffer
            'http_chunk_size': 10485760,  # 10MB chunks
        })
        
        # Add progress hook
        if progress_callback:
            ydl_opts['progress_hooks'] = [self._create_progress_hook(progress_callback)]
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                print(f"Starting download with format: {format_id}")
                
                info = await loop.run_in_executor(
                    None,
                    lambda: ydl.extract_info(url, download=True)
                )
                
                if not info:
                    return {
                        'success': False,
                        'error': 'Failed to extract video info'
                    }
                
                # Get downloaded file path
                downloaded_file = ydl.prepare_filename(info)
                
                # Try to find the actual file
                file_path = None
                possible_extensions = ['.mp4', '.mkv', '.webm', '.m4a', '.mp3']
                
                for ext in possible_extensions:
                    # Try with extension from info
                    base_name = downloaded_file.rsplit('.', 1)[0]
                    test_path = f"{base_name}{ext}"
                    if Path(test_path).exists():
                        file_path = test_path
                        break
                
                # If still not found, check for files with similar names
                if not file_path:
                    for file in self.temp_dir.glob(f"{timestamp}_*"):
                        if file.is_file():
                            file_path = str(file)
                            break
                
                if file_path and Path(file_path).exists():
                    file_size = Path(file_path).stat().st_size
                    
                    # Check file size limit
                    if file_size > 2000 * 1024 * 1024:  # 2GB
                        return {
                            'success': False,
                            'error': f'File too large ({file_size/(1024*1024):.1f}MB). Telegram limit is 2GB.'
                        }
                    
                    # Get resolution info
                    resolution_display = "Best Available" if format_id == 'best' else f"{format_id}"
                    if 'height' in info:
                        resolution_display = f"{info['height']}p"
                    
                    return {
                        'success': True,
                        'filepath': file_path,
                        'filename': f"{info['title'][:100]}.mp4",
                        'title': info['title'],
                        'resolution': format_id,
                        'resolution_display': resolution_display,
                        'file_size': file_size,
                        'file_size_mb': file_size / (1024 * 1024),
                        'duration': info.get('duration', 0),
                        'width': info.get('width', 1280),
                        'height': info.get('height', 720),
                        'has_audio': info.get('acodec') != 'none',
                    }
                else:
                    return {
                        'success': False,
                        'error': 'Downloaded file not found'
                    }
                    
        except yt_dlp.utils.DownloadError as e:
            print(f"DownloadError: {e}")
            
            # Try with simpler format if specific format failed
            if format_id != '18' and format_id != 'best':
                print(f"Trying fallback format 18 (360p)")
                return await self.download_video(url, '18', user_id, progress_callback)
            
            return {
                'success': False,
                'error': f'Download error: {str(e)[:200]}'
            }
        except Exception as e:
            print(f"Unexpected error in download_video: {e}")
            return {
                'success': False,
                'error': str(e)[:200]
            }
    
    def _create_progress_hook(self, progress_callback: Callable):
        """Create progress hook for yt-dlp."""
        def hook(d):
            if d['status'] == 'downloading':
                downloaded = d.get('downloaded_bytes', 0)
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                
                if total > 0:
                    percentage = (downloaded / total) * 100
                    speed = d.get('speed', 0)
                    eta = d.get('eta', 0)
                    
                    progress_data = {
                        'percentage': percentage,
                        'downloaded_mb': downloaded / (1024 * 1024),
                        'total_mb': total / (1024 * 1024),
                        'speed_mb': speed / (1024 * 1024) if speed else 0,
                        'eta_seconds': eta,
                        'status': 'downloading'
                    }
                    
                    try:
                        progress_callback(progress_data)
                    except:
                        pass
            elif d['status'] == 'finished':
                progress_data = {
                    'percentage': 100,
                    'status': 'finished'
                }
                try:
                    progress_callback(progress_data)
                except:
                    pass
                    
        return hook
    
    def _format_duration(self, seconds: int) -> str:
        """Format duration in seconds to HH:MM:SS."""
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
        """Format YYYYMMDD date string."""
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
        """Verify if cookies are working."""
        test_urls = [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",  # Public video
            "https://www.youtube.com/watch?v=jNQXAC9IVRw",  # First YouTube video
        ]
        
        for test_url in test_urls:
            try:
                info = await self.get_video_info(test_url, user_id)
                if info:
                    print(f"✅ Cookies working for: {test_url}")
                    return True
            except Exception as e:
                print(f"Cookie test failed for {test_url}: {e}")
        
        return False
    
    def cleanup_old_files(self, max_age_hours: int = 24):
        """Clean up old temporary files."""
        try:
            current_time = time.time()
            for file in self.temp_dir.glob("*"):
                if file.is_file():
                    file_age = current_time - file.stat().st_mtime
                    if file_age > max_age_hours * 3600:
                        file.unlink()
                        print(f"Cleaned up old file: {file.name}")
        except Exception as e:
            print(f"Error cleaning up files: {e}")
