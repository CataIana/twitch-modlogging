import requests
import json

client_id = input("Provide your client ID: ")
print("Input at least one USERNAME, or multiple seperated by commas without spaces")
while True:
    username = input("Provide User ID: ")
    response = requests.get(url=f"https://api.twitch.tv/kraken/users?login={username}", headers={"Accept": "application/vnd.twitchtv.v5+json", "Client-ID": client_id})
    json_obj = response.json()
    if "error" in json_obj.keys():
        print(f"Error {json_obj['error']}: {json_obj['message']}")
        break
    else:
        for user in json_obj["users"]:
            print(f"{user['name']}: {user['_id']}")