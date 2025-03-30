import logging
from datetime import datetime
from typing import TYPE_CHECKING

import disnake
from aiohttp import ClientSession

from modactions import ModAction
from streamer import Streamer

if TYPE_CHECKING:
    from messageparser import Parser

class Message:
    def __init__(self, parser, raw, streamer, mod_action, ignore, embed, embed_text, **kwargs):
        self._parser: Parser = parser
        self.__raw_message: dict = raw
        self.logging = logging.getLogger("Twitch Pubsub Logging")
        self.__streamer: Streamer = streamer
        self.__mod_action: str = mod_action
        self.__ignore_message: bool = ignore
        self.__embed: disnake.Embed = embed
        self.__embed_text: str = embed_text
        self.__created_at = datetime.utcnow()

        self.footer_message: str = "Mew"

    @property
    def streamer(self):
        return self.__streamer

    @property
    def mod_action(self):
        return self.__mod_action

    @property
    def created_at(self):
        return self.__created_at

    @property
    def embed(self):
        return self.__embed

    @property
    def embed_text(self):
        return self.__embed_text

    @property
    def ignore(self):
        return self.__ignore_message

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
            
        self.__embed.set_footer(text=self.footer_message, icon_url=self.__streamer.icon)
        for webhook in webhooks:
            try:
                if self.mod_action == ModAction.automod_allowed_message or self.mod_action == ModAction.automod_denied_message:
                    existing = self._parser.automod_cache.get(self.__raw_message["payload"]["event"]["message_id"], None)
                    if existing: #If we found the older message in the cache, update it :)
                        try:
                            if self._parser.use_embeds:
                                await existing["message"].edit(embed=self.__embed, allowed_mentions=disnake.AllowedMentions.none())
                            else:
                                await existing["message"].edit(content=self.__embed_text, allowed_mentions=disnake.AllowedMentions.none())
                        except disnake.NotFound:
                            pass
                        del self._parser.automod_cache[self.__raw_message["payload"]["event"]["message_id"]]
                    else: #If it's not in the cache for some reason just send it as normal
                        if self._parser.use_embeds:
                            w_message = await webhook.send(embed=self.__embed, allowed_mentions=disnake.AllowedMentions.none())
                        else:
                            w_message = await webhook.send(content=self.__embed_text, allowed_mentions=disnake.AllowedMentions.none())
                else:
                    if self._parser.use_embeds:
                        w_message = await webhook.send(embed=self.__embed, allowed_mentions=disnake.AllowedMentions.none(), wait=True)
                    else:
                        w_message = await webhook.send(content=self.__embed_text, allowed_mentions=disnake.AllowedMentions.none(), wait=True)
                    if self.mod_action == ModAction.automod_caught_message:
                        self._parser.automod_cache.update({self.__raw_message["payload"]["event"]["message_id"]: {"object": self, "message": w_message}})
            except disnake.NotFound:
                self.logging.warning(
                    f"Webhook not found for {self.streamer.username}")
            except disnake.HTTPException as e:
                self.logging.error(f"HTTP Exception sending webhook: {e}")
        if close_when_done:
            await session.close()