"""Rebuild the eight D-504 assets using the installed character renderer."""
from pathlib import Path

from emotion.character import NAMES, frame


def main() -> None:
    assets = Path(__file__).resolve().parent / "emotion"
    for name in NAMES:
        frames = [frame(name, phase) for phase in range(20)]
        frames[0].save(assets / f"{name}.gif", save_all=True, append_images=frames[1:],
                       duration=100, loop=0, optimize=False)


if __name__ == "__main__":
    main()
