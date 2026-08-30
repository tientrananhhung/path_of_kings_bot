from __future__ import annotations

from enum import Enum


class BotState(str, Enum):
    STOPPED = "STOPPED"
    PREFLIGHT = "PREFLIGHT"
    SYNC = "SYNC"
    DISCONNECTED = "DISCONNECTED"
    HOME_SCREEN = "HOME_SCREEN"
    GAME_PLAY = "GAME_PLAY"
    REWARD_PROMPT = "REWARD_PROMPT"
    AD_WATCHING = "AD_WATCHING"
    AD_CLOSING = "AD_CLOSING"
    AD_ESCAPED = "AD_ESCAPED"
    STUCK = "STUCK"
    PANIC = "PANIC"


# Hết timeout -> chuyển sang STUCK (hoặc xử lý riêng trong machine)
TIMEOUTS: dict[BotState, float] = {
    BotState.PREFLIGHT: 15.0,
    BotState.SYNC: 10.0,
    BotState.DISCONNECTED: 120.0,
    BotState.HOME_SCREEN: 30.0,
    BotState.REWARD_PROMPT: 15.0,
    # phải lớn hơn ads.min_watch_seconds (8s) + no_ad_grace_s
    BotState.AD_WATCHING: 60.0,
    # phải lớn hơn ads.rescan_max_s (120s) + countdown_max_wait_s (75s),
    # nếu không STUCK cắt ngang giữa lúc đang quét
    BotState.AD_CLOSING: 210.0,
    BotState.AD_ESCAPED: 60.0,
    BotState.STUCK: 30.0,
}
