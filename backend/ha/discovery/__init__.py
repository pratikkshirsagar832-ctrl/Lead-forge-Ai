"""Discovery providers (swappable implementations behind DiscoveryClient)."""
from .base import (
    DiscoveryClient,
    DiscoveryConfigError,
    DiscoveryError,
    RawPost,
    SearchBatchResult,
    canonical_post_url,
    parse_posted_at,
)
from .socialcrawl_client import SocialCrawlDiscoveryClient

__all__ = [
    "DiscoveryClient",
    "DiscoveryConfigError",
    "DiscoveryError",
    "RawPost",
    "SearchBatchResult",
    "canonical_post_url",
    "parse_posted_at",
    "SocialCrawlDiscoveryClient",
]
