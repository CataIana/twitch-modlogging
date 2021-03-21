#!/usr/bin/env python3

import asyncio
import websockets
from requests import get
import uuid
import json
import sys
from random import uniform
from traceback import format_tb
from datetime import datetime
from discord_webhook import DiscordEmbed, DiscordWebhook
import logging


class PubSubLogging:
    def __init__(self):
        self.logging = logging.getLogger("Twitch Pubsub Logging")
        self.logging.setLevel(logging.DEBUG)
        formatter = logging.Formatter("%(asctime)s %(levelname)s [%(module)s %(funcName)s %(lineno)d]: %(message)s", "%Y-%m-%d %I:%M:%S%p")

        #File logging
        fh = logging.FileHandler("log.log")
        fh.setLevel(logging.WARNING)
        fh.setFormatter(formatter)
        self.logging.addHandler(fh)

        #Console logging
        chandler = logging.StreamHandler(sys.stdout)
        chandler.setLevel(logging.DEBUG)
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
        self.subscribe_message = {"type": "LISTEN", "nonce": str(self.generate_nonce()), "data": {
            "topics": topics, "auth_token": auth_token}}

    def run(self):
        self.loop = asyncio.get_event_loop()
        self.loop.run_until_complete(self.main())

    async def main(self):
        while True:
            failed_attempts = 0
            while True:
                self.connection = await websockets.client.connect("wss://pubsub-edge.twitch.tv")
                if self.connection.closed:
                    await asyncio.sleep(1**failed_attempts)
                    failed_attempts += 1
                    self.logging.warning(f"{failed_attempts} failed attempts.")
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
            except websockets.exceptions.ConnectionClosed:
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
            except websockets.exceptions.ConnectionClosed:
                self.logging.warning("Connection with server closed")
                break

    def generate_nonce(self):
        nonce = uuid.uuid1()
        oauth_nonce = nonce.hex
        return oauth_nonce

    async def messagehandler(self, raw_message):
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
                self.logging.warn("Reconnecting...")
                await asyncio.sleep(5)
                self.connection.close()
            elif json_message["type"] == "MESSAGE":
                message = json.loads(json_message["data"]["message"])
                streamer_id = json_message["data"]["topic"].split(".")[-1]
                streamer = self._streamers[streamer_id]
                webhook = DiscordWebhook(
                    url=streamer["webhook_urls"])
                if message["type"] == "moderation_action":
                    info = message["data"]
                    channel_name = streamer["username"]
                    channel_display_name = streamer["display_name"]

                    if info["moderation_action"] == "slow":
                        embed = DiscordEmbed(
                        title=f"Slow Chat Mode Enabled",
                        color=0xFFFF00
                        )
                        embed.add_embed_field(
                            name="Channel", value=f"[{channel_display_name}](https://www.twitch.tv/{channel_name})", inline=True)
                        embed.add_embed_field(
                            name="Moderator", value=f"`{info['created_by']}`", inline=True)
                        embed.add_embed_field(
                            name="Slow Amount (seconds)", value=f"`{info['args'][0]}`", inline=True)
                    elif info["moderation_action"] == "slowoff":
                        embed = DiscordEmbed(
                        title=f"Slow Chat Mode Disabled",
                        color=0xFFFF00
                        )
                        embed.add_embed_field(
                            name="Channel", value=f"[{channel_display_name}](https://www.twitch.tv/{channel_name})", inline=True)
                        embed.add_embed_field(
                            name="Moderator", value=f"`{info['created_by']}`", inline=True)


                    elif info["moderation_action"] == "r9kbeta":
                        embed = DiscordEmbed(
                        title=f"Unique Chat Mode Enabled",
                        color=0xFFFF00
                        )
                        embed.add_embed_field(
                            name="Channel", value=f"[{channel_display_name}](https://www.twitch.tv/{channel_name})", inline=True)
                        embed.add_embed_field(
                            name="Moderator", value=f"`{info['created_by']}`", inline=True)
                    elif info["moderation_action"] == "r9kbetaoff":
                        embed = DiscordEmbed(
                        title=f"Unique Chat Mode Disabled",
                        color=0xFFFF00
                        )
                        embed.add_embed_field(
                            name="Channel", value=f"[{channel_display_name}](https://www.twitch.tv/{channel_name})", inline=True)
                        embed.add_embed_field(
                            name="Moderator", value=f"`{info['created_by']}`", inline=True)


                    elif info["moderation_action"] == "clear":
                        embed = DiscordEmbed(
                        title=f"Chat Cleared by Moderator",
                        color=0xFFFF00
                        )
                        embed.add_embed_field(
                            name="Channel", value=f"[{channel_display_name}](https://www.twitch.tv/{channel_name})", inline=True)
                        embed.add_embed_field(
                            name="Moderator", value=f"`{info['created_by']}`", inline=True)


                    elif info["moderation_action"] == "emoteonly":
                        embed = DiscordEmbed(
                        title=f"Emote Only Chat Mode Enabled",
                        color=0xFFFF00
                        )
                        embed.add_embed_field(
                            name="Channel", value=f"[{channel_display_name}](https://www.twitch.tv/{channel_name})", inline=True)
                        embed.add_embed_field(
                            name="Moderator", value=f"`{info['created_by']}`", inline=True)
                    elif info["moderation_action"] == "emoteonlyoff":
                        embed = DiscordEmbed(
                        title=f"Emote Only Chat Mode Disabled",
                        color=0xFFFF00
                        )
                        embed.add_embed_field(
                            name="Channel", value=f"[{channel_display_name}](https://www.twitch.tv/{channel_name})", inline=True)
                        embed.add_embed_field(
                            name="Moderator", value=f"`{info['created_by']}`", inline=True)

                    
                    elif info["moderation_action"] == "subscribers":
                        embed = DiscordEmbed(
                        title=f"Subscriber Only Chat Mode Enabled",
                        color=0xFFFF00
                        )
                        embed.add_embed_field(
                            name="Channel", value=f"[{channel_display_name}](https://www.twitch.tv/{channel_name})", inline=True)
                        embed.add_embed_field(
                            name="Moderator", value=f"`{info['created_by']}`", inline=True)
                    elif info["moderation_action"] == "subscribersoff":
                        embed = DiscordEmbed(
                        title=f"Subscriber Only Chat Mode Disabled",
                        color=0xFFFF00
                        )
                        embed.add_embed_field(
                            name="Channel", value=f"[{channel_display_name}](https://www.twitch.tv/{channel_name})", inline=True)
                        embed.add_embed_field(
                            name="Moderator", value=f"`{info['created_by']}`", inline=True)


                    elif info["moderation_action"] == "followers":
                        embed = DiscordEmbed(
                        title=f"Follower Only Chat Mode Enabled",
                        color=0xFFFF00
                        )
                        embed.add_embed_field(
                            name="Channel", value=f"[{channel_display_name}](https://www.twitch.tv/{channel_name})", inline=True)
                        embed.add_embed_field(
                            name="Moderator", value=f"`{info['created_by']}`", inline=True)
                        embed.add_embed_field(
                            name="Time Needed to be Following (minutes)", value=f"`{info['args'][0]}`", inline=True)
                    elif info["moderation_action"] == "followersoff":
                        embed = DiscordEmbed(
                        title=f"Follower Only Chat Mode Disabled",
                        color=0xFFFF00
                        )
                        embed.add_embed_field(
                            name="Channel", value=f"[{channel_display_name}](https://www.twitch.tv/{channel_name})", inline=True)
                        embed.add_embed_field(
                            name="Moderator", value=f"`{info['created_by']}`", inline=True)

                    
                    elif info["moderation_action"] == "host":
                        embed = DiscordEmbed(
                        title=f"Host Action Performed",
                        color=0xFFFF00
                        )
                        embed.add_embed_field(
                            name="Channel", value=f"[{channel_display_name}](https://www.twitch.tv/{channel_name})", inline=True)
                        embed.add_embed_field(
                            name="Moderator", value=f"`{info['created_by']}`", inline=True)
                        embed.add_embed_field(
                            name="Hosted Channel", value=f"[{info['args'][0]}](https://www.twitch.tv/{info['args'][0]})", inline=True)
                    elif info["moderation_action"] == "unhost":
                        embed = DiscordEmbed(
                        title=f"Unhost Action Performed",
                        color=0xFFFF00
                        )
                        embed.add_embed_field(
                            name="Channel", value=f"[{channel_display_name}](https://www.twitch.tv/{channel_name})", inline=True)
                        embed.add_embed_field(
                            name="Moderator", value=f"`{info['created_by']}`", inline=True)


                    elif info["moderation_action"] == "raid":
                        embed = DiscordEmbed(
                        title=f"Raid Action Performed",
                        color=0xFFFF00
                        )
                        embed.add_embed_field(
                            name="Channel", value=f"[{channel_display_name}](https://www.twitch.tv/{channel_name})", inline=True)
                        embed.add_embed_field(
                            name="Moderator", value=f"`{info['created_by']}`", inline=True)
                        embed.add_embed_field(
                            name="Raided Channel", value=f"[{info['args'][0]}](https://www.twitch.tv/{info['args'][0]})", inline=True)
                    elif info["moderation_action"] == "unraid":
                        embed = DiscordEmbed(
                        title=f"Unraid Action Performed",
                        color=0xFFFF00
                        )
                        embed.add_embed_field(
                            name="Channel", value=f"[{channel_display_name}](https://www.twitch.tv/{channel_name})", inline=True)
                        embed.add_embed_field(
                            name="Moderator", value=f"`{info['created_by']}`", inline=True)

                    elif info["moderation_action"] == "mod":
                        return
                    
                    else:
                        if info["args"] == None:
                            embed = DiscordEmbed(
                                title=f"Mod {info['moderation_action'].replace('_', ' ').title()} Action",
                                color=0xFF0000
                            )
                        else:
                            embed = DiscordEmbed(
                                title=f"Mod {info['moderation_action'].replace('_', ' ').title()} Action",
                                description=f"[Review Viewercard for User](https://www.twitch.tv/popout/{channel_name}/viewercard/{info['args'][0]})",
                                color=0xFF0000
                            )

                        embed.add_embed_field(
                            name="Channel", value=f"[{channel_display_name}](https://www.twitch.tv/{channel_name})", inline=True)
                        if info["created_by"] == "":
                            embed.add_embed_field(
                                name="Moderator", value=f"NONE", inline=True)
                        else:
                            embed.add_embed_field(
                                name="Moderator", value=f"`{info['created_by']}`", inline=True)
                        try:
                            embed.add_embed_field(
                                name="Flagged Account", value=f"`{info['args'][0]}`", inline=True)
                        except KeyError:
                            pass
                        except TypeError:
                            pass
                        if info['moderation_action'] == "timeout":
                            if info['args'][2] == "":
                                embed.add_embed_field(
                                    name="Flag Reason", value=f"`None Provided`", inline=False)
                            else:
                                embed.add_embed_field(
                                    name="Flag Reason", value=f"`{info['args'][2]}`", inline=False)

                            embed.add_embed_field(
                                name="Duration", value=f"{info['args'][1]} seconds", inline=False)
                            if info['msg_id'] == "":
                                embed.add_embed_field(
                                    name="Message ID", value=f"NONE", inline=False)
                            else:
                                embed.add_embed_field(
                                    name="Message ID", value=f"`{info['msg_id']}`", inline=False)
                        elif info['moderation_action'] == "untimeout":
                            pass
                        elif info['moderation_action'] == "ban":
                            if info['args'][1] == "":
                                embed.add_embed_field(
                                    name="Flag Reason", value=f"`None Provided`", inline=False)
                            else:
                                embed.add_embed_field(
                                    name="Flag Reason", value=f"`{info['args'][1]}`", inline=False)
                        elif info['moderation_action'] == "unban":
                            pass
                        elif info['moderation_action'] == "delete":
                            embed.add_embed_field(
                                name="Message", value=f"`{info['args'][1]}`", inline=False)
                            embed.add_embed_field(
                                name="Message ID", value=f"`{info['args'][2]}`", inline=False)
                        elif info["moderation_action"] == "automod_rejected":
                            embed.add_embed_field(
                                name="Message", value=f"`{info['args'][1]}`", inline=False)
                            embed.add_embed_field(
                                name="Rejected Reason", value=f"`{info['args'][2]}`", inline=False)
                            embed.add_embed_field(
                                name="Message ID", value=f"`{info['msg_id']}`", inline=False)
                        elif info["moderation_action"] == "approved_automod_message":
                            embed.add_embed_field(
                                name="Message ID", value=f"`{info['msg_id']}`", inline=False)
                        elif info["moderation_action"] == "add_permitted_term":
                            embed.add_embed_field(
                                name="Added by", value=f"`{info['created_by']}`", inline=False)
                            embed.add_embed_field(
                                name="Value", value=f"`{info['args'][0]}`", inline=False)
                        elif info["moderation_action"] == "add_blocked_term":
                            embed.add_embed_field(
                                name="Added by", value=f"`{info['created_by']}`", inline=False)
                            embed.add_embed_field(
                                name="Value", value=f"`{info['args'][0]}`", inline=False)
                        elif info["moderation_action"] == "delete_permitted_term":
                            embed.add_embed_field(
                                name="Removed by", value=f"`{info['created_by']}`", inline=False)
                            embed.add_embed_field(
                                name="Value", value=f"`{info['args'][0]}`", inline=False)
                        else:
                            embed.add_embed_field(
                                name="UNKNOWN ACTION", value=f"`{info['moderation_action']}`", inline=False)

                    embed.set_footer(text="Mew", icon_url=streamer["icon"])
                    embed.set_timestamp()
                    webhook.add_embed(embed)
                    response = webhook.execute()
                    if type(response).__name__ == "list":
                        self.logging.info(f"Sent webhook, response:  {', '.join([str(response.status_code) for response in response])}")
                    elif type(response).__name__ == "str":
                        self.logging.info(f"Sent webhook, response:  {str(response.status_code)}")
                elif message["type"] == "moderator_added":
                    channel_name = streamer["username"]
                    channel_display_name = streamer["display_name"]
                    embed = DiscordEmbed(
                        title=f"{message['type'].replace('_', ' ').title()} action",
                        description=f"[Review Viewercard for User](https://www.twitch.tv/popout/{channel_name}/viewercard/{message['data']['target_user_login']})",
                        color=0x00FF00
                    )
                    embed.add_embed_field(
                        name="Channel", value=f"[{channel_display_name}](https://www.twitch.tv/{channel_name})", inline=True)
                    embed.add_embed_field(
                        name="Moderator", value=f"`{message['data']['created_by']}`", inline=True)
                    embed.add_embed_field(
                        name="Flagged Account", value=f"`{message['data']['target_user_login']}`", inline=True)

                    embed.set_footer(text="Mew", icon_url=streamer["icon"])
                    embed.set_timestamp()
                    webhook.add_embed(embed)
                    response = webhook.execute()
                    if type(response).__name__ == "list":
                        self.logging.info(f"Sent webhook, response:  {', '.join([str(response.status_code) for response in response])}")
                    elif type(response).__name__ == "str":
                        self.logging.info(f"Sent webhook, response:  {str(response.status_code)}")

                elif message["type"] == "approve_unban_request" or message["type"] == "deny_unban_request":
                    channel_name = streamer["username"]
                    channel_display_name = streamer["display_name"]
                    if message["type"] == "approve_unban_request":
                        color = 0x00FF00
                    else:
                        color = 0xFF0000
                    embed = DiscordEmbed(
                        title=f"Mod {message['type'].replace('_', ' ').title()} action",
                        description=f"[Review Viewercard for User](https://www.twitch.tv/popout/{channel_name}/viewercard/{message['data']['target_user_login']})",
                        color=color
                    )
                    embed.add_embed_field(
                        name="Channel", value=f"[{channel_display_name}](https://www.twitch.tv/{channel_name})", inline=True)
                    embed.add_embed_field(
                        name="Moderator", value=f"`{message['data']['created_by_login']}`", inline=True)
                    embed.add_embed_field(
                        name="Flagged Account", value=f"`{message['data']['target_user_login']}`", inline=True)

                    embed.set_footer(text="Mew", icon_url=streamer["icon"])
                    embed.set_timestamp()
                    webhook.add_embed(embed)
                    response = webhook.execute()
                    if type(response).__name__ == "list":
                        self.logging.info(f"Sent webhook, response:  {', '.join([str(response.status_code) for response in response])}")
                    elif type(response).__name__ == "str":
                        self.logging.info(f"Sent webhook, response:  {str(response.status_code)}")
                    
                else:
                    raise TypeError("Unkown Type")
        except Exception as e:
            formatted_exception = "Traceback (most recent call last):\n" + ''.join(format_tb(e.__traceback__)) + f"{type(e).__name__}: {e}"
            self.logging.error(formatted_exception)
            if "data" not in json.loads(str(raw_message)).keys():
                self.logging.error(raw_message)
                return
            streamer_id = json.loads(str(raw_message))["data"]["topic"].split(".")[-1]
            streamer = self._streamers[streamer_id]
            webhook = DiscordWebhook(url=streamer["webhook_urls"])
            embed = DiscordEmbed(
                title=f"Safety Embed",
                description=f"If you see this something went wrong in the embed process, with the data from Twitch, or with how we are handling the Twitch Data.",
                color=0x880080
            )
            embed.add_embed_field(
                name="Traceback", value=f"```python\n{formatted_exception}```", inline=False)
            embed.add_embed_field(
                name="Debug Data", value=f"`{json.loads(str(raw_message))}`", inline=False)
            embed.set_footer(text="Mew", icon_url=streamer["icon"])
            embed.set_timestamp()
            webhook.add_embed(embed)
            response = webhook.execute()
            if type(response).__name__ == "list":
                self.logging.info(f"Sent webhook, response:  {', '.join([str(response.status_code) for response in response])}")
            elif type(response).__name__ == "str":
                self.logging.info(f"Sent webhook, response:  {str(response.status_code)}")


p = PubSubLogging()
p.run()
