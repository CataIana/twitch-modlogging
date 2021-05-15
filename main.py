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
from parser import Parser
import logging

class PubSubLogging:
    def __init__(self):
        self.logging = logging.getLogger("Twitch Pubsub Logging")
        self.logging.setLevel(logging.DEBUG)
        formatter = logging.Formatter("%(asctime)s %(levelname)s [%(module)s %(funcName)s %(lineno)d]: %(message)s", "%Y-%m-%d %I:%M:%S%p")

        #File logging
        # fh = logging.FileHandler("log.log", "w")
        # fh.setLevel(logging.WARNING)
        # fh.setFormatter(formatter)
        # self.logging.addHandler(fh)

        #Console logging
        chandler = logging.StreamHandler(sys.stdout)
        chandler.setLevel(self.logging.level)
        chandler.setFormatter(formatter)
        self.logging.addHandler(chandler)

        try:
            with open("settings2.json") as f:
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
                self.logging.warning("Reconnecting...")
                await asyncio.sleep(5)
                await self.connection.close()
            elif json_message["type"] == "MESSAGE":
                message = json.loads(json_message["data"]["message"])
                streamer_id = json_message["data"]["topic"].split(".")[-1]
                streamer = self._streamers[streamer_id]
                channel_name = streamer["username"]
                channel_display_name = streamer["display_name"]
                if message["type"] in ["moderation_action", "moderator_added", "moderator_removed", "approve_unban_request", "deny_unban_request"]: #This one handles just about everything
                    if message["type"] == "moderation_action" and message["data"].get("moderation_action", None) in ["mod"]:
                        return #Ignore some duplicates
                    p = Parser(streamer, message["data"]) #Data parser, along with all the switches for various mod actions
                    embed = await p.get_embed()
                    if embed is None: #If nothing is returned, do not send anything
                        return
                    else:
                        await p.send(self.aioSession)

                elif message["type"] == "channel_terms_action": #These are funky so they're done seperately
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
                    if info.get("requester_login", "") == "":
                        embed.add_field(
                            name="Moderator", value=f"NONE", inline=True)
                    else:
                        embed.add_field(
                            name="Moderator", value=f"`{info['requester_login']}`", inline=True)

                    if mod_action in ["add_permitted_term", "add_blocked_term"]:
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

                    await self.finalise_embed(embed, streamer)

                elif message["type"] == "vip_added": #This is a weird one. Can't be parsed by the usual thing.
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
            embed = DiscordEmbed(
                title=f"Safety Embed",
                description=f"If you see this something went wrong with the data from Twitch, or how it is being handled.",
                color=0x880080,
                timestamp=datetime.utcnow()
            )
            embed.add_field(
                name="Traceback", value=f"```python\n{formatted_exception}```", inline=False)
            embed.add_field(
                name="Debug Data", value=f"`{json.loads(str(raw_message))}`", inline=False)
            await self.finalise_embed(embed, streamer)

    async def finalise_embed(self, embed, streamer):
        webhooks = []
        for webhook in streamer["webhook_urls"]:
            webhooks.append(DiscordWebhook.from_url(webhook, adapter=AsyncWebhookAdapter(self.aioSession)))
        embed.set_footer(text="Mew", icon_url=streamer["icon"])
        for webhook in webhooks:
            try:
                await webhook.send(embed=embed)
            except NotFound:
                self.logging.error(f"Webhook not found for {streamer}")


p = PubSubLogging()
p.run()
