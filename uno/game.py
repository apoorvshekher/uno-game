"""
Core game logic — no I/O here so it can be reused for a network/online layer.
Actions return (success: bool, message: str) tuples.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from uno.card import Card, Color, CardType
from uno.deck import Deck
from uno.player import Player

HAND_SIZE = 7


@dataclass
class GameState:
    """Snapshot of the game — safe to serialize for online play."""
    current_player_index: int
    direction: int  # 1 = clockwise, -1 = counter-clockwise
    active_color: Color
    top_card: Card
    draw_pile_size: int
    player_names: List[str]
    player_card_counts: List[int]
    player_is_human: List[bool]
    winner: Optional[str]
    pending_draw: int  # accumulated draw penalty (Draw Two / Wild Draw Four stacking)


class Game:
    def __init__(self, players: List[Player]):
        if len(players) < 2 or len(players) > 10:
            raise ValueError("UNO requires 2–10 players.")
        self.players = players
        self.deck = Deck()
        self._current_idx = 0
        self._direction = 1
        self._active_color = Color.RED
        self._pending_draw = 0
        self._winner: Optional[Player] = None
        self._started = False

    # ── Setup ──────────────────────────────────────────────────────────────

    def start(self) -> Card:
        for player in self.players:
            player.add_cards(self.deck.draw_many(HAND_SIZE))
        starting_card = self.deck.flip_starting_card()
        self._active_color = starting_card.color
        self._apply_starting_effects(starting_card)
        self._started = True
        return starting_card

    def _apply_starting_effects(self, card: Card) -> None:
        if card.card_type == CardType.SKIP:
            self._advance()
        elif card.card_type == CardType.REVERSE:
            self._direction *= -1
        elif card.card_type == CardType.DRAW_TWO:
            self._pending_draw += 2

    # ── Queries ────────────────────────────────────────────────────────────

    @property
    def current_player(self) -> Player:
        return self.players[self._current_idx]

    @property
    def top_card(self) -> Card:
        return self.deck.top_card

    @property
    def active_color(self) -> Color:
        return self._active_color

    @property
    def direction(self) -> int:
        return self._direction

    @property
    def winner(self) -> Optional[Player]:
        return self._winner

    @property
    def pending_draw(self) -> int:
        return self._pending_draw

    def playable_indices(self) -> List[int]:
        return self.current_player.playable_cards(self.top_card, self._active_color)

    def state_snapshot(self) -> GameState:
        return GameState(
            current_player_index=self._current_idx,
            direction=self._direction,
            active_color=self._active_color,
            top_card=self.top_card,
            draw_pile_size=self.deck.draw_pile_size,
            player_names=[p.name for p in self.players],
            player_card_counts=[p.card_count for p in self.players],
            player_is_human=[p.is_human for p in self.players],
            winner=self._winner.name if self._winner else None,
            pending_draw=self._pending_draw,
        )

    # ── Actions ────────────────────────────────────────────────────────────

    def play_card(
        self,
        card_index: int,
        chosen_color: Optional[Color] = None,
    ) -> Tuple[bool, str]:
        player = self.current_player
        if card_index < 0 or card_index >= player.card_count:
            return False, "Invalid card index."

        card = player.hand[card_index]
        playable = self.playable_indices()

        if card_index not in playable:
            return False, f"{card.full_name} cannot be played on {self.top_card.full_name}."

        # Wild card requires a color choice
        if card.color == Color.WILD and chosen_color is None:
            return False, "You must choose a color for a wild card."
        if card.color == Color.WILD and chosen_color == Color.WILD:
            return False, "Chosen color cannot be Wild."

        player.remove_card(card_index)
        self.deck.discard(card)

        # Resolve active color
        self._active_color = chosen_color if card.color == Color.WILD else card.color

        # Check win before applying effects (player empties hand)
        if player.card_count == 0:
            self._winner = player
            return True, f"{player.name} played {card.full_name} and wins!"

        msg = self._apply_effects(card, player)

        # Auto UNO announcement
        if player.card_count == 1:
            player.say_uno()
            msg += f" UNO! {player.name} has one card left!"

        return True, msg

    def draw_cards(self) -> Tuple[List[Card], str]:
        """Current player draws — either the pending penalty or one card."""
        player = self.current_player
        count = self._pending_draw if self._pending_draw > 0 else 1
        drawn = self.deck.draw_many(count)
        player.add_cards(drawn)
        self._pending_draw = 0
        self._advance()
        names = ", ".join(c.full_name for c in drawn)
        if count == 1:
            return drawn, f"{player.name} draws a card."
        return drawn, f"{player.name} draws {count} cards ({names})."

    def force_draw_penalty(self, target_idx: int, count: int) -> List[Card]:
        """Draw cards for a specific player (from card effects)."""
        drawn = self.deck.draw_many(count)
        self.players[target_idx].add_cards(drawn)
        return drawn

    # ── Internal ───────────────────────────────────────────────────────────

    def _apply_effects(self, card: Card, player: Player) -> str:
        if card.card_type == CardType.SKIP:
            self._advance()  # skip next
            skipped = self.current_player.name
            self._advance()
            return f"{player.name} played {card.full_name}. {skipped} is skipped!"

        if card.card_type == CardType.REVERSE:
            self._direction *= -1
            if len(self.players) == 2:
                # In 2-player, Reverse acts like Skip
                self._advance()
                return f"{player.name} played Reverse — plays again!"
            self._advance()
            return f"{player.name} played Reverse — direction changed!"

        if card.card_type == CardType.DRAW_TWO:
            self._pending_draw += 2
            next_player = self.players[self._next_idx()]
            self._advance()
            return (
                f"{player.name} played {card.full_name}. "
                f"{next_player.name} must draw {self._pending_draw} cards!"
            )

        if card.card_type == CardType.WILD_DRAW_FOUR:
            self._pending_draw += 4
            next_player = self.players[self._next_idx()]
            self._advance()
            return (
                f"{player.name} played Wild Draw Four. "
                f"{next_player.name} must draw {self._pending_draw} cards! "
                f"Color is now {self._active_color.value}."
            )

        if card.card_type == CardType.WILD:
            self._advance()
            return f"{player.name} played Wild. Color is now {self._active_color.value}."

        # Regular number card
        self._advance()
        return f"{player.name} played {card.full_name}."

    def _next_idx(self) -> int:
        return (self._current_idx + self._direction) % len(self.players)

    def _advance(self) -> None:
        self._current_idx = self._next_idx()
