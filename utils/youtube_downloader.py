import asyncio
import re
import json
import random
import time
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any
import yt_dlp
from datetime import datetime
import aiohttp
import logging

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
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1',
        ]
        
        # Rate limiting
        self.last_request_time = 0
        self.min_request_interval = 1  # Reduced from 5 to 1 second
        
    def is_youtube_url(self, url: str) -> bool:
        """Check if the URL is a valid YouTube URL."""
        patterns = [
            r'^(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+$',
            r'^https?://youtu\.be/[a-zA-Z0-9_-]+',
            r'^https?://www\.youtube\.com/shorts/[a-zA-Z0-9_-]+',
            r'^https?://www\.youtube\.com/embed/[a-zA-Z0-9_-]+',
            r'^https?://www\.youtube\.com/live/[a-zA-Z0-9_-]+',
            r'^https?://www\.youtube\.com/watch\?v=[a-zA-Z0-9_-]+',
            r'^https?://www\.youtube\.com/playlist\?list=[a-zA-Z0-9_-]+',
            r'^https?://www\.youtube\.com/c/[a-zA-Z0-9_-]+',
            r'^https?://www\.youtube\.com/user/[a-zA-Z0-9_-]+',
            r'^https?://www\.youtube\.com/channel/[a-zA-Z0-9_-]+',
        ]
        
        return any(re.match(pattern, url, re.IGNORECASE) for pattern in patterns)
    
    def _rate_limit(self):
        """Implement rate limiting to avoid 429 errors."""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        if time_since_last < self.min_request_interval:
            sleep_time = self.min_request_interval - time_since_last
            if sleep_time > 0.1:  # Only sleep if more than 100ms
                logger.debug(f"Rate limiting: sleeping for {sleep_time:.2f} seconds")
                time.sleep(sleep_time)
        
        self.last_request_time = time.time()
    
    def _get_ydl_opts(self, user_id: int, extract_flat: bool = False) -> Dict:
        """Get YouTube DL options with enhanced configuration."""
        cookies_path = self.cookie_manager.get_cookies_path(user_id)
        
        opts = {
            'quiet': True,
            'no_warnings': False,
            'ignoreerrors': True,
            'no_color': True,
            'extract_flat': extract_flat,
            
            # Enhanced headers to avoid detection
            'http_headers': {
                'User-Agent': random.choice(self.user_agents),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Cache-Control': 'max-age=0',
                'Referer': 'https://www.youtube.com/',
            },
            
            # Retry configuration - reduced for faster response
            'retries': 3,
            'fragment_retries': 3,
            'skip_unavailable_fragments': True,
            'continuedl': True,
            
            # Throttling - reduced for faster downloads
            'sleep_interval': 2,
            'max_sleep_interval': 5,
            'sleep_interval_requests': 2,
            
            # Signature extraction fixes
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web'],
                    'player_skip': ['configs', 'webpage'],
                }
            },
            
            # Avoid problematic formats
            'format_sort': ['res', 'fps', 'vcodec:avc1'],
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            
            # Cache
            'cachedir': False,  # Disable cache to avoid issues
            
            # Verbose for debugging
            'verbose': False,
            
            # Timeouts - reduced to avoid hanging
            'socket_timeout': 15,
            'extract_timeout': 30,
            'download_timeout': 60,
        }
        
        # Add cookies if available
        if cookies_path and cookies_path.exists():
            opts['cookiefile'] = str(cookies_path)
            logger.info(f"Using cookies from: {cookies_path}")
        else:
            logger.warning("No cookies found, some videos may not work")
        
        # Add geobypass for region-restricted content
        opts['geo_bypass'] = True
        opts['geo_bypass_country'] = 'US'
        
        # For age-restricted content
        opts['age_limit'] = 0
        
        # Add proxy support (optional)
        # opts['proxy'] = 'http://proxy:port'
        
        # Disable some extractors that cause issues
        opts['extractor_retries'] = 2
        opts['ignore_no_formats_error'] = True
        
        # Add progress updates more frequently
        opts['progress_hooks'] = [self._create_dummy_progress_hook()]  # Dummy hook to avoid None
        
        return opts
    
    def _create_dummy_progress_hook(self):
        """Create a dummy progress hook to avoid None in ydl_opts."""
        def hook(d):
            pass
        return hook
    
    async def get_video_info(self, url: str, user_id: int) -> Optional[Dict]:
        """Get video information including available formats."""
        loop = asyncio.get_event_loop()
        
        try:
            # Apply rate limiting before making request
            self._rate_limit()
            
            ydl_opts = self._get_ydl_opts(user_id, extract_flat=False)
            
            # Set timeout for the operation
            try:
                info = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: self._extract_info_with_retry(url, ydl_opts)
                    ),
                    timeout=45  # 45 second timeout
                )
            except asyncio.TimeoutError:
                logger.error(f"Timeout getting video info for {url}")
                return None
            
            if not info:
                logger.error(f"Failed to get video info for {url}")
                return None
            
            # Get available video formats
            formats = []
            seen_formats = set()
            
            for f in info.get('formats', []):
                if f.get('vcodec') != 'none':  # Has video
                    # Create format identifier
                    height = f.get('height', 0)
                    if height:
                        resolution = f"{height}p"
                    else:
                        resolution = "unknown"
                    
                    fps = f.get('fps')
                    if fps:
                        resolution += f"@{int(fps)}fps"
                    
                    # Check if audio is included
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
                'formats': formats[:8],  # Limit to 8 formats
                'webpage_url': info.get('webpage_url', url),
                'age_limit': info.get('age_limit', 0),
                'is_live': info.get('is_live', False),
                'video_id': info.get('id', ''),
            }
                
        except Exception as e:
            logger.error(f"Error getting video info for {url}: {e}")
            return None
    
    def _extract_info_with_retry(self, url: str, ydl_opts: Dict, max_attempts: int = 2):
        """Extract info with retry logic."""
        for attempt in range(max_attempts):
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if info:
                        return info
                    else:
                        logger.warning(f"Attempt {attempt + 1}: No info returned")
                        time.sleep(2)
                        
            except yt_dlp.utils.DownloadError as e:
                error_str = str(e)
                if "429" in error_str or "Too Many Requests" in error_str:
                    logger.error(f"Rate limited on attempt {attempt + 1}")
                    # Wait longer if rate limited
                    time.sleep(10)
                    continue
                elif "400" in error_str or "Bad Request" in error_str:
                    logger.error(f"Bad request on attempt {attempt + 1}, trying different options")
                    # Try with different extractor options
                    ydl_opts['extractor_args']['youtube']['player_client'] = ['ios', 'android_embedded']
                    time.sleep(5)
                    continue
                else:
                    logger.error(f"DownloadError on attempt {attempt + 1}: {e}")
                    time.sleep(3)
                    continue
            
            except Exception as e:
                logger.error(f"Error on attempt {attempt + 1}: {e}")
                time.sleep(3)
                continue
        
        return None
    
    async def download_video(self, url: str, format_id: str, user_id: int, 
                           progress_callback: Optional[Callable] = None) -> Dict:
        """Download video with specified format."""
        loop = asyncio.get_event_loop()
        
        # Apply rate limiting before making request
        self._rate_limit()
        
        # Create output template
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_template = str(self.temp_dir / f"{timestamp}_%(title).100s.%(ext)s")
        
        # Get base options
        ydl_opts = self._get_ydl_opts(user_id)
        
        # Handle format selection
        if format_id == 'best':
            # Try multiple format combinations
            format_strings = [
                'bestvideo[ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'bestvideo+bestaudio/best',
                'best',
                '22/18',  # Fallback to common formats
            ]
            
            # Try each format string until one works
            download_result = None
            for format_string in format_strings:
                try:
                    ydl_opts['format'] = format_string
                    ydl_opts.update({
                        'outtmpl': output_template,
                        'merge_output_format': 'mp4',
                        'postprocessors': [{
                            'key': 'FFmpegVideoConvertor',
                            'preferedformat': 'mp4',
                        }],
                        'concurrent_fragment_downloads': 2,  # Reduced for stability
                        'buffersize': 1024 * 1024 * 8,  # 8MB buffer
                        'http_chunk_size': 4194304,  # 4MB chunks
                    })
                    
                    # Add progress hook
                    if progress_callback:
                        ydl_opts['progress_hooks'] = [self._create_progress_hook(progress_callback)]
                    
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        logger.info(f"Trying format: {format_string}")
                        info = ydl.extract_info(url, download=True)
                        
                        if info:
                            # Get downloaded file
                            downloaded_file = ydl.prepare_filename(info)
                            file_path = self._find_downloaded_file(downloaded_file, info)
                            
                            if file_path:
                                file_size = Path(file_path).stat().st_size
                                
                                # Check file size limit
                                if file_size > 2000 * 1024 * 1024:  # 2GB
                                    return {
                                        'success': False,
                                        'error': f'File too large ({file_size/(1024*1024):.1f}MB). Telegram limit is 2GB.'
                                    }
                                
                                download_result = {
                                    'success': True,
                                    'filepath': file_path,
                                    'filename': f"{info['title'][:100]}.mp4",
                                    'title': info['title'],
                                    'resolution': 'best',
                                    'resolution_display': 'Best Available',
                                    'file_size': file_size,
                                    'file_size_mb': file_size / (1024 * 1024),
                                    'duration': info.get('duration', 0),
                                    'width': info.get('width', 1280),
                                    'height': info.get('height', 720),
                                    'has_audio': info.get('acodec') != 'none',
                                }
                                break
                
                except Exception as e:
                    logger.warning(f"Format {format_string} failed: {e}")
                    time.sleep(3)
                    continue
            
            if download_result:
                return download_result
            else:
                return {
                    'success': False,
                    'error': 'All format attempts failed'
                }
        
        else:
            # Specific format requested
            try:
                # Try with the specific format
                ydl_opts['format'] = f'{format_id}+bestaudio/best'
                ydl_opts.update({
                    'outtmpl': output_template,
                    'merge_output_format': 'mp4',
                    'postprocessors': [{
                        'key': 'FFmpegVideoConvertor',
                        'preferedformat': 'mp4',
                    }],
                    'concurrent_fragment_downloads': 2,
                    'buffersize': 1024 * 1024 * 8,
                    'http_chunk_size': 4194304,
                })
                
                # Add progress hook
                if progress_callback:
                    ydl_opts['progress_hooks'] = [self._create_progress_hook(progress_callback)]
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    
                    if info:
                        # Get downloaded file
                        downloaded_file = ydl.prepare_filename(info)
                        file_path = self._find_downloaded_file(downloaded_file, info)
                        
                        if file_path:
                            file_size = Path(file_path).stat().st_size
                            
                            # Check file size limit
                            if file_size > 2000 * 1024 * 1024:  # 2GB
                                return {
                                    'success': False,
                                    'error': f'File too large ({file_size/(1024*1024):.1f}MB). Telegram limit is 2GB.'
                                }
                            
                            return {
                                'success': True,
                                'filepath': file_path,
                                'filename': f"{info['title'][:100]}.mp4",
                                'title': info['title'],
                                'resolution': format_id,
                                'resolution_display': f'{format_id}',
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
                    else:
                        return {
                            'success': False,
                            'error': 'Failed to extract video info'
                        }
                        
            except yt_dlp.utils.DownloadError as e:
                logger.error(f"DownloadError for format {format_id}: {e}")
                
                # Try fallback format
                if format_id != '18':  # If not already trying 360p
                    logger.info(f"Trying fallback format 18 (360p)")
                    return await self.download_video(url, '18', user_id, progress_callback)
                
                return {
                    'success': False,
                    'error': f'Download error: {str(e)[:200]}'
                }
            except Exception as e:
                logger.error(f"Unexpected error in download_video: {e}")
                return {
                    'success': False,
                    'error': str(e)[:200]
                }
    
    async def download_audio(self, url: str, user_id: int, 
                           progress_callback: Optional[Callable] = None) -> Dict:
        """Download audio only in MP3 format."""
        loop = asyncio.get_event_loop()
        
        # Apply rate limiting before making request
        self._rate_limit()
        
        # Create output template
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_template = str(self.temp_dir / f"{timestamp}_%(title).100s.%(ext)s")
        
        # Get base options
        ydl_opts = self._get_ydl_opts(user_id)
        
        try:
            # Set options for audio download
            ydl_opts.update({
                'format': 'bestaudio/best',
                'outtmpl': output_template,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'keepvideo': False,
                'concurrent_fragment_downloads': 2,
                'buffersize': 1024 * 1024 * 8,
                'http_chunk_size': 4194304,
            })
            
            # Add progress hook
            if progress_callback:
                ydl_opts['progress_hooks'] = [self._create_progress_hook(progress_callback)]
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                if info:
                    # Get downloaded file
                    downloaded_file = ydl.prepare_filename(info)
                    file_path = self._find_audio_file(downloaded_file, info)
                    
                    if file_path:
                        file_size = Path(file_path).stat().st_size
                        
                        # Check file size limit
                        if file_size > 200 * 1024 * 1024:  # 200MB for audio
                            return {
                                'success': False,
                                'error': f'Audio file too large ({file_size/(1024*1024):.1f}MB).'
                            }
                        
                        return {
                            'success': True,
                            'filepath': file_path,
                            'filename': f"{info['title'][:100]}.mp3",
                            'title': info['title'],
                            'resolution': 'audio',
                            'resolution_display': 'MP3 Audio',
                            'file_size': file_size,
                            'file_size_mb': file_size / (1024 * 1024),
                            'duration': info.get('duration', 0),
                            'has_audio': True,
                        }
                    else:
                        return {
                            'success': False,
                            'error': 'Downloaded audio file not found'
                        }
                else:
                    return {
                        'success': False,
                        'error': 'Failed to extract audio info'
                    }
                    
        except yt_dlp.utils.DownloadError as e:
            logger.error(f"DownloadError for audio: {e}")
            return {
                'success': False,
                'error': f'Audio download error: {str(e)[:200]}'
            }
        except Exception as e:
            logger.error(f"Unexpected error in download_audio: {e}")
            return {
                'success': False,
                'error': str(e)[:200]
            }
    
    def _find_downloaded_file(self, base_filename: str, info: Dict) -> Optional[str]:
        """Find the actual downloaded file with various extensions."""
        # Try with extension from info
        possible_extensions = ['.mp4', '.mkv', '.webm', '.m4a', '.mp3', '.flv', '.3gp']
        
        # First try the prepared filename
        if Path(base_filename).exists():
            return base_filename
        
        # Try without extension then add common extensions
        base_name = base_filename.rsplit('.', 1)[0] if '.' in base_filename else base_filename
        
        for ext in possible_extensions:
            test_path = f"{base_name}{ext}"
            if Path(test_path).exists():
                return test_path
        
        # Search for files with similar names
        timestamp = datetime.now().strftime("%Y%m%d")
        for file in self.temp_dir.glob(f"{timestamp}_*"):
            if file.is_file() and file.stat().st_size > 0:
                return str(file)
        
        return None
    
    def _find_audio_file(self, base_filename: str, info: Dict) -> Optional[str]:
        """Find the actual downloaded audio file."""
        # First try MP3 version (post-processor changes extension)
        base_name = base_filename.rsplit('.', 1)[0] if '.' in base_filename else base_filename
        mp3_path = f"{base_name}.mp3"
        
        if Path(mp3_path).exists():
            return mp3_path
        
        # Try other audio extensions
        audio_extensions = ['.m4a', '.ogg', '.wav', '.opus', '.aac']
        
        for ext in audio_extensions:
            test_path = f"{base_name}{ext}"
            if Path(test_path).exists():
                return test_path
        
        # Search for files with similar names
        timestamp = datetime.now().strftime("%Y%m%d")
        for file in self.temp_dir.glob(f"{timestamp}_*"):
            if file.is_file() and file.stat().st_size > 0:
                # Check if it's likely an audio file
                if any(file.suffix.lower() == ext for ext in ['.mp3', '.m4a', '.ogg', '.wav', '.opus', '.aac']):
                    return str(file)
        
        return None
    
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
    
    async def extract_playlist(self, url: str, user_id: int) -> Dict:
        """Extract playlist or video links to text content."""
        loop = asyncio.get_event_loop()
        
        try:
            # Apply rate limiting
            self._rate_limit()
            
            # Configure for playlist extraction
            ydl_opts = self._get_ydl_opts(user_id, extract_flat=True)
            ydl_opts.update({
                'quiet': True,
                'extract_flat': True,
                'force_generic_extractor': True,
                'skip_download': True,
            })
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await loop.run_in_executor(
                    None,
                    lambda: ydl.extract_info(url, download=False)
                )
                
                if not info:
                    return {
                        'success': False,
                        'error': 'Could not extract playlist information'
                    }
                
                videos = []
                title = info.get('title', 'YouTube Playlist')
                
                if 'entries' in info:
                    # This is a playlist or channel
                    for entry in info['entries']:
                        if entry and entry.get('url'):
                            video_title = entry.get('title', 'Unknown Title')
                            video_url = entry.get('url')
                            videos.append(f"{video_title}: {video_url}")
                else:
                    # Single video
                    video_title = info.get('title', 'Unknown Title')
                    video_url = info.get('webpage_url', url)
                    videos.append(f"{video_title}: {video_url}")
                
                if not videos:
                    return {
                        'success': False,
                        'error': 'No videos found in the playlist'
                    }
                
                content = '\n'.join(videos)
                
                return {
                    'success': True,
                    'title': title,
                    'count': len(videos),
                    'content': content,
                    'url': url
                }
                
        except Exception as e:
            logger.error(f"Error extracting playlist {url}: {e}")
            return {
                'success': False,
                'error': str(e)[:200]
            }
    
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
        test_url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"  # First YouTube video (less likely to be restricted)
        
        try:
            info = await self.get_video_info(test_url, user_id)
            return info is not None
        except:
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
                        logger.info(f"Cleaned up old file: {file.name}")
        except Exception as e:
            logger.error(f"Error cleaning up files: {e}")