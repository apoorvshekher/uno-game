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

    def _state_for(self, viewer: 'RoomPlayer', messages: List[str]) -> dict:
        g        = self.game
        playable = g.playable_indices()
        is_my_turn = (g._current_idx == viewer.game_index and g.current_player.is_human)

        players_out = []
        for i, p in enumerate(g.players):
            is_viewer = (i == viewer.game_index)
            hand = (
                [_card_dict(c, j in playable) for j, c in enumerate(p.hand)]
                if is_viewer else []
            )
            players_out.append({
                'index':      i,
                'name':       p.name,
                'is_human':   p.is_human,
                'is_current': (i == g._current_idx),
                'is_viewer':  is_viewer,
                'card_count': p.card_count,
                'hand':       hand,
            })

        return {
            'game_id':              self.code,
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
