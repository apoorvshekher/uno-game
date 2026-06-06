"""FastAPI application — transport layer over the uno/ game engine."""
import asyncio
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from server.room import create_room as _room_create, join_room as _room_join, get_room as _room_get

from uno.card import Color
from uno.game import Game
from uno.player import Player
from uno.ai import choose_action
import server.session as sessions

# ── UNO call tracking (local games) ───────────────────────────────────────────
# Maps game_id → set of player indices who have called UNO this vulnerable window.
# A window opens when a player drops to 1 card; resets when they leave 1-card state.
_uno_called: dict = {}


def _compute_vulnerable(gid: str, game: Game) -> list:
    """Return list of player indices with 1 card who haven't called UNO."""
    called = _uno_called.get(gid, set())
    # Clear called entries for players no longer at 1 card (new window later)
    stale = {i for i in called if game.players[i].card_count != 1}
    if stale:
        _uno_called[gid] -= stale
        called = _uno_called[gid]
    return [i for i, p in enumerate(game.players)
            if p.card_count == 1 and i not in called]


# ── App setup ──────────────────────────────────────────────────────────────────

app = FastAPI(title="UNO")

STATIC_DIR = Path(__file__).parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    return (STATIC_DIR / "index.html").read_text()


# ── Serialization helpers ──────────────────────────────────────────────────────

_COLOR_HEX = {
    Color.RED:    "#dc2626",
    Color.BLUE:   "#2563eb",
    Color.GREEN:  "#16a34a",
    Color.YELLOW: "#ca8a04",
    Color.WILD:   "#7c3aed",
}

_SYMBOL = {
    "Number":         lambda c: str(c.number),
    "Skip":           lambda _: "⊘",
    "Reverse":        lambda _: "↺",
    "Draw Two":       lambda _: "+2",
    "Wild":           lambda _: "★",
    "Wild Draw Four": lambda _: "+4",
}


def _card_dict(card, playable: Optional[bool] = None) -> dict:
    symbol_fn = _SYMBOL.get(card.card_type.value, lambda _: "?")
    return {
        "color":     card.color.value,
        "color_hex": _COLOR_HEX[card.color],
        "card_type": card.card_type.value,
        "number":    card.number,
        "label":     card.full_name,
        "symbol":    symbol_fn(card),
        "short":     card.short,
        "playable":  playable,
    }


def _game_state(gid: str, game: Game, messages: List[str]) -> dict:
    cp = game.current_player
    playable = game.playable_indices()
    vulnerable = _compute_vulnerable(gid, game)

    players_out = []
    for i, p in enumerate(game.players):
        is_current = (i == game._current_idx)
        hand = (
            [_card_dict(c, i in playable) for i, c in enumerate(p.hand)]
            if is_current and p.is_human
            else []
        )
        players_out.append({
            "index":          i,
            "name":           p.name,
            "is_human":       p.is_human,
            "is_current":     is_current,
            "card_count":     p.card_count,
            "hand":           hand,
            "uno_vulnerable": i in vulnerable,
        })

    human_count = sum(1 for p in game.players if p.is_human)

    return {
        "game_id":             gid,
        "status":              "finished" if game.winner else "playing",
        "winner":              game.winner.name if game.winner else None,
        "current_player_index": game._current_idx,
        "direction":           game._direction,
        "active_color":        game.active_color.value,
        "active_color_hex":    _COLOR_HEX[game.active_color],
        "top_card":            _card_dict(game.top_card),
        "pending_draw":        game.pending_draw,
        "draw_pile_size":      game.deck.draw_pile_size,
        "players":             players_out,
        "playable_indices":    playable if cp.is_human else [],
        "human_count":         human_count,
        "messages":            messages,
    }


async def _run_cpu_turns(gid: str, game: Game) -> List[str]:
    """Process all consecutive CPU turns and collect their messages."""
    msgs = []
    while not game.winner and not game.current_player.is_human:
        await asyncio.sleep(0)  # yield to event loop
        card_idx, color = choose_action(game)
        if card_idx is None:
            _, msg = game.draw_cards()
        else:
            ok, msg = game.play_card(card_idx, color)
            if not ok:
                _, msg = game.draw_cards()
        msgs.append(msg)
    return msgs


# ── API routes ─────────────────────────────────────────────────────────────────

class NewGameRequest(BaseModel):
    players: List[dict]  # [{name: str, is_human: bool}]


@app.post("/api/game/new")
async def new_game(req: NewGameRequest):
    if len(req.players) < 2 or len(req.players) > 10:
        raise HTTPException(400, "UNO requires 2–10 players.")

    players = [Player(p["name"], p.get("is_human", True)) for p in req.players]
    game = Game(players)
    start_card = game.start()

    gid = sessions.create(game)
    msgs = [f"Game started! First card: {start_card.full_name}."]

    # If first player is CPU, auto-play
    cpu_msgs = await _run_cpu_turns(gid, game)
    msgs.extend(cpu_msgs)

    return _game_state(gid, game, msgs)


@app.get("/api/game/{gid}/state")
async def get_state(gid: str):
    game = sessions.get(gid)
    if not game:
        raise HTTPException(404, "Game not found.")
    return _game_state(gid, game, sessions.flush_log(gid))


class PlayRequest(BaseModel):
    card_index: int
    chosen_color: Optional[str] = None


@app.post("/api/game/{gid}/play")
async def play_card(gid: str, req: PlayRequest):
    game = sessions.get(gid)
    if not game:
        raise HTTPException(404, "Game not found.")
    if game.winner:
        raise HTTPException(400, "Game is already over.")
    if not game.current_player.is_human:
        raise HTTPException(400, "It is not a human player's turn.")

    chosen_color = None
    if req.chosen_color:
        try:
            chosen_color = Color[req.chosen_color.upper()]
        except KeyError:
            raise HTTPException(400, f"Unknown color: {req.chosen_color}")

    ok, msg = game.play_card(req.card_index, chosen_color)
    if not ok:
        raise HTTPException(422, msg)

    msgs = [msg]
    cpu_msgs = await _run_cpu_turns(gid, game)
    msgs.extend(cpu_msgs)

    return _game_state(gid, game, msgs)


@app.post("/api/game/{gid}/draw")
async def draw_card(gid: str):
    game = sessions.get(gid)
    if not game:
        raise HTTPException(404, "Game not found.")
    if game.winner:
        raise HTTPException(400, "Game is already over.")
    if not game.current_player.is_human:
        raise HTTPException(400, "It is not a human player's turn.")

    _, msg = game.draw_cards()
    msgs = [msg]
    cpu_msgs = await _run_cpu_turns(gid, game)
    msgs.extend(cpu_msgs)

    return _game_state(gid, game, msgs)


@app.delete("/api/game/{gid}")
async def end_game(gid: str):
    sessions.delete(gid)
    _uno_called.pop(gid, None)
    return {"ok": True}


@app.post("/api/game/{gid}/call_uno")
async def call_uno(gid: str):
    game = sessions.get(gid)
    if not game:
        raise HTTPException(404, "Game not found.")
    _uno_called.setdefault(gid, set()).add(game._current_idx)
    return _game_state(gid, game, [])


@app.post("/api/game/{gid}/catch/{target_idx}")
async def catch_uno(gid: str, target_idx: int):
    game = sessions.get(gid)
    if not game:
        raise HTTPException(404, "Game not found.")
    vulnerable = _compute_vulnerable(gid, game)
    if target_idx not in vulnerable:
        raise HTTPException(400, "That player already called UNO!")
    player = game.players[target_idx]
    player.add_cards(game.deck.draw_many(4))
    _uno_called.setdefault(gid, set()).add(target_idx)  # close window
    msg = f"Caught! {player.name} forgot to call UNO and draws 4 cards!"
    return _game_state(gid, game, [msg])


# ── Online multiplayer rooms ───────────────────────────────────────────────────

class RoomRequest(BaseModel):
    name: str = 'Player'


@app.post("/api/room/new")
async def new_room(req: RoomRequest):
    name = req.name.strip()[:16] or 'Player'
    code, player_id = _room_create(name)
    return {'room_code': code, 'player_id': player_id}


@app.post("/api/room/{code}/join")
async def join_room(code: str, req: RoomRequest):
    name = req.name.strip()[:16] or 'Player'
    try:
        room, player_id = _room_join(code, name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {'room_code': room.code, 'player_id': player_id}


@app.websocket("/ws/{room_code}/{player_id}")
async def ws_endpoint(ws: WebSocket, room_code: str, player_id: str):
    room = _room_get(room_code)
    if not room or player_id not in room.players:
        await ws.close(code=4004)
        return

    await ws.accept()
    rp = room.players[player_id]
    rp.ws = ws
    room.cancel_cleanup()  # someone is here — abort any pending room teardown

    if room.status == 'playing' and room.game is not None:
        # Reconnecting into a live game: send the board straight away and let others know.
        await ws.send_json({'type': 'game_state', 'state': room._state_for(rp, ['You reconnected.'])})
        room.cancel_autopilot()  # hand control back to the returning player
        await room.broadcast_game([f'{rp.name} reconnected.'])
    else:
        await ws.send_json(room.room_msg())
        await room.broadcast(room.room_msg())

    try:
        while True:
            data = await ws.receive_json()
            t = data.get('type')
            if t == 'start_game':
                await room.start_game(player_id)
            elif t == 'play':
                await room.play_card(player_id, data.get('card_index', 0), data.get('chosen_color'))
            elif t == 'draw':
                await room.draw_card(player_id)
            elif t == 'call_uno':
                await room.call_uno(player_id)
            elif t == 'catch_uno':
                await room.catch_uno(player_id, data.get('target_index', -1))
    except WebSocketDisconnect:
        room.players[player_id].ws = None
        if room.status == 'playing' and room.game is not None:
            # Mid-game: tell everyone on the board. broadcast_game re-arms the autopilot,
            # so the AI covers this seat if it's their turn.
            await room.broadcast_game([f'{room.players[player_id].name} disconnected.'])
        else:
            await room.broadcast(room.room_msg())
        room.schedule_cleanup_if_empty()
