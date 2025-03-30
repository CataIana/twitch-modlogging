#!/usr/bin/env python3

import asyncio
import json
import logging
import sys
from socket import gaierror
from time import time
from traceback import format_tb
from typing import Dict

import disnake
import websockets
from aiohttp import ClientSession
from requests import get

from message import Message
from messageparser import Parser
from streamer import Streamer


class ConfigError(Exception):
    pass

# https://id.twitch.tv/oauth2/authorize?client_id=CLIENT_ID&redirect_uri=https://twitchapps.com/tmi/&response_type=token&scope=channel:moderate+chat:read

DEFAULT_CONNECTION_URL = "wss://eventsub.wss.twitch.tv/ws"
API_URL = "https://api.twitch.tv/helix"

class PubSubLogging:
    def __init__(self):
        self.logging = logging.getLogger("Twitch Pubsub Logging")
        self.logging.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            "%(levelname)s [%(module)s %(funcName)s %(lineno)d]: %(message)s")

        # Console logging
        chandler = logging.StreamHandler(sys.stdout)
        chandler.setLevel(self.logging.level)
        chandler.setFormatter(formatter)
        self.logging.addHandler(chandler)

        self.queue = asyncio.Queue(maxsize=0)
        self._streamers: Dict[str, Streamer] = {}
        self._tasks: list[asyncio.Task] = []
        
        self.connection_url: str = DEFAULT_CONNECTION_URL
        self.last_message_time: int = 0
        self.should_resubscribe: bool = True
        self.current_session_id: str = None
        self.current_user_id: str = None
        self.client_id: str = None
        self.authorisation: str = None

        # Read twitch authorization data

        try:
            with open("settings.json") as f:
                channels = json.load(f)
        except FileNotFoundError:
            raise ConfigError("Unable to locate settings file!")
        if not channels.get("authorization", None):
            raise ConfigError("Authorization not provided")
        try:  # Get authorization data
            self.current_user_id = str(channels["authorization"]["id"])
            self.authorisation = channels["authorization"]["auth_token"].split("oauth:", 1)[-1]
            self.client_id = channels["authorization"]["client_id"]
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
            response = get(url=f"https://api.twitch.tv/helix/users?login={'&login='.join([channel for channel in channels.keys() if not channel.startswith('_')])}", headers={"Client-ID": self.client_id, "Authorization": f"Bearer {self.authorisation}"})
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
            f"Listening for chat moderation actions for: {', '.join(v.display_name for v in self._streamers.values())}")
        using_automod = [v.display_name for v in self._streamers.values() if v.enable_automod]
        if using_automod != []:
            self.logging.info(f"Listening for automod actions for: {', '.join(using_automod)}")

        self.parser = Parser(self._streamers, use_embeds=use_embeds, ignored_mods=ignored_mods)

    async def subscribe_to_events(self, session_id: str):
        headers = {
            "Authorization": f"Bearer {self.authorisation}",
            "Client-ID": self.client_id,
        }
        for c_id in list(self._streamers.keys()):
            r1 = await self.aioSession.post(f"{API_URL}/eventsub/subscriptions", headers=headers, json={
                "type": "channel.moderate",
                "version": "2",
                "condition": {
                    "broadcaster_user_id": c_id,
                    "moderator_user_id": self.current_user_id
                },
                "transport": {
                    "method": "websocket",
                    "session_id": session_id
                }
            })
            r1.raise_for_status()
            if self._streamers[c_id].enable_automod: #Subscribe to automod topics if enabled.
                r2 = await self.aioSession.post(f"{API_URL}/eventsub/subscriptions", headers=headers, json={
                    "type": "automod.message.hold",
                    "version": "2",
                    "condition": {
                        "broadcaster_user_id": c_id,
                        "moderator_user_id": self.current_user_id
                    },
                    "transport": {
                        "method": "websocket",
                        "session_id": session_id
                    }
                })
                r2.raise_for_status()
                r3 = await self.aioSession.post(f"{API_URL}/eventsub/subscriptions", headers=headers, json={
                    "type": "automod.message.update",
                    "version": "2",
                    "condition": {
                        "broadcaster_user_id": c_id,
                        "moderator_user_id": self.current_user_id
                    },
                    "transport": {
                        "method": "websocket",
                        "session_id": session_id
                    }
                })
                r3.raise_for_status()
            await asyncio.sleep(0.1)
        self.logging.debug("Events Subscribed")

    def run(self):
        self.loop = asyncio.new_event_loop()
        self.loop.run_until_complete(self.main())

    async def main(self):
        self.aioSession = ClientSession()
        while True:  # Tasks will finish if connection is closed, loop ensures everything reconnects
            failed_attempts = 0
            while True:  # Not sure if it works, but an attempt at a connecting backoff, using while True since self.connection isn't defined yet
                try:
                    self.connection = await websockets.connect(self.connection_url)
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
            if self.connection_url != DEFAULT_CONNECTION_URL:
                self.connection_url = DEFAULT_CONNECTION_URL
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
            self.logging.info("Initiating reconnection")

    async def message_reciever(self):
        while not self.connection.closed:
            try:
                message = await self.connection.recv()
                self.last_message_time = time()
                await self.messagehandler(message)
            except websockets.exceptions.ConnectionClosed:
                self.logging.warning("Connection with server closed")
        [task.cancel() for task in self._tasks if task is not asyncio.tasks.current_task()]

    async def twitch_heartbeat(self):
        while not self.connection.closed:
            await asyncio.sleep(30)
            if self.last_message_time + 30 < time():
                self.logging.info("Connection seems dead, restarting websocket")
                await self.connection.close()
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
            metadata = json_message.get("metadata", {})
            payload = json_message.get("payload", {})
            if metadata["message_type"] == "session_welcome":
                self.logging.debug("Welcome message received")
                self.current_session_id = payload["session"]["id"]
                if self.should_resubscribe:
                    await self.subscribe_to_events(self.current_session_id)
                self.should_resubscribe = True

            # Twitch sends this message when it wants the client to reconnect, so we force disconnect and reconnect with the provided url
            elif metadata["message_type"] == "session_reconnect":
                self.logging.warning("Twitch requested reconnection")
                self.connection_url = json_message["payload"]["session"]["reconnect_url"]
                self.should_resubscribe = False
                # Close the connection and let the code reconnect automatically
                await self.connection.close()

            elif metadata["message_type"] == "notification":
                self.logging.debug(json.dumps(json_message, indent=4))
                # Data parser, along with all the switches for various mod actions
                message = await self.parser.parse_message(json_message)
                self.queue.put_nowait(message)

            elif metadata["message_type"] == "session_keepalive":
                return

            else:
                # Catch all other messages and log them to the console
                self.logging.warning(f"Unhandled event!: {json.dumps(json_message, indent=4)}")

        except Exception as e: #Catch every exception and send it to the associated streamer, if they can be gathered
            formatted_exception = "Traceback (most recent call last):\n" + ''.join(
                format_tb(e.__traceback__)) + f"{type(e).__name__}: {e}"
            self.logging.error(formatted_exception)
            json_message = json.loads(str(raw_message))
            if json_message.get("payload", {}) == {}:
                self.logging.error(raw_message)
                return
            streamer_id = json_message["payload"]["subscription"]["condition"]["broadcaster_user_id"]
            streamer = self._streamers[streamer_id]
            minimised_message = dict(json_message)
            for k, v in json_message["payload"]["event"].items():
                if v == None:
                    del minimised_message["payload"]["event"][k]
            embed = disnake.Embed(
                title=f"Safety Embed",
                description=f"If you see this something went wrong with the data from Twitch, or how it is being handled.",
                color=0x880080,
                timestamp=disnake.utils.utcnow()
            )
            embed.add_field(
                name="Traceback", value=f"```python\n{formatted_exception}```", inline=False)
            embed.add_field(
                name="Debug Data", value=f"`{json.dumps(minimised_message, indent=4)}`", inline=False)

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
