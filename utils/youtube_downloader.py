import asyncio
import re
import json
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any
import yt_dlp
from datetime import datetime

class YouTubeDownloader:
    def __init__(self, cookie_manager):
        self.cookie_manager = cookie_manager
        self.temp_dir = Path("temp")
        self.temp_dir.mkdir(exist_ok=True)
        
    def is_youtube_url(self, url: str) -> bool:
        """Check if the URL is a valid YouTube URL."""
        youtube_regex = r'^(https?://)?(www\.)?(youtube\.com|youtu\.?be)/.+$'
        return re.match(youtube_regex, url) is not None
    
    async def get_video_info(self, url: str, user_id: int) -> Optional[Dict]:
        """Get video information including available formats."""
        loop = asyncio.get_event_loop()
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        
        # Add cookies if available
        cookies_path = self.cookie_manager.get_cookies_path(user_id)
        if cookies_path:
            ydl_opts['cookiefile'] = str(cookies_path)
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
                
                if not info:
                    return None
                
                # Get available video formats
                formats = []
                for f in info.get('formats', []):
                    if f.get('vcodec') != 'none' and f.get('acodec') != 'none':  # Video with audio
                        resolution = f"{f.get('height', 'N/A')}p"
                        if f.get('fps'):
                            resolution += f"@{int(f.get('fps'))}fps"
                        
                        formats.append({
                            'format_id': f['format_id'],
                            'resolution': resolution,
                            'ext': f['ext'],
                            'filesize': f.get('filesize'),
                            'vcodec': f.get('vcodec'),
                            'acodec': f.get('acodec'),
                        })
                
                # Sort by resolution (height)
                formats.sort(key=lambda x: int(x['resolution'].split('p')[0]) if x['resolution'][0].isdigit() else 0, reverse=True)
                
                return {
                    'title': info.get('title', 'Unknown'),
                    'duration': info.get('duration', 0),
                    'duration_string': self._format_duration(info.get('duration', 0)),
                    'view_count': info.get('view_count', 0),
                    'like_count': info.get('like_count', 0),
                    'upload_date': info.get('upload_date', 'Unknown'),
                    'thumbnail': info.get('thumbnail'),
                    'channel': info.get('channel', 'Unknown'),
                    'formats': formats[:10],  # Limit to top 10 formats
                }
                
        except Exception as e:
            print(f"Error getting video info: {e}")
            return None
    
    async def download_video(self, url: str, format_id: str, user_id: int, 
                           progress_callback: Optional[Callable] = None) -> Dict:
        """Download video with specified format."""
        loop = asyncio.get_event_loop()
        
        # Create output template
        output_template = str(self.temp_dir / f"%(title).50s.%(ext)s")
        
        ydl_opts = {
            'format': format_id,
            'outtmpl': output_template,
            'quiet': True,
            'no_warnings': True,
            'merge_output_format': 'mp4',
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }],
        }
        
        # Add cookies if available
        cookies_path = self.cookie_manager.get_cookies_path(user_id)
        if cookies_path:
            ydl_opts['cookiefile'] = str(cookies_path)
        
        # Add progress hook
        if progress_callback:
            ydl_opts['progress_hooks'] = [self._create_progress_hook(progress_callback)]
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))
                
                # Get downloaded file path
                downloaded_file = ydl.prepare_filename(info)
                if not Path(downloaded_file).exists():
                    # Try with mp4 extension
                    downloaded_file = downloaded_file.rsplit('.', 1)[0] + '.mp4'
                
                if Path(downloaded_file).exists():
                    file_size = Path(downloaded_file).stat().st_size
                    
                    return {
                        'success': True,
                        'filepath': downloaded_file,
                        'filename': f"{info['title'][:50]}.mp4",
                        'title': info['title'],
                        'resolution': format_id,
                        'file_size': file_size,
                        'file_size_mb': file_size / (1024 * 1024),
                        'duration': info.get('duration', 0),
                        'width': info.get('width', 1280),
                        'height': info.get('height', 720),
                    }
                else:
                    return {
                        'success': False,
                        'error': 'File not found after download'
                    }
                    
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
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
                    
                    # Call progress callback
                    progress_callback(progress_data)
                    
        return hook
    
    def _format_duration(self, seconds: int) -> str:
        """Format duration in seconds to HH:MM:SS."""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        
        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes}:{secs:02d}"
