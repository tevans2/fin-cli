"""Branding: the fin logo + banner, embedded so it ships with the package."""

from __future__ import annotations

LOGO = '⠀ ⢯⠙⠲⢤⣀⠀⠀⠀⠀⠀⠀⠀⠀⠀\n⠀⠀⠸⡆⠀⠀⠈⠳⣄⠀⠀⠀⠀⠀⠀⠀\n⠀⠀⠀⡇⠀⠀⠀⠀⠈⢳⡀⠀⠀⠀⠀⠀\n⠀⠀⢰⠇⠀⠀⠀⠀⠀⠈⢷⠀⠀⠀⠀⠀\n⣀⡴⠒⢾⡀⣀⡴⠒⢦⣀⢀⡼⠓⢦⣀\n⣩⠴⠒⢶⣉⣉⡴⠒⢦⣉⣉⡴⠒⠶⣌\n⠁⠀⠀⠀⠈⠁⠀⠀⠀⠈⠁⠀⠀⠀⠈'

TAGLINE = "fin — a personal finance CLI built on hledger"


def banner() -> str:
    return f"{LOGO}\n\n{TAGLINE}"
