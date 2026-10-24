"""Card dispatch for the native face owner; rendering dependencies are injected."""
from typing import Callable


def card_renderer(info_screen) -> Callable[[dict], object]:
    """D-433: one entry for every card the table can ask for; a release image each.

    ``card["screen"]`` is ``face_screen.screen_for``'s answer (absent on a release
    without it: the boot card, as before).
    """

    def render(card: dict):
        screen = card.get("screen") or {}
        kind = screen.get("kind")
        frame = int(card.get("frame") or 0)
        if kind == "stopped":
            image = info_screen.render_stopped({"device_name": card.get("device_name"),
                                                "cause": screen.get("cause"), "release": screen.get("release")})
        elif kind == "light":
            image = info_screen.render_light_assist()
        elif kind == "update":
            image = info_screen.render_notice("Updating", [f"to {screen.get('release') or '?'}",
                                                           f"now {card.get('release_id') or '?'}"], frame=frame)
        elif kind == "shutdown":
            image = info_screen.render_notice(str(card.get("shutdown_title") or "Shutting down"),
                                              [str(card.get("device_name") or "")])
        elif screen.get("row") == "network_recovery":
            page = screen["recovery_page"]
            image = info_screen.render_notice(page["title"], page["lines"])
        elif kind == "face" and screen.get("overlay"):  # a card takes the expression area, under the bar
            image = info_screen.render_overlay(screen["overlay"]["payload"])
        elif screen.get("row") == "peer_request":
            # D-483: ASCII, as every card (the DejaVu card font has no Hangul).
            # One "XXXX  CODE" line per live request, so each requester reads its own code.
            peer = screen.get("peer") or {}
            lines = [f"{r['display_code']}  {r['approval_code']}" for r in peer.get("requests") or []]
            if peer.get("tls_ca_sha256"):
                # What the tablet asks a first-contact requester to compare (its first 16 digits).
                ca = peer["tls_ca_sha256"][:16]
                lines.append("CA " + " ".join(ca[i:i + 4] for i in range(0, 16, 4)))
            image = info_screen.render_notice("Pair request", lines)
        else:
            image = info_screen.render_boot(card, frame=frame)
        if kind == "face" and card.get("bar"):
            band, mask = info_screen.render_bar(*card["bar"][:4])
            image.paste(band, (0, 0), mask)
        return image

    return render
