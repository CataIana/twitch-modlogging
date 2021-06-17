from discord import Embed as DiscordEmbed
from discord import Webhook as DiscordWebhook
from discord import AsyncWebhookAdapter
from aiohttp import ClientSession
from discord import NotFound
from datetime import datetime
import json

class Colours:
    def __init__(self):
        self.red = 0xE74C3C
        self.yellow = 0xFFBF00
        self.green = 0x2ECC71


class Parser:
    def __init__(self, parent, streamers, data, **kwargs):
        self.logging = parent.logging
        if type(data["message"]) == str:
            self._message = json.loads(data["message"])
        else:
            self._message = data["message"]
        self.info = self._message["data"]
        self.streamer = streamers[data["topic"].split(".")[-1]]
        self.ignored_mods = kwargs.get("ignored_mods", [])
        self.ignore_message = False
        self.footer_message = "Mew"

        self.colour = Colours()
        

        self.use_embeds = kwargs.get("use_embeds", True)

        try:
            self.mod_action = self.info["moderation_action"].lower()
        except KeyError:
            try:
                self.mod_action = self.info["type"]
            except KeyError:
                self.mod_action = self._message["type"]

        if self.mod_action in ["delete_notification", "vip"]:
            self.ignore_message = True
        if self.mod_action == "mod" and self._message["type"] != "moderator_added":
            self.ignore_message = True

        self._chatroom_actions = {
            "slow": "Slow Chat Mode Enabled",
            "slowoff": "Slow Chat Mode Disabled",
            "r9kbeta": "Unique Chat Mode Enabled",
            "r9kbetaoff": "Unique Chat Mode Disabled",
            "clear": "Chat Cleared by Moderator",
            "emoteonly": "Emote Only Chat Mode Enabled",
            "emoteonlyoff": "Emote Only Chat Mode Disabled",
            "subscribers": "Subscriber Only Chat Mode Enabled",
            "subscribersoff": "Subscriber Only Chat Mode Disabled",
            "followers": "Follower Only Chat Mode Enabled",
            "followersoff": "Follower Only Chat Mode Disabled",
            "host": "Host Action",
            "unhost": "Unhost Action",
            "raid": "Raid Action",
            "unraid": "Unraid Action"
        }

        self.embed = DiscordEmbed(timestamp=datetime.utcnow())

    async def create_message(self):
        self.embed.add_field(
            name="Channel", value=f"[{self.streamer.display_name}](<https://www.twitch.tv/{self.streamer.username}>)", inline=True)  # Every embed should have the channel link

        if self.info.get("created_by", "") == "": #Try get who performed the action
            if self.info.get("created_by_login", "") == "":
                if self.info.get("resolver_login", "") == "":
                    moderator = "NONE"
                else:
                    moderator = self.info["resolver_login"].replace('_', '\_')
            else:
                moderator = self.info["created_by_login"].replace('_', '\_')
        else:
            moderator = self.info["created_by"].replace('_', '\_')

        if moderator in self.ignored_mods:
            self.ignore_message = True

        self.embed.add_field(name="Moderator", value=moderator, inline=True)

        try:
            mod_action_func = getattr(self, self.mod_action.lower())
            await mod_action_func()
        except AttributeError:
            self.embed.add_field(
                name="UNKNOWN ACTION", value=f"`{self.mod_action}`", inline=False)

        #Make the text version out of the embed. This is shitty, I know. Works surprisingly well though, for now...
        d = self.embed.to_dict()
        self.embed_text = "\n"
        if d.get("title", None) is not None:
            self.embed_text += f"**{d['title']}**"
        self.embed_text += f" **||** **Channel:** {d['fields'][0]['value']}"
        self.embed_text += f" **||** **Moderator:** {d['fields'][1]['value']}"
        if d.get("description", None) is not None:
            self.embed_text += f" **||** {d['description']}\n"
        else:
            self.embed_text += "\n"
        self.embed_text += '\n'.join([f"{i['name']}: {i['value']}" for i in d['fields'][2:]])

    async def send(self, session=None):
        close_when_done = False
        if session is None:
            session = ClientSession()
            close_when_done = True
        session = session or ClientSession()
        webhooks = []
        for webhook in self.streamer.webhook_urls:
            webhooks.append(DiscordWebhook.from_url(
                webhook, adapter=AsyncWebhookAdapter(session)))
        self.embed.set_footer(text=self.footer_message, icon_url=self.streamer.icon)
        for webhook in webhooks:
            try:
                if self.use_embeds:
                    await webhook.send(embed=self.embed)
                else:
                    await webhook.send(content=self.embed_text)
            except NotFound:
                self.logging.warning(f"Webhook not found for {self.streamer.username}")
        if close_when_done:
            await session.close()

    #More generic functions that the specifics call

    async def set_user_attrs(self):
        user = self.info["target_user_login"] or self.info['args'][0]
        user_escaped = user.lower().replace('_', '\_')
        self.embed.title=f"Mod {self.mod_action.replace('_', ' ').title()} Action"
        #self.embed.description=f"[Review Viewercard for User](<https://www.twitch.tv/popout/{self.streamer.username}/viewercard/{user.lower()}>)"
        self.embed.color=self.colour.red
        self.embed.add_field(
                name="Flagged Account", value=f"[{user_escaped}](<https://www.twitch.tv/popout/{self.streamer.username}/viewercard/{user_escaped}>)", inline=True)

    async def set_terms_attrs(self):
        self.embed.title=f"Mod {self.mod_action.replace('_', ' ').title()} Action"
        self.embed.color=self.colour.red

    async def set_appeals_attrs(self):
        await self.set_user_attrs()
        self.embed.add_field(
                name="Moderator Reason", value=f"{self.info['moderator_message'] if self.info['moderator_message'] != '' else 'NONE'}", inline=False)

    async def set_chatroom_attrs(self):
        self.embed.title=self._chatroom_actions[self.mod_action]
        self.embed.color=self.colour.yellow

    #Action type specific functions

    async def approve_unban_request(self):
        self.embed.colour = self.colour.green
        return await self.set_appeals_attrs()

    async def deny_unban_request(self):
        return await self.set_appeals_attrs()

    async def slow(self):
        await self.set_chatroom_attrs()
        self.embed.add_field(
            name=f"Slow Amount (second{'' if int(self.info['args'][0]) == 1 else 's'})", value=f"`{self.info['args'][0]}`", inline=True)

    async def slowoff(self):
        return await self.set_chatroom_attrs()

    async def r9kbeta(self):
        return await self.set_chatroom_attrs()

    async def r9kbetaoff(self):
        return await self.set_chatroom_attrs()

    async def clear(self):
        return await self.set_chatroom_attrs()

    async def emoteonly(self):
        return await self.set_chatroom_attrs()

    async def emoteonlyoff(self):
        return await self.set_chatroom_attrs()

    async def subscribers(self):
        return await self.set_chatroom_attrs()

    async def subscribersoff(self):
        return await self.set_chatroom_attrs()

    async def followers(self):
        await self.set_chatroom_attrs()
        self.embed.add_field(
            name="Time Needed to be Following (minutes)", value=f"`{self.info['args'][0]}`", inline=True)

    async def followersoff(self):
        return await self.set_chatroom_attrs()

    async def host(self):
        await self.set_chatroom_attrs()
        self.embed.add_field(
            name="Hosted Channel", value=f"[{self.info['args'][0]}](<https://www.twitch.tv/{self.info['args'][0]}>)", inline=True)

    async def unhost(self):
        return await self.set_chatroom_attrs()

    async def raid(self):
        await self.set_chatroom_attrs()
        self.embed.add_field(
            name="Raided Channel", value=f"[{self.info['args'][0]}](<https://www.twitch.tv/{self.info['args'][0]}>)", inline=True)

    async def unraid(self):
        return await self.set_chatroom_attrs()

    async def timeout(self):
        await self.set_user_attrs()
        if self.info['args'][2] == "":
            self.embed.add_field(
                name="Flag Reason", value=f"`None Provided`", inline=False)
        else:
            self.embed.add_field(
                name="Flag Reason", value=f"`{self.info['args'][2]}`", inline=False)

        self.embed.add_field(
            name="Duration", value=f"{self.info['args'][1]} second{'' if int(self.info['args'][1]) == 1 else 's'}", inline=False)

    async def untimeout(self):
        return await self.set_user_attrs()

    async def ban(self):
        await self.set_user_attrs()
        if self.info['args'][1] == "":
            self.embed.add_field(
                name="Flag Reason", value=f"`None Provided`", inline=False)
        else:
            self.embed.add_field(
                name="Flag Reason", value=f"`{self.info['args'][1]}`", inline=False)

    async def unban(self):
        self.embed.colour = self.colour.green
        return await self.set_user_attrs()

    async def delete_notification(self):
        return await self.set_user_attrs()

    async def delete(self):
        await self.set_user_attrs()
        self.embed.add_field(
            name="Message", value=f"`{self.info['args'][1]}`", inline=False)
        # self.embed.add_field(
        #     name="Message ID", value=f"`{self.info['args'][2]}`", inline=False)

    async def mod(self):
        await self.set_user_attrs()
        self.embed.title = "Moderator Added Action"
        self.embed.colour = self.colour.green

    async def unmod(self):
        await self.set_user_attrs()
        self.embed.title = "Moderator Removed Action"

    async def vip(self):
        await self.set_user_attrs()
        self.embed.title = self.embed.title.replace('Vip', 'VIP')
        self.embed.colour = self.colour.green

    async def vip_added(self):
        await self.set_user_attrs()
        self.embed.title = self.embed.title.replace('Vip', 'VIP')
        self.embed.colour = self.colour.green

    async def unvip(self):
        await self.set_user_attrs()
        self.embed.title = self.embed.title.replace('Unvip', 'UnVIP')

    async def add_permitted_term(self):
        await self.set_terms_attrs()
        self.embed.colour = self.colour.green
        self.embed.add_field(
            name="Added by", value=f"{self.info['requester_login']}", inline=True)
        self.embed.add_field(
            name="Value", value=f"`{self.info['text']}`", inline=False)
        self.embed.add_field(
            name="From Automod", value=f"`{self.info['from_automod']}`", inline=False)
        if self.info["expires_at"] != "":
            d = datetime.strptime(self.info["expires_at"][:-4] + "Z", "%Y-%m-%dT%H:%M:%S.%fZ")
            epoch = d.timestamp()+1 - datetime.utcnow().timestamp()
            days = int(str(epoch // 86400).split('.')[0])
            hours = int(str(epoch // 3600 % 24).split('.')[0])
            minutes = int(str(epoch // 60 % 60).split('.')[0])
            seconds = int(str(epoch % 60).split('.')[0])

            full = []
            if days != 0:
                full.append(f"{days}d")
            if hours != 0:
                full.append(f"{hours}h")
            if minutes != 0:
                full.append(f"{minutes}m")
            if seconds != 0:
                full.append(f"{seconds}s")

            expiry = ''.join(full)
        else:
            expiry = "Permanent"
        self.embed.add_field(
            name="Expires in", value=expiry, inline=True)
        self.embed.remove_field(1)

    async def add_blocked_term(self):
        return await self.add_permitted_term()

    async def delete_permitted_term(self):
        await self.set_terms_attrs()
        self.embed.add_field(
            name="Removed by", value=f"{self.info['requester_login']}", inline=True)
        self.embed.add_field(
            name="Value", value=f"`{self.info['text']}`", inline=False)
        self.embed.remove_field(1)

    async def delete_blocked_term(self):
        return await self.delete_permitted_term()

    async def automod_caught_message(self):
        user = self.info["message"]["sender"]["login"]
        user_escaped = user.lower().replace('_', '\_')
        self.embed.title=f"{self.mod_action.replace('_', ' ').title()}"
        self.embed.color=self.colour.red
        self.embed.add_field(
            name="Flagged Account", value=f"[{user_escaped}](<https://www.twitch.tv/popout/{self.streamer.username}/viewercard/{user_escaped}>)", inline=True)
        self.embed.add_field(
            name="Content Classification", value=f"{self.info['content_classification']['category'].title()} level {self.info['content_classification']['level']}", inline=True)
        text_fragments = []
        topics = []
        for fragment in self.info["message"]["content"]["fragments"]:
            if fragment != {}:
                for topic in fragment.get("automod", {}).get("topics", {}).keys():
                    if topic not in topics:
                        topics.append(topic.replace("_", " "))
                if fragment.get("text", None) is not None:
                    text_fragments.append(fragment.get("text", None))

                
        self.embed.add_field(name="Text fragments", value=f"`{', '.join(text_fragments).strip(', ')}`")
        self.embed.add_field(name="Topics", value=f"`{', '.join(topics).strip(', ')}`")
        if self.info["status"] != "PENDING":
            self.embed.title = self.embed.title.replace("Caught", self.info["status"].title())
        if self.info["status"] == "ALLOWED":
            self.embed.colour = self.colour.green
        elif self.info["status"] == "DENIED":
            self.embed.colour = self.colour.red
        else:
            self.embed.colour = self.colour.yellow