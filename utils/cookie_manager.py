import json
import hashlib
from pathlib import Path
from typing import Optional

class CookieManager:
    def __init__(self, cookies_dir: Path):
        self.cookies_dir = cookies_dir
        self.cookies_dir.mkdir(exist_ok=True)
    
    def update_cookies(self, cookies_file_path: Path, user_id: int) -> bool:
        """Update cookies file for a user."""
        try:
            # Validate cookies file
            if not self._validate_cookies_file(cookies_file_path):
                return False
            
            # Create user-specific cookies file
            user_cookies_path = self.cookies_dir / f"cookies_{user_id}.txt"
            
            # Copy cookies file
            with open(cookies_file_path, 'r', encoding='utf-8') as src:
                content = src.read()
            
            with open(user_cookies_path, 'w', encoding='utf-8') as dst:
                dst.write(content)
            
            # Create a backup
            backup_path = self.cookies_dir / f"cookies_{user_id}.backup.txt"
            with open(backup_path, 'w', encoding='utf-8') as backup:
                backup.write(content)
            
            return True
            
        except Exception as e:
            print(f"Error updating cookies: {e}")
            return False
    
    def get_cookies_path(self, user_id: int) -> Optional[Path]:
        """Get cookies file path for a user."""
        cookies_path = self.cookies_dir / f"cookies_{user_id}.txt"
        if cookies_path.exists():
            return cookies_path
        
        # Try default cookies
        default_cookies = self.cookies_dir / "cookies.txt"
        if default_cookies.exists():
            return default_cookies
        
        return None
    
    def has_cookies(self, user_id: Optional[int] = None) -> bool:
        """Check if cookies are available for user or globally."""
        if user_id:
            return (self.cookies_dir / f"cookies_{user_id}.txt").exists()
        else:
            # Check if any cookies file exists
            return any(self.cookies_dir.glob("cookies_*.txt")) or (self.cookies_dir / "cookies.txt").exists()
    
    def _validate_cookies_file(self, file_path: Path) -> bool:
        """Basic validation of cookies file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Basic checks for Netscape format
            lines = content.strip().split('\n')
            if len(lines) < 2:
                return False
            
            # Check for common cookies fields
            cookie_indicators = ['# HTTP', 'domain', 'path', 'secure', 'expiration']
            has_cookie_data = any(any(indicator in line.lower() for indicator in cookie_indicators) for line in lines)
            
            return has_cookie_data
            
        except Exception:
            return False
    
    def cleanup_old_cookies(self, max_age_days: int = 30):
        """Clean up old cookies files."""
        # Implementation for cleaning old files
        pass
