"""In-memory game session store — swap for Redis/DB when adding online play."""
import uuid
from typing import Dict, List, Optional
from uno.game import Game

_games: Dict[str, Game] = {}
_message_log: Dict[str, List[str]] = {}


def create(game: Game) -> str:
    gid = uuid.uuid4().hex[:8]
    _games[gid] = game
    _message_log[gid] = []
    return gid


def get(gid: str) -> Optional[Game]:
    return _games.get(gid)


def log(gid: str, msg: str) -> None:
    _message_log.setdefault(gid, []).append(msg)


def flush_log(gid: str) -> List[str]:
    msgs = _message_log.get(gid, [])
    _message_log[gid] = []
    return msgs


def delete(gid: str) -> None:
    _games.pop(gid, None)
    _message_log.pop(gid, None)
