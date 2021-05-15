#!/usr/bin/env python3

import asyncio
from websockets import client as wclient
from websockets.exceptions import ConnectionClosed
from requests import get
import uuid
import json
import sys
from random import uniform
from traceback import format_tb
from datetime import datetime
from time import time
from discord import NotFound
from discord import Webhook as DiscordWebhook
from discord import Embed as DiscordEmbed
from discord import AsyncWebhookAdapter
from aiohttp import ClientSession
import logging

class PubSubLogging:
    def __init__(self):
        self.logging = logging.getLogger("Twitch Pubsub Logging")
        self.logging.setLevel(logging.INFO)
        formatter = logging.Formatter("%(asctime)s %(levelname)s [%(module)s %(funcName)s %(lineno)d]: %(message)s", "%Y-%m-%d %I:%M:%S%p")

        #File logging
        fh = logging.FileHandler("log.log", "w")
        fh.setLevel(logging.WARNING)
        fh.setFormatter(formatter)
        self.logging.addHandler(fh)

        #Console logging
        chandler = logging.StreamHandler(sys.stdout)
        chandler.setLevel(self.logging.level)
        chandler.setFormatter(formatter)
        self.logging.addHandler(chandler)

        try:
            with open("settings.json") as f:
                channels = json.load(f)
        except FileNotFoundError:
            raise TypeError("Unable to locate settings file!")
        if "authorization" not in channels.keys():
            raise TypeError("Authorization not provided")
        try:
            uid = str(channels["authorization"]["id"])
            auth_token = channels["authorization"]["auth_token"].lstrip("oauth:")
            client_id = channels["authorization"]["client_id"]
            del channels["authorization"]
        except KeyError:
            raise TypeError("Unable to fetch user ID and Authorization Token!")
        try:
            self._streamers = {}
            response = get(url=f"https://api.twitch.tv/kraken/users?login={','.join(channels.keys())}", headers={
                       "Accept": "application/vnd.twitchtv.v5+json", "Client-ID": client_id})
            json_obj = json.loads(response.content.decode())
            for user in json_obj["users"]:
                self._streamers[user['_id']] = {"username": user["name"], "display_name": user["display_name"], "icon": user["logo"], "webhook_urls": channels[user["name"]]}
        except KeyError:
            raise TypeError("Error during initialization. Check your client id and settings file!")

        self.logging.info(f"Listening for chat moderation actions for streamers {', '.join(channels.keys())}")

        topics = [f"chat_moderator_actions.{uid}.{c_id}" for c_id in list(self._streamers.keys())]
        self.subscribe_message = {"type": "LISTEN", "nonce": str(uuid.uuid1().hex), "data": {
            "topics": topics, "auth_token": auth_token}}

    def run(self):
        self.loop = asyncio.get_event_loop()
        self.loop.run_until_complete(self.main())

    async def main(self):
        self.aioSession = ClientSession()
        while True:
            failed_attempts = 0
            while True:
                self.connection = await wclient.connect("wss://pubsub-edge.twitch.tv")
                if self.connection.closed:
                    await asyncio.sleep(1**failed_attempts)
                    failed_attempts += 1
                    self.logging.warning(f"{failed_attempts} failed attempts to connect.")
                else:
                    break
            self.logging.info("Connected to websocket")
            json_message = json.dumps(self.subscribe_message)
            await self.connection.send(json_message)
            tasks = [self.loop.create_task(self.heartbeat()),
                     self.loop.create_task(self.message_reciever())]
            await asyncio.wait(tasks)

    async def message_reciever(self):
        while True:
            try:
                message = await self.connection.recv()
                #self.logging.info('Received message from server: ' + str(message))
                await self.messagehandler(message)
            except ConnectionClosed:
                self.logging.warning("Connection with server closed")
                break

    async def heartbeat(self):
        while True:
            try:
                data_set = {"type": "PING"}
                json_request = json.dumps(data_set)
                self.logging.debug("Ping!")
                await self.connection.send(json_request)
                await asyncio.sleep(120+uniform(-0.25, 0.25))
            except ConnectionClosed:
                self.logging.warning("Connection with server closed")
                break

    async def messagehandler(self, raw_message): #I really could handle this better... so many elseifs. PAIN
        try:
            json_message = json.loads(str(raw_message))
            self.logging.debug(json.dumps(json_message, indent=4))
            if json_message["type"] == "RESPONSE":
                if json_message["error"] != "":
                    self.logging.error(f"Error while subscribing to topics: {json_message['error']}")
            elif json_message["type"] == "PONG":
                self.logging.debug("Pong!")
                self.last_ping = datetime.now()
            elif json_message["type"] == "RECONNECT":
                self.logging.warning("Reconnecting...")
                await asyncio.sleep(5)
                await self.connection.close()
            elif json_message["type"] == "MESSAGE":
                message = json.loads(json_message["data"]["message"])
                streamer_id = json_message["data"]["topic"].split(".")[-1]
                streamer = self._streamers[streamer_id]
                webhooks = []
                for webhook in streamer["webhook_urls"]:
                    webhooks.append(DiscordWebhook.from_url(webhook, adapter=AsyncWebhookAdapter(self.aioSession)))
                if message["type"] in ["moderation_action", "chat_moderator_actions"]:
                    info = message["data"]
                    channel_name = streamer["username"]
                    channel_display_name = streamer["display_name"]
                    mod_action = info["moderation_action"]

                    #Chat mod actions
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

                    if mod_action in name_dict.keys():
                        embed = DiscordEmbed(
                        title=name_dict[mod_action],
                        color=0xFFFF00,
                        timestamp=datetime.utcnow()
                        )
                        embed.add_field(
                            name="Channel", value=f"[{channel_display_name}](https://www.twitch.tv/{channel_name})", inline=True)
                        embed.add_field(
                            name="Moderator", value=f"`{info['created_by']}`", inline=True)

                    if mod_action == "slow":
                        embed.add_field(
                            name=f"Slow Amount (second{'' if int(info['args'][0]) == 1 else 's'})", value=f"`{info['args'][0]}`", inline=True)

                    elif mod_action == "followers":
                        embed.add_field(
                            name="Time Needed to be Following (minutes)", value=f"`{info['args'][0]}`", inline=True)

                    elif mod_action == "host":
                        embed.add_field(
                            name="Hosted Channel", value=f"[{info['args'][0]}](https://www.twitch.tv/{info['args'][0]})", inline=True)

                    elif mod_action == "raid":
                        embed.add_field(
                            name="Raided Channel", value=f"[{info['args'][0]}](https://www.twitch.tv/{info['args'][0]})", inline=True)

                    #Otherwise switch to user mod actions
                    if mod_action not in name_dict.keys():
                        title = f"Mod {mod_action.replace('_', ' ').title()} Action"
                        colour = 0xFF0000
                        if mod_action == "mod":
                            title = "Moderator Added Action"
                            colour = 0x00FF00
                        if mod_action == "unmod":
                            title = "Moderator Removed Action"
                        if info["args"] == None or mod_action in ["delete_permitted_term", "add_permitted_term", "add_blocked_term", "delete_blocked_term"]:
                            embed = DiscordEmbed(
                                title=title,
                                color=colour,
                                timestamp=datetime.utcnow()
                            )
                        else:
                            embed = DiscordEmbed(
                                title=title,
                                description=f"[Review Viewercard for User](https://www.twitch.tv/popout/{channel_name}/viewercard/{info['args'][0]})",
                                color=colour,
                                timestamp=datetime.utcnow()
                            )

                        embed.add_field(
                            name="Channel", value=f"[{channel_display_name}](https://www.twitch.tv/{channel_name})", inline=True)
                        if "created_by" in info.keys():
                            if info["created_by"] == "":
                                embed.add_field(
                                    name="Moderator", value=f"NONE", inline=True)
                            else:
                                embed.add_field(
                                    name="Moderator", value=f"`{info['created_by']}`", inline=True)
                        else:
                            embed.add_field(
                                name="Moderator", value=f"NONE", inline=True)
                        try:
                            embed.add_field(
                                name="Flagged Account", value=f"`{info['args'][0]}`", inline=True)
                        except KeyError:
                            pass
                        except TypeError:
                            pass
                        if mod_action == "timeout":
                            if info['args'][2] == "":
                                embed.add_field(
                                    name="Flag Reason", value=f"`None Provided`", inline=False)
                            else:
                                embed.add_field(
                                    name="Flag Reason", value=f"`{info['args'][2]}`", inline=False)

                            embed.add_field(
                                name="Duration", value=f"{info['args'][1]} second{'' if int(info['args'][1]) == 1 else 's'}", inline=False)
                            if info['msg_id'] == "":
                                embed.add_field(
                                    name="Message ID", value=f"NONE", inline=False)
                            else:
                                embed.add_field(
                                    name="Message ID", value=f"`{info['msg_id']}`", inline=False)
                        elif mod_action == "untimeout":
                            pass
                        elif mod_action == "ban":
                            if info['args'][1] == "":
                                embed.add_field(
                                    name="Flag Reason", value=f"`None Provided`", inline=False)
                            else:
                                embed.add_field(
                                    name="Flag Reason", value=f"`{info['args'][1]}`", inline=False)
                        elif mod_action == "unban":
                            pass
                        elif mod_action == "delete_notification":
                            return
                        elif mod_action == "delete":
                            embed.add_field(
                                name="Message", value=f"`{info['args'][1]}`", inline=False)
                            embed.add_field(
                                name="Message ID", value=f"`{info['args'][2]}`", inline=False)

                        elif mod_action == "unmod":
                            pass
                        elif mod_action == "mod":
                            return

                        elif mod_action == "vip":
                            pass
                        elif mod_action == "unvip":
                            pass

                        elif mod_action in ["automod_rejected", "automod_message_rejected"]:
                            embed.add_field(
                                name="Message", value=f"`{info['args'][1]}`", inline=False)
                            embed.add_field(
                                name="Rejected Reason", value=f"`{info['args'][2]}`", inline=False)
                            embed.add_field(
                                name="Message ID", value=f"`{info['msg_id']}`", inline=False)
                        elif mod_action == "automod_message_approved":
                            embed.add_field(
                                name="Message ID", value=f"`{info['msg_id']}`", inline=False)
                        elif mod_action in ["add_permitted_term", "add_blocked_term"]:
                            embed.description = None
                            embed.add_field(
                                name="Added by", value=f"`{info['requester_login']}`", inline=False)
                            embed.add_field(
                                name="Value", value=f"`{info['text']}`", inline=False)
                            embed.add_field(
                                name="From Automod", value=f"`{info['from_automod']}`", inline=False)
                            if info["expires_at"] != "":
                                d = datetime.strptime(info["expires_at"][:-4] + "Z", "%Y-%m-%dT%H:%M:%S.%fZ")
                                unix = float(d.timestamp())
                                epoch = time() - unix
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
                            embed.add_field(
                                name="Expires in", value=expiry, inline=True)
                            embed.remove_field(2)
                        elif mod_action in ["delete_permitted_term", "delete_blocked_term"]:
                            embed.add_field(
                                name="Removed by", value=f"`{info['created_by']}`", inline=False)
                            embed.add_field(
                                name="Value", value=f"`{info['args'][0]}`", inline=False)
                            embed.remove_field(2)
                        else: #In case there's something new/unknown that happens
                            embed.add_field(
                                name="UNKNOWN ACTION", value=f"`{mod_action}`", inline=False)

                    embed.set_footer(text="Mew", icon_url=streamer["icon"])
                    for webhook in webhooks:
                        try:
                            await webhook.send(embed=embed)
                        except NotFound:
                            self.logging.error("Unknown Webhook")

                elif message["type"] == "moderator_added":
                    channel_name = streamer["username"]
                    channel_display_name = streamer["display_name"]
                    embed = DiscordEmbed(
                        title=f"{message['type'].replace('_', ' ').title()} action",
                        description=f"[Review Viewercard for User](https://www.twitch.tv/popout/{channel_name}/viewercard/{message['data']['target_user_login']})",
                        color=0x00FF00,
                        timestamp=datetime.utcnow()
                    )
                    embed.add_field(
                        name="Channel", value=f"[{channel_display_name}](https://www.twitch.tv/{channel_name})", inline=True)
                    embed.add_field(
                        name="Moderator", value=f"`{message['data']['created_by']}`", inline=True)
                    embed.add_field(
                        name="Flagged Account", value=f"`{message['data']['target_user_login']}`", inline=True)

                    embed.set_footer(text="Mew", icon_url=streamer["icon"])
                    for webhook in webhooks:
                        try:
                            await webhook.send(embed=embed)
                        except NotFound:
                            self.logging.error("Unknown Webhook")

                elif message["type"] == "moderator_removed":
                    channel_name = streamer["username"]
                    channel_display_name = streamer["display_name"]
                    embed = DiscordEmbed(
                        title=f"{message['type'].replace('_', ' ').title()} action",
                        description=f"[Review Viewercard for User](https://www.twitch.tv/popout/{channel_name}/viewercard/{message['data']['target_user_login']})",
                        color=0x00FF00,
                        timestamp=datetime.utcnow()
                    )
                    embed.add_field(
                        name="Channel", value=f"[{channel_display_name}](https://www.twitch.tv/{channel_name})", inline=True)
                    embed.add_field(
                        name="Moderator", value=f"`{message['data']['created_by']}`", inline=True)
                    embed.add_field(
                        name="Flagged Account", value=f"`{message['data']['target_user_login']}`", inline=True)

                    embed.set_footer(text="Mew", icon_url=streamer["icon"])
                    for webhook in webhooks:
                        try:
                            await webhook.send(embed=embed)
                        except NotFound:
                            self.logging.error("Unknown Webhook")
        
                elif message["type"] == "channel_terms_action":
                    channel_name = streamer["username"]
                    channel_display_name = streamer["display_name"]
                    info = message["data"]
                    mod_action = info["type"]

                    title = f"Mod {mod_action.replace('_', ' ').title()} Action"
                    colour = 0xFF0000
                    embed = DiscordEmbed(
                        title=title,
                        color=colour,
                        timestamp=datetime.utcnow()
                    )

                    embed.add_field(
                        name="Channel", value=f"[{channel_display_name}](https://www.twitch.tv/{channel_name})", inline=True)
                    if "requester_login" in info.keys():
                        if info["requester_login"] == "":
                            embed.add_field(
                                name="Moderator", value=f"NONE", inline=True)
                        else:
                            embed.add_field(
                                name="Moderator", value=f"`{info['requester_login']}`", inline=True)
                    else:
                        embed.add_field(
                            name="Moderator", value=f"NONE", inline=True)

                    if mod_action in ["automod_rejected", "automod_message_rejected"]:
                        embed.add_field(
                            name="Message", value=f"`{info['args'][1]}`", inline=False)
                        embed.add_field(
                            name="Rejected Reason", value=f"`{info['args'][2]}`", inline=False)
                        embed.add_field(
                            name="Message ID", value=f"`{info['msg_id']}`", inline=False)
                    elif mod_action in ["add_permitted_term", "add_blocked_term"]:
                        embed.description = None
                        embed.add_field(
                            name="Added by", value=f"`{info['requester_login']}`", inline=False)
                        embed.add_field(
                            name="Value", value=f"`{info['text']}`", inline=False)
                        embed.add_field(
                            name="From Automod", value=f"`{info['from_automod']}`", inline=False)
                        if info["expires_at"] != "":
                            d = datetime.strptime(info["expires_at"][:-4] + "Z", "%Y-%m-%dT%H:%M:%S.%fZ")
                            unix = float(d.timestamp())
                            epoch = time() - unix
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
                        embed.add_field(
                            name="Expires in", value=expiry, inline=True)
                        embed.remove_field(2)
                    elif mod_action in ["delete_permitted_term", "delete_blocked_term"]:
                        embed.add_field(
                            name="Removed by", value=f"`{info['requester_login']}`", inline=False)
                        embed.add_field(
                            name="Value", value=f"`{info['text']}`", inline=False)
                        embed.remove_field(2)
                    else: #In case there's something new/unknown that happens
                        embed.add_field(
                            name="UNKNOWN ACTION", value=f"`{mod_action}`", inline=False)

                    embed.set_footer(text="Mew", icon_url=streamer["icon"])
                    for webhook in webhooks:
                        try:
                            await webhook.send(embed=embed)
                        except NotFound:
                            self.logging.error("Unknown Webhook")

                elif message["type"] == "approve_unban_request" or message["type"] == "deny_unban_request":
                    channel_name = streamer["username"]
                    channel_display_name = streamer["display_name"]
                    if message["type"] == "approve_unban_request":
                        colour = 0x00FF00
                    else:
                        colour = 0xFF0000
                    embed = DiscordEmbed(
                        title=f"Mod {message['type'].replace('_', ' ').title()} action",
                        description=f"[Review Viewercard for User](https://www.twitch.tv/popout/{channel_name}/viewercard/{message['data']['target_user_login']})",
                        color=colour,
                        timestamp=datetime.utcnow()
                    )
                    embed.add_field(
                        name="Channel", value=f"[{channel_display_name}](https://www.twitch.tv/{channel_name})", inline=True)
                    embed.add_field(
                        name="Moderator", value=f"`{message['data']['created_by_login']}`", inline=True)
                    embed.add_field(
                        name="Flagged Account", value=f"`{message['data']['target_user_login']}`", inline=True)
                    embed.add_field(
                        name="Moderator Reason", value=f"{message['data']['moderator_message'] if message['data']['moderator_message'] != '' else 'NONE'}", inline=False
                    )

                    embed.set_footer(text="Mew", icon_url=streamer["icon"])
                    for webhook in webhooks:
                        try:
                            await webhook.send(embed=embed)
                        except NotFound:
                            self.logging.error("Webhook Not Found")

                elif message["type"] == "vip_added":
                    return

                else:
                    raise TypeError(f"Unknown Type {message['type']}")
        except Exception as e:
            formatted_exception = "Traceback (most recent call last):\n" + ''.join(format_tb(e.__traceback__)) + f"{type(e).__name__}: {e}"
            self.logging.error(formatted_exception)
            if "data" not in json.loads(str(raw_message)).keys():
                self.logging.error(raw_message)
                return
            streamer_id = json.loads(str(raw_message))["data"]["topic"].split(".")[-1]
            streamer = self._streamers[streamer_id]
            webhooks = []
            for webhook in streamer["webhook_urls"]:
                webhooks.append(DiscordWebhook.from_url(webhook, adapter=AsyncWebhookAdapter(self.aioSession)))
            embed = DiscordEmbed(
                title=f"Safety Embed",
                description=f"If you see this something went wrong in the embed process, with the data from Twitch, or with how we are handling the Twitch Data.",
                color=0x880080,
                timestamp=datetime.utcnow()
            )
            embed.add_field(
                name="Traceback", value=f"```python\n{formatted_exception}```", inline=False)
            embed.add_field(
                name="Debug Data", value=f"`{json.loads(str(raw_message))}`", inline=False)
            embed.set_footer(text="Mew", icon_url=streamer["icon"])
            for webhook in webhooks:
                await webhook.send(embed=embed)

p = PubSubLogging()
p.run()
