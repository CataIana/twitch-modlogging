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
from discord import NotFound, HTTPException
from discord import Webhook as DiscordWebhook
from discord import Embed as DiscordEmbed
from discord import AsyncWebhookAdapter
from aiohttp import ClientSession
from parser import Parser
import logging


class Streamer:
    def __init__(self, username, display_name, icon, webhook_urls, automod=False, whitelist=[]):
        self.username = username
        self.user = username
        self.display_name = display_name
        self.icon = icon
        self.webhook_urls = webhook_urls
        self.automod = automod
        self.enable_automod = automod
        self.action_whitelist = whitelist

    def __str__(self):
        return self.username

class ConfigError(Exception):
    pass


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
            raise ConfigError("Unable to locate settings file!")
        if "authorization" not in channels.keys():
            raise ConfigError("Authorization not provided")
        try:  # Get authorization data
            uid = str(channels["authorization"]["id"])
            auth_token = channels["authorization"]["auth_token"].split("oauth:", 1)[-1]
            client_id = channels["authorization"]["client_id"]
            del channels["authorization"]
        except KeyError:
            raise ConfigError("Unable to fetch user ID and Authorization Token!")

        self.use_embeds = channels["_config"].get("use_embeds", True)
        self.ignored_mods = channels["_config"].get("ignored_moderators", [])
        if type(self.ignored_mods) == str:
            self.ignored_mods = [self.ignored_mods]
        if self.ignored_mods == None:
            self.ignored_mods = []
        del channels["_config"]

        try:
            # Get information of each defined streamer, such as ID, icon, and display name
            self._streamers = {}
            response = get(url=f"https://api.twitch.tv/helix/users?login={'&login='.join([channel for channel in channels.keys() if not channel.startswith('_')])}", headers={"Client-ID": client_id, "Authorization": f"Bearer {auth_token}"})
            json_obj = json.loads(response.content.decode())
            for user in json_obj["data"]: 
                if type(channels[user["login"]]) == list: #If settings file is the old configuration.
                    webhooks = channels[user["login"]]
                    self._streamers[user['id']] = Streamer(
                        user["login"], display_name=user["display_name"], icon=user["profile_image_url"], webhook_urls=webhooks)
                else:
                    webhooks = channels[user["login"]]["webhooks"]
                    enable_automod = channels[user["login"]].get("enable_automod", False)
                    mod_action_whitelist = channels[user["login"]].get("mod_action_whitelist", [])
                    self._streamers[user['id']] = Streamer(
                        user["login"], display_name=user["display_name"], icon=user["profile_image_url"], webhook_urls=webhooks, automod=enable_automod, whitelist=mod_action_whitelist)
        except KeyError:
            raise ConfigError("Error during initialization. Check your client id and settings file!")

        self.logging.info(
            f"Listening for chat moderation actions for: {', '.join(channels.keys())}")

        # Create the subscription message to be sent when connecting/reconnecting
        topics = []
        using_automod = [] #Purely for the logging message
        for c_id in list(self._streamers.keys()):
            topics.append(f"chat_moderator_actions.{uid}.{c_id}")
            if self._streamers[c_id].automod: #Subscribe to automod topics if enabled.
                topics.append(f"automod-queue.{uid}.{c_id}")
                #topics.append(f"user-moderation-notifications.{uid}.{c_id}")
                using_automod.append(self._streamers[c_id].username)
        if using_automod != []:
            self.logging.info(f"Listening for automod actions for: {', '.join(using_automod)}")
        if len(topics) > 50:
            raise ConfigError("You have too many topics! Limit of 50 topics (Mod actions count for 1, automod counts for 1 more)")
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
                    failed_attempts += 1 # Continue to back off exponentially with every failed connection attempt up to 2 minutes
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
            # Twitch sends this message when it wants the client to reconnect, so we force disconnect.
            elif json_message["type"] == "RECONNECT":
                self.logging.warning("Reconnecting...")
                await asyncio.sleep(5)
                # Close the connection and let the code reconnect automatically
                await self.connection.close()
            elif json_message["type"] == "MESSAGE":
                # Data parser, along with all the switches for various mod actions
                p = Parser(self._streamers, json_message["data"], use_embeds=self.use_embeds, ignored_mods=self.ignored_mods)
                await p.create_message()
                if not p.ignore_message:  # Some messages can be ignored as duplicates are recieved etc
                    await p.send(session=self.aioSession)

        except Exception as e: #Catch every exception and send it to the associated streamer, if they can be gathered
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
                except HTTPException as e:
                    self.logging.error(f"HTTP Exception sending webhook: {e}")

if __name__ == "__main__":
    p = PubSubLogging()
    p.run()
