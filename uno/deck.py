import random
from typing import List
from uno.card import Card, Color, CardType


def _build_deck() -> List[Card]:
    cards: List[Card] = []
    colors = [Color.RED, Color.BLUE, Color.GREEN, Color.YELLOW]

    for color in colors:
        # One zero per color
        cards.append(Card(color, CardType.NUMBER, 0))
        # Two of each 1-9, Skip, Reverse, Draw Two
        for n in range(1, 10):
            cards.append(Card(color, CardType.NUMBER, n))
            cards.append(Card(color, CardType.NUMBER, n))
        for _ in range(2):
            cards.append(Card(color, CardType.SKIP))
            cards.append(Card(color, CardType.REVERSE))
            cards.append(Card(color, CardType.DRAW_TWO))

    # Four of each wild
    for _ in range(4):
        cards.append(Card(Color.WILD, CardType.WILD))
        cards.append(Card(Color.WILD, CardType.WILD_DRAW_FOUR))

    return cards  # 108 cards total


class Deck:
    def __init__(self):
        self._draw_pile: List[Card] = _build_deck()
        self._discard_pile: List[Card] = []
        random.shuffle(self._draw_pile)

    @property
    def top_card(self) -> Card:
        return self._discard_pile[-1]

    @property
    def discard_pile(self) -> List[Card]:
        return list(self._discard_pile)

    @property
    def draw_pile_size(self) -> int:
        return len(self._draw_pile)

    def draw(self) -> Card:
        if not self._draw_pile:
            self._reshuffle_discard()
        return self._draw_pile.pop()

    def draw_many(self, count: int) -> List[Card]:
        return [self.draw() for _ in range(count)]

    def discard(self, card: Card) -> None:
        self._discard_pile.append(card)

    def flip_starting_card(self) -> Card:
        """Draw cards until we get a non-wild starting card."""
        while True:
            card = self._draw_pile.pop()
            if card.color != Color.WILD:
                self._discard_pile.append(card)
                return card
            self._draw_pile.insert(0, card)  # put wild back at bottom

    def _reshuffle_discard(self) -> None:
        top = self._discard_pile.pop()
        self._draw_pile = self._discard_pile[:]
        random.shuffle(self._draw_pile)
        self._discard_pile = [top]
