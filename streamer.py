class Streamer:
    def __init__(self, username, display_name, icon, webhook_urls, automod=False, whitelist=[]):
        self.username = username
        self.user = username
        self.display_name = display_name
        self.icon = icon
        self.webhook_urls = webhook_urls
        self.automod = automod
        self.enable_automod = automod
        self.action_whitelist = whitelist

    def __str__(self):
        return self.username