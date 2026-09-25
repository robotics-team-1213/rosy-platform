// ROS 통신 격리·연결 지도 렌더 (D-262 두 번째 분해). 셸은 render(runtime)
// 한 줄만 부른다. 이력 버퍼는 셸이 쥐고 팩토리에 넘긴다. map.js·vision.js와
// 같은 팩토리 모양이다.

export function createRosNetwork({
  elements, setText, metricNumber, rate, svgText, history,
}) {
  function pushSample(series, value) {
    const amount = metricNumber(value);
    if (amount === null) return;
    series.push(amount);
    if (series.length > 30) series.splice(0, series.length - 30);
  }

  function sparkline(id, values) {
    const svg = elements[id];
    if (!svg) return;
    svg.replaceChildren();
    if (!values.length) return;
    const width = 120;
    const height = 36;
    const peak = Math.max(...values, 1);
    const step = values.length > 1 ? width / (values.length - 1) : width;
    const points = values.map((value, index) => (
      `${(index * step).toFixed(2)},${(height - (value / peak) * (height - 4) - 2).toFixed(2)}`
    )).join(" ");
    const line = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    line.setAttribute("points", points);
    line.setAttribute("vector-effect", "non-scaling-stroke");
    svg.append(line);
  }

  function renderRosGraph(graph) {
    const svg = elements["ros-graph-map"];
    if (!svg) return;
    svg.replaceChildren();
    const nodes = (graph.nodes || []).slice(0, 12);
    const topics = (graph.topics || []).slice(0, 12);
    if (!nodes.length && !topics.length) {
      svg.append(svgText("ROS 그래프 데이터 없음", 400, 164, "graph-empty"));
      return;
    }

    const nodePositions = new Map();
    const topicPositions = new Map();
    const positionRows = (items, x) => items.map((item, index) => ({
      item,
      x,
      y: ((index + 1) * 300) / (items.length + 1) + 10,
    }));
    const nodeRows = positionRows(nodes, 150);
    const topicRows = positionRows(topics, 650);
    nodeRows.forEach(({ item, x, y }) => nodePositions.set(item.name, { x, y }));
    topicRows.forEach(({ item, x, y }) => topicPositions.set(item.name, { x, y }));

    (graph.edges || []).slice(0, 48).forEach((edge) => {
      const start = nodePositions.get(edge.source) || topicPositions.get(edge.source);
      const end = nodePositions.get(edge.target) || topicPositions.get(edge.target);
      if (!start || !end) return;
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("x1", start.x);
      line.setAttribute("y1", start.y);
      line.setAttribute("x2", end.x);
      line.setAttribute("y2", end.y);
      line.setAttribute("class", `graph-edge ${edge.kind}`);
      svg.append(line);
    });

    nodeRows.forEach(({ item, x, y }) => {
      const marker = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      marker.setAttribute("x", x - 108);
      marker.setAttribute("y", y - 13);
      marker.setAttribute("width", 216);
      marker.setAttribute("height", 26);
      marker.setAttribute("rx", 3);
      marker.setAttribute("class", `graph-node${item.foreign ? " foreign" : ""}`);
      svg.append(marker, svgText(item.name, x, y + 4, "graph-node-label"));
    });
    topicRows.forEach(({ item, x, y }) => {
      const marker = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      marker.setAttribute("cx", x);
      marker.setAttribute("cy", y);
      marker.setAttribute("r", 8);
      marker.setAttribute("class", "graph-topic");
      svg.append(marker, svgText(item.name, x - 14, y - 14, "graph-topic-label"));
    });
  }

  function render(runtime) {
    const graph = runtime.ros || {};
    const throughput = runtime.network?.throughput || {};
    const status = graph.status || "UNAVAILABLE";
    setText("ros-graph-status", status);
    elements["ros-graph-status"]?.setAttribute("data-status", status);
    setText("ros-domain-id", graph.domain_id);
    setText("ros-namespace", graph.namespace);
    const isolationLabels = {
      localhost_only: "LOOPBACK ONLY",
      network_visible: "NETWORK VISIBLE",
      unknown: "UNKNOWN",
    };
    setText("dds-isolation", isolationLabels[graph.isolation?.mode] || "—");
    setText("dds-interface", graph.isolation?.interface ? `interface ${graph.isolation.interface}` : "인터페이스 확인 불가");
    setText("dds-rmw", graph.rmw || "—");
    setText("ros-node-count", graph.node_count);
    setText("ros-topic-count", graph.topic_count);
    setText("network-rx-rate", rate(throughput.rx_bytes_per_second));
    setText("network-tx-rate", rate(throughput.tx_bytes_per_second));

    pushSample(history.rx, throughput.rx_bytes_per_second);
    pushSample(history.tx, throughput.tx_bytes_per_second);
    sparkline("network-sparkline-rx", history.rx);
    sparkline("network-sparkline-tx", history.tx);
    renderRosGraph(graph);

    const riskList = elements["ros-risk-list"];
    if (!riskList) return;
    riskList.replaceChildren();
    const risks = graph.risks || [];
    if (status === "UNAVAILABLE") {
      const item = document.createElement("li");
      item.className = "risk-unavailable";
      item.textContent = "ROS 그래프 수집 불가 — 충돌 상태를 확인할 수 없습니다.";
      riskList.append(item);
      return;
    }
    if (!risks.length) {
      const item = document.createElement("li");
      item.className = "risk-clear";
      item.textContent = "감지된 충돌 지표 없음";
      riskList.append(item);
      return;
    }
    risks.forEach((risk) => {
      const item = document.createElement("li");
      const code = document.createElement("strong");
      const message = document.createElement("span");
      code.textContent = risk.code || "UNKNOWN";
      message.textContent = risk.message || "상세 정보 없음";
      item.append(code, message);
      riskList.append(item);
    });
  }

  return { render };
}
