from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta
import asyncio
from ..utils.errors import RateLimitError

class RateLimiter:
    """Handles rate limiting for responses with burst and cooldown support."""
    
    def __init__(
        self, 
        requests_per_minute: int = 5,
        burst_limit: int = 2,
        burst_cooldown: int = 30
    ):
        """Initialize rate limiter.
        
        Args:
            requests_per_minute: Maximum requests allowed per minute
            burst_limit: Maximum burst requests allowed
            burst_cooldown: Cooldown period in seconds after burst
        """
        if requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be positive")
            
        self.requests_per_minute = requests_per_minute
        self.burst_limit = burst_limit
        self.burst_cooldown = burst_cooldown
        self.user_requests: Dict[int, list] = {}
        self.burst_usage: Dict[int, Tuple[int, datetime]] = {}
        self.locks: Dict[int, asyncio.Lock] = {}
        
    async def check_rate_limit(self, user_id: int) -> None:
        """Check if user is rate limited.
        
        Args:
            user_id: ID of the user to check
            
        Raises:
            RateLimitError: If user is rate limited
        """
        if not await self.acquire(user_id):
            retry_after = await self.get_retry_after(user_id)
            raise RateLimitError(
                f"Rate limit exceeded. Try again in {retry_after:.1f} seconds"
            )

    async def acquire(self, user_id: int) -> bool:
        """Attempt to acquire a rate limit slot.
        
        Args:
            user_id: ID of the user requesting
            
        Returns:
            bool: True if successful, False if rate limited
        """
        if user_id not in self.locks:
            self.locks[user_id] = asyncio.Lock()
            
        async with self.locks[user_id]:
            now = datetime.now()
            
            # Initialize user requests if needed
            if user_id not in self.user_requests:
                self.user_requests[user_id] = []
                
            # Clean up old requests
            self.user_requests[user_id] = [
                timestamp for timestamp in self.user_requests[user_id]
                if timestamp > now - timedelta(minutes=1)
            ]
            
            # Check burst usage
            if await self._check_burst_limit(user_id, now):
                return True
                
            # Check regular rate limit
            if len(self.user_requests[user_id]) >= self.requests_per_minute:
                return False
                
            # Add new request
            self.user_requests[user_id].append(now)
            return True
            
    async def _check_burst_limit(self, user_id: int, now: datetime) -> bool:
        """Check if burst limit can be used.
        
        Args:
            user_id: ID of the user
            now: Current timestamp
            
        Returns:
            bool: True if burst limit is available
        """
        if user_id in self.burst_usage:
            count, timestamp = self.burst_usage[user_id]
            
            # Reset burst if cooldown has passed
            if now - timestamp > timedelta(seconds=self.burst_cooldown):
                del self.burst_usage[user_id]
            # Use burst if available
            elif count < self.burst_limit:
                self.burst_usage[user_id] = (count + 1, timestamp)
                return True
        else:
            # Initialize burst usage
            self.burst_usage[user_id] = (1, now)
            return True
            
        return False
            
    async def get_retry_after(self, user_id: int) -> Optional[float]:
        """Get the number of seconds until the rate limit resets.
        
        Args:
            user_id: ID of the user to check
            
        Returns:
            Optional[float]: Seconds until reset, or None if not rate limited
        """
        if user_id not in self.user_requests or not self.user_requests[user_id]:
            return None
            
        now = datetime.now()
        
        # Check burst cooldown
        if user_id in self.burst_usage:
            count, timestamp = self.burst_usage[user_id]
            burst_reset = timestamp + timedelta(seconds=self.burst_cooldown)
            if burst_reset > now:
                return (burst_reset - now).total_seconds()
        
        # Check regular rate limit
        oldest_request = min(self.user_requests[user_id])
        reset_time = oldest_request + timedelta(minutes=1)
        
        if reset_time > now:
            return (reset_time - now).total_seconds()
        return None
        
    async def cleanup(self) -> None:
        """Cleanup rate limiter resources."""
        self.user_requests.clear()
        self.burst_usage.clear()
        self.locks.clear()
