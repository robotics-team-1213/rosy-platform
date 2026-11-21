---
surface: fleet
kind: additive
slug: text-double-encoded
date: 2026-11-21
title: Site map saves refuse double-encoded text
history: Draft and profile saves answer 400 TEXT_DOUBLE_ENCODED
---
PUT /api/fleet/site-map/draft and PUT /api/fleet/site-map/profiles/{profile_id} refuse a map or profile name whose text was decoded and encoded twice (UTF-8 read as cp1252, Hangul turned into Latin-1 look-alikes): 400 TEXT_DOUBLE_ENCODED, detail.detail.message lists up to five field paths such as places.0.name. Send the text as UTF-8 again. Nothing is stored.
