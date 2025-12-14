import asyncio
import logging
from datetime import datetime, timedelta

import disnake

from message import Message
from modactions import ModAction
from streamer import Streamer
from humanize import precisedelta


class Colours:
    def __init__(self):
        self.red = 0xE74C3C
        self.yellow = 0xFFBF00
        self.orange = 0xFFA500
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
            ModAction.uniquechat: "Unique Chat Mode Enabled",
            ModAction.uniquechatoff: "Unique Chat Mode Disabled",
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
        metadata = data["metadata"]
        subscription = data["payload"]["subscription"]
        event = data["payload"]["event"]
        streamer: Streamer = self.streamers[event["broadcaster_user_id"]]
        ignore_message = False

        embed = disnake.Embed(timestamp=disnake.utils.utcnow())

        embed.add_field(
            name="Channel", value=f"[{streamer.display_name}](<https://www.twitch.tv/{streamer.username}>)", inline=True)  # Every embed should have the channel link
        
        if subscription["type"] == "automod.message.hold":
            mod_action_str = "automod_caught_message"
            moderator = "Automod"
        elif subscription["type"] == "automod.message.update": 
            if event["status"] == "approved":
                mod_action_str = "automod_allowed_message"
            else:
                mod_action_str = "automod_denied_message"
            moderator = event["moderator_user_name"]
        else:
            mod_action_str = event["action"]
            moderator = event["moderator_user_name"]

        embed.add_field(name="Moderator", value=moderator, inline=True)

        try:
            mod_action = ModAction(mod_action_str)
            mod_action_func = getattr(self, mod_action.value)
            r = mod_action_func(streamer, event, metadata, mod_action, embed)
            if type(r) == tuple:
                embed = r[1]
                ignore_message = r[0]
            else:
                embed = r
        except AttributeError:
            embed.add_field(name="UNKNOWN ACTION", value=f"`{mod_action_str}`", inline=False)

        if moderator in self.ignored_mods:
            ignore_message = True

        #Ignores
        if mod_action.value not in streamer.action_whitelist and streamer.action_whitelist != [] and mod_action != ModAction.automod_caught_message: #Automod ignoring handled seperately
            ignore_message = True

        # Make the text version out of the embed. This is shitty, I know. Works surprisingly well though, for now...
        d = embed.to_dict()
        embed_text = "\n"
        if d.get("title", None) is not None:
            embed_text += f"**{d['title']}**"
        for field in d["fields"]:
            if field["name"] == "Channel":
                embed_text += f" **||** **Channel:** {field['value']}"
            elif field["name"] == "Moderator":
                embed_text += f" **||** **Moderator:** {field['value']}"
        if d.get("description", None) is not None:
            embed_text += f" **||** {d['description']}\n"
        else:
            embed_text += "\n"
        embed_text += '\n'.join([f"{i['name']}: {i['value']}" for i in d['fields'] if i["name"] != "Moderator" and i["name"] != "Channel"])

        self.logging.info(f"{moderator} used {mod_action.value} in #{streamer.username}")

        return Message(self, data, streamer, mod_action, ignore_message, embed, embed_text)

    # More generic functions that the specifics call

    def set_user_attrs(self, streamer: Streamer, event: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        user = event[mod_action.name.replace("approve_", "").replace("deny_", "")]["user_login"]
        user_escaped = user.lower().replace('_', r'\_')
        embed.title = f"Mod {mod_action.value.replace('_', ' ').title()} Action"
        #embed.description=f"[Review Viewercard for User](<https://www.twitch.tv/popout/{streamer.username}/viewercard/{user.lower()}>)"
        embed.color = self.colour.red
        embed.add_field(
            name="Flagged Account", value=f"[{user_escaped}](<https://www.twitch.tv/popout/{streamer.username}/viewercard/{user_escaped}>)", inline=True)
        return embed

    def set_terms_attrs(self, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        embed.title = f"Mod {mod_action.value.replace('_', ' ').title()} Action"
        embed.color = self.colour.red
        return embed

    def set_appeals_attrs(self, streamer: Streamer, event: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        self.set_user_attrs(streamer, event, mod_action, embed)
        moderator_reason = event[mod_action.name.replace("approve_", "").replace("deny_", "")]['moderator_message'] if event[mod_action.name.replace("approve_", "").replace("deny_", "")]['moderator_message'] != '' else 'None Provided'
        embed.add_field(
            name="Moderator Reason", value=f"`{moderator_reason}`", inline=False)
        return embed

    def set_chatroom_attrs(self, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        embed.title = self._chatroom_actions[mod_action]
        embed.color = self.colour.yellow
        return embed

    # Action type specific functions that are fetched using getattr()

    def approve_unban_request(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        embed.colour = self.colour.green
        return self.set_appeals_attrs(streamer, event, mod_action, embed)

    def deny_unban_request(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        return self.set_appeals_attrs(streamer, event, mod_action, embed)

    def slow(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        embed = self.set_chatroom_attrs(mod_action, embed)
        embed.add_field(
            name=f"Slow Amount (second{'' if event[mod_action.name]['wait_time_seconds'] == 1 else 's'})", value=f"`{event[mod_action.name]['wait_time_seconds']}`", inline=True)
        return embed

    def slowoff(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        return self.set_chatroom_attrs(mod_action, embed)

    def uniquechat(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        return self.set_chatroom_attrs(mod_action, embed)

    def uniquechatoff(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        return self.set_chatroom_attrs(mod_action, embed)

    def clear(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        return self.set_chatroom_attrs(mod_action, embed)

    def emoteonly(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        return self.set_chatroom_attrs(mod_action, embed)

    def emoteonlyoff(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        return self.set_chatroom_attrs(mod_action, embed)

    def subscribers(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        return self.set_chatroom_attrs(mod_action, embed)

    def subscribersoff(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        return self.set_chatroom_attrs(mod_action, embed)

    def followers(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        embed = self.set_chatroom_attrs(mod_action, embed)
        embed.add_field(
            name=f"Time Needed to be Following (minute{'' if int(event[mod_action.name]['follow_duration_minutes']) == 1 else 's'})", value=f"`{event[mod_action.name]['follow_duration_minutes']}`", inline=True)
        return embed

    def followersoff(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        return self.set_chatroom_attrs(mod_action, embed)

    def raid(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        embed = self.set_chatroom_attrs(mod_action, embed)
        embed.add_field(
            name="Raided Channel", value=f"[{event[mod_action.name]['user_name']}](<https://www.twitch.tv/{event[mod_action.name]['user_login']}>)", inline=True)
        return embed

    def unraid(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        return self.set_chatroom_attrs(mod_action, embed)

    def timeout(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        embed = self.set_user_attrs(streamer, event, mod_action, embed)
        if event[mod_action.name]["reason"] == "":
            embed.add_field(
                name="Flag Reason", value=f"`None Provided`")
        else:
            if "`" in event[mod_action.name]["reason"]:
                embed.add_field(
                    name="Flag Reason", value=f"```{event[mod_action.name]['reason']}```")
            else:
                embed.add_field(
                    name="Flag Reason", value=f"`{event[mod_action.name]['reason']}`")
            
        delta = datetime.fromisoformat(event[mod_action.name]["expires_at"]) - datetime.fromisoformat(metadata["message_timestamp"])
        duration = round(delta.total_seconds())
        humanized_duration = precisedelta(delta, format="%0.0f")

        if humanized_duration != f"{duration} second{'' if duration == 1 else 's'}":
            seconds_display = f" ({duration} second{'' if duration == 1 else 's'})"
        else:
            seconds_display = ""

        embed.add_field(
            name="Duration", value=f"{humanized_duration}{seconds_display}")

        #embed.add_field(name="\u200b", value="\u200b")
        return embed

    def untimeout(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        return self.set_user_attrs(streamer, event, mod_action, embed)

    def ban(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        embed = self.set_user_attrs(streamer, event, mod_action, embed)
        if event[mod_action.name]["reason"] == "":
            embed.add_field(
                name="Flag Reason", value=f"`None Provided`")
        else:
            if "`" in event[mod_action.name]["reason"]:
                embed.add_field(
                    name="Flag Reason", value=f"```{event[mod_action.name]['reason']}```")
            else:
                embed.add_field(
                    name="Flag Reason", value=f"`{event[mod_action.name]['reason']}`")
        return embed

    def unban(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        embed.colour = self.colour.green
        return self.set_user_attrs(streamer, event, mod_action, embed)

    def delete(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        embed = self.set_user_attrs(streamer, event, mod_action, embed)
        if "`" in event[mod_action.name]['message_body']:
            embed.add_field(
                name="Message", value=f"```{event[mod_action.name]['message_body']}```")
        else:
            embed.add_field(
                name="Message", value=f"`{event[mod_action.name]['message_body']}`")

        return embed

    def mod(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        embed = self.set_user_attrs(streamer, event, mod_action, embed)
        embed.title = "Moderator Added Action" #Use a custom title for adding/removing mods for looks
        embed.colour = self.colour.green
        return embed

    def unmod(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        embed = self.set_user_attrs(streamer, event, mod_action, embed)
        embed.title = "Moderator Removed Action"
        return embed

    def vip(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        embed = self.set_user_attrs(streamer, event, mod_action, embed)
        embed.title = embed.title.replace('Vip', 'VIP') #Capitalize VIP for the looks
        embed.colour = self.colour.green
        return embed

    def unvip(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        embed = self.set_user_attrs(streamer, event, mod_action, embed)
        embed.title = embed.title.replace('Unvip', 'UnVIP')
        return embed
    
    def warn(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        embed.colour = self.colour.yellow
        embed.add_field(
            name="Moderator Reason", value=f"`{event[mod_action.name]['reason']}`", inline=False)
        return self.set_user_attrs(streamer, event, mod_action, embed)
    
    def acknowledge_warning(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        embed = self.set_user_attrs(streamer, event, mod_action, embed)
        embed.colour = self.colour.green
        embed.title = "User Acknowledged Warning Action"
        embed.remove_field(1)
        return embed
    
    def shared_chat_ban(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        embed = self.set_user_attrs(streamer, event, mod_action, embed)
        if event[mod_action.name]["reason"] == "":
            embed.add_field(
                name="Flag Reason", value=f"`None Provided`")
        else:
            if "`" in event[mod_action.name]["reason"]:
                embed.add_field(
                    name="Flag Reason", value=f"```{event[mod_action.name]['reason']}```")
            else:
                embed.add_field(
                    name="Flag Reason", value=f"`{event[mod_action.name]['reason']}`")
        return embed
    
    def shared_chat_unban(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        embed.colour = self.colour.green
        return self.set_user_attrs(streamer, event, mod_action, embed)
    
    def shared_chat_timeout(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        embed = self.set_user_attrs(streamer, event, mod_action, embed)
        if event[mod_action.name]["reason"] == "":
            embed.add_field(
                name="Flag Reason", value=f"`None Provided`")
        else:
            if "`" in event[mod_action.name]["reason"]:
                embed.add_field(
                    name="Flag Reason", value=f"```{event[mod_action.name]['reason']}```")
            else:
                embed.add_field(
                    name="Flag Reason", value=f"`{event[mod_action.name]['reason']}`")
                
        def round_seconds(obj: timedelta) -> int:
            if obj.microseconds >= 500_000:
                obj += timedelta(seconds=1)
                return obj.seconds
            
        duration = round_seconds(datetime.fromisoformat(event[mod_action.name]["expires_at"]) - datetime.fromisoformat(metadata["message_timestamp"]))

        embed.add_field(
            name="Duration", value=f"{duration} second{'' if duration == 1 else 's'}")       
        
        return embed
    
    def shared_chat_untimeout(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        return self.set_user_attrs(streamer, event, mod_action, embed)
    
    def shared_chat_delete(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        embed = self.set_user_attrs(streamer, event, mod_action, embed)
        if "`" in event[mod_action.name]['message_body']:
            embed.add_field(
                name="Message", value=f"```{event[mod_action.name]['message_body']}```")
        else:
            embed.add_field(
                name="Message", value=f"`{event[mod_action.name]['message_body']}`")

        return embed

    def add_permitted_term(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        embed = self.set_terms_attrs(mod_action, embed)
        embed.colour = self.colour.green
        embed.add_field(
            name="Added by", value=f"{event['moderator_user_login']}")
        if "`" in event['automod_terms']["terms"][0]:
            embed.add_field(
                name="Term", value=f"```{event['automod_terms']['terms'][0]}```", inline=False)
        else:
            embed.add_field(
                name="Term", value=f"`{event['automod_terms']['terms'][0]}`", inline=False)
        embed.add_field(
            name="From Automod", value=f"`{'Yes' if event['automod_terms']['from_automod'] else 'No'}`")
        
        embed.remove_field(1)
        return embed

    def add_blocked_term(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        return self.add_permitted_term(streamer, event, metadata, mod_action, embed)

    def remove_permitted_term(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        embed = self.set_terms_attrs(mod_action, embed)
        embed.add_field(
            name="Added by", value=f"{event['moderator_user_login']}")
        if "`" in event['automod_terms']["terms"][0]:
            embed.add_field(
                name="Term", value=f"```{event['automod_terms']['terms'][0]}```", inline=False)
        else:
            embed.add_field(
                name="Term", value=f"`{event['automod_terms']['terms'][0]}`", inline=False)
        embed.remove_field(1)
        return embed

    def remove_blocked_term(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        return self.remove_permitted_term(streamer, event, metadata, mod_action, embed)

    def automod_caught_message(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        ignore_message = False
        user = event["user_login"]
        user_escaped = user.replace('_', r'\_')
        embed.title = f"{mod_action.value.replace('_', ' ').title()}"
        embed.color = self.colour.red
        embed.add_field(
            name="Flagged Account", value=f"[{user_escaped}](<https://www.twitch.tv/popout/{streamer.username}/viewercard/{user_escaped}>)", inline=True)
        # Automod events
        if event["automod"] != None:
            embed.add_field(
                name="Content Classification", value=f"{event['automod']['category'].title()} level {event['automod']['level']}", inline=True)
        
        # Blocked term events
        elif event["blocked_term"] != None:
            terms_list = set([event["message"]["text"][term["boundary"]["start_pos"]:term["boundary"]["end_pos"]+1] for term in event["blocked_term"]["terms_found"]])
            embed.add_field(
                name=f"Relevant Blocked Term{'s' if len(terms_list) != 1 else ''}", value=f"{'  '.join(f'`{term}`' for term in terms_list)}", inline=True)

        text_fragments = []
        for fragment in event["message"]["fragments"]:
            if fragment != {}:
                if fragment.get("text", None) is not None:
                    text_fragments.append(fragment.get("text", None))

        embed.add_field(name="Text fragments", value=f"""{'  '.join(f"`{f.strip(' ')}`" for f in text_fragments)}""")
        
        if event.get("status") == "allowed":
            if "automod_allowed_message" not in streamer.action_whitelist and streamer.action_whitelist != []:
                ignore_message = True
            embed.colour = self.colour.green
        elif event.get("status") == "denied":
            if "automod_denied_message" not in streamer.action_whitelist and streamer.action_whitelist != []:
                ignore_message = True
            embed.colour = self.colour.red
        else:
            if "automod_caught_message" not in streamer.action_whitelist and streamer.action_whitelist != []:
                ignore_message = True
            embed.colour = self.colour.yellow
        return ignore_message, embed
    
    def automod_allowed_message(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        return self.automod_caught_message(streamer, event, metadata, mod_action, embed)

    def automod_denied_message(self, streamer: Streamer, event: dict, metadata: dict, mod_action: ModAction, embed: disnake.Embed) -> disnake.Embed:
        return self.automod_caught_message(streamer, event, metadata, mod_action, embed)