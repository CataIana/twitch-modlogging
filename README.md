# Twitch mod logging with Python

Figuring out how to do this was a pain, and there was nothing good on the internet that I could find, so I might as well give it out to anyone who might want it.

Thanks to phoenpc for help with design choices and being the test subject


### Current Issues

* Unmodding and Unviping do not send a message when the command is run via the native twitch chat. They will send a message when the command is sent through an IRC Client such as Chatty

### The looks:

Top is with embeds disabled, and bottom enabled

![How logs look](https://i.catalana.dev/modlogging/thelooks.png)

### Installation

* Clone the repo with `git clone https://github.com/CataIana/twitch-modlogging.git` in your preferred terminal application

* Python 3.6 and up supported only.

* Install the required dependencies `cd twitch-modlogging && sudo pip3 install --upgrade -r requirements.txt` on linux. On windows run cmd as admin and run `pip install --upgrade -r requirements.txt`

* Copy `examplesettings.json` to `settings.json`

* Go to the [twitch developer console](https://dev.twitch.tv/console) and click Register Your Application
![Registering Application](https://i.catalana.dev/modlogging/devconsole.png)

* Give the application a name (make it unique). If you have a redirect URI you can put yours in, but I just used `https://twitchapps.com/tmi/` since I don't have one.
![Creating application](https://i.catalana.dev/modlogging/createapplication.png)

* Finish creating your application. It will redirect you to your list of applications after creation. Find your application and click `Manage`
![Finish creating application](https://i.catalana.dev/modlogging/manageapplication.png)

* Open `settings.json`. From the twitch developers website, copy the Client ID and put it into the `client_id` key.
![Getting Client ID](https://i.catalana.dev/modlogging/clientid.png)

* Then put the user ID in the "id" key that will be used for getting logs. If you do not know this, run the python file `get_userid.py` included in this repo. You will need to enter the same client ID used above in this program.
![Getting user ID](https://i.catalana.dev/modlogging/getuserid.png)

* Then you will need to authorize the Application to access your account. If the authorized user does not have mod privileges for the streamer you wish to log for, no mod actions will be recieved. In this URL `https://id.twitch.tv/oauth2/authorize?client_id=CLIENT_ID&redirect_uri=https://twitchapps.com/tmi/&response_type=token&scope=channel:moderate+chat:read` replace `CLIENT_ID` with your Client ID. If you have your own redirect URI, replace `https://twitchapps.com/tmi/` with your own. Upon authorizing with your twitch account, you will be redirected and shown an authorization token. Keep this safe and do not share it. You can always revoke access [here](https://www.twitch.tv/settings/connections) and authorize again for a new token. Copy that token into the "auth_token" key in the settings file. Removing `oauth:` from the beginning is optional
![Getting auth token 1](https://i.catalana.dev/modlogging/getauthtoken1.png)
![Getting auth token 2](https://i.catalana.dev/modlogging/getauthtoken2.png)

* Now you can configure which streamer/s mod actions you want to listen for. Each streamer allows a list of webhooks if you want to send each mod action to multiple webhooks. For more information on creating webhooks, see [here](https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks)

* Now you can start up the bot and it will listen and post mod actions in your discord servers.
* The output should look like this:
![script running](https://i.catalana.dev/modlogging/running.png)

* I personally run this on linux using a systemd service. I highly recommend following a similar approach. For setting up such approach, check out [this](https://tecadmin.net/setup-autorun-python-script-using-systemd/)

**If there are a large number of mod actions in a small time frame (when a nuke happens or similar), the webhook will be throttled and will take some time to catch up.**
