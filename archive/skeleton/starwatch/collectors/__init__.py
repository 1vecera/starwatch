from .facebook import FacebookCollector
from .instagram import InstagramCollector
from .tiktok import TiktokCollector
from .website import WebsiteCollector
from .x import XCollector
from .youtube import YoutubeCollector

COLLECTORS = [
    WebsiteCollector(),
    FacebookCollector(),
    InstagramCollector(),
    TiktokCollector(),
    YoutubeCollector(),
    XCollector(),
]

__all__ = ["COLLECTORS"]
