#!/usr/bin/env python3

import asyncio
import json
import logging
import sys
from contextlib import suppress
from time import sleep, time
from traceback import format_tb
from typing import Dict

import disnake
import websockets
from aiohttp import ClientSession
from requests import get
from requests.exceptions import ConnectionError
from websockets.legacy.client import WebSocketClientProtocol

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
        self.logging.setLevel(logging.INFO)
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
            failed_attempts = 0
            while True:
                # Get information of each defined streamer, such as ID, icon, and display name
                try:
                    response = get(url=f"https://api.twitch.tv/helix/users?login={'&login='.join([channel for channel in channels.keys() if not channel.startswith('_')])}", headers={"Client-ID": self.client_id, "Authorization": f"Bearer {self.authorisation}"})
                except ConnectionError:
                    if 2**failed_attempts > 128:
                        sleep(120)
                    else:
                        sleep(2**failed_attempts)
                    failed_attempts += 1 # Continue to back off exponentially with every failed connection attempt up to 2 minutes
                    self.logging.warning(
                        f"{failed_attempts} failed attempts to fetch broadcaster data.")
                    continue
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
                break
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
            await asyncio.sleep(0.05)
        self.logging.debug("Events Subscribed")
        self.logging.info("Ready")

    def run(self):
        self.loop = asyncio.new_event_loop()
        try:
            self.loop.run_until_complete(self.main())
        except KeyboardInterrupt:
            pass
        finally:
            self.logging.debug("Shutting down")
            for task in self._tasks:
                task.cancel()
                # Now we should await task to execute it's cancellation.
                # Cancelled task raises asyncio.CancelledError that we can suppress:
                with suppress(asyncio.CancelledError):
                    self.loop.run_until_complete(task)
            self.loop.run_until_complete(self.aioSession.close())
            # Takes forever to close
            self.loop.run_until_complete(self.connection.close())
        self.loop.close()

    async def main(self):
        self.aioSession = ClientSession()
        while True:
            self.logging.debug("Connecting to websocket")
            async for connection in websockets.connect(self.connection_url):
                self.connection = connection
                self.logging.info("Connected to websocket")
                if self.connection_url != DEFAULT_CONNECTION_URL:
                    self.connection_url = DEFAULT_CONNECTION_URL
                self._tasks = [
                    self.loop.create_task(self.twitch_heartbeat(connection)), # Twitch Pubsub requires occasional pings
                    self.loop.create_task(self.message_reciever(connection)), # Recieves the messages from the websocket and parses them
                    self.loop.create_task(self.worker(connection)) # Handles sending the messages created by the message reciever
                ]
                if self.robot_heartbeat_url and self.robot_heartbeat_frequency > 0:
                    self._tasks += [
                        self.loop.create_task(self.robot_heartbeat(connection)) # If configured, send occasional pings to uptimerobot
                    ]
                await asyncio.wait(self._tasks) # Tasks will run until the connection closes, we need to re-establish it if it closes

    async def message_reciever(self, connection: WebSocketClientProtocol):
        while not connection.closed:
            try:
                message = await connection.recv()
                self.last_message_time = time()
                await self.messagehandler(message)
            except websockets.exceptions.ConnectionClosed:
                self.logging.warning("Connection with server closed")
                [task.cancel() for task in self._tasks if task is not asyncio.tasks.current_task()]

    async def twitch_heartbeat(self, connection: WebSocketClientProtocol):
        while not connection.closed:
            await asyncio.sleep(30)
            if self.last_message_time + 30 < time() and not connection.closed:
                self.logging.info("Connection seems dead, restarting websocket")
                await connection.close()
                [task.cancel() for task in self._tasks if task is not asyncio.tasks.current_task()]

    async def robot_heartbeat(self, connection: WebSocketClientProtocol):
        while not connection.closed:
            if self.robot_heartbeat_url and self.robot_heartbeat_frequency > 0:
                self.logging.debug("Sending uptime heartbeat")
                await self.aioSession.get(self.robot_heartbeat_url)
            # Sleep for defined value
            await asyncio.sleep(self.robot_heartbeat_frequency*60)

    async def worker(self, connection: WebSocketClientProtocol):
        while not connection.closed:
            message: Message = await self.queue.get()
            self.logging.debug(f"Recieved queue event")
            if not message.ignore:  # Some messages can be ignored as duplicates are recieved etc
                await message.send(session=self.aioSession)
            self.queue.task_done()

    async def messagehandler(self, raw_message: str):
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
            try:
                json_message = json.loads(raw_message)

                # If payload is empty we have no broadcaster to go by so just log and continue
                if json_message.get("payload", {}) == {}:
                    self.logging.error(json.dumps(raw_message, indent=4))
                    return
                
                streamer_id = json_message["payload"]["subscription"]["condition"]["broadcaster_user_id"]
                streamer = self._streamers[streamer_id]
                # Remove null values to save space
                exclude_these_keys = ['broadcaster_user_id', 'broadcaster_user_login', 'broadcaster_user_name', 'user_name', 'moderator_user_name']
                minimised = {k: v for k, v in json_message["payload"]["event"].items() if v is not None and k != exclude_these_keys}
                del minimised["message"]["fragments"]
                embed = disnake.Embed(
                    title=f"Safety Embed",
                    description=f"If you see this something went wrong with the data from Twitch, or how it is being handled.",
                    color=0x880080,
                    timestamp=disnake.utils.utcnow()
                )
                embed.add_field(
                    name="Traceback", value=f"```python\n{formatted_exception}```", inline=False)
                embed.add_field(
                    name="Debug Data", value=f"`{json.dumps(minimised)}`", inline=False)

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
            except Exception as ee:
                self.logging.error("Exception handling exception message")
                formatted_nested_exception = "Traceback (most recent call last):\n" + ''.join(
                format_tb(ee.__traceback__)) + f"{type(ee).__name__}: {ee}"
                self.logging.error(formatted_nested_exception)

if __name__ == "__main__":
    p = PubSubLogging()
    p.run()
