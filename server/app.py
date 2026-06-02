"""FastAPI application — transport layer over the uno/ game engine."""
import asyncio
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from uno.card import Color
from uno.game import Game
from uno.player import Player
from uno.ai import choose_action
import server.session as sessions

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

    players_out = []
    for i, p in enumerate(game.players):
        is_current = (i == game._current_idx)
        hand = (
            [_card_dict(c, i in playable) for i, c in enumerate(p.hand)]
            if is_current and p.is_human
            else []
        )
        players_out.append({
            "index":      i,
            "name":       p.name,
            "is_human":   p.is_human,
            "is_current": is_current,
            "card_count": p.card_count,
            "hand":       hand,
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
    return {"ok": True}
