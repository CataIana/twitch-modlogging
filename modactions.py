from enum import Enum


class ModAction(Enum):
    #Chatroom actions
    slow = "slow"
    slowoff = "slowoff"
    uniquechat = "uniquechat"
    uniquechatoff = "uniquechatoff"
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
    warn = "warn"
    acknowledge_warning = "acknowledge_warning"

    #Channel Terms
    add_permitted_term = "add_permitted_term"
    add_blocked_term = "add_blocked_term"
    remove_permitted_term = "remove_permitted_term"
    remove_blocked_term = "remove_blocked_term"

    #Automod
    automod_caught_message = "automod_caught_message"
    #Unused automod since they're faked by me
    automod_allowed_message = "automod_allowed_message"
    automod_denied_message = "automod_denied_message"

    #Unban Requests
    approve_unban_request = "approve_unban_request"
    deny_unban_request = "deny_unban_request"

    #Shared mod actions (unsure if currently used)
    shared_chat_ban = "shared_chat_ban"
    shared_chat_unban = "shared_chat_unban"
    shared_chat_timeout = "shared_chat_timeout"
    shared_chat_untimeout = "shared_chat_untimeout"
    shared_chat_delete = "shared_chat_delete"

    def __int__(self):
        return self.value