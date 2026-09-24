const canvas = document.getElementById("pitch");
const ctx = canvas.getContext("2d");
const MARKER_IDS = [10, 11, 12, 13, 1, 2, 20, 21];
const MARKER_LABEL = {
  10: "코너",
  11: "코너",
  12: "코너",
  13: "코너",
  1: "로봇",
  2: "로봇",
  20: "골",
  21: "골",
};

function draw(payload) {
  const field = payload.field || { length_m: 2, width_m: 1.4, goal_width_m: 0.35 };
  const w = canvas.width;
  const h = canvas.height;
  ctx.fillStyle = "#17351f";
  ctx.fillRect(0, 0, w, h);
  const pad = 36;
  const sx = (w - pad * 2) / field.length_m;
  const sy = (h - pad * 2) / field.width_m;
  const s = Math.min(sx, sy);
  const ox = w / 2;
  const oy = h / 2;
  const X = (x) => ox + x * s;
  const Y = (y) => oy - y * s;
  ctx.strokeStyle = "#e8f4ea";
  ctx.lineWidth = 2;
  ctx.strokeRect(
    X(-field.length_m / 2),
    Y(field.width_m / 2),
    field.length_m * s,
    field.width_m * s,
  );
  ctx.beginPath();
  ctx.moveTo(X(0), Y(-field.width_m / 2));
  ctx.lineTo(X(0), Y(field.width_m / 2));
  ctx.stroke();
  const gw = field.goal_width_m / 2;
  ctx.strokeStyle = "#7ec8ff";
  ctx.strokeRect(X(-field.length_m / 2) - 10, Y(gw), 10, field.goal_width_m * s);
  ctx.strokeStyle = "#ffb3c7";
  ctx.strokeRect(X(field.length_m / 2), Y(gw), 10, field.goal_width_m * s);
  if (payload.home_goal) {
    strokePoly(payload.home_goal, X, Y, "#7ec8ff");
  }
  if (payload.away_goal) {
    strokePoly(payload.away_goal, X, Y, "#ffb3c7");
  }
  const robots = payload.robots || {};
  const homeId = field.home_id;
  Object.entries(robots).forEach(([id, pose]) => {
    ctx.fillStyle = id === homeId ? "#7ec8ff" : "#ffb3c7";
    wedge(X(pose.x), Y(pose.y), pose.yaw, 11);
    ctx.fillStyle = "#f4f1ea";
    ctx.font = "11px sans-serif";
    ctx.fillText(id, X(pose.x) + 8, Y(pose.y) - 8);
  });
  if (payload.ball) {
    ctx.fillStyle = "#f27a1a";
    ctx.beginPath();
    ctx.arc(X(payload.ball.x), Y(payload.ball.y), 7, 0, Math.PI * 2);
    ctx.fill();
  }
}

function strokePoly(points, X, Y, color) {
  if (!points.length) return;
  ctx.strokeStyle = color;
  ctx.beginPath();
  ctx.moveTo(X(points[0][0]), Y(points[0][1]));
  points.slice(1).forEach((p) => ctx.lineTo(X(p[0]), Y(p[1])));
  ctx.closePath();
  ctx.stroke();
}

function wedge(x, y, yaw, r) {
  ctx.beginPath();
  ctx.moveTo(x + Math.cos(-yaw) * r, y + Math.sin(-yaw) * r);
  ctx.lineTo(x + Math.cos(-yaw + 2.5) * r * 0.7, y + Math.sin(-yaw + 2.5) * r * 0.7);
  ctx.lineTo(x + Math.cos(-yaw - 2.5) * r * 0.7, y + Math.sin(-yaw - 2.5) * r * 0.7);
  ctx.closePath();
  ctx.fill();
}

function chips(payload) {
  const seen = new Set(payload.markers || []);
  const root = document.getElementById("markers");
  root.replaceChildren();
  MARKER_IDS.forEach((id) => {
    const li = document.createElement("li");
    li.textContent = `${id} ${MARKER_LABEL[id] || ""}`.trim();
    if (seen.has(id)) li.className = "on";
    root.append(li);
  });
}

async function tick() {
  const res = await fetch("/overlay.json", { cache: "no-store" });
  if (!res.ok) return;
  const payload = await res.json();
  if (!payload.field) return;
  document.getElementById("phase").textContent = payload.phase || "—";
  document.getElementById("home-name").textContent = payload.field.home_id;
  document.getElementById("away-name").textContent = payload.field.away_id;
  document.getElementById("home-score").textContent = payload.score?.[payload.field.home_id] ?? 0;
  document.getElementById("away-score").textContent = payload.score?.[payload.field.away_id] ?? 0;
  const lost = payload.lost_ball || (payload.lost_robots || []).length;
  document.getElementById("lost").hidden = !lost;
  document.getElementById("lost").textContent = payload.reason || (payload.lost_ball ? "공을 잃음" : "로봇을 잃음");
  draw(payload);
  chips(payload);
  const vis = payload.visibility || {};
  const stair1 = document.getElementById("stair1");
  if (stair1) {
    stair1.textContent = vis.ready
      ? "계단 1 마커 보임 (FIELD GO 아님)"
      : "계단 1 아직 (FIELD GO 아님)";
  }
  const frame = document.getElementById("frame");
  if (!payload.has_frame) {
    frame.hidden = true;
    return;
  }
  frame.onerror = () => {
    frame.hidden = true;
  };
  frame.onload = () => {
    frame.hidden = false;
  };
  frame.src = `/frame.jpg?t=${Date.now()}`;
}

document.getElementById("halt").addEventListener("click", async () => {
  await fetch("/stop", { method: "POST" });
});

setInterval(tick, 250);
tick();
