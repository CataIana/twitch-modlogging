from discord import Embed as DiscordEmbed
from discord import Webhook as DiscordWebhook
from discord import AsyncWebhookAdapter
from aiohttp import ClientSession
from discord import NotFound
from datetime import datetime
from time import time


class Parser:
    def __init__(self, streamer, info):
        self.info = info
        self.streamer = streamer
        channel_name = streamer["username"]
        channel_display_name = streamer["display_name"]
        mod_action = info["moderation_action"].lower()
        title = f"Mod {mod_action.replace('_', ' ').title()} Action"
        colour = 0xFF0000

        name_dict = {
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
        
        if name_dict.get(mod_action, None) is not None:
            self.embed = DiscordEmbed(title=name_dict[mod_action], color=0xFFFF00, timestamp=datetime.utcnow())
        else:
            if mod_action in ["moderator_added", "moderator_removed"]:
                user = info['args'][0]
            else:
                user = info["target_user_login"]
            self.embed = DiscordEmbed(title=title,
                description=f"[Review Viewercard for User](https://www.twitch.tv/popout/{channel_name}/viewercard/{user})",
                color=colour, timestamp=datetime.utcnow())

        self.embed.add_field(
            name="Channel", value=f"[{channel_display_name}](https://www.twitch.tv/{channel_name})", inline=True) #Every embed should have the channel link

        if info.get("created_by", "") == "":
            self.embed.add_field(
                name="Moderator", value=f"NONE", inline=True)
        else:
            self.embed.add_field(
                name="Moderator", value=f"`{info['created_by']}`", inline=True)
        if name_dict.get(mod_action, None) is None:
            try:
                self.embed.add_field(
                    name="Flagged Account", value=f"`{info['args'][0]}`", inline=True)
            except KeyError:
                pass
            except TypeError:
                pass

        if mod_action in ["approve_unban_request", "deny_unban_request"]:
            self.embed.add_field(
                name="Moderator Reason", value=f"{self.info['moderator_message'] if self.info['moderator_message'] != '' else 'NONE'}", inline=False
            )

    async def send(self, session = None):
        session = ClientSession() or session
        webhooks = []
        for webhook in self.streamer["webhook_urls"]:
            webhooks.append(DiscordWebhook.from_url(webhook, adapter=AsyncWebhookAdapter(session)))
        self.embed.set_footer(text="Mew", icon_url=self.streamer["icon"])
        for webhook in webhooks:
            try:
                await webhook.send(embed=self.embed)
            except NotFound:
                #self.logging.error(f"Webhook not found for {self.streamer}")
                print(f"Webhook not found for {self.streamer['username']}")
        await session.close()

    async def get_embed(self):
        try:
            mod_action_func = getattr(self, self.info["moderation_action"].lower())
            r = await mod_action_func()
            if r == 0:
                return
        except AttributeError:
            self.embed.add_field(name="UNKNOWN ACTION", value=f"`{self.info['moderation_action']}`", inline=False)
        return self.embed

    async def approve_unban_request(self):
        return

    async def deny_unban_request(self):
        return

    async def slow(self):
        self.embed.add_field(
            name=f"Slow Amount (second{'' if int(self.info['args'][0]) == 1 else 's'})", value=f"`{self.info['args'][0]}`", inline=True)

    async def slowoff(self):
        return

    async def r9kbeta(self):
        return

    async def r9kbetaoff(self):
        return

    async def clear(self):
        return
    
    async def emoteonly(self):
        return

    async def emoteonlyoff(self):
        return

    async def subscribers(self):
        return

    async def subscribersoff(self):
        return
    
    async def followers(self):
        self.embed.add_field(
            name="Time Needed to be Following (minutes)", value=f"`{self.info['args'][0]}`", inline=True)
    
    async def followersoff(self):
        return

    async def host(self):
        self.embed.add_field(
            name="Hosted Channel", value=f"[{self.info['args'][0]}](https://www.twitch.tv/{self.info['args'][0]})", inline=True)

    async def unhost(self):
        return

    async def raid(self):
        self.embed.add_field(
            name="Raided Channel", value=f"[{self.info['args'][0]}](https://www.twitch.tv/{self.info['args'][0]})", inline=True)

    async def unraid(self):
        return

    async def timeout(self):
        if self.info['args'][2] == "":
            self.embed.add_field(
                name="Flag Reason", value=f"`None Provided`", inline=False)
        else:
            self.embed.add_field(
                name="Flag Reason", value=f"`{self.info['args'][2]}`", inline=False)

        self.embed.add_field(
            name="Duration", value=f"{self.info['args'][1]} second{'' if int(self.info['args'][1]) == 1 else 's'}", inline=False)
        if self.info['msg_id'] == "":
            self.embed.add_field(
                name="Message ID", value=f"NONE", inline=False)
        else:
            self.embed.add_field(
                name="Message ID", value=f"`{self.info['msg_id']}`", inline=False)
        return

    async def untimeout(self):
        return

    async def ban(self):
        if self.info['args'][1] == "":
            self.embed.add_field(
                name="Flag Reason", value=f"`None Provided`", inline=False)
        else:
            self.embed.add_field(
                name="Flag Reason", value=f"`{self.info['args'][1]}`", inline=False)
        return

    async def unban(self):
        return

    async def delete_notification(self):
        return 0

    async def delete(self):
        self.embed.add_field(
            name="Message", value=f"`{self.info['args'][1]}`", inline=False)
        self.embed.add_field(
            name="Message ID", value=f"`{self.info['args'][2]}`", inline=False)
        return

    async def mod(self):
        self.embed.title = "Moderator Added Action"
        self.embed.colour = 0x00FF00
        return

    async def unmod(self):
        self.embed.title = "Moderator Removed Action"

    async def vip(self):
        self.embed.colour = 0x00FF00

    async def unvip(self):
        return

    async def automod_rejected(self):
        self.embed.add_field(
            name="Message", value=f"`{self.info['args'][1]}`", inline=False)
        self.embed.add_field(
            name="Rejected Reason", value=f"`{self.info['args'][2]}`", inline=False)
        self.embed.add_field(
            name="Message ID", value=f"`{self.info['msg_id']}`", inline=False)

    async def approved_automod_message(self):
        self.embed.add_field(
            name="Message ID", value=f"`{self.info['msg_id']}`", inline=False)

    async def denied_automod_message(self):
        self.embed.add_field(
            name="Message ID", value=f"`{self.info['msg_id']}`", inline=False)

    async def add_permitted_term(self):
        self.embed.description = None
        self.embed.add_field(
            name="Added by", value=f"`{self.info['requester_login']}`", inline=False)
        self.embed.add_field(
            name="Value", value=f"`{self.info['text']}`", inline=False)
        self.embed.add_field(
            name="From Automod", value=f"`{self.info['from_automod']}`", inline=False)
        if self.info["expires_at"] != "":
            d = datetime.strptime(self.info["expires_at"][:-4] + "Z", "%Y-%m-%dT%H:%M:%S.%fZ")
            epoch = time() - d.timestamp()
            days = str(epoch // 86400).split('.')[0]
            hours = str(epoch // 3600 % 24).split('.')[0]
            minutes = str(epoch // 60 % 60).split('.')[0]
            seconds = str(epoch % 60).split('.')[0]

            full = []
            if days != 0: full.append(f"{days}d")
            if hours != 0: full.append(f"{hours}h")
            if minutes != 0: full.append(f"{minutes}m")
            if seconds != 0: full.append(f"{seconds}s")

            expiry = ''.join(full)
        else:
            expiry = "Permanent"
        self.embed.add_field(
            name="Expires in", value=expiry, inline=True)
        self.embed.remove_field(2)

    async def add_blocked_term(self):
        await self.add_permitted_term(self)

    async def delete_permitted_term(self):
        self.embed.add_field(
            name="Removed by", value=f"`{self.info['created_by']}`", inline=False)
        self.embed.add_field(
            name="Value", value=f"`{self.info['args'][0]}`", inline=False)
        self.embed.remove_field(2)

    async def delete_blocked_term(self):
        await self.delete_permitted_term(self)
