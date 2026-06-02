"""Terminal display helpers — ANSI colors, card rendering, game state output."""
import os
from typing import List, Optional
from uno.card import Card, Color, CardType
from uno.player import Player
from uno.game import Game

# ── ANSI codes ─────────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
ITALIC = "\033[3m"

FG_RED    = "\033[91m"
FG_GREEN  = "\033[92m"
FG_YELLOW = "\033[93m"
FG_BLUE   = "\033[94m"
FG_MAGENTA= "\033[95m"
FG_CYAN   = "\033[96m"
FG_WHITE  = "\033[97m"
FG_GRAY   = "\033[90m"

_CARD_COLOR_MAP = {
    Color.RED:    FG_RED,
    Color.BLUE:   FG_BLUE,
    Color.GREEN:  FG_GREEN,
    Color.YELLOW: FG_YELLOW,
    Color.WILD:   FG_MAGENTA,
}


def _cc(color: Color) -> str:
    return _CARD_COLOR_MAP.get(color, FG_WHITE)


def _b(text: str, code: str) -> str:
    return f"{BOLD}{code}{text}{RESET}"


def _d(text: str) -> str:
    return f"{DIM}{FG_GRAY}{text}{RESET}"


# ── Card rendering ─────────────────────────────────────────────────────────────

def render_card(card: Card, highlight: Optional[bool] = None) -> str:
    """
    highlight=True  → bold (playable)
    highlight=False → dim (not playable)
    highlight=None  → normal
    """
    name = card.full_name
    code = _cc(card.color)
    if highlight is True:
        return f"{BOLD}{code}[{name}]{RESET}"
    if highlight is False:
        return f"{DIM}{FG_GRAY}[{name}]{RESET}"
    return f"{code}[{name}]{RESET}"


def render_top_card(card: Card, active_color: Color) -> str:
    color_bar = _b(f"  {active_color.value.upper()}  ", _cc(active_color))
    return f"{render_card(card)}  active color: {color_bar}"


# ── Screen helpers ─────────────────────────────────────────────────────────────

def clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def print_header() -> None:
    line = "═" * 46
    print(f"{BOLD}{FG_CYAN}╔{line}╗{RESET}")
    title = "U N O  C A R D  G A M E"
    padding = (46 - len(title)) // 2
    print(f"{BOLD}{FG_CYAN}║{' ' * padding}{FG_WHITE}{title}{FG_CYAN}{' ' * (46 - padding - len(title))}║{RESET}")
    print(f"{BOLD}{FG_CYAN}╚{line}╝{RESET}")
    print()


def print_scoreboard(game: Game, highlight_idx: Optional[int] = None) -> None:
    n = len(game.players)
    arrow = "→" if game.direction == 1 else "←"
    print(f"  Direction: {FG_CYAN}{arrow}{RESET}   "
          f"Draw pile: {FG_GRAY}{game.deck.draw_pile_size} cards{RESET}")
    print()
    print(f"  {'PLAYERS':}")
    for i, p in enumerate(game.players):
        is_current = (i == game._current_idx)
        tag = f"{FG_CYAN}▶ {RESET}" if is_current else "  "
        name_fmt = f"{BOLD}{FG_WHITE}{p.name}{RESET}" if is_current else p.name
        kind = f"{FG_GRAY}CPU{RESET}" if not p.is_human else f"{FG_GREEN}you{RESET}" if i == highlight_idx else ""
        cards = f"{p.card_count} card{'s' if p.card_count != 1 else ''}"
        if p.card_count == 1:
            cards = f"{BOLD}{FG_YELLOW}UNO! 1 card{RESET}"
        print(f"  {tag}{name_fmt:<20} {kind:>4}  {cards}")
    print()


def print_hand(player: Player, playable: List[int]) -> None:
    print(f"  {BOLD}Your hand:{RESET}")
    for i, card in enumerate(player.hand):
        can_play = i in playable
        num = f"{BOLD}{FG_GREEN}{i+1:>2}.{RESET}" if can_play else f"{FG_GRAY}{i+1:>2}.{RESET}"
        rendered = render_card(card, highlight=can_play)
        suffix = f"  {FG_GREEN}✓{RESET}" if can_play else ""
        print(f"  {num} {rendered}{suffix}")
    print()


def print_event(msg: str) -> None:
    print(f"\n  {FG_CYAN}▸{RESET} {msg}")


def print_error(msg: str) -> None:
    print(f"  {FG_RED}✗ {msg}{RESET}")


def print_warning(msg: str) -> None:
    print(f"  {BOLD}{FG_YELLOW}⚠  {msg}{RESET}")


def print_winner(winner: Player) -> None:
    print()
    bar = "★" * 44
    print(f"{BOLD}{FG_YELLOW}  {bar}{RESET}")
    print(f"{BOLD}{FG_YELLOW}  🎉  {winner.name} wins the game!  🎉{RESET}")
    print(f"{BOLD}{FG_YELLOW}  {bar}{RESET}")
    print()


def print_turn_divider(player: Player, viewer_idx: int) -> None:
    """Printed before showing a human player's hand — others should look away."""
    kind = "(you)" if player.is_human else "(CPU)"
    print(f"\n  {BOLD}{FG_CYAN}━━━  {player.name}'s turn {kind}  ━━━{RESET}\n")


def print_pending_draw(count: int, player_name: str) -> None:
    print_warning(f"{player_name} must draw {count} cards or stack a Draw card!")
