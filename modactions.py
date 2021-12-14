from enum import Enum

class ModAction(Enum):
    #Chatroom actions
    slow = "slow"
    slowoff = "slowoff"
    r9kbeta = "r9kbeta"
    r9kbetaoff = "r9kbetaoff"
    clear = "clear"
    emoteonly = "emoteonly"
    emoteonlyoff = "emoteonlyoff"
    subscribers = "subscribers"
    subscribersoff = "subscribersoff"
    followers = "followers"
    followersoff = "followersoff"
    host = "host"
    unhost = "unhost"
    raid = "raid"
    unraid = "unraid"

    #User Moderation Actions
    timeout = "timeout"
    untimeout = "untimeout"
    ban = "ban"
    unban = "unban"
    delete = "delete"
    delete_notification = "delete_notification"
    mod = "mod"
    unmod = "unmod"
    vip = "vip"
    vip_added = "vip_added"
    unvip = "unvip"

    #Channel Terms
    add_permitted_term = "add_permitted_term"
    add_blocked_term = "add_blocked_term"
    delete_permitted_term = "delete_permitted_term"
    delete_blocked_term = "delete_blocked_term"

    #Automod
    automod_caught_message = "automod_caught_message"
    #Unused automod since they're faked by me
    automod_allowed_message = "automod_allowed_message"
    automod_denied_message = "automod_denied_message"

    #Unban Requests
    approve_unban_request = "approve_unban_request"
    deny_unban_request = "deny_unban_request"

    def __int__(self):
        return self.value