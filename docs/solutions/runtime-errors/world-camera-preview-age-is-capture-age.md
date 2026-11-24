---
title: Rosy World camera preview age starts at capture
category: runtime-errors
problem_type: runtime_error
date: 2026-11-24
tags: [rosy-world, rosy-cam, preview, timestamp]
---

# Rosy World camera preview age starts at capture

Rosy World received HTTP 200 and valid Rosy Cam JPEGs while the camera UI reported no recent image. In the same sample, the HTTP `Date` and `Last-Modified` headers differed by 2–3 seconds for the rectified field preview and by 0 seconds for the local MuJoCo preview. The 3-second cutoff for all sources could reject an otherwise current field frame. The HTTP date headers have whole-second precision, so the comparison can also differ by a second from raw wall-clock age.

The camera bridge keeps the capture time as the snapshot file's modification time. This preserves the age of a frame through retries and through HTTP serving. The field source uses a 5-second preview limit. Gazebo and MuJoCo retain 3 seconds. The browser decodes the next JPEG before swapping it in and keeps the last valid frame with a delayed label after its freshness window expires. Switching camera sources or turning the panel off clears the frame.

To diagnose the issue, request the JPEG and compare both HTTP headers before changing polling frequency. In Chromium, both actual Rosy Cam and MuJoCo frames rendered after the change. Injected HTTP 503s kept the last image visible for 3.4 seconds after the delayed label appeared, and restoring the response resumed display. These budgets apply to visual monitoring. The capture timestamp and preview limit do not govern robot control.
