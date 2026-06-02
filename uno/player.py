from typing import List, Optional
from uno.card import Card, Color


class Player:
    def __init__(self, name: str, is_human: bool = True):
        self.name = name
        self.is_human = is_human
        self.hand: List[Card] = []
        self._said_uno = False

    @property
    def card_count(self) -> int:
        return len(self.hand)

    def add_cards(self, cards: List[Card]) -> None:
        self.hand.extend(cards)
        if len(self.hand) > 1:
            self._said_uno = False

    def remove_card(self, index: int) -> Card:
        return self.hand.pop(index)

    def playable_cards(self, top_card: Card, active_color: Color) -> List[int]:
        return [i for i, c in enumerate(self.hand) if c.can_play_on(top_card, active_color)]

    def say_uno(self) -> None:
        self._said_uno = True

    def forgot_uno(self) -> bool:
        """True if player has 1 card but never said UNO."""
        return self.card_count == 1 and not self._said_uno

    def dominant_color(self) -> Optional[Color]:
        """Most common color in hand (for wild card choice)."""
        from collections import Counter
        color_counts = Counter(
            c.color for c in self.hand if c.color != Color.WILD
        )
        if not color_counts:
            return Color.RED
        return color_counts.most_common(1)[0][0]

    def __repr__(self) -> str:
        tag = "human" if self.is_human else "CPU"
        return f"Player({self.name!r}, {tag}, {self.card_count} cards)"
