from enum import Enum
from dataclasses import dataclass
from typing import Optional


class Color(Enum):
    RED = "Red"
    BLUE = "Blue"
    GREEN = "Green"
    YELLOW = "Yellow"
    WILD = "Wild"


class CardType(Enum):
    NUMBER = "Number"
    SKIP = "Skip"
    REVERSE = "Reverse"
    DRAW_TWO = "Draw Two"
    WILD = "Wild"
    WILD_DRAW_FOUR = "Wild Draw Four"


@dataclass(frozen=True)
class Card:
    color: Color
    card_type: CardType
    number: Optional[int] = None

    def can_play_on(self, top_card: "Card", active_color: Color) -> bool:
        if self.color == Color.WILD:
            return True
        if self.color == active_color:
            return True
        if self.card_type not in (CardType.NUMBER, CardType.WILD, CardType.WILD_DRAW_FOUR):
            if self.card_type == top_card.card_type:
                return True
        if self.card_type == CardType.NUMBER and top_card.card_type == CardType.NUMBER:
            return self.number == top_card.number
        return False

    @property
    def short(self) -> str:
        if self.card_type == CardType.NUMBER:
            return f"{self.color.value[0]}{self.number}"
        if self.card_type == CardType.SKIP:
            return f"{self.color.value[0]}SK"
        if self.card_type == CardType.REVERSE:
            return f"{self.color.value[0]}RV"
        if self.card_type == CardType.DRAW_TWO:
            return f"{self.color.value[0]}+2"
        if self.card_type == CardType.WILD:
            return "WLD"
        if self.card_type == CardType.WILD_DRAW_FOUR:
            return "W+4"
        return "???"

    @property
    def full_name(self) -> str:
        if self.color == Color.WILD:
            return self.card_type.value
        if self.card_type == CardType.NUMBER:
            return f"{self.color.value} {self.number}"
        return f"{self.color.value} {self.card_type.value}"

    def __str__(self) -> str:
        return self.full_name
