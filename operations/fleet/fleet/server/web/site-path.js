// D-499 site path words. The page passes results of calls it already makes.

function pending(name) {
  return { name, word: "확인 중", kind: "neutral" };
}

export function proxyRow(sample) {
  if (!sample) return pending("프록시");
  const body = sample.body;
  const exact = sample.finished === true && sample.status === 200
    && body !== null && typeof body === "object" && !Array.isArray(body)
    && Object.keys(body).length === 1 && body.status === "ok";
  return exact ? { name: "프록시", word: "정상", kind: "good" }
    : { name: "프록시", word: "끊김", kind: "crit" };
}

export function fleetRow(sample) {
  if (!sample) return pending("Fleet");
  if (sample.finished === true && typeof sample.status === "number") {
    return { name: "Fleet", word: "정상", kind: "good" };
  }
  return { name: "Fleet", word: "끊김", kind: "crit" };
}

export function visionRow(sample) {
  if (!sample) return pending("Vision");
  if (sample.finished !== true) return { name: "Vision", word: "끊김", kind: "crit" };
  if (sample.status === 200 && Array.isArray(sample.names) && sample.names.length) {
    return { name: "Vision", word: sample.names.join(", "), kind: "good" };
  }
  if (sample.status === 200) return { name: "Vision", word: "없음", kind: "warn" };
  return { name: "Vision", word: `응답 ${sample.status}`, kind: "warn" };
}

export function sitePathSummary(rows) {
  const issues = rows.filter((row) => row.kind === "warn" || row.kind === "crit");
  if (issues.length) return `${issues[0].name} ${issues[0].word}${issues.length > 1 ? ` 외 ${issues.length - 1}건` : ""}`;
  return rows.some((row) => row.kind === "neutral") ? "확인 중" : "모두 정상";
}
