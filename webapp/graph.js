const state = {
  graph: null,
  selections: null,
  showReasons: true,
  searchTerm: "",
};

const svg = d3.select("#graphSvg");
const statsPill = document.getElementById("statsPill");
const detailBody = document.getElementById("detailBody");
const searchInput = document.getElementById("searchInput");
const minWeightInput = document.getElementById("minWeightInput");
const limitInput = document.getElementById("limitInput");
const verifiedOnlyInput = document.getElementById("verifiedOnlyInput");
const showReasonsInput = document.getElementById("showReasonsInput");
const refreshBtn = document.getElementById("refreshBtn");

function edgeReasonLabel(edge) {
  const text = edge.reason || "No explicit reason captured.";
  return text.length > 46 ? `${text.slice(0, 43)}...` : text;
}

function colorForCategoryType(type) {
  if (type === "income") return "#60d97f";
  if (type === "expense") return "#ff9a3c";
  return "#d1d9de";
}

function buildQueryString() {
  const params = new URLSearchParams();
  params.set("min_weight", `${Number(minWeightInput.value || 0)}`);
  params.set("limit", `${Number(limitInput.value || 250)}`);
  params.set("verified_only", verifiedOnlyInput.checked ? "1" : "0");
  return params.toString();
}

function setDetailPanel(content) {
  detailBody.textContent = content;
}

function updateStats(stats) {
  statsPill.textContent =
    `Rows ${stats.rows_scanned} | Nodes ${stats.total_nodes} | ` +
    `Edges ${stats.total_edges_after_limit}`;
}

function updateSearchHighlight() {
  const selections = state.selections;
  if (!selections) return;

  const term = state.searchTerm.trim().toLowerCase();
  if (!term) {
    selections.node.style("opacity", 1);
    selections.nodeLabel.style("opacity", 1);
    selections.link.style("opacity", 0.65);
    selections.edgeLabel.style("opacity", state.showReasons ? 0.65 : 0);
    return;
  }

  const matchingNodeIds = new Set();
  selections.node.each((d) => {
    const haystack = `${d.label} ${d.kind}`.toLowerCase();
    if (haystack.includes(term)) {
      matchingNodeIds.add(d.id);
    }
  });

  const matchingEdgeIds = new Set();
  selections.link.each((d) => {
    const haystack = `${d.keyword} ${d.category_label} ${d.reason}`.toLowerCase();
    if (
      haystack.includes(term) ||
      matchingNodeIds.has(d.source.id || d.source) ||
      matchingNodeIds.has(d.target.id || d.target)
    ) {
      matchingEdgeIds.add(d.id);
      matchingNodeIds.add(d.source.id || d.source);
      matchingNodeIds.add(d.target.id || d.target);
    }
  });

  selections.node.style("opacity", (d) => (matchingNodeIds.has(d.id) ? 1 : 0.15));
  selections.nodeLabel.style("opacity", (d) => (matchingNodeIds.has(d.id) ? 1 : 0.1));
  selections.link.style("opacity", (d) => (matchingEdgeIds.has(d.id) ? 0.85 : 0.08));
  selections.edgeLabel.style("opacity", (d) => {
    if (!state.showReasons) return 0;
    return matchingEdgeIds.has(d.id) ? 0.85 : 0.05;
  });
}

function renderGraph(graph) {
  const width = svg.node().clientWidth || 1200;
  const height = svg.node().clientHeight || 700;
  svg.selectAll("*").remove();

  const nodeData = graph.nodes.map((d) => ({ ...d }));
  const edgeData = graph.edges.map((d) => ({ ...d }));

  if (!nodeData.length || !edgeData.length) {
    setDetailPanel("No graph edges found. Add or review more transactions to build memory links.");
    return;
  }

  const viewport = svg.append("g").attr("class", "viewport");
  const defs = svg.append("defs");
  const glow = defs.append("filter").attr("id", "keywordGlow");
  glow
    .append("feDropShadow")
    .attr("dx", 0)
    .attr("dy", 0)
    .attr("stdDeviation", 3.5)
    .attr("flood-color", "rgba(64, 183, 255, 0.55)");

  const zoom = d3
    .zoom()
    .scaleExtent([0.3, 3.6])
    .on("zoom", (event) => {
      viewport.attr("transform", event.transform);
    });
  svg.call(zoom);

  const [minWeight, maxWeight] = d3.extent(edgeData, (d) => d.weight);
  const strokeScale = d3
    .scaleLinear()
    .domain([minWeight || 0.1, maxWeight || 1])
    .range([1.2, 8.5]);

  const link = viewport
    .append("g")
    .attr("stroke", "#9ec0d3")
    .attr("stroke-opacity", 0.65)
    .selectAll("line")
    .data(edgeData, (d) => d.id)
    .join("line")
    .attr("stroke-width", (d) => strokeScale(d.weight));

  const edgeLabel = viewport
    .append("g")
    .selectAll("text")
    .data(edgeData, (d) => d.id)
    .join("text")
    .attr("class", "graph-edge-label")
    .text((d) => edgeReasonLabel(d))
    .attr("opacity", state.showReasons ? 0.65 : 0);

  const node = viewport
    .append("g")
    .selectAll("circle")
    .data(nodeData, (d) => d.id)
    .join("circle")
    .attr("r", (d) => d.size)
    .attr("fill", (d) => (d.kind === "keyword" ? "#40b7ff" : colorForCategoryType(d.category_type)))
    .attr("stroke", "#d7edf8")
    .attr("stroke-width", (d) => (d.kind === "keyword" ? 0.9 : 0.55))
    .attr("filter", (d) => (d.kind === "keyword" ? "url(#keywordGlow)" : null));

  const nodeLabel = viewport
    .append("g")
    .selectAll("text")
    .data(nodeData, (d) => d.id)
    .join("text")
    .attr("class", "graph-node-label")
    .text((d) => d.label);

  const simulation = d3
    .forceSimulation(nodeData)
    .force("link", d3.forceLink(edgeData).id((d) => d.id).distance((d) => 45 + d.weight * 10))
    .force("charge", d3.forceManyBody().strength((d) => (d.kind === "keyword" ? -260 : -390)))
    .force("collide", d3.forceCollide().radius((d) => d.size + 8))
    .force("center", d3.forceCenter(width / 2, height / 2))
    .alpha(1)
    .alphaDecay(0.034);

  function dragstarted(event) {
    if (!event.active) simulation.alphaTarget(0.2).restart();
    event.subject.fx = event.subject.x;
    event.subject.fy = event.subject.y;
  }

  function dragged(event) {
    event.subject.fx = event.x;
    event.subject.fy = event.y;
  }

  function dragended(event) {
    if (!event.active) simulation.alphaTarget(0);
    event.subject.fx = null;
    event.subject.fy = null;
  }

  node.call(d3.drag().on("start", dragstarted).on("drag", dragged).on("end", dragended));

  node
    .on("mouseenter", (_, d) => {
      const nodeEdges = edgeData.filter((e) => (e.source.id || e.source) === d.id || (e.target.id || e.target) === d.id);
      const topEdges = nodeEdges
        .slice()
        .sort((a, b) => b.weight - a.weight)
        .slice(0, 4)
        .map((e) => `${e.keyword} -> ${e.category_label} (w=${e.weight.toFixed(2)})`);
      const summary = [
        `Node: ${d.label}`,
        `Type: ${d.kind}`,
        `Connections: ${nodeEdges.length}`,
        "",
        topEdges.join("\n") || "No connections",
      ].join("\n");
      setDetailPanel(summary);
    })
    .on("mouseleave", () => {
      setDetailPanel("Hover a node or edge to inspect details.");
    });

  link
    .on("mouseenter", (_, d) => {
      const reasonRollup =
        (d.reasons || [])
          .map((r) => `- (${r.count}) ${r.text}`)
          .join("\n") || "- No explicit reason captured.";
      const summary = [
        `${d.keyword} -> ${d.category_label}`,
        `Weight: ${d.weight.toFixed(2)}`,
        `Occurrences: ${d.count}`,
        `Avg confidence: ${d.avg_confidence.toFixed(2)}`,
        `Verified ratio: ${(d.verified_ratio * 100).toFixed(0)}%`,
        "",
        "Reasons:",
        reasonRollup,
      ].join("\n");
      setDetailPanel(summary);
    })
    .on("mouseleave", () => {
      setDetailPanel("Hover a node or edge to inspect details.");
    });

  simulation.on("tick", () => {
    link
      .attr("x1", (d) => d.source.x)
      .attr("y1", (d) => d.source.y)
      .attr("x2", (d) => d.target.x)
      .attr("y2", (d) => d.target.y);

    edgeLabel
      .attr("x", (d) => (d.source.x + d.target.x) / 2)
      .attr("y", (d) => (d.source.y + d.target.y) / 2 - 4);

    node.attr("cx", (d) => d.x).attr("cy", (d) => d.y);
    nodeLabel.attr("x", (d) => d.x + d.size + 4).attr("y", (d) => d.y + 3);
  });

  state.selections = { node, nodeLabel, link, edgeLabel };
  updateSearchHighlight();
}

async function loadGraph() {
  statsPill.textContent = "Loading graph...";
  setDetailPanel("Loading keyword-category memory links...");
  const query = buildQueryString();

  try {
    const response = await fetch(`/api/graph?${query}`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || `Request failed with ${response.status}`);
    }
    state.graph = payload;
    updateStats(payload.stats);
    renderGraph(payload);
  } catch (error) {
    statsPill.textContent = "Failed to load graph";
    setDetailPanel(`Could not load graph data.\n${error.message}`);
  }
}

refreshBtn.addEventListener("click", () => {
  loadGraph();
});

showReasonsInput.addEventListener("change", () => {
  state.showReasons = showReasonsInput.checked;
  updateSearchHighlight();
});

searchInput.addEventListener("input", () => {
  state.searchTerm = searchInput.value || "";
  updateSearchHighlight();
});

window.addEventListener("resize", () => {
  if (state.graph) renderGraph(state.graph);
});

loadGraph();
