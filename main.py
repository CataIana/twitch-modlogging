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
        self.logging.setLevel(logging.INFO)
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
        self.subscribe_message = {"type": "LISTEN", "nonce": str(uuid.uuid1().hex), "data": {
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
                webhook = DiscordWebhook(
                    url=streamer["webhook_urls"])
                if message["type"] == "moderation_action":
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
                        color=0xFFFF00
                        )
                        embed.add_embed_field(
                            name="Channel", value=f"[{channel_display_name}](https://www.twitch.tv/{channel_name})", inline=True)
                        embed.add_embed_field(
                            name="Moderator", value=f"`{info['created_by']}`", inline=True)

                    if mod_action == "slow":
                        embed.add_embed_field(
                            name="Slow Amount (seconds)", value=f"`{info['args'][0]}`", inline=True)

                    elif mod_action == "followers":
                        embed.add_embed_field(
                            name="Time Needed to be Following (minutes)", value=f"`{info['args'][0]}`", inline=True)
                    
                    elif mod_action == "host":
                        embed.add_embed_field(
                            name="Hosted Channel", value=f"[{info['args'][0]}](https://www.twitch.tv/{info['args'][0]})", inline=True)

                    elif mod_action == "raid":
                        embed.add_embed_field(
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
                        if info["args"] == None:
                            embed = DiscordEmbed(
                                title=title,
                                color=colour
                            )
                        else:
                            embed = DiscordEmbed(
                                title=title,
                                description=f"[Review Viewercard for User](https://www.twitch.tv/popout/{channel_name}/viewercard/{info['args'][0]})",
                                color=colour
                            )

                        embed.add_embed_field(
                            name="Channel", value=f"[{channel_display_name}](https://www.twitch.tv/{channel_name})", inline=True)
                        if "created_by" in info.keys():
                            if info["created_by"] == "":
                                embed.add_embed_field(
                                    name="Moderator", value=f"NONE", inline=True)
                            else:
                                embed.add_embed_field(
                                    name="Moderator", value=f"`{info['created_by']}`", inline=True)
                        else:
                            embed.add_embed_field(
                                name="Moderator", value=f"NONE", inline=True)
                        try:
                            embed.add_embed_field(
                                name="Flagged Account", value=f"`{info['args'][0]}`", inline=True)
                        except KeyError:
                            pass
                        except TypeError:
                            pass
                        if mod_action == "timeout":
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
                        elif mod_action == "untimeout":
                            pass
                        elif mod_action == "ban":
                            if info['args'][1] == "":
                                embed.add_embed_field(
                                    name="Flag Reason", value=f"`None Provided`", inline=False)
                            else:
                                embed.add_embed_field(
                                    name="Flag Reason", value=f"`{info['args'][1]}`", inline=False)
                        elif mod_action == "unban":
                            pass
                        elif mod_action == "delete":
                            embed.add_embed_field(
                                name="Message", value=f"`{info['args'][1]}`", inline=False)
                            embed.add_embed_field(
                                name="Message ID", value=f"`{info['args'][2]}`", inline=False)

                        elif mod_action == "unmod":
                            pass
                        elif mod_action == "mod":
                            pass

                        #Automod stuff
                        elif mod_action == "automod_rejected":
                            embed.add_embed_field(
                                name="Message", value=f"`{info['args'][1]}`", inline=False)
                            embed.add_embed_field(
                                name="Rejected Reason", value=f"`{info['args'][2]}`", inline=False)
                            embed.add_embed_field(
                                name="Message ID", value=f"`{info['msg_id']}`", inline=False)
                        elif mod_action == "approved_automod_message":
                            embed.add_embed_field(
                                name="Message ID", value=f"`{info['msg_id']}`", inline=False)
                        elif mod_action == "add_permitted_term":
                            embed.add_embed_field(
                                name="Added by", value=f"`{info['created_by']}`", inline=False)
                            embed.add_embed_field(
                                name="Value", value=f"`{info['args'][0]}`", inline=False)
                        elif mod_action == "add_blocked_term":
                            embed.add_embed_field(
                                name="Added by", value=f"`{info['created_by']}`", inline=False)
                            embed.add_embed_field(
                                name="Value", value=f"`{info['args'][0]}`", inline=False)
                        elif mod_action == "delete_permitted_term":
                            embed.add_embed_field(
                                name="Removed by", value=f"`{info['created_by']}`", inline=False)
                            embed.add_embed_field(
                                name="Value", value=f"`{info['args'][0]}`", inline=False)
                        else: #In case there's something new/unknown that happens
                            embed.add_embed_field(
                                name="UNKNOWN ACTION", value=f"`{mod_action}`", inline=False)

                    embed.set_footer(text="Mew", icon_url=streamer["icon"])
                    embed.set_timestamp()
                    webhook.add_embed(embed)
                    response = webhook.execute()
                    if type(response).__name__ == "list":
                        self.logging.info(f"Sent webhook, response:  {', '.join([str(response.status_code) for response in response])}")
                    elif type(response).__name__ == "str":
                        self.logging.info(f"Sent webhook, response:  {str(response.status_code)}")

                elif message["type"] == "moderator_added":
                    pass

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
                        color=colour
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
                    raise TypeError("Unknown Type")
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
                response_list = [str(response.status_code) for response in response]
                if all([True for response in response_list if response == "200"]):
                    self.logging.debug(f"Sent webhook, response:  {', '.join(response_list)}")
                else:
                    self.logging.warning(f"Sent webhook, response:  {', '.join(response_list)}")
            elif type(response).__name__ == "str":
                if str(response.status_code) == "200":
                    self.logging.debug(f"Sent webhook, response:  {str(response.status_code)}")
                else:
                    self.logging.warning(f"Sent webhook, response:  {str(response.status_code)}")


p = PubSubLogging()
p.run()
