const state = {
  graph: null,
  selections: null,
  searchTerm: "",
  focusNodeId: null,
  focusEdgeId: null,
  tagNodeId: null,
  zoomBehavior: null,
  showEdgeText: false,
  showNodeText: false,
  connectedNodeScale: 0.78,
  drawerOpen: true,
};

const svg = d3.select("#graphSvg");
const statsPill = document.getElementById("statsPill");
const detailBody = document.getElementById("detailBody");
const detailPanel = document.getElementById("detailPanel");

const searchInput = document.getElementById("searchInput");
const minWeightInput = document.getElementById("minWeightInput");
const limitInput = document.getElementById("limitInput");
const verifiedOnlyInput = document.getElementById("verifiedOnlyInput");
const refreshBtn = document.getElementById("refreshBtn");

const edgeTextToggle = document.getElementById("edgeTextToggle");
const nodeTextToggle = document.getElementById("nodeTextToggle");
const connectedNodeSizeRange = document.getElementById("connectedNodeSizeRange");
const connectedNodeSizeValue = document.getElementById("connectedNodeSizeValue");
const drawerToggleBtn = document.getElementById("drawerToggleBtn");
const drawerCloseBtn = document.getElementById("drawerCloseBtn");

const zoomInBtn = document.getElementById("zoomInBtn");
const zoomOutBtn = document.getElementById("zoomOutBtn");
const zoomResetBtn = document.getElementById("zoomResetBtn");

function sourceId(edge) {
  return typeof edge.source === "object" ? edge.source.id : edge.source;
}

function targetId(edge) {
  return typeof edge.target === "object" ? edge.target.id : edge.target;
}

function edgeReasonLabel(edge) {
  const text = edge.reason || "No explicit reason captured.";
  return text.length > 32 ? `${text.slice(0, 29)}...` : text;
}

function formatDate(value) {
  if (!value) return "unknown";
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return value;
  return dt.toISOString().slice(0, 10);
}

function formatAmount(value) {
  if (typeof value !== "number") return "-";
  return value.toFixed(2);
}

function nodeRadius(node) {
  if (node.kind === "transaction") {
    return 2.7;
  }
  return Math.max(4.4, node.size * state.connectedNodeScale);
}

function buildQueryString() {
  const params = new URLSearchParams();
  params.set("min_weight", `${Number(minWeightInput.value || 0)}`);
  params.set("limit", `${Number(limitInput.value || 250)}`);
  params.set("verified_only", verifiedOnlyInput.checked ? "1" : "0");
  params.set("include_transactions", "1");
  params.set("tx_per_keyword", "14");
  params.set("tx_node_limit", "1200");
  return params.toString();
}

function setDetailPanel(content) {
  detailBody.textContent = content;
}

function setDefaultDetail() {
  setDetailPanel(
    [
      "Hover a node or edge to inspect details.",
      "",
      "Merchant nodes connect to categories.",
      "Small satellite nodes are transactions linked by keyword.",
    ].join("\n"),
  );
}

function updateStats(stats) {
  statsPill.textContent =
    `Rows ${stats.rows_scanned} | Nodes ${stats.total_nodes} | ` +
    `Edges ${stats.total_edges_after_limit}`;
}

function updateZoomIndicator(transform) {
  if (!zoomResetBtn) return;
  zoomResetBtn.textContent = `${Math.round(transform.k * 100)}%`;
}

function syncConnectedNodeScaleLabel() {
  if (!connectedNodeSizeValue || !connectedNodeSizeRange) return;
  connectedNodeSizeValue.textContent = `${state.connectedNodeScale.toFixed(2)}x`;
}

function setDrawerOpen(isOpen) {
  state.drawerOpen = Boolean(isOpen);
  if (!detailPanel || !drawerToggleBtn) return;
  detailPanel.classList.toggle("collapsed", !state.drawerOpen);
  drawerToggleBtn.classList.toggle("hidden", state.drawerOpen);
}

function collectActiveSets() {
  const selections = state.selections;
  const activeNodeIds = new Set();
  const activeEdgeIds = new Set();
  if (!selections) return { activeNodeIds, activeEdgeIds, filtered: false };

  const term = state.searchTerm.trim().toLowerCase();
  if (term) {
    selections.nodeData.forEach((node) => {
      const haystack = `${node.label} ${node.kind} ${node.description || ""}`.toLowerCase();
      if (haystack.includes(term)) activeNodeIds.add(node.id);
    });

    selections.edgeData.forEach((edge) => {
      const sid = sourceId(edge);
      const tid = targetId(edge);
      const haystack = `${edge.keyword || ""} ${edge.category_label || ""} ${edge.reason || ""} ${
        edge.transaction_label || ""
      }`.toLowerCase();
      if (haystack.includes(term) || activeNodeIds.has(sid) || activeNodeIds.has(tid)) {
        activeEdgeIds.add(edge.id);
        activeNodeIds.add(sid);
        activeNodeIds.add(tid);
      }
    });
  }

  if (state.focusNodeId) {
    activeNodeIds.add(state.focusNodeId);
    selections.edgeData.forEach((edge) => {
      const sid = sourceId(edge);
      const tid = targetId(edge);
      if (sid === state.focusNodeId || tid === state.focusNodeId) {
        activeEdgeIds.add(edge.id);
        activeNodeIds.add(sid);
        activeNodeIds.add(tid);
      }
    });
  }

  if (state.focusEdgeId) {
    const edge = selections.edgeData.find((row) => row.id === state.focusEdgeId);
    if (edge) {
      activeEdgeIds.add(edge.id);
      activeNodeIds.add(sourceId(edge));
      activeNodeIds.add(targetId(edge));
    }
  }

  return {
    activeNodeIds,
    activeEdgeIds,
    filtered:
      term.length > 0 || state.focusNodeId !== null || state.focusEdgeId !== null,
  };
}

function applyVisualState() {
  const selections = state.selections;
  if (!selections) return;
  const { nodeGroup, nodeRing, nodeCore, nodeLabel, link, edgeLabel, strokeScale } = selections;
  const { activeNodeIds, activeEdgeIds, filtered } = collectActiveSets();

  nodeGroup.style("opacity", (d) => {
    if (!filtered) return d.kind === "transaction" ? 0.64 : 0.98;
    if (activeNodeIds.has(d.id)) return 1;
    return d.kind === "transaction" ? 0.06 : 0.2;
  });

  nodeRing
    .attr("stroke", (d) => {
      if (d.id === state.focusNodeId) return "#26363f";
      if (d.kind === "keyword") return filtered && activeNodeIds.has(d.id) ? "#3f6a7f" : "#6f8f9f";
      if (d.kind === "transaction") return "#d8dcdf";
      return filtered && activeNodeIds.has(d.id) ? "#6f7c86" : "#98a3ab";
    })
    .attr("stroke-width", (d) => {
      if (d.kind === "transaction") return 0.9;
      if (d.id === state.focusNodeId) return 2.6;
      if (filtered && activeNodeIds.has(d.id)) return 1.8;
      return 1.25;
    });

  nodeCore.attr("fill", (d) => {
    if (d.kind === "keyword") {
      if (d.id === state.focusNodeId) return "#2f586b";
      if (filtered && activeNodeIds.has(d.id)) return "#4f7a8d";
      return "#5f8798";
    }
    if (d.kind === "category") {
      if (d.id === state.focusNodeId) return "#6a7780";
      if (filtered && activeNodeIds.has(d.id)) return "#7a8790";
      return "#88949c";
    }
    return "#cfd5d9";
  });

  link
    .attr("stroke", (d) => {
      if (d.id === state.focusEdgeId) return "#5f8ea2";
      if (d.edge_type === "transaction_keyword") {
        return filtered && activeEdgeIds.has(d.id) ? "#b8c3ca" : "#d5dade";
      }
      return filtered && activeEdgeIds.has(d.id) ? "#8ca8b6" : "#c9d0d5";
    })
    .attr("stroke-width", (d) => {
      const base = strokeScale(d.weight);
      if (d.edge_type === "transaction_keyword") {
        const txBase = Math.max(0.6, base * 0.72);
        return filtered && activeEdgeIds.has(d.id) ? txBase * 1.2 : txBase;
      }
      return filtered && activeEdgeIds.has(d.id) ? base * 1.16 : base;
    })
    .style("opacity", (d) => {
      if (!filtered) return d.edge_type === "transaction_keyword" ? 0.3 : 0.56;
      return activeEdgeIds.has(d.id) ? 0.95 : 0.12;
    });

  edgeLabel.style("opacity", (d) => {
    if (!state.showEdgeText) return 0;
    if (!filtered) return d.edge_type === "transaction_keyword" ? 0 : 0.4;
    return activeEdgeIds.has(d.id) && d.edge_type !== "transaction_keyword" ? 0.82 : 0.03;
  });

  nodeLabel.style("opacity", (d) => {
    if (!state.showNodeText || d.kind === "transaction") return 0;
    if (!filtered) return 0.72;
    return activeNodeIds.has(d.id) ? 0.92 : 0.08;
  });
}

function renderNodeDetails(node, edgeData) {
  if (node.kind === "transaction") {
    setDetailPanel(
      [
        "Transaction Node",
        `${node.label || "-"}`,
        `Date: ${formatDate(node.date)}`,
        `Amount: ${formatAmount(node.amount)}`,
        `Type: ${node.tx_type || "unknown"}`,
      ].join("\n"),
    );
    return;
  }

  const nodeEdges = edgeData.filter(
    (edge) => sourceId(edge) === node.id || targetId(edge) === node.id,
  );

  const topEdges = nodeEdges
    .filter((edge) => edge.edge_type === "keyword_category")
    .slice()
    .sort((a, b) => b.weight - a.weight)
    .slice(0, 4)
    .map((edge) => `${edge.keyword} -> ${edge.category_label} (${edge.weight.toFixed(2)})`);

  const txCount = nodeEdges.filter((edge) => edge.edge_type === "transaction_keyword").length;

  setDetailPanel(
    [
      node.label,
      `${node.kind.toUpperCase()} NODE`,
      `Connections: ${nodeEdges.length}`,
      txCount > 0 ? `Transactions linked: ${txCount}` : "",
      "",
      topEdges.length ? topEdges.join("\n") : "No category connections",
    ]
      .filter(Boolean)
      .join("\n"),
  );
}

function renderEdgeDetails(edge) {
  if (edge.edge_type === "transaction_keyword") {
    setDetailPanel(
      [
        "Transaction -> Merchant Keyword",
        `Keyword: ${edge.keyword}`,
        `Transaction ID: ${edge.transaction_id}`,
        `Weight: ${edge.weight.toFixed(2)}`,
      ].join("\n"),
    );
    return;
  }

  const reasonRollup =
    (edge.reasons || [])
      .map((item) => `- (${item.count}) ${item.text}`)
      .join("\n") || "- No explicit reason captured.";

  setDetailPanel(
    [
      `${edge.keyword} -> ${edge.category_label}`,
      `Weight: ${edge.weight.toFixed(2)}`,
      `Confidence: ${edge.avg_confidence.toFixed(2)}`,
      `Verified: ${(edge.verified_ratio * 100).toFixed(0)}%`,
      "",
      "Reasons:",
      reasonRollup,
    ].join("\n"),
  );
}

function renderGraph(graph) {
  const width = svg.node().clientWidth || 1200;
  const height = svg.node().clientHeight || 760;
  svg.selectAll("*").remove();

  const nodeData = graph.nodes.map((item) => ({ ...item }));
  const edgeData = graph.edges.map((item) => ({ ...item }));

  state.focusNodeId = null;
  state.focusEdgeId = null;
  state.tagNodeId = null;

  if (!nodeData.length || !edgeData.length) {
    setDetailPanel("No graph edges found. Import or review transactions to build memory links.");
    return;
  }

  const defs = svg.append("defs");
  const noise = defs
    .append("filter")
    .attr("id", "lineSoften")
    .attr("x", "-20%")
    .attr("y", "-20%")
    .attr("width", "140%")
    .attr("height", "140%");
  noise.append("feGaussianBlur").attr("in", "SourceGraphic").attr("stdDeviation", 0.2);

  const viewport = svg.append("g").attr("class", "viewport");

  const zoomBehavior = d3
    .zoom()
    .scaleExtent([0.25, 4.4])
    .on("zoom", (event) => {
      viewport.attr("transform", event.transform);
      updateZoomIndicator(event.transform);
    });
  state.zoomBehavior = zoomBehavior;
  svg.call(zoomBehavior).on("dblclick.zoom", null);
  updateZoomIndicator(d3.zoomIdentity);

  const [minWeight, maxWeight] = d3.extent(edgeData, (d) => d.weight);
  const strokeScale = d3
    .scaleLinear()
    .domain([minWeight || 0.1, maxWeight || 1])
    .range([0.75, 3.8]);

  const link = viewport
    .append("g")
    .attr("class", "links")
    .selectAll("line")
    .data(edgeData, (d) => d.id)
    .join("line")
    .attr("stroke-linecap", "round")
    .attr("filter", "url(#lineSoften)");

  const edgeLabel = viewport
    .append("g")
    .selectAll("text")
    .data(edgeData, (d) => d.id)
    .join("text")
    .attr("class", "graph-edge-label")
    .text((d) => edgeReasonLabel(d));

  const nodeGroup = viewport
    .append("g")
    .selectAll("g")
    .data(nodeData, (d) => d.id)
    .join("g")
    .attr("class", "graph-node");

  const nodeRing = nodeGroup
    .append("circle")
    .attr("class", "node-ring")
    .attr("r", (d) => nodeRadius(d) + (d.kind === "transaction" ? 0.85 : 2.0))
    .attr("fill", "#f9f9fa");

  const nodeCore = nodeGroup
    .append("circle")
    .attr("class", "node-core")
    .attr("r", (d) => Math.max(1.8, nodeRadius(d) - (d.kind === "transaction" ? 0.2 : 2.8)));

  const nodeLabel = viewport
    .append("g")
    .selectAll("text")
    .data(nodeData, (d) => d.id)
    .join("text")
    .attr("class", "graph-node-label")
    .text((d) => d.label);

  const floatingTag = viewport
    .append("g")
    .attr("class", "floating-node-tag")
    .style("display", "none");
  const floatingTagRect = floatingTag.append("rect").attr("rx", 3).attr("ry", 3);
  const floatingTagText = floatingTag.append("text");

  function fitTagText(raw) {
    const text = (raw || "").trim().toUpperCase();
    if (text.length <= 34) return text;
    return `${text.slice(0, 31)}...`;
  }

  function updateFloatingTagPosition() {
    if (!state.tagNodeId) {
      floatingTag.style("display", "none");
      return;
    }

    const node = nodeData.find((row) => row.id === state.tagNodeId);
    if (!node || !Number.isFinite(node.x) || !Number.isFinite(node.y)) {
      floatingTag.style("display", "none");
      return;
    }

    const label = fitTagText(node.label);
    floatingTagText.text(label);
    const bbox = floatingTagText.node().getBBox();
    const horizontalPad = 8;
    const verticalPad = 4;
    const width = bbox.width + horizontalPad * 2;
    const height = bbox.height + verticalPad * 2;
    const x = node.x - width / 2;
    const y = node.y + nodeRadius(node) + 14;

    floatingTagRect
      .attr("x", x)
      .attr("y", y)
      .attr("width", width)
      .attr("height", height);

    floatingTagText.attr("x", x + horizontalPad).attr("y", y + height - verticalPad - 1);
    floatingTag.style("display", null);
  }

  const simulation = d3
    .forceSimulation(nodeData)
    .force(
      "link",
      d3
        .forceLink(edgeData)
        .id((d) => d.id)
        .distance((d) => {
          if (d.edge_type === "transaction_keyword") return 34;
          return Math.max(52, 118 - d.weight * 3.0);
        })
        .strength((d) => (d.edge_type === "transaction_keyword" ? 0.38 : 0.44)),
    )
    .force(
      "charge",
      d3.forceManyBody().strength((d) => (d.kind === "transaction" ? -56 : -340)),
    )
    .force("collide", d3.forceCollide().radius((d) => nodeRadius(d) + 10))
    .force("center", d3.forceCenter(width / 2, height / 2))
    .alpha(1)
    .alphaDecay(0.03);

  function dragStarted(event) {
    if (!event.active) simulation.alphaTarget(0.22).restart();
    event.subject.fx = event.subject.x;
    event.subject.fy = event.subject.y;
  }

  function dragged(event) {
    event.subject.fx = event.x;
    event.subject.fy = event.y;
  }

  function dragEnded(event) {
    if (!event.active) simulation.alphaTarget(0);
    event.subject.fx = null;
    event.subject.fy = null;
  }

  nodeGroup.call(d3.drag().on("start", dragStarted).on("drag", dragged).on("end", dragEnded));

  nodeGroup
    .on("mouseenter", (_, node) => {
      state.focusNodeId = node.id;
      state.focusEdgeId = null;
      state.tagNodeId = node.id;
      applyVisualState();
      renderNodeDetails(node, edgeData);
      updateFloatingTagPosition();
    })
    .on("mouseleave", () => {
      state.focusNodeId = null;
      state.tagNodeId = null;
      applyVisualState();
      setDefaultDetail();
      updateFloatingTagPosition();
    });

  link
    .on("mouseenter", (_, edge) => {
      state.focusNodeId = null;
      state.focusEdgeId = edge.id;
      state.tagNodeId = null;
      applyVisualState();
      renderEdgeDetails(edge);
      updateFloatingTagPosition();
    })
    .on("mouseleave", () => {
      state.focusEdgeId = null;
      applyVisualState();
      setDefaultDetail();
      updateFloatingTagPosition();
    });

  simulation.on("tick", () => {
    link
      .attr("x1", (d) => d.source.x)
      .attr("y1", (d) => d.source.y)
      .attr("x2", (d) => d.target.x)
      .attr("y2", (d) => d.target.y);

    edgeLabel
      .attr("x", (d) => (d.source.x + d.target.x) / 2)
      .attr("y", (d) => (d.source.y + d.target.y) / 2 - 6);

    nodeGroup.attr("transform", (d) => `translate(${d.x},${d.y})`);

    nodeLabel
      .attr("x", (d) => d.x + nodeRadius(d) + 6)
      .attr("y", (d) => d.y + 4);

    updateFloatingTagPosition();
  });

  state.selections = {
    nodeData,
    edgeData,
    nodeGroup,
    nodeRing,
    nodeCore,
    nodeLabel,
    link,
    edgeLabel,
    strokeScale,
  };

  applyVisualState();
  setDefaultDetail();
  updateFloatingTagPosition();
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

searchInput.addEventListener("input", () => {
  state.searchTerm = searchInput.value || "";
  applyVisualState();
});

if (edgeTextToggle) {
  edgeTextToggle.addEventListener("change", () => {
    state.showEdgeText = edgeTextToggle.checked;
    applyVisualState();
  });
}

if (nodeTextToggle) {
  nodeTextToggle.addEventListener("change", () => {
    state.showNodeText = nodeTextToggle.checked;
    applyVisualState();
  });
}

if (connectedNodeSizeRange) {
  connectedNodeSizeRange.addEventListener("input", () => {
    state.connectedNodeScale = Number(connectedNodeSizeRange.value) / 100;
    syncConnectedNodeScaleLabel();
    if (state.graph) renderGraph(state.graph);
  });
}

if (drawerToggleBtn) {
  drawerToggleBtn.addEventListener("click", () => {
    setDrawerOpen(true);
  });
}

if (drawerCloseBtn) {
  drawerCloseBtn.addEventListener("click", () => {
    setDrawerOpen(false);
  });
}

if (zoomInBtn) {
  zoomInBtn.addEventListener("click", () => {
    if (!state.zoomBehavior) return;
    svg.transition().duration(140).call(state.zoomBehavior.scaleBy, 1.2);
  });
}

if (zoomOutBtn) {
  zoomOutBtn.addEventListener("click", () => {
    if (!state.zoomBehavior) return;
    svg.transition().duration(140).call(state.zoomBehavior.scaleBy, 0.84);
  });
}

if (zoomResetBtn) {
  zoomResetBtn.addEventListener("click", () => {
    if (!state.zoomBehavior) return;
    svg.transition().duration(180).call(state.zoomBehavior.transform, d3.zoomIdentity);
  });
}

window.addEventListener("resize", () => {
  if (state.graph) renderGraph(state.graph);
});

if (edgeTextToggle) edgeTextToggle.checked = state.showEdgeText;
if (nodeTextToggle) nodeTextToggle.checked = state.showNodeText;
if (connectedNodeSizeRange) connectedNodeSizeRange.value = String(
  Math.round(state.connectedNodeScale * 100),
);
syncConnectedNodeScaleLabel();
setDrawerOpen(true);
loadGraph();
