import discord
import asyncio
from datetime import datetime
import json
import logging
from message import Message
from modactions import ModAction
from streamer import Streamer

class Colours:
    def __init__(self):
        self.red = 0xE74C3C
        self.yellow = 0xFFBF00
        self.green = 0x2ECC71

AUTOMOD_TIMEOUT = 180
class Parser:
    def __init__(self, streamers, **kwargs):
        self.logging = logging.getLogger("Twitch Pubsub Logging")
        self.streamers = streamers
        self.ignored_mods = kwargs.get("ignored_mods", [])
        self.use_embeds = kwargs.get("use_embeds", True)
        self.colour = Colours()
        self._chatroom_actions = {
            ModAction.slow: "Slow Chat Mode Enabled",
            ModAction.slowoff: "Slow Chat Mode Disabled",
            ModAction.r9kbeta: "Unique Chat Mode Enabled",
            ModAction.r9kbetaoff: "Unique Chat Mode Disabled",
            ModAction.clear: "Chat Cleared by Moderator",
            ModAction.emoteonly: "Emote Only Chat Mode Enabled",
            ModAction.emoteonlyoff: "Emote Only Chat Mode Disabled",
            ModAction.subscribers: "Subscriber Only Chat Mode Enabled",
            ModAction.subscribersoff: "Subscriber Only Chat Mode Disabled",
            ModAction.followers: "Follower Only Chat Mode Enabled",
            ModAction.followersoff: "Follower Only Chat Mode Disabled",
            ModAction.host: "Host Action",
            ModAction.unhost: "Unhost Action",
            ModAction.raid: "Raid Action",
            ModAction.unraid: "Unraid Action"
        }
        self.automod_cache = {}
        self.loop = asyncio.get_event_loop()
        self.loop.create_task(self.cleanup_automod())

    async def cleanup_automod(self):
        while True:
            await asyncio.sleep(360)
            count = 0
            for id, i in dict(self.automod_cache).items():
                if i["object"].created_at.timestamp() > datetime.utcnow().timestamp() - AUTOMOD_TIMEOUT:
                    del self.automod_cache[id]
                    count += 1
            if count > 0:
                self.logging.info(f"Cleaned up {count} unanswered events")

    async def parse_message(self, data: dict) -> Message:
        if type(data["message"]) == str:
            message = json.loads(data["message"])
        else:
            message = data["message"]
        info = message["data"]
        streamer: Streamer = self.streamers[data["topic"].split(".")[-1]]
        ignore_message = False

        if discord.__version__ == "2.0.0.a":
            embed = discord.Embed(timestamp=discord.utils.utcnow())
        else:
            embed = discord.Embed(timestamp=datetime.utcnow())

        embed.add_field(
            name="Channel", value=f"[{streamer.display_name}](<https://www.twitch.tv/{streamer.username}>)", inline=True)  # Every embed should have the channel link

        if info.get("created_by", "") == "":  # Try get who performed the action
            if info.get("created_by_login", "") == "":
                if info.get("resolver_login", "") == "":
                    moderator = "NONE"
                else:
                    moderator = info["resolver_login"].replace('_', '\_')
            else:
                moderator = info["created_by_login"].replace('_', '\_')
        else:
            moderator = info["created_by"].replace('_', '\_')

        embed.add_field(name="Moderator", value=moderator, inline=True)

        try:  # Get the moderation action that was done, different mod actions have it in different places so we have some extra lines
            mod_action_str = info["moderation_action"].lower()
        except KeyError:
            try:
                mod_action_str = info["type"]
            except KeyError:
                mod_action_str = message["type"]
        try:
            mod_action = ModAction(mod_action_str)
            mod_action_func = getattr(self, mod_action.value)
            r = mod_action_func(streamer, info, mod_action, embed)
            if type(r) == tuple:
                embed = r[1]
                ignore_message = r[0]
            else:
                embed = r
        except KeyError:
            embed.add_field(name="UNKNOWN ACTION", value=f"`{mod_action_str}`", inline=False)

        if moderator in self.ignored_mods:
            ignore_message = True

        #Ignores
        if mod_action.value not in streamer.action_whitelist and streamer.action_whitelist != [] and mod_action != ModAction.automod_caught_message: #Automod ignoring handled seperately
            ignore_message = True

        if mod_action == ModAction.mod and message["type"] != "moderator_added":
            ignore_message = True

        # Make the text version out of the embed. This is shitty, I know. Works surprisingly well though, for now...
        d = embed.to_dict()
        embed_text = "\n"
        if d.get("title", None) is not None:
            embed_text += f"**{d['title']}**"
        embed_text += f" **||** **Channel:** {d['fields'][0]['value']}"
        embed_text += f" **||** **Moderator:** {d['fields'][1]['value']}"
        if d.get("description", None) is not None:
            embed_text += f" **||** {d['description']}\n"
        else:
            embed_text += "\n"
        embed_text += '\n'.join([f"{i['name']}: {i['value']}" for i in d['fields'][2:]])

        return Message(self, message, streamer, mod_action, ignore_message, embed, embed_text)

    # More generic functions that the specifics call

    def set_user_attrs(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        user = info["target_user_login"] or info['args'][0]
        user_escaped = user.lower().replace('_', '\_')
        embed.title = f"Mod {mod_action.value.replace('_', ' ').title()} Action"
        #embed.description=f"[Review Viewercard for User](<https://www.twitch.tv/popout/{streamer.username}/viewercard/{user.lower()}>)"
        embed.color = self.colour.red
        embed.add_field(
            name="Flagged Account", value=f"[{user_escaped}](<https://www.twitch.tv/popout/{streamer.username}/viewercard/{user_escaped}>)", inline=True)
        return embed

    def set_terms_attrs(self, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        embed.title = f"Mod {mod_action.value.replace('_', ' ').title()} Action"
        embed.color = self.colour.red
        return embed

    def set_appeals_attrs(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        self.set_user_attrs(streamer, info, mod_action, embed)
        embed.add_field(
            name="Moderator Reason", value=f"{info['moderator_message'] if info['moderator_message'] != '' else 'NONE'}", inline=False)
        return embed

    def set_chatroom_attrs(self, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        embed.title = self._chatroom_actions[mod_action]
        embed.color = self.colour.yellow
        return embed

    # Action type specific functions that are fetched using getattr()

    def approve_unban_request(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        embed.colour = self.colour.green
        return self.set_appeals_attrs(streamer, info, mod_action, embed)

    def deny_unban_request(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        return self.set_appeals_attrs(streamer, info, mod_action, embed)

    def slow(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        embed = self.set_chatroom_attrs(mod_action, embed)
        embed.add_field(
            name=f"Slow Amount (second{'' if int(info['args'][0]) == 1 else 's'})", value=f"`{info['args'][0]}`", inline=True)
        return embed

    def slowoff(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        return self.set_chatroom_attrs(mod_action, embed)

    def r9kbeta(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        return self.set_chatroom_attrs(mod_action, embed)

    def r9kbetaoff(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        return self.set_chatroom_attrs(mod_action, embed)

    def clear(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        return self.set_chatroom_attrs(mod_action, embed)

    def emoteonly(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        return self.set_chatroom_attrs(mod_action, embed)

    def emoteonlyoff(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        return self.set_chatroom_attrs(mod_action, embed)

    def subscribers(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        return self.set_chatroom_attrs(mod_action, embed)

    def subscribersoff(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        return self.set_chatroom_attrs(mod_action, embed)

    def followers(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        embed = self.set_chatroom_attrs(mod_action, embed)
        embed.add_field(
            name=f"Time Needed to be Following (minute{'' if int(info['args'][0]) == 1 else 's'})", value=f"`{info['args'][0]}`", inline=True)
        return embed

    def followersoff(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        return self.set_chatroom_attrs(mod_action, embed)

    def host(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        embed = self.set_chatroom_attrs(mod_action, embed)
        embed.add_field(
            name="Hosted Channel", value=f"[{info['args'][0]}](<https://www.twitch.tv/{info['args'][0]}>)", inline=True)
        return embed

    def unhost(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        return self.set_chatroom_attrs(mod_action, embed)

    def raid(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        embed = self.set_chatroom_attrs(mod_action, embed)
        embed.add_field(
            name="Raided Channel", value=f"[{info['args'][0]}](<https://www.twitch.tv/{info['args'][0]}>)", inline=True)
        return embed

    def unraid(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        return self.set_chatroom_attrs(mod_action, embed)

    def timeout(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        embed = self.set_user_attrs(streamer, info, mod_action, embed)
        if info['args'][2] == "":
            embed.add_field(
                name="Flag Reason", value=f"`None Provided`")
        else:
            if "`" in info["args"][2]:
                embed.add_field(
                    name="Flag Reason", value=f"```{info['args'][2]}```")
            else:
                embed.add_field(
                    name="Flag Reason", value=f"`{info['args'][2]}`")

        embed.add_field(
            name="Duration", value=f"{info['args'][1]} second{'' if int(info['args'][1]) == 1 else 's'}")        

        #embed.add_field(name="\u200b", value="\u200b")
        return embed

    def untimeout(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        return self.set_user_attrs(streamer, info, mod_action, embed)

    def ban(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        embed = self.set_user_attrs(streamer, info, mod_action, embed)
        if info['args'][1] == "":
            embed.add_field(
                name="Flag Reason", value=f"`None Provided`")
        else:
            if "`" in info["args"][1]:
                embed.add_field(
                    name="Flag Reason", value=f"```{info['args'][1]}```")
            else:
                embed.add_field(
                    name="Flag Reason", value=f"`{info['args'][1]}`")
        return embed

    def unban(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        embed.colour = self.colour.green
        return self.set_user_attrs(streamer, info, mod_action, embed)

    def delete_notification(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        return True, self.set_user_attrs(streamer, info, mod_action, embed)

    def delete(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        embed = self.set_user_attrs(streamer, info, mod_action, embed)
        if "`" in info['args'][1]:
            embed.add_field(
                name="Message", value=f"```{info['args'][1]}```")
        else:
            embed.add_field(
                name="Message", value=f"`{info['args'][1]}`")
        # embed.add_field(
        #     name="Message ID", value=f"`{info['args'][2]}`")
        return embed

    def mod(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        embed = self.set_user_attrs(streamer, info, mod_action, embed)
        embed.title = "Moderator Added Action" #Use a custom title for adding/removing mods for looks
        embed.colour = self.colour.green
        return embed

    def unmod(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        embed = self.set_user_attrs(streamer, info, mod_action, embed)
        embed.title = "Moderator Removed Action"
        return embed

    def vip(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        embed = self.set_user_attrs(streamer, info, mod_action, embed)
        embed.title = embed.title.replace('Vip', 'VIP') #Capitalize VIP for the looks
        embed.colour = self.colour.green
        return True, embed

    def vip_added(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        embed = self.set_user_attrs(streamer, info, mod_action, embed)
        embed.title = embed.title.replace('Vip', 'VIP')
        embed.colour = self.colour.green
        return embed

    def unvip(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        embed = self.set_user_attrs(streamer, info, mod_action, embed)
        embed.title = embed.title.replace('Unvip', 'UnVIP')
        return embed

    def add_permitted_term(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        embed = self.set_terms_attrs(mod_action, embed)
        embed.colour = self.colour.green
        embed.add_field(
            name="Added by", value=f"{info['requester_login']}")
        if "`" in info["text"]:
            embed.add_field(
                name="Value", value=f"```{info['text']}```", inline=False)
        else:
            embed.add_field(
                name="Value", value=f"`{info['text']}`", inline=False)
        embed.add_field(
            name="From Automod", value=f"`{info['from_automod']}`")
        if info["expires_at"] != "":
            d = datetime.strptime(
                info["expires_at"][:-4] + "Z", "%Y-%m-%dT%H:%M:%S.%fZ")
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
            embed.add_field(
                name="Expires in", value=f"{expiry} (<t:{int(epoch+datetime.now().timestamp())}:R>)")
        else:
            embed.add_field(name="Expires in", value="Permanent")
        
        embed.remove_field(1)
        return embed

    def add_blocked_term(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        return self.add_permitted_term(streamer, info, mod_action, embed)

    def delete_permitted_term(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        embed = self.set_terms_attrs(mod_action, embed)
        embed.add_field(
            name="Removed by", value=f"{info['requester_login']}")
        if "`" in info["text"]:
            embed.add_field(
                name="Value", value=f"```{info['text']}```")
        else:
            embed.add_field(
                name="Value", value=f"`{info['text']}`")
        embed.remove_field(1)
        return embed

    def delete_blocked_term(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        return self.delete_permitted_term(streamer, info, mod_action, embed)

    def automod_caught_message(self, streamer: Streamer, info, mod_action: ModAction, embed: discord.Embed) -> discord.Embed:
        ignore_message = False
        user = info["message"]["sender"]["login"]
        user_escaped = user.lower().replace('_', '\_')
        embed.title = f"{mod_action.value.replace('_', ' ').title()}"
        embed.color = self.colour.red
        embed.add_field(
            name="Flagged Account", value=f"[{user_escaped}](<https://www.twitch.tv/popout/{streamer.username}/viewercard/{user_escaped}>)", inline=True)
        embed.add_field(
            name="Content Classification", value=f"{info['content_classification']['category'].title()} level {info['content_classification']['level']}", inline=True)
        text_fragments = []
        topics = []
        for fragment in info["message"]["content"]["fragments"]:
            if fragment != {}:
                for topic in fragment.get("automod", {}).get("topics", {}).keys():
                    if topic not in topics:
                        topics.append(topic.replace("_", " "))
                if fragment.get("text", None) is not None:
                    text_fragments.append(fragment.get("text", None))

        text_fragments = list(dict.fromkeys(text_fragments)) #Remove duplicates from topics and text fragments, they're pointless
        topics = list(dict.fromkeys(topics))
        embed.add_field(name="Text fragments",
                             value=f"`{', '.join([f.strip(' ') for f in text_fragments]).strip(', ')}`")
        embed.add_field(
            name="Topics", value=f"`{', '.join(topics).strip(', ')}`")
        if info["status"] == "PENDING":
            embed.colour = self.colour.yellow
            if "automod_caught_message" not in streamer.action_whitelist and streamer.action_whitelist != []:
                ignore_message = True
        elif info["status"] == "ALLOWED":
            if "automod_allowed_message" not in streamer.action_whitelist and streamer.action_whitelist != []:
                ignore_message = True
            embed.colour = self.colour.green
        elif info["status"] == "DENIED":
            if "automod_denied_message" not in streamer.action_whitelist and streamer.action_whitelist != []:
                ignore_message = True
            embed.colour = self.colour.red
        else:
            if "automod_caught_message" not in streamer.action_whitelist and streamer.action_whitelist != []:
                ignore_message = True
        if info["status"] != "PENDING":
            embed.title = embed.title.replace("Caught", info["status"].title())
        return ignore_message, embed
