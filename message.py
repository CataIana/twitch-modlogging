import logging
from datetime import datetime
import disnake
from streamer import Streamer
from aiohttp import ClientSession
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from messageparser import Parser

class Message:
    def __init__(self, parser, raw, streamer, mod_action, ignore, embed, embed_text, **kwargs):
        self._parser: Parser = parser
        self.__raw_message: dict = raw
        self.logging = logging.getLogger("Twitch Pubsub Logging")
        self._streamer: Streamer = streamer
        self._mod_action: str = mod_action
        self._ignore_message: bool = ignore
        self._embed: disnake.Embed = embed
        self._embed_text: str = embed_text
        self._created_at = datetime.utcnow()

        self.footer_message: str = "Mew"

    @property
    def streamer(self):
        return self._streamer

    @property
    def mod_action(self):
        return self._mod_action

    @property
    def created_at(self):
        return self._created_at

    @property
    def embed(self):
        return self._embed

    @property
    def embed_text(self):
        return self._embed_text

    @property
    def ignore(self):
        return self._ignore_message

    async def send(self, session=None):
        close_when_done = False
        if session is None:
            session = ClientSession()
            close_when_done = True
        session = session or ClientSession()
        webhooks = []
        for webhook in self.streamer.webhook_urls:
            webhooks.append(disnake.Webhook.from_url(
                webhook, session=session))
            
        self._embed.set_footer(text=self.footer_message, icon_url=self._streamer.icon)
        for webhook in webhooks:
            try:
                if self.mod_action == "automod_caught_message" and self.__raw_message["data"]["status"] in ["DENIED", "ALLOWED"]:
                    existing = self._parser.automod_cache.get(self.__raw_message["data"]["message"]["id"], None)
                    if existing: #If we found the older message in the cache, update it :)
                        try:
                            if self._parser.use_embeds:
                                await existing["message"].edit(embed=self._embed, allowed_mentions=disnake.AllowedMentions.none())
                            else:
                                await existing["message"].edit(embed=self._embed_text, allowed_mentions=disnake.AllowedMentions.none())
                        except disnake.NotFound:
                            pass
                        del self._parser.automod_cache[self.__raw_message["data"]["message"]["id"]]
                    else: #If it's not in the cache for some reason just send it as normal
                        if self._parser.use_embeds:
                            w_message = await webhook.send(embed=self._embed, allowed_mentions=disnake.AllowedMentions.none())
                        else:
                            w_message = await webhook.send(content=self._embed_text, allowed_mentions=disnake.AllowedMentions.none())
                else:
                    if self._parser.use_embeds:
                        w_message = await webhook.send(embed=self._embed, allowed_mentions=disnake.AllowedMentions.none(), wait=True)
                    else:
                        w_message = await webhook.send(content=self._embed_text, allowed_mentions=disnake.AllowedMentions.none(), wait=True)
                    if self.mod_action == "automod_caught_message":
                        self._parser.automod_cache[self.__raw_message["data"]["message"]["id"]] = {"object": self, "message": w_message}
            except disnake.NotFound:
                self.logging.warning(
                    f"Webhook not found for {self.streamer.username}")
            except disnake.HTTPException as e:
                self.logging.error(f"HTTP Exception sending webhook: {e}")
        if close_when_done:
            await session.close()