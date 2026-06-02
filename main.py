#!/usr/bin/env python3
"""UNO — local multiplayer entry point."""
import time
from typing import Optional

from uno.card import Color, CardType
from uno.game import Game
from uno.player import Player
from uno.ai import choose_action
import uno.display as ui

# ── Color picker for wild cards ────────────────────────────────────────────────

COLOR_CHOICES = {
    "r": Color.RED,
    "b": Color.BLUE,
    "g": Color.GREEN,
    "y": Color.YELLOW,
}

COLOR_LABELS = {
    Color.RED: "\033[91mRed\033[0m",
    Color.BLUE: "\033[94mBlue\033[0m",
    Color.GREEN: "\033[92mGreen\033[0m",
    Color.YELLOW: "\033[93mYellow\033[0m",
}


def pick_color() -> Color:
    while True:
        print("\n  Choose a color: [r]ed  [b]lue  [g]reen  [y]ellow")
        choice = input("  > ").strip().lower()
        if choice in COLOR_CHOICES:
            return COLOR_CHOICES[choice]
        ui.print_error("Enter r, b, g, or y.")


# ── Human turn ─────────────────────────────────────────────────────────────────

def human_turn(game: Game, player_idx: int) -> str:
    player = game.current_player
    playable = game.playable_indices()

    ui.print_turn_divider(player, player_idx)

    if game.pending_draw and not playable:
        ui.print_pending_draw(game.pending_draw, player.name)

    ui.print_hand(player, playable)

    has_playable = bool(playable)
    pending = game.pending_draw

    if pending:
        # Can stack a matching draw card or must draw
        stack_options = [
            i for i in playable
            if player.hand[i].card_type in (CardType.DRAW_TWO, CardType.WILD_DRAW_FOUR)
        ]
        if stack_options:
            prompt = "  Play a draw card to stack, or 'd' to draw penalty: "
        else:
            prompt = f"  No valid play — press 'd' to draw {pending} cards: "
            has_playable = False
    else:
        prompt = "  Enter card number to play, or 'd' to draw: "

    while True:
        raw = input(prompt).strip().lower()

        if raw == "d":
            drawn, msg = game.draw_cards()
            ui.print_event(msg)
            return msg

        if raw.isdigit():
            idx = int(raw) - 1
            if idx < 0 or idx >= player.card_count:
                ui.print_error("No such card.")
                continue
            if idx not in playable:
                ui.print_error("That card cannot be played right now.")
                continue

            chosen_color: Optional[Color] = None
            card = player.hand[idx]
            if card.color.name == "WILD":
                chosen_color = pick_color()

            success, msg = game.play_card(idx, chosen_color)
            if success:
                ui.print_event(msg)
                return msg
            ui.print_error(msg)
        else:
            ui.print_error("Enter a card number or 'd'.")


# ── CPU turn ───────────────────────────────────────────────────────────────────

def cpu_turn(game: Game) -> str:
    player = game.current_player
    time.sleep(0.8)

    card_idx, chosen_color = choose_action(game)

    if card_idx is None:
        drawn, msg = game.draw_cards()
        ui.print_event(msg)
        return msg

    success, msg = game.play_card(card_idx, chosen_color)
    if success:
        ui.print_event(msg)
        if chosen_color:
            print(f"  {player.name} chose {COLOR_LABELS[chosen_color]}.")
        return msg

    # Fallback — should not happen
    drawn, msg = game.draw_cards()
    ui.print_event(msg)
    return msg


# ── Setup ──────────────────────────────────────────────────────────────────────

def setup() -> Game:
    ui.clear()
    ui.print_header()

    print("  Welcome to UNO!\n")

    while True:
        try:
            n_humans = int(input("  How many human players? (1–4): ").strip())
            if 1 <= n_humans <= 4:
                break
        except ValueError:
            pass
        ui.print_error("Enter a number between 1 and 4.")

    players: list[Player] = []
    for i in range(n_humans):
        name = input(f"  Player {i+1} name: ").strip() or f"Player {i+1}"
        players.append(Player(name, is_human=True))

    n_cpu = 0
    if n_humans < 4:
        while True:
            try:
                n_cpu = int(input(f"  How many CPU opponents? (0–{4 - n_humans}): ").strip())
                if 0 <= n_cpu <= 4 - n_humans and n_humans + n_cpu >= 2:
                    break
            except ValueError:
                pass
            ui.print_error(f"Enter 0–{4 - n_humans} (need at least 2 players total).")

    for i in range(n_cpu):
        players.append(Player(f"CPU-{i+1}", is_human=False))

    return Game(players)


# ── Main loop ──────────────────────────────────────────────────────────────────

def main() -> None:
    game = setup()
    starting_card = game.start()

    # Index of the first human (used to label "you" in scoreboard)
    first_human_idx = next(
        (i for i, p in enumerate(game.players) if p.is_human), 0
    )

    while not game.winner:
        current = game.current_player

        ui.clear()
        ui.print_header()
        ui.print_scoreboard(game, highlight_idx=first_human_idx)
        print(f"  Top card: {ui.render_top_card(game.top_card, game.active_color)}\n")

        if game.pending_draw:
            ui.print_pending_draw(game.pending_draw, current.name)

        if current.is_human:
            # For local multiplayer: gate on enter so others can look away
            if len([p for p in game.players if p.is_human]) > 1:
                input(f"\n  Pass to {current.name} and press Enter to reveal your hand...")
                ui.clear()
                ui.print_header()
                ui.print_scoreboard(game, highlight_idx=first_human_idx)
                print(f"  Top card: {ui.render_top_card(game.top_card, game.active_color)}\n")
            human_turn(game, first_human_idx)
        else:
            ui.print_turn_divider(current, first_human_idx)
            cpu_turn(game)

        if game.winner:
            break

        input("\n  Press Enter to continue...")

    # Game over
    ui.clear()
    ui.print_header()
    ui.print_winner(game.winner)

    # Show final hands
    print("  Final hands:")
    for p in game.players:
        cards = ", ".join(c.full_name for c in p.hand) or "empty"
        print(f"    {p.name}: {cards}")

    print()
    again = input("  Play again? [y/n]: ").strip().lower()
    if again == "y":
        main()
    else:
        print("\n  Thanks for playing UNO! Goodbye.\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  Game quit. Bye!\n")
