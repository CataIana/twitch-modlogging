# Twitch mod logging with Python

Figuring out how to do this was a pain, and there was nothing good on the internet that I could find, so I might as well give it out to anyone who might want it.

### Known Issues

- Unmodding and Unviping do not send a message when the command is run in the native twitch chat. They will send a message when the command is sent through an IRC Client such as Chatty

### The looks:

Top is with embeds disabled, and bottom enabled

![How logs look](/assets/thelooks.png)

### Installation

- Recommended Python Version: 3.12

- Clone the repo with `git clone https://github.com/CataIana/twitch-modlogging.git` in your preferred terminal application

- Install the required dependencies
  - `cd twitch-modlogging`
  - `python3 -m venv venv`
  - `source venv/bin/activate` on linux or `venv/scripts/activate.ps1` on windows
  - `pip install --upgrade -r requirements.txt`

- Copy `examplesettings.json` to `settings.json`

- Go to the [twitch developer console](https://dev.twitch.tv/console) and click Register Your Application

![Registering Application](/assets/devconsole.png)

- Give the application a name (make it unique). If you have a redirect URI you can put yours in, but I just used `https://twitchapps.com/tmi/` since I don't have one.

![Creating application](/assets/createapplication.png)

- Finish creating your application. It will redirect you to your list of applications after creation. Find your application and click `Manage`

![Finish creating application](/assets/manageapplication.png)

- Open `settings.json`. From the twitch developers website, copy the Client ID and put it into the `client_id` key.

![Getting Client ID](/assets/clientid.png)

- Then you will need to authorize the Application to access your account. If the authorized user does not have mod privileges for the streamer you wish to log for, no mod actions will be recieved. In this URL `https://id.twitch.tv/oauth2/authorize?client_id=CLIENT_ID&redirect_uri=https://twitchapps.com/tmi/&response_type=token&scope=channel:moderate+chat:read` replace `CLIENT_ID` with your Client ID. If you have your own redirect URI, replace `https://twitchapps.com/tmi/` with your own. Upon authorizing with your twitch account, you will be redirected and shown an authorization token. Keep this safe and do not share it. You can always revoke access [here](https://www.twitch.tv/settings/connections) and authorize again for a new token. Copy that token into the "auth_token" key in the settings file. Removing `oauth:` from the beginning is optional

![Getting auth token 1](/assets/getauthtoken1.png)
![Getting auth token 2](/assets/getauthtoken2.png)

- Finally put the user ID in the "id" key that will be used for getting logs. If you do not know this, run the python file `get_userid.py` included in this repo. You will need to enter the same client ID and Oauth token used above in this script.

![Getting user ID](/assets/getuserid.png)

- Now you can configure which streamer/s mod actions you want to listen for. Each streamer allows a list of webhooks if you want to send each mod action to multiple webhooks. For more information on creating webhooks, see [here](https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks)

- Config options that can be setup now: Toggling automod, moderator ignoring, toggling embeds, configuring moderation action whitelisting. All of these are optional

- Now you can start up the bot and it will listen and post mod actions in your discord servers.
- The output should look like this:

![script running](/assets/running.png)

- I personally run this on linux using a systemd service. I highly recommend following a similar approach. For help setting up such approach, check out [this](https://tecadmin.net/setup-autorun-python-script-using-systemd/)

Have a nice day :)

Copyright &copy; 2021 CataIana, under the GNU GPLv3 License.
