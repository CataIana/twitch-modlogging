# Twitch Modlogging Using Websockets and Python
This is my version of modlogging with python.

Figuring out how to do this was a pain, and there was nothing good on the internet that I could find, so I might as well give it out to anyone who might want it.


### Installation

* Clone the repo `git clone https://github.com/CataIana/twitch-modlogging.git`

* Make sure you have a recent python 3 installation. E.g Python 3.7 or 3.8

* Install the required dependencies `pip install --upgrade -r requirements.txt`

* Rename `examplesettings.json` to `settings.json`

* Go to the [twitch developer console](https://dev.twitch.tv/console) and click Register Your Application

* Give the application a name, if you have a redirect uri you can put yours in, but I just used `https://twitchapps.com/tmi/` since I don't

* Finish creating your application

* Open `settings.json`. From the twitch developers website, copy the Client ID and put it into the `client_id` key.

* Then put the user ID in the "id" key that will be used for getting logs. If you do not know this, run `get_userid.py` included in this repo. You will need to enter the same client ID used above in this program.

* Then you will need to authorize the Application to access your account. If the authorized user does not have mod privileges, no mod actions will be recieved. In this URL `https://id.twitch.tv/oauth2/authorize?client_id=CLIENT_ID&redirect_uri=https://twitchapps.com/tmi/&response_type=token&scope=channel:moderate` replace `CLIENT_ID` with your Client ID. If you have your own redirect URI, replace `https://twitchapps.com/tmi/` with your own. Upon authorizing with your twitch account, you will be redirected and shown an authorization token. Keep this safe. You can always revoke access [here](https://www.twitch.tv/settings/connections) and authorize again for a new token. Copy that token into the "auth_token" key in the settings file.

* Now you can configure which streamer mod actions you want to listen for. Each streamer allows a list of webhooks if you want to send them to multiple places. 

* Now you can start up the bot and it will listen and post mod actions in your discord servers.

**If there are a large number of mod actions in a small time frame (a nuke happens or similar), the webhook will be throttled and may not display all moderation actions.**
