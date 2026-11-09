"""D-721 Amendment: the person request kinds and the robot screen's words for them (no dependencies).

The face stays English by user decision (2026-11-06); the card font has no Hangul. Short and upper case so the
text fits the caution strip. ``protocol.person_request`` and ``face_screen`` both read this one table.
"""

KINDS = ("unplug_charger", "plug_charger", "move_robot", "clear_area", "other")
FACE_TEXT = {"unplug_charger": "UNPLUG CHARGER", "plug_charger": "PLUG CHARGER", "move_robot": "MOVE ROBOT",
             "clear_area": "CLEAR AREA", "other": "SEE CONSOLE"}
DEFAULT_TTL_S = 600.0
MAX_TTL_S = 3600.0
REPEAT_S = 15.0   # the robot beeps on arrival and then this often until the request is gone
