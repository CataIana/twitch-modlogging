from typing import List

class Streamer:
    def __init__(self, username, display_name, icon, webhook_urls, automod=False, whitelist=[]):
        self.username: str = username
        self.user: str = username
        self.display_name: str = display_name
        self.icon: str = icon
        self.webhook_urls: List[str] = webhook_urls
        self.automod: bool = automod
        self.enable_automod: bool = automod
        self.action_whitelist: List[str] = whitelist

    def __str__(self):
        return self.username