"""D-438/D-577 Fleet stuck judgment: open-stuck board and answer record (``board``), pure rule core
(``resolver``), lane-lost rules and AI proposal check (``lane_lost``), async poll loop (``loop``), AI PC
facts and proposals (``ai_facts``). Moved out of ``server/`` by D-607 P0.

``server/app.py`` and ``server/console_routes.py`` import this package.
"""
