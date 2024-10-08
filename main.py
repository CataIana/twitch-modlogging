#!/usr/bin/env python3

import asyncio
from websockets import client as wclient
from websockets.exceptions import ConnectionClosed
import disnake
import uuid
import json
import sys
from socket import gaierror
from requests import get
from random import uniform
from traceback import format_tb
from aiohttp import ClientSession
from messageparser import Parser
from message import Message
from streamer import Streamer
import logging
from typing import Dict

class ConfigError(Exception):
    pass

# https://id.twitch.tv/oauth2/authorize?client_id=CLIENT_ID&redirect_uri=https://twitchapps.com/tmi/&response_type=token&scope=channel:moderate+chat:read

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

        self.queue = asyncio.Queue(maxsize=0)
        self._streamers: Dict[str, Streamer] = {}
        self._tasks: list[asyncio.Task] = []

        # Read twitch authorization data

        try:
            with open("settings.json") as f:
                channels = json.load(f)
        except FileNotFoundError:
            raise ConfigError("Unable to locate settings file!")
        if not channels.get("authorization", None):
            raise ConfigError("Authorization not provided")
        try:  # Get authorization data
            uid = str(channels["authorization"]["id"])
            auth_token = channels["authorization"]["auth_token"].split("oauth:", 1)[-1]
            client_id = channels["authorization"]["client_id"]
            del channels["authorization"]
        except KeyError:
            raise ConfigError("Unable to fetch user ID and Authorization Token!")

        # Read config options

        use_embeds = channels["_config"].get("use_embeds", True)
        ignored_mods = channels["_config"].get("ignored_moderators", [])
        if type(ignored_mods) == str:
            ignored_mods = [ignored_mods]
        elif ignored_mods == None:
            ignored_mods = []

        self.robot_heartbeat_url = channels["_config"].get("uptime_heartbeat_url", None)
        try:
            self.robot_heartbeat_frequency = int(channels["_config"].get("uptime_heartbeat_frequency_every_x_minutes", 0))
        except ValueError:
            raise ConfigError("Uptime heartbeat frequency is not a valid integer!")

        del channels["_config"]

        try:
            # Get information of each defined streamer, such as ID, icon, and display name
            response = get(url=f"https://api.twitch.tv/helix/users?login={'&login='.join([channel for channel in channels.keys() if not channel.startswith('_')])}", headers={"Client-ID": client_id, "Authorization": f"Bearer {auth_token}"})
            json_obj = response.json()
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
                        user["login"], display_name=user["display_name"], icon=user["profile_image_url"], webhook_urls=webhooks, enable_automod=enable_automod, action_whitelist=mod_action_whitelist)
        except KeyError:
            raise ConfigError("Error during initialization. Check your client id and settings file!")

        self.logging.info(
            f"Listening for chat moderation actions for: {', '.join(channels.keys())}")

        # Create the subscription message to be sent when connecting/reconnecting
        topics = []
        using_automod = [] #Purely for the logging message
        for c_id in list(self._streamers.keys()):
            topics.append(f"chat_moderator_actions.{uid}.{c_id}")
            if self._streamers[c_id].enable_automod: #Subscribe to automod topics if enabled.
                topics.append(f"automod-queue.{uid}.{c_id}")
                #topics.append(f"user-moderation-notifications.{uid}.{c_id}")
                using_automod.append(self._streamers[c_id].username)
        if using_automod != []:
            self.logging.info(f"Listening for automod actions for: {', '.join(using_automod)}")
        if len(topics) > 50:
            raise ConfigError("You have too many topics! Limit of 50 topics (Mod actions count for 1, automod counts for 1 more)")
        self.subscribe_message = {"type": "LISTEN", "nonce": str(uuid.uuid1().hex), "data": {
            "topics": topics, "auth_token": auth_token}}

        self.parser = Parser(self._streamers, use_embeds=use_embeds, ignored_mods=ignored_mods)

    def run(self):
        self.loop = asyncio.new_event_loop()
        #self.loop = asyncio.get_event_loop()
        self.loop.run_until_complete(self.main())

    async def main(self):
        self.aioSession = ClientSession()
        while True:  # Tasks will finish if connection is closed, loop ensures everything reconnects
            failed_attempts = 0
            while True:  # Not sure if it works, but an attempt at a connecting backoff, using while True since self.connection isn't defined yet
                try:
                    self.connection = await wclient.connect("wss://pubsub-edge.twitch.tv")
                except gaierror:
                    pass
                # If connection didn't succeed, use getattr in case of error
                if getattr(self.connection, "closed", True):
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
            self._tasks = [
                self.loop.create_task(self.twitch_heartbeat()), # Twitch Pubsub requires occasional pings
                self.loop.create_task(self.message_reciever()), # Recieves the messages from the websocket and parses them
                self.loop.create_task(self.worker()) # Handles sending the messages created by the message reciever
            ]
            if self.robot_heartbeat_url and self.robot_heartbeat_frequency > 0:
                self._tasks += [
                    self.loop.create_task(self.robot_heartbeat()) # If configured, send occasional pings to uptimerobot
                ]
            try:
                await asyncio.wait(self._tasks) # Tasks will run until the connection closes, we need to re-establish it if it closes
            except asyncio.exceptions.CancelledError:
                pass
            self.logging.info("Reconnecting")

    async def message_reciever(self):
        while not self.connection.closed:
            try:
                message = await self.connection.recv()
                await self.messagehandler(message)
            except ConnectionClosed:
                self.logging.warning("Connection with server closed")
        [task.cancel() for task in self._tasks if task is not asyncio.tasks.current_task()]

    async def twitch_heartbeat(self):
        while not self.connection.closed:
            try:
                json_request = json.dumps({"type": "PING"})
                self.logging.debug("Ping!")
                await self.connection.send(json_request)
                # Send a ping every 120 seconds with a slight variance in delay
                await asyncio.sleep(120+uniform(-0.25, 0.25))
            except ConnectionClosed:
                self.logging.warning("Connection with server closed")
        [task.cancel() for task in self._tasks if task is not asyncio.tasks.current_task()]
    
    async def robot_heartbeat(self):
        while not self.connection.closed:
            if self.robot_heartbeat_url and self.robot_heartbeat_frequency > 0:
                self.logging.debug("Sending uptime heartbeat")
                await self.aioSession.get(self.robot_heartbeat_url)
            # Sleep for defined value
            await asyncio.sleep(self.robot_heartbeat_frequency*60)
    
    async def worker(self):
        while not self.connection.closed:
            message: Message = await self.queue.get()
            self.logging.debug(f"Recieved queue event")
            if not message.ignore:  # Some messages can be ignored as duplicates are recieved etc
                await message.send(session=self.aioSession)
            self.queue.task_done()

    async def messagehandler(self, raw_message: dict):
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
                message = await self.parser.parse_message(json_message["data"])
                self.queue.put_nowait(message)
        except Exception as e: #Catch every exception and send it to the associated streamer, if they can be gathered
            formatted_exception = "Traceback (most recent call last):\n" + ''.join(
                format_tb(e.__traceback__)) + f"{type(e).__name__}: {e}"
            self.logging.error(formatted_exception)
            if "data" not in json.loads(str(raw_message)).keys():
                self.logging.error(raw_message)
                return
            streamer_id = json.loads(str(raw_message))["data"]["topic"].split(".")[-1]
            streamer = self._streamers[streamer_id]
            embed = disnake.Embed(
                title=f"Safety Embed",
                description=f"If you see this something went wrong with the data from Twitch, or how it is being handled.",
                color=0x880080,
                timestamp=disnake.utils.utcnow()
            )
            embed.add_field(
                name="Traceback", value=f"```python\n{formatted_exception}```", inline=False)
            embed.add_field(
                name="Debug Data", value=f"`{json.loads(str(raw_message))}`", inline=False)

            webhooks = []
            for webhook in streamer.webhook_urls:
                webhooks.append(disnake.Webhook.from_url(
                    webhook, session=self.aioSession))
            embed.set_footer(text="Sad", icon_url=streamer.icon)
            for webhook in webhooks:
                try:
                    await webhook.send(embed=embed)
                except disnake.NotFound:
                    self.logging.error(f"Webhook not found for {streamer}")
                except disnake.HTTPException as e:
                    self.logging.error(f"HTTP Exception sending webhook: {e}")

if __name__ == "__main__":
    p = PubSubLogging()
    p.run()
