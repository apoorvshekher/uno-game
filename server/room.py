"""Online multiplayer room management with WebSocket support."""
import asyncio
import random
import uuid
from typing import Dict, List, Optional

from fastapi import WebSocket

from uno.card import Color
from uno.game import Game
from uno.player import Player
from uno.ai import choose_action

# ── Tuning ─────────────────────────────────────────────────────────────────────

AUTO_TAKEOVER_GRACE = 10   # seconds a disconnected player's turn waits before the AI steps in
AUTO_MOVE_DELAY     = 1.2  # seconds between consecutive AI auto-moves (so plays are watchable)
ABANDON_TTL         = 120  # seconds with zero connected players before a room is deleted

# ── Serialization (mirrors app.py helpers) ─────────────────────────────────────

_COLOR_HEX = {
    Color.RED:    '#dc2626',
    Color.BLUE:   '#2563eb',
    Color.GREEN:  '#16a34a',
    Color.YELLOW: '#ca8a04',
    Color.WILD:   '#7c3aed',
}

_SYMBOL = {
    'Number':         lambda c: str(c.number),
    'Skip':           lambda _: '⊘',
    'Reverse':        lambda _: '↺',
    'Draw Two':       lambda _: '+2',
    'Wild':           lambda _: '★',
    'Wild Draw Four': lambda _: '+4',
}


def _card_dict(card, playable=None):
    fn = _SYMBOL.get(card.card_type.value, lambda _: '?')
    return {
        'color':     card.color.value,
        'color_hex': _COLOR_HEX[card.color],
        'card_type': card.card_type.value,
        'number':    card.number,
        'label':     card.full_name,
        'symbol':    fn(card),
        'short':     card.short,
        'playable':  playable,
    }


# ── Storage ────────────────────────────────────────────────────────────────────

_ROOMS: Dict[str, 'Room'] = {}


def _gen_code() -> str:
    chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    while True:
        code = ''.join(random.choices(chars, k=5))
        if code not in _ROOMS:
            return code


# ── Room ───────────────────────────────────────────────────────────────────────

class RoomPlayer:
    def __init__(self, player_id: str, name: str):
        self.player_id        = player_id
        self.name             = name
        self.ws: Optional[WebSocket] = None
        self.game_index: Optional[int] = None


class Room:
    def __init__(self, code: str, host_id: str):
        self.code     = code
        self.host_id  = host_id
        self.players: Dict[str, RoomPlayer] = {}
        self.order:   List[str] = []
        self.game:    Optional[Game] = None
        self.status   = 'waiting'   # waiting | playing | finished
        self._uno_called: set = set()  # player indices who called UNO this window
        self._autopilot_task: Optional[asyncio.Task] = None  # AI fills in for away players
        self._cleanup_task:   Optional[asyncio.Task] = None  # deletes the room once abandoned

    # ── Players ────────────────────────────────────────────────────────────────

    def add_player(self, player_id: str, name: str) -> 'RoomPlayer':
        rp = RoomPlayer(player_id, name)
        self.players[player_id] = rp
        self.order.append(player_id)
        return rp

    # ── Messaging ──────────────────────────────────────────────────────────────

    def room_msg(self) -> dict:
        return {
            'type':      'room_state',
            'room_code': self.code,
            'host_id':   self.host_id,
            'status':    self.status,
            'players': [
                {
                    'player_id': pid,
                    'name':      self.players[pid].name,
                    'connected': self.players[pid].ws is not None,
                }
                for pid in self.order if pid in self.players
            ],
        }

    async def send(self, player_id: str, msg: dict):
        rp = self.players.get(player_id)
        if rp and rp.ws:
            try:
                await rp.ws.send_json(msg)
            except Exception:
                rp.ws = None

    async def broadcast(self, msg: dict):
        for pid in list(self.order):
            await self.send(pid, msg)

    async def broadcast_game(self, messages: List[str]):
        for pid in list(self.order):
            rp = self.players.get(pid)
            if rp and rp.ws:
                state = self._state_for(rp, messages)
                await self.send(pid, {'type': 'game_state', 'state': state})
        # Re-evaluate after every state change: if the next player is away, let the AI take over.
        self.ensure_autopilot()

    def _vulnerable(self) -> List[int]:
        g = self.game
        # Clear stale called entries
        stale = {i for i in self._uno_called if g.players[i].card_count != 1}
        self._uno_called -= stale
        return [i for i, p in enumerate(g.players)
                if p.card_count == 1 and i not in self._uno_called]

    def _state_for(self, viewer: 'RoomPlayer', messages: List[str]) -> dict:
        g        = self.game
        playable = g.playable_indices()
        is_my_turn = (g._current_idx == viewer.game_index and g.current_player.is_human)

        vulnerable = self._vulnerable()
        players_out = []
        for i, p in enumerate(g.players):
            is_viewer = (i == viewer.game_index)
            hand = (
                [_card_dict(c, j in playable) for j, c in enumerate(p.hand)]
                if is_viewer else []
            )
            # Game seat i corresponds to the player_id at self.order[i]
            seat_rp = self.players.get(self.order[i]) if i < len(self.order) else None
            players_out.append({
                'index':          i,
                'name':           p.name,
                'is_human':       p.is_human,
                'is_current':     (i == g._current_idx),
                'is_viewer':      is_viewer,
                'card_count':     p.card_count,
                'hand':           hand,
                'uno_vulnerable': i in vulnerable,
                'connected':      seat_rp.ws is not None if seat_rp else False,
            })

        return {
            'game_id':              self.code,
            'room_code':            self.code,
            'status':               'finished' if g.winner else 'playing',
            'winner':               g.winner.name if g.winner else None,
            'current_player_index': g._current_idx,
            'direction':            g._direction,
            'active_color':         g.active_color.value,
            'active_color_hex':     _COLOR_HEX[g.active_color],
            'top_card':             _card_dict(g.top_card),
            'pending_draw':         g.pending_draw,
            'draw_pile_size':       g.deck.draw_pile_size,
            'players':              players_out,
            'playable_indices':     playable if is_my_turn else [],
            'human_count':          sum(1 for p in g.players if p.is_human),
            'messages':             messages,
            'is_my_turn':           is_my_turn,
            'my_player_index':      viewer.game_index,
        }

    # ── CPU helper ─────────────────────────────────────────────────────────────

    async def _run_cpu(self) -> List[str]:
        msgs = []
        while not self.game.winner and not self.game.current_player.is_human:
            await asyncio.sleep(0)
            card_idx, color = choose_action(self.game)
            if card_idx is None:
                _, msg = self.game.draw_cards()
            else:
                ok, msg = self.game.play_card(card_idx, color)
                if not ok:
                    _, msg = self.game.draw_cards()
            msgs.append(msg)
        return msgs

    # ── Autopilot for disconnected players ───────────────────────────────────────

    def _current_seat_player(self) -> Optional['RoomPlayer']:
        if self.game is None:
            return None
        idx = self.game._current_idx
        if idx >= len(self.order):
            return None
        return self.players.get(self.order[idx])

    def _current_is_away_human(self) -> bool:
        rp = self._current_seat_player()
        return (
            self.game is not None
            and not self.game.winner
            and self.game.current_player.is_human
            and (rp is None or rp.ws is None)
        )

    def ensure_autopilot(self) -> None:
        """Start the autopilot if the current player is an away human and it isn't already running."""
        if self.status != 'playing' or not self._current_is_away_human():
            return
        if self._autopilot_task and not self._autopilot_task.done():
            return
        self._autopilot_task = asyncio.create_task(self._autopilot())

    def cancel_autopilot(self) -> None:
        if self._autopilot_task and not self._autopilot_task.done():
            self._autopilot_task.cancel()
        self._autopilot_task = None

    async def _autopilot(self) -> None:
        """Play moves on behalf of disconnected humans until a connected human is up or the game ends.

        Spends nearly all its time in asyncio.sleep, so cancellation (on reconnect) lands
        during the wait, never mid-mutation.
        """
        try:
            while self.game and not self.game.winner:
                if not self._current_is_away_human():
                    break
                seat_idx = self.game._current_idx
                await asyncio.sleep(AUTO_TAKEOVER_GRACE)
                # Re-check after the grace wait — the player may have reconnected or the turn moved.
                if not self.game or self.game.winner:
                    break
                if self.game._current_idx != seat_idx or not self._current_is_away_human():
                    continue
                name = self.game.current_player.name
                card_idx, color = choose_action(self.game)
                if card_idx is None:
                    _, msg = self.game.draw_cards()
                else:
                    ok, msg = self.game.play_card(card_idx, color)
                    if not ok:
                        _, msg = self.game.draw_cards()
                msgs = [f'{name} (away) — auto: {msg}']
                msgs.extend(await self._run_cpu())  # clear any following real CPUs
                await self.broadcast_game(msgs)
                await asyncio.sleep(AUTO_MOVE_DELAY)
        except asyncio.CancelledError:
            pass
        finally:
            self._autopilot_task = None

    # ── Room lifecycle / cleanup ─────────────────────────────────────────────────

    def _has_connected_player(self) -> bool:
        return any(rp.ws is not None for rp in self.players.values())

    def schedule_cleanup_if_empty(self) -> None:
        """If nobody is connected, delete the room after ABANDON_TTL (unless someone returns)."""
        if self._has_connected_player():
            return
        if self._cleanup_task and not self._cleanup_task.done():
            return
        self._cleanup_task = asyncio.create_task(self._cleanup_after_ttl())

    def cancel_cleanup(self) -> None:
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
        self._cleanup_task = None

    async def _cleanup_after_ttl(self) -> None:
        try:
            await asyncio.sleep(ABANDON_TTL)
            if not self._has_connected_player():
                self.cancel_autopilot()
                _ROOMS.pop(self.code, None)
        except asyncio.CancelledError:
            pass
        finally:
            self._cleanup_task = None

    # ── Game actions ───────────────────────────────────────────────────────────

    async def start_game(self, requester_id: str):
        if requester_id != self.host_id:
            await self.send(requester_id, {'type': 'error', 'message': 'Only the host can start.'})
            return
        if len(self.order) < 2:
            await self.send(requester_id, {'type': 'error', 'message': 'Need at least 2 players to start.'})
            return
        if self.status != 'waiting':
            return

        game_players = [Player(self.players[pid].name, is_human=True) for pid in self.order]
        self.game   = Game(game_players)
        start_card  = self.game.start()
        self.status = 'playing'

        for i, pid in enumerate(self.order):
            self.players[pid].game_index = i

        msgs = [f'Game started! First card: {start_card.full_name}.']
        msgs.extend(await self._run_cpu())
        await self.broadcast_game(msgs)

    async def play_card(self, player_id: str, card_index: int, chosen_color: Optional[str]):
        rp = self.players.get(player_id)
        if not rp or self.game is None:
            return
        if self.game._current_idx != rp.game_index:
            await self.send(player_id, {'type': 'error', 'message': "It's not your turn."})
            return

        color = None
        if chosen_color:
            try:
                color = Color[chosen_color.upper()]
            except KeyError:
                await self.send(player_id, {'type': 'error', 'message': f'Unknown color: {chosen_color}'})
                return

        ok, msg = self.game.play_card(card_index, color)
        if not ok:
            await self.send(player_id, {'type': 'error', 'message': msg})
            return

        msgs = [msg] + await self._run_cpu()
        await self.broadcast_game(msgs)

    async def call_uno(self, player_id: str):
        rp = self.players.get(player_id)
        if not rp or self.game is None:
            return
        self._uno_called.add(rp.game_index)
        await self.broadcast_game([])

    async def catch_uno(self, catcher_id: str, target_index: int):
        if self.game is None:
            return
        vulnerable = self._vulnerable()
        if target_index not in vulnerable:
            await self.send(catcher_id, {'type': 'error', 'message': 'That player already called UNO!'})
            return
        player = self.game.players[target_index]
        player.add_cards(self.game.deck.draw_many(4))
        self._uno_called.add(target_index)  # close window
        msg = f"Caught! {player.name} forgot to call UNO and draws 4 cards!"
        await self.broadcast_game([msg])

    async def draw_card(self, player_id: str):
        rp = self.players.get(player_id)
        if not rp or self.game is None:
            return
        if self.game._current_idx != rp.game_index:
            await self.send(player_id, {'type': 'error', 'message': "It's not your turn."})
            return

        _, msg = self.game.draw_cards()
        msgs = [msg] + await self._run_cpu()
        await self.broadcast_game(msgs)


# ── Public helpers ─────────────────────────────────────────────────────────────

def create_room(host_name: str):
    code      = _gen_code()
    player_id = str(uuid.uuid4())
    room      = Room(code, host_id=player_id)
    room.add_player(player_id, host_name)
    _ROOMS[code] = room
    return code, player_id


def join_room(code: str, name: str):
    room = _ROOMS.get(code.upper())
    if not room:
        raise ValueError('Room not found.')
    if room.status != 'waiting':
        raise ValueError('Game already started.')
    if len(room.order) >= 10:
        raise ValueError('Room is full (max 10 players).')
    player_id = str(uuid.uuid4())
    room.add_player(player_id, name)
    return room, player_id


def get_room(code: str) -> Optional[Room]:
    return _ROOMS.get(code.upper())
