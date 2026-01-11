"""
Rate limiting utility to avoid YouTube API bans
"""

import time
import asyncio
import logging
from typing import Optional, Dict
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class RateLimiter:
    def __init__(self, max_requests_per_minute: int = 10, max_requests_per_hour: int = 50):
        self.max_per_minute = max_requests_per_minute
        self.max_per_hour = max_requests_per_hour
        
        # Track request times
        self.requests = []
        self.hourly_requests = []
        
        # Lock for thread safety
        self.lock = asyncio.Lock()
    
    async def wait_if_needed(self):
        """Wait if rate limit would be exceeded."""
        async with self.lock:
            now = time.time()
            
            # Clean old requests
            minute_ago = now - 60
            hour_ago = now - 3600
            
            self.requests = [req_time for req_time in self.requests if req_time > minute_ago]
            self.hourly_requests = [req_time for req_time in self.hourly_requests if req_time > hour_ago]
            
            # Check limits
            if len(self.requests) >= self.max_per_minute:
                # Calculate wait time
                oldest_request = min(self.requests)
                wait_time = 60 - (now - oldest_request)
                
                if wait_time > 0:
                    logger.warning(f"Rate limit exceeded. Waiting {wait_time:.2f} seconds")
                    await asyncio.sleep(wait_time)
                    # Clean again after wait
                    now = time.time()
                    minute_ago = now - 60
                    self.requests = [req_time for req_time in self.requests if req_time > minute_ago]
            
            if len(self.hourly_requests) >= self.max_per_hour:
                # Calculate wait time
                oldest_hourly = min(self.hourly_requests)
                wait_time = 3600 - (now - oldest_hourly)
                
                if wait_time > 0:
                    logger.warning(f"Hourly rate limit exceeded. Waiting {wait_time:.2f} seconds")
                    await asyncio.sleep(wait_time)
                    # Clean again after wait
                    now = time.time()
                    hour_ago = now - 3600
                    self.hourly_requests = [req_time for req_time in self.hourly_requests if req_time > hour_ago]
            
            # Record this request
            self.requests.append(now)
            self.hourly_requests.append(now)
    
    def get_stats(self) -> Dict:
        """Get current rate limiting statistics."""
        now = time.time()
        minute_ago = now - 60
        hour_ago = now - 3600
        
        recent_requests = [req for req in self.requests if req > minute_ago]
        hourly_requests = [req for req in self.hourly_requests if req > hour_ago]
        
        return {
            'recent_requests': len(recent_requests),
            'max_per_minute': self.max_per_minute,
            'hourly_requests': len(hourly_requests),
            'max_per_hour': self.max_per_hour,
            'can_make_request': len(recent_requests) < self.max_per_minute and len(hourly_requests) < self.max_per_hour,
        }


# Global rate limiter instance
rate_limiter = RateLimiter()
