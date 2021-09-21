import requests

client_id = input("Provide your client ID: ")
oauth = input("Provide your oauth token: ")
oauth = oauth.split("oauth:")[-1] #Remove the oauth: to prevent errors
print("Input at least one USERNAME, or multiple seperated by commas without spaces")
while True:
    username = input("Provide User ID: ")
    response = requests.get(url=f"https://api.twitch.tv/helix/users?login={'&login='.join(username.split(','))}", headers={"Client-ID": client_id, "Authorization": f"Bearer {oauth}"})
    json_obj = response.json()
    try:
        for user in json_obj["data"]:
            print(f"{user['login']}: {user['id']}")
    except Exception:
        print(f"Error {json_obj.get('error', None)}: {json_obj.get('message', None)}")