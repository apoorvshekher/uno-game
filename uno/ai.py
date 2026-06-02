"""Simple rule-based AI strategy for CPU players."""
from typing import Optional, Tuple
from uno.card import Card, Color, CardType
from uno.player import Player
from uno.game import Game


def choose_action(game: Game) -> Tuple[Optional[int], Optional[Color]]:
    """
    Returns (card_index, chosen_color) for a CPU player.
    card_index=None means the CPU will draw.
    """
    player = game.current_player
    playable = game.playable_indices()

    if not playable:
        return None, None

    # Score each playable card — higher is better to play now
    def score(idx: int) -> int:
        card = player.hand[idx]
        if card.card_type == CardType.WILD_DRAW_FOUR:
            return 50
        if card.card_type == CardType.DRAW_TWO:
            return 40
        if card.card_type == CardType.SKIP:
            return 30
        if card.card_type == CardType.REVERSE:
            return 25
        if card.card_type == CardType.WILD:
            return 20
        # Prefer higher-numbered cards to shed more value
        return card.number if card.number is not None else 0

    best_idx = max(playable, key=score)
    chosen_color = None

    if player.hand[best_idx].color == Color.WILD:
        chosen_color = player.dominant_color() or Color.RED

    return best_idx, chosen_color
