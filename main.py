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
from discord import NotFound
from discord import Webhook as DiscordWebhook
from discord import Embed as DiscordEmbed
from discord import AsyncWebhookAdapter
from aiohttp import ClientSession
from parser import Parser
import logging


class Streamer:
    def __init__(self, username, display_name, icon, webhook_urls):
        self.username = username
        self.display_name = display_name
        self.icon = icon
        self.webhook_urls = webhook_urls

    def __str__(self):
        return self.username


class PubSubLogging:
    def __init__(self):
        self.logging = logging.getLogger("Twitch Pubsub Logging")
        self.logging.setLevel(logging.INFO)
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s [%(module)s %(funcName)s %(lineno)d]: %(message)s", "%Y-%m-%d %I:%M:%S%p")

        # File logging
        fh = logging.FileHandler("log.log", "w")
        fh.setLevel(logging.WARNING)
        fh.setFormatter(formatter)
        self.logging.addHandler(fh)

        # Console logging
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
        try:  # Get authorization data
            uid = str(channels["authorization"]["id"])
            auth_token = channels["authorization"]["auth_token"].split("oauth:", 1)[-1]
            client_id = channels["authorization"]["client_id"]
            del channels["authorization"]
        except KeyError:
            raise TypeError("Unable to fetch user ID and Authorization Token!")

        self.use_embeds = channels["_config"].get("use_embeds", True)
        self.ignored_mods = channels["_config"].get("ignored_moderators", [])
        del channels["_config"]

        try:
            # Get information of each defined streamer, such as ID, icon, and display name
            self._streamers = {}
            response = get(url=f"https://api.twitch.tv/kraken/users?login={','.join(channels.keys())}", headers={
                "Accept": "application/vnd.twitchtv.v5+json", "Client-ID": client_id})
            json_obj = json.loads(response.content.decode())
            for user in json_obj["users"]:
                self._streamers[user['_id']] = Streamer(
                    user["name"], display_name=user["display_name"], icon=user["logo"], webhook_urls=channels[user["name"]])
        except KeyError:
            raise TypeError(
                "Error during initialization. Check your client id and settings file!")

        self.logging.info(
            f"Listening for chat moderation actions for streamers {', '.join(channels.keys())}")

        # Create the subscription message to be sent when connecting/reconnecting
        topics = [f"chat_moderator_actions.{uid}.{c_id}" for c_id in list(
            self._streamers.keys())]
        self.subscribe_message = {"type": "LISTEN", "nonce": str(uuid.uuid1().hex), "data": {
            "topics": topics, "auth_token": auth_token}}

    def run(self):
        self.loop = asyncio.get_event_loop()
        self.loop.run_until_complete(self.main())

    async def main(self):
        self.aioSession = ClientSession()
        while True:  # Tasks will finish if connection is closed, loop ensures everything reconnects
            failed_attempts = 0
            while True:  # Not sure if it works, but an attempt at a connecting backoff, using while True since self.connection isn't defined yet
                self.connection = await wclient.connect("wss://pubsub-edge.twitch.tv")
                if self.connection.closed:
                    if 2**failed_attempts > 128:
                        await asyncio.sleep(120)
                    else:
                        await asyncio.sleep(2**failed_attempts)
                    failed_attempts += 1
                    self.logging.warning(
                        f"{failed_attempts} failed attempts to connect.")
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
                json_request = json.dumps({"type": "PING"})
                self.logging.debug("Ping!")
                await self.connection.send(json_request)
                # Send a ping every 120 seconds with a slight variance in delay
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
                    self.logging.error(
                        f"Error while subscribing to topics: {json_message['error']}")
            # Client sends the pings, nothing to be done when the server responds
            elif json_message["type"] == "PONG":
                self.logging.debug("Pong!")
            # Twitch sends this message when it wants the client to reconnect.
            elif json_message["type"] == "RECONNECT":
                self.logging.warning("Reconnecting...")
                await asyncio.sleep(5)
                # Close the connection and let the code reconnect automatically
                await self.connection.close()
            elif json_message["type"] == "MESSAGE":
                # Data parser, along with all the switches for various mod actions
                p = Parser(self, json_message["data"], use_embeds=self.use_embeds)
                await p.create_message()
                if not p.ignore_message:  # Some messages can be ignored as duplicates are recieved etc
                    await p.send(self.aioSession)

        except Exception as e:
            formatted_exception = "Traceback (most recent call last):\n" + ''.join(
                format_tb(e.__traceback__)) + f"{type(e).__name__}: {e}"
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

            webhooks = []
            for webhook in streamer.webhook_urls:
                webhooks.append(DiscordWebhook.from_url(
                    webhook, adapter=AsyncWebhookAdapter(self.aioSession)))
            embed.set_footer(text="Sad", icon_url=streamer.icon)
            for webhook in webhooks:
                try:
                    await webhook.send(embed=embed)
                except NotFound:
                    self.logging.error(f"Webhook not found for {streamer}")


p = PubSubLogging()
p.run()
