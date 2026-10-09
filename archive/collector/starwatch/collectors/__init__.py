from .costs import SettleCosts
from .facebook import FacebookCollector
from .identity import CheckLookalikes
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
    CheckLookalikes(),  # runs beside the lanes until the name searches have judged every look-alike
    SettleCosts(),  # reads the job's final Apify spend back once every lane has ended
]

__all__ = ["COLLECTORS"]
