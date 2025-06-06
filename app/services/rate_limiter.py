"""
⚡ Rate Limiter Service - Controls Microsoft Graph API rate limits
Prevents API throttling and optimizes request distribution
"""

import asyncio
import time
from typing import Dict, Optional
from asyncio_throttle import Throttler
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core.config import settings
from app.utils.logger import logger

@dataclass
class RateLimitInfo:
    """Rate limit information for a resource"""
    requests_made: int = 0
    reset_time: float = 0
    remaining: int = 0
    limit: int = 0
    
class RateLimiterService:
    """
    Advanced rate limiter for Microsoft Graph API
    
    Features:
    - Per-tenant rate limiting
    - Adaptive throttling based on responses
    - Burst protection
    - Request queuing
    - Metrics collection
    """
    
    def __init__(self):
        # Global throttler for Microsoft Graph
        self.global_throttler = Throttler(
            rate_limit=settings.MS_GRAPH_RATE_LIMIT,
            period=1.0  # per second
        )
        
        # Per-tenant throttlers
        self.tenant_throttlers: Dict[str, Throttler] = {}
        
        # Rate limit tracking per tenant
        self.rate_limits: Dict[str, RateLimitInfo] = defaultdict(RateLimitInfo)
        
        # Request timing for adaptive throttling
        self.request_times: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        
        # Metrics
        self.metrics = {
            'total_requests': 0,
            'throttled_requests': 0,
            'avg_response_time': 0,
            'cache_hits': 0,
            'cache_misses': 0
        }
        
    def get_tenant_throttler(self, tenant_id: str) -> Throttler:
        """Get or create throttler for specific tenant"""
        if tenant_id not in self.tenant_throttlers:
            self.tenant_throttlers[tenant_id] = Throttler(
                rate_limit=settings.MS_GRAPH_RATE_LIMIT,
                period=1.0
            )
        return self.tenant_throttlers[tenant_id]
    
    async def acquire(self, tenant_id: str = "default", resource: str = "graph") -> None:
        """
        Acquire permission to make a request
        
        Args:
            tenant_id: Microsoft tenant ID for rate limiting
            resource: Resource type (graph, mail, calendar, etc.)
        """
        start_time = time.time()
        
        # Global throttling first
        await self.global_throttler.acquire()
        
        # Tenant-specific throttling
        tenant_throttler = self.get_tenant_throttler(tenant_id)
        await tenant_throttler.acquire()
        
        # Check if we need to wait due to previous rate limit responses
        rate_limit = self.rate_limits[tenant_id]
        if rate_limit.reset_time > time.time() and rate_limit.remaining <= 0:
            wait_time = rate_limit.reset_time - time.time()
            if wait_time > 0:
                logger.warning(f"⏱️ Rate limit hit for tenant {tenant_id}. Waiting {wait_time:.2f}s")
                await asyncio.sleep(wait_time)
                self.metrics['throttled_requests'] += 1
        
        self.metrics['total_requests'] += 1
        
        # Track request timing
        self.request_times[tenant_id].append(start_time)
    
    def update_rate_limit_info(self, tenant_id: str, headers: Dict[str, str]) -> None:
        """
        Update rate limit information from response headers
        
        Microsoft Graph returns these headers:
        - RateLimit-Limit: The request limit per time window
        - RateLimit-Remaining: Requests remaining in current window
        - RateLimit-Reset: UTC epoch time when the window resets
        """
        try:
            rate_limit = self.rate_limits[tenant_id]
            
            if 'RateLimit-Limit' in headers:
                rate_limit.limit = int(headers['RateLimit-Limit'])
            
            if 'RateLimit-Remaining' in headers:
                rate_limit.remaining = int(headers['RateLimit-Remaining'])
            
            if 'RateLimit-Reset' in headers:
                rate_limit.reset_time = float(headers['RateLimit-Reset'])
            
            # Adaptive throttling based on remaining requests
            if rate_limit.remaining < rate_limit.limit * 0.1:  # Less than 10% remaining
                # Slow down the tenant throttler
                new_rate = max(1, settings.MS_GRAPH_RATE_LIMIT * 0.5)
                self.tenant_throttlers[tenant_id] = Throttler(rate_limit=new_rate, period=1.0)
                logger.warning(f"🐌 Adaptive throttling: Reduced rate to {new_rate}/s for tenant {tenant_id}")
            
        except (ValueError, KeyError) as e:
            logger.debug(f"Could not parse rate limit headers: {e}")
    
    def get_avg_response_time(self, tenant_id: str) -> float:
        """Calculate average response time for a tenant"""
        times = self.request_times[tenant_id]
        if len(times) < 2:
            return 0.0
        
        intervals = [times[i] - times[i-1] for i in range(1, len(times))]
        return sum(intervals) / len(intervals) if intervals else 0.0
    
    def get_metrics(self) -> Dict:
        """Get performance metrics"""
        return {
            **self.metrics,
            'tenant_count': len(self.tenant_throttlers),
            'avg_tenant_response_times': {
                tenant: self.get_avg_response_time(tenant) 
                for tenant in self.request_times.keys()
            }
        }
    
    def reset_tenant_throttler(self, tenant_id: str) -> None:
        """Reset throttler for a tenant (useful after successful requests)"""
        if tenant_id in self.tenant_throttlers:
            self.tenant_throttlers[tenant_id] = Throttler(
                rate_limit=settings.MS_GRAPH_RATE_LIMIT,
                period=1.0
            )
    
    async def wait_for_reset(self, tenant_id: str) -> None:
        """Wait for rate limit to reset for a specific tenant"""
        rate_limit = self.rate_limits[tenant_id]
        if rate_limit.reset_time > time.time():
            wait_time = rate_limit.reset_time - time.time()
            if wait_time > 0:
                logger.info(f"⏳ Waiting {wait_time:.2f}s for rate limit reset (tenant: {tenant_id})")
                await asyncio.sleep(wait_time)

# Global rate limiter instance
rate_limiter = RateLimiterService()

def rate_limited(tenant_id_arg: str = "tenant_id", resource: str = "graph"):
    """
    Decorator for rate-limited Microsoft Graph API calls
    
    Usage:
    @rate_limited(tenant_id_arg="tenant_id", resource="mail")
    async def get_emails(self, tenant_id: str, ...):
        # API call here
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            # Extract tenant_id from arguments
            tenant_id = "default"
            if tenant_id_arg in kwargs:
                tenant_id = kwargs[tenant_id_arg]
            elif hasattr(args[0], 'integration') and args[0].integration:
                tenant_id = getattr(args[0].integration, 'tenant_id', 'default')
            
            # Acquire rate limit permission
            await rate_limiter.acquire(tenant_id, resource)
            
            # Execute the function
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                
                # Update metrics
                response_time = time.time() - start_time
                rate_limiter.metrics['avg_response_time'] = (
                    rate_limiter.metrics['avg_response_time'] * 0.9 + response_time * 0.1
                )
                
                return result
                
            except Exception as e:
                # Log the error and re-raise
                logger.warning(f"Rate-limited function {func.__name__} failed: {e}")
                raise
                
        return wrapper
    return decorator 