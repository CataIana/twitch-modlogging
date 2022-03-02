from dataclasses import dataclass, field
from typing import List

@dataclass(frozen=True, order=True)
class Streamer:
    username: str
    display_name: str
    icon: str
    webhook_urls: List[str]
    enable_automod: bool = field(default=False)
    action_whitelist: List[str] = field(default_factory=list)

    def __str__(self):
        return self.username