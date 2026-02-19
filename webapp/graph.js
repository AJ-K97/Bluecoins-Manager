const state = {
  graph: null,
  selections: null,
  searchTerm: "",
  focusNodeId: null,
  focusEdgeId: null,
  pinnedNodeId: null,
  tagNodeId: null,
  zoomBehavior: null,
  showEdgeText: false,
  showNodeText: false,
  showInitialMissLinks: true,
  connectedNodeScale: 0.78,
  drawerOpen: true,
  qualityDrawerOpen: false,
  insightsDrawerOpen: false,
  insightsData: null,
  selectedInsightCaseId: null,
  timelinePoints: [],
  timelineIndex: 0,
  isTimelinePlaying: false,
  timelineTimer: null,
  lastVisibleNodeIds: new Set(),
  lastVisibleEdgeIds: new Set(),
};

const svg = d3.select("#graphSvg");
const statsPill = document.getElementById("statsPill");
const detailBody = document.getElementById("detailBody");
const detailPanel = document.getElementById("detailPanel");
const qualityPanel = document.getElementById("qualityPanel");
const insightsPanel = document.getElementById("insightsPanel");

const searchInput = document.getElementById("searchInput");
const minWeightInput = document.getElementById("minWeightInput");
const limitInput = document.getElementById("limitInput");
const verifiedOnlyInput = document.getElementById("verifiedOnlyInput");
const refreshBtn = document.getElementById("refreshBtn");

const edgeTextToggle = document.getElementById("edgeTextToggle");
const nodeTextToggle = document.getElementById("nodeTextToggle");
const llmMissToggle = document.getElementById("llmMissToggle");
const connectedNodeSizeRange = document.getElementById("connectedNodeSizeRange");
const connectedNodeSizeValue = document.getElementById("connectedNodeSizeValue");
const drawerToggleBtn = document.getElementById("drawerToggleBtn");
const drawerCloseBtn = document.getElementById("drawerCloseBtn");
const qualityDrawerToggleBtn = document.getElementById("qualityDrawerToggleBtn");
const qualityCloseBtn = document.getElementById("qualityCloseBtn");
const insightsDrawerToggleBtn = document.getElementById("insightsDrawerToggleBtn");
const insightsCloseBtn = document.getElementById("insightsCloseBtn");

const zoomInBtn = document.getElementById("zoomInBtn");
const zoomOutBtn = document.getElementById("zoomOutBtn");
const zoomResetBtn = document.getElementById("zoomResetBtn");

const timelinePlayBtn = document.getElementById("timelinePlayBtn");
const timelineSlider = document.getElementById("timelineSlider");
const timelineValue = document.getElementById("timelineValue");
const qualityRefreshBtn = document.getElementById("qualityRefreshBtn");
const qualitySummary = document.getElementById("qualitySummary");
const qualityCategoryTable = document.getElementById("qualityCategoryTable");
const qualityConfusion = document.getElementById("qualityConfusion");
const qualityCalibration = document.getElementById("qualityCalibration");
const qualityReplay = document.getElementById("qualityReplay");
const insightsRefreshBtn = document.getElementById("insightsRefreshBtn");
const insightsSummary = document.getElementById("insightsSummary");
const insightsCaseSelect = document.getElementById("insightsCaseSelect");
const insightsCaseBody = document.getElementById("insightsCaseBody");
const insightsRiskTable = document.getElementById("insightsRiskTable");
const insightsStabilityTable = document.getElementById("insightsStabilityTable");

function sourceId(edge) {
  return typeof edge.source === "object" ? edge.source.id : edge.source;
}

function targetId(edge) {
  return typeof edge.target === "object" ? edge.target.id : edge.target;
}

function edgeReasonLabel(edge) {
  if (edge.edge_type === "llm_initial_category") {
    const strength = Math.round((Number(edge.decay_strength || 0) || 0) * 100);
    return `Initial LLM guess (${strength}%)`;
  }
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

function formatPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function shortCategoryLabel(rawLabel) {
  const label = String(rawLabel || "").trim();
  if (!label) return "Unknown";
  const noType = label.replace(/\s*\[[^\]]+\]\s*$/, "");
  const parts = noType.split(">");
  const compact = (parts[parts.length - 1] || noType).trim();
  if (compact.length <= 18) return compact;
  return `${compact.slice(0, 15)}...`;
}

function timelineMsFromDate(value) {
  if (!value) return null;
  const raw = String(value).trim();
  if (!raw) return null;
  const normalized = /^\d{4}-\d{2}-\d{2}$/.test(raw) ? `${raw}T00:00:00Z` : raw;
  const ms = Date.parse(normalized);
  if (!Number.isFinite(ms)) return null;
  return ms;
}

function timelinePointLabel(ms) {
  if (!Number.isFinite(ms)) return "All time";
  return new Date(ms).toISOString().slice(0, 10);
}

function timelineMsForEdge(edge) {
  if (edge.edge_type === "transaction_keyword") {
    return timelineMsFromDate(edge.transaction_date);
  }
  return timelineMsFromDate(edge.first_seen_date || edge.last_seen_date);
}

function timelineMsForNode(node) {
  return timelineMsFromDate(node.first_seen_date || node.date || node.last_seen_date);
}

function edgeKeyword(edge) {
  if (edge.keyword) return String(edge.keyword);
  const sid = sourceId(edge);
  if (typeof sid === "string" && sid.startsWith("keyword::")) {
    return sid.slice("keyword::".length);
  }
  return "";
}

function nodeRadius(node) {
  if (node.kind === "transaction") {
    return 3.5;
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
      "Click a node to lock focus and zoom. Click blank canvas to clear focus.",
      "",
      "Merchant nodes connect to categories.",
      "Small satellite nodes are transactions linked by keyword.",
      "Subtle red links show initial LLM category guesses that were later corrected.",
    ].join("\n"),
  );
}

function updateStats(stats) {
  statsPill.textContent =
    `Rows ${stats.rows_scanned} | Nodes ${stats.total_nodes} | ` +
    `Edges ${stats.total_edges_after_limit} | Time ${stats.timeline_points || 0} | ` +
    `Initial misses ${stats.initial_miss_edges || 0}`;
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

function setQualityDrawerOpen(isOpen) {
  state.qualityDrawerOpen = Boolean(isOpen);
  if (!qualityPanel || !qualityDrawerToggleBtn) return;
  qualityPanel.classList.toggle("collapsed", !state.qualityDrawerOpen);
  qualityDrawerToggleBtn.classList.toggle("hidden", state.qualityDrawerOpen);
}

function setInsightsDrawerOpen(isOpen) {
  state.insightsDrawerOpen = Boolean(isOpen);
  if (!insightsPanel || !insightsDrawerToggleBtn) return;
  insightsPanel.classList.toggle("collapsed", !state.insightsDrawerOpen);
  insightsDrawerToggleBtn.classList.toggle("hidden", state.insightsDrawerOpen);
}

async function fetchJsonOrThrow(url, label) {
  const response = await fetch(url);
  const rawText = await response.text();
  let payload = null;
  try {
    payload = JSON.parse(rawText);
  } catch (_error) {
    const preview = rawText.replace(/\s+/g, " ").trim().slice(0, 140);
    const isHtml = /^<!doctype|^<html/i.test(rawText.trim());
    const hint = isHtml
      ? "Received HTML instead of JSON. Restart graph-web to load the latest API routes."
      : preview || "Empty response.";
    throw new Error(`${label} returned non-JSON (${response.status}). ${hint}`);
  }
  if (!response.ok) {
    throw new Error(payload?.error || `${label} request failed (${response.status})`);
  }
  return payload;
}

function stopTimelinePlayback() {
  if (state.timelineTimer !== null) {
    window.clearInterval(state.timelineTimer);
    state.timelineTimer = null;
  }
  state.isTimelinePlaying = false;
  if (timelinePlayBtn) {
    timelinePlayBtn.textContent = "Play";
    timelinePlayBtn.classList.remove("active");
  }
}

function getTimelineCutoffMs() {
  if (!state.timelinePoints.length) return null;
  const idx = Math.max(0, Math.min(state.timelineIndex, state.timelinePoints.length - 1));
  return state.timelinePoints[idx];
}

function updateTimelineLabel() {
  if (!timelineValue) return;
  const cutoff = getTimelineCutoffMs();
  if (cutoff === null) {
    timelineValue.textContent = "All time";
    timelineValue.classList.add("disabled");
    return;
  }

  timelineValue.classList.remove("disabled");
  timelineValue.textContent = timelinePointLabel(cutoff);
}

function setTimelineIndex(nextIndex, options = {}) {
  const shouldApply = options.apply !== false;
  if (!state.timelinePoints.length) {
    state.timelineIndex = 0;
    updateTimelineLabel();
    if (timelineSlider) timelineSlider.value = "0";
    if (shouldApply) applyVisualState({ animateTimeline: true });
    return;
  }

  const upper = state.timelinePoints.length - 1;
  const clamped = Math.max(0, Math.min(upper, Number(nextIndex) || 0));
  state.timelineIndex = clamped;
  if (timelineSlider) timelineSlider.value = String(clamped);
  updateTimelineLabel();
  if (shouldApply) applyVisualState({ animateTimeline: true });
}

function setupTimeline(graph, nodeData, edgeData) {
  const previousCutoff = getTimelineCutoffMs();
  stopTimelinePlayback();

  const points = new Set();
  (graph.timeline?.points || []).forEach((item) => {
    const ms = timelineMsFromDate(item);
    if (ms !== null) points.add(ms);
  });
  nodeData.forEach((node) => {
    if (Number.isFinite(node.timeline_ms)) points.add(node.timeline_ms);
  });
  edgeData.forEach((edge) => {
    if (Number.isFinite(edge.timeline_ms)) points.add(edge.timeline_ms);
  });

  state.timelinePoints = Array.from(points).sort((a, b) => a - b);

  if (!timelineSlider || !timelinePlayBtn) {
    updateTimelineLabel();
    return;
  }

  if (!state.timelinePoints.length) {
    timelineSlider.min = "0";
    timelineSlider.max = "0";
    timelineSlider.step = "1";
    timelineSlider.value = "0";
    timelineSlider.disabled = true;
    timelinePlayBtn.disabled = true;
    timelinePlayBtn.classList.remove("active");
    state.timelineIndex = 0;
    updateTimelineLabel();
    return;
  }

  timelineSlider.disabled = false;
  timelinePlayBtn.disabled = state.timelinePoints.length <= 1;
  timelineSlider.min = "0";
  timelineSlider.max = String(state.timelinePoints.length - 1);
  timelineSlider.step = "1";

  let nextIndex = state.timelinePoints.length - 1;
  if (previousCutoff !== null) {
    const closest = state.timelinePoints.filter((ms) => ms <= previousCutoff).pop();
    if (closest !== undefined) {
      nextIndex = state.timelinePoints.indexOf(closest);
    }
  }

  setTimelineIndex(nextIndex, { apply: false });
}

function runNodePopAnimation(nodeIds) {
  const selections = state.selections;
  if (!selections || !nodeIds || nodeIds.size === 0) return;

  const idSet = nodeIds instanceof Set ? nodeIds : new Set(nodeIds);
  const { nodeRing, nodeCore } = selections;
  const ringTargetRadius = (d) => nodeRadius(d) + (d.kind === "transaction" ? 0.95 : 2.0);
  const coreTargetRadius = (d) => Math.max(2.1, nodeRadius(d) - (d.kind === "transaction" ? 0.05 : 2.8));

  nodeRing
    .filter((d) => idSet.has(d.id))
    .interrupt()
    .attr("r", (d) => ringTargetRadius(d) * 0.68)
    .transition()
    .duration(170)
    .ease(d3.easeCubicOut)
    .attr("r", (d) => ringTargetRadius(d) * 1.08)
    .transition()
    .duration(130)
    .ease(d3.easeCubicInOut)
    .attr("r", ringTargetRadius);

  nodeCore
    .filter((d) => idSet.has(d.id))
    .interrupt()
    .attr("r", (d) => coreTargetRadius(d) * 0.62)
    .transition()
    .duration(170)
    .ease(d3.easeCubicOut)
    .attr("r", (d) => coreTargetRadius(d) * 1.1)
    .transition()
    .duration(130)
    .ease(d3.easeCubicInOut)
    .attr("r", coreTargetRadius);
}

function stepTimelineForward() {
  if (!state.timelinePoints.length) {
    stopTimelinePlayback();
    return;
  }
  const atEnd = state.timelineIndex >= state.timelinePoints.length - 1;
  if (atEnd) {
    stopTimelinePlayback();
    return;
  }
  setTimelineIndex(state.timelineIndex + 1);
}

function toggleTimelinePlayback() {
  if (state.isTimelinePlaying) {
    stopTimelinePlayback();
    return;
  }

  if (state.timelinePoints.length <= 1) return;
  if (state.timelineIndex >= state.timelinePoints.length - 1) {
    setTimelineIndex(0);
  }

  state.isTimelinePlaying = true;
  if (timelinePlayBtn) {
    timelinePlayBtn.textContent = "Pause";
    timelinePlayBtn.classList.add("active");
  }

  state.timelineTimer = window.setInterval(() => {
    stepTimelineForward();
  }, 900);
}

function collectVisibilitySets() {
  const selections = state.selections;
  const visibleNodeIds = new Set();
  const visibleEdgeIds = new Set();
  if (!selections) {
    return { visibleNodeIds, visibleEdgeIds, hasTimeline: false };
  }

  const cutoff = getTimelineCutoffMs();
  const hasTimeline = cutoff !== null;
  const edgesInWindow = selections.edgeData.filter((edge) => {
    return !hasTimeline || edge.timeline_ms === null || edge.timeline_ms <= cutoff;
  });
  const keywordsWithVisibleTransactions = new Set();

  edgesInWindow.forEach((edge) => {
    if (edge.edge_type !== "transaction_keyword") return;
    visibleEdgeIds.add(edge.id);
    visibleNodeIds.add(sourceId(edge));
    visibleNodeIds.add(targetId(edge));
    const keyword = edgeKeyword(edge);
    if (keyword) keywordsWithVisibleTransactions.add(keyword);
  });

  edgesInWindow.forEach((edge) => {
    if (edge.edge_type !== "keyword_category" && edge.edge_type !== "llm_initial_category") return;
    if (edge.edge_type === "llm_initial_category" && !state.showInitialMissLinks) return;
    const keyword = edgeKeyword(edge);
    if (keyword && !keywordsWithVisibleTransactions.has(keyword)) return;
    visibleEdgeIds.add(edge.id);
    visibleNodeIds.add(sourceId(edge));
    visibleNodeIds.add(targetId(edge));
  });

  selections.nodeData.forEach((node) => {
    if (visibleNodeIds.has(node.id)) return;
    const nodeVisibleByDate = !hasTimeline || node.timeline_ms === null || node.timeline_ms <= cutoff;
    if (node.kind === "transaction" && nodeVisibleByDate) {
      visibleNodeIds.add(node.id);
    }
  });

  return { visibleNodeIds, visibleEdgeIds, hasTimeline };
}

function collectActiveSets(visibility) {
  const selections = state.selections;
  const activeNodeIds = new Set();
  const activeEdgeIds = new Set();
  if (!selections) {
    return { activeNodeIds, activeEdgeIds, filtered: false };
  }

  const term = state.searchTerm.trim().toLowerCase();
  if (term) {
    selections.nodeData.forEach((node) => {
      if (!visibility.visibleNodeIds.has(node.id)) return;
      const haystack = `${node.label} ${node.kind} ${node.description || ""}`.toLowerCase();
      if (haystack.includes(term)) activeNodeIds.add(node.id);
    });

    selections.edgeData.forEach((edge) => {
      if (!visibility.visibleEdgeIds.has(edge.id)) return;
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

  if (state.focusNodeId && visibility.visibleNodeIds.has(state.focusNodeId)) {
    activeNodeIds.add(state.focusNodeId);
    selections.edgeData.forEach((edge) => {
      if (!visibility.visibleEdgeIds.has(edge.id)) return;
      const sid = sourceId(edge);
      const tid = targetId(edge);
      if (sid === state.focusNodeId || tid === state.focusNodeId) {
        activeEdgeIds.add(edge.id);
        activeNodeIds.add(sid);
        activeNodeIds.add(tid);
      }
    });
  }

  if (state.focusEdgeId && visibility.visibleEdgeIds.has(state.focusEdgeId)) {
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
    filtered: term.length > 0 || state.focusNodeId !== null || state.focusEdgeId !== null,
  };
}

function applyVisualState(options = {}) {
  const selections = state.selections;
  if (!selections) return;

  const { nodeGroup, nodeRing, nodeCore, nodeLabel, link, edgeLabel, strokeScale } = selections;
  const visibility = collectVisibilitySets();
  const shouldAnimateTimeline = Boolean(options.animateTimeline);
  const newlyVisibleNodeIds = new Set();
  const newlyLinkedNodeIds = new Set();

  if (shouldAnimateTimeline) {
    visibility.visibleNodeIds.forEach((nodeId) => {
      if (!state.lastVisibleNodeIds.has(nodeId)) {
        newlyVisibleNodeIds.add(nodeId);
      }
    });
    visibility.visibleEdgeIds.forEach((edgeId) => {
      if (state.lastVisibleEdgeIds.has(edgeId)) return;
      const edge = selections.edgeById?.get(edgeId);
      if (!edge) return;
      newlyLinkedNodeIds.add(sourceId(edge));
      newlyLinkedNodeIds.add(targetId(edge));
    });
  }

  if (state.pinnedNodeId && !visibility.visibleNodeIds.has(state.pinnedNodeId)) {
    state.pinnedNodeId = null;
  }
  if (state.focusNodeId && !visibility.visibleNodeIds.has(state.focusNodeId)) {
    state.focusNodeId = null;
    state.tagNodeId = null;
  }
  if (state.focusEdgeId && !visibility.visibleEdgeIds.has(state.focusEdgeId)) {
    state.focusEdgeId = null;
  }

  const { activeNodeIds, activeEdgeIds, filtered } = collectActiveSets(visibility);

  nodeGroup
    .style("display", (d) => (visibility.visibleNodeIds.has(d.id) ? null : "none"))
    .style("pointer-events", (d) => (visibility.visibleNodeIds.has(d.id) ? null : "none"))
    .style("opacity", (d) => {
      if (!visibility.visibleNodeIds.has(d.id)) return 0;
      if (!filtered) return d.kind === "transaction" ? 0.84 : 0.98;
      if (activeNodeIds.has(d.id)) return 1;
      return d.kind === "transaction" ? 0.16 : 0.2;
    });

  nodeRing
    .attr("stroke", (d) => {
      if (d.id === state.focusNodeId) return "#26363f";
      if (d.kind === "keyword") return filtered && activeNodeIds.has(d.id) ? "#3f6a7f" : "#6f8f9f";
      if (d.kind === "transaction") return "#8fa7b4";
      return filtered && activeNodeIds.has(d.id) ? "#6f7c86" : "#98a3ab";
    })
    .attr("stroke-width", (d) => {
      if (d.kind === "transaction") return 1.05;
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
    if (filtered && activeNodeIds.has(d.id)) return "#8ca8b7";
    return "#9fb8c4";
  });

  link
    .style("display", (d) => (visibility.visibleEdgeIds.has(d.id) ? null : "none"))
    .style("pointer-events", (d) => (visibility.visibleEdgeIds.has(d.id) ? null : "none"))
    .attr("stroke", (d) => {
      if (d.id === state.focusEdgeId) return "#5f8ea2";
      if (d.edge_type === "llm_initial_category") {
        return filtered && activeEdgeIds.has(d.id) ? "#b74a56" : "#cb727d";
      }
      if (d.edge_type === "transaction_keyword") {
        return filtered && activeEdgeIds.has(d.id) ? "#8ea8b8" : "#bcc9d1";
      }
      return filtered && activeEdgeIds.has(d.id) ? "#8ca8b6" : "#c9d0d5";
    })
    .attr("stroke-width", (d) => {
      const base = strokeScale(d.weight);
      if (d.edge_type === "llm_initial_category") {
        const missBase = Math.max(1.05, base * 1.08);
        return filtered && activeEdgeIds.has(d.id) ? missBase * 1.2 : missBase;
      }
      if (d.edge_type === "transaction_keyword") {
        const txBase = Math.max(0.82, base * 0.92);
        return filtered && activeEdgeIds.has(d.id) ? txBase * 1.2 : txBase;
      }
      return filtered && activeEdgeIds.has(d.id) ? base * 1.16 : base;
    })
    .style("opacity", (d) => {
      if (!visibility.visibleEdgeIds.has(d.id)) return 0;
      if (!filtered) {
        if (d.edge_type === "transaction_keyword") return 0.5;
        if (d.edge_type === "llm_initial_category") return 0.62;
        return 0.56;
      }
      if (activeEdgeIds.has(d.id)) return 0.95;
      if (d.edge_type === "transaction_keyword") return 0.22;
      if (d.edge_type === "llm_initial_category") return 0.32;
      return 0.12;
    });

  edgeLabel
    .style("display", (d) => {
      if (!state.showEdgeText || d.edge_type === "transaction_keyword") return "none";
      return visibility.visibleEdgeIds.has(d.id) ? null : "none";
    })
    .style("opacity", (d) => {
      if (!state.showEdgeText || !visibility.visibleEdgeIds.has(d.id)) return 0;
      if (!filtered) return 0.4;
      return activeEdgeIds.has(d.id) ? 0.82 : 0.03;
    });

  nodeLabel
    .style("display", (d) => {
      if (!state.showNodeText || d.kind === "transaction") return "none";
      return visibility.visibleNodeIds.has(d.id) ? null : "none";
    })
    .style("opacity", (d) => {
      if (!state.showNodeText || d.kind === "transaction" || !visibility.visibleNodeIds.has(d.id)) return 0;
      if (!filtered) return 0.72;
      return activeNodeIds.has(d.id) ? 0.92 : 0.08;
    });

  if (shouldAnimateTimeline) {
    const nodesToPop = new Set([...newlyVisibleNodeIds, ...newlyLinkedNodeIds]);
    runNodePopAnimation(nodesToPop);
  }

  state.lastVisibleNodeIds = new Set(visibility.visibleNodeIds);
  state.lastVisibleEdgeIds = new Set(visibility.visibleEdgeIds);
}

function renderNodeDetails(node, edgeData, visibleEdgeIds = null) {
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

  const nodeEdges = edgeData.filter((edge) => {
    if (visibleEdgeIds && !visibleEdgeIds.has(edge.id)) return false;
    return sourceId(edge) === node.id || targetId(edge) === node.id;
  });

  const topEdges = nodeEdges
    .filter((edge) => edge.edge_type === "keyword_category")
    .slice()
    .sort((a, b) => b.weight - a.weight)
    .slice(0, 4)
    .map((edge) => `${edge.keyword} -> ${edge.category_label} (${edge.weight.toFixed(2)})`);
  const initialMissEdges = nodeEdges
    .filter((edge) => edge.edge_type === "llm_initial_category")
    .slice()
    .sort((a, b) => b.weight - a.weight)
    .slice(0, 3)
    .map((edge) => `${edge.keyword} -> ${edge.category_label} [initial miss x${edge.miss_count}]`);

  const txCount = nodeEdges.filter((edge) => edge.edge_type === "transaction_keyword").length;

  setDetailPanel(
    [
      node.label,
      `${node.kind.toUpperCase()} NODE`,
      `Connections: ${nodeEdges.length}`,
      txCount > 0 ? `Transactions linked: ${txCount}` : "",
      initialMissEdges.length > 0 ? `Initial LLM miss links: ${initialMissEdges.length}` : "",
      "",
      topEdges.length ? topEdges.join("\n") : "No category connections in this time window",
      initialMissEdges.length ? "Initial LLM links:" : "",
      initialMissEdges.length ? initialMissEdges.join("\n") : "",
    ]
      .filter(Boolean)
      .join("\n"),
  );
}

function renderEdgeDetails(edge) {
  if (edge.edge_type === "llm_initial_category") {
    setDetailPanel(
      [
        "Initial LLM Category Guess",
        `Keyword: ${edge.keyword}`,
        `Suggested category: ${edge.category_label}`,
        `First seen: ${formatDate(edge.first_seen_date)}`,
        `Miss count: ${edge.miss_count || edge.count || 0}`,
        `Corrective decisions: ${edge.correction_count || 0}`,
        `Residual strength: ${Math.round((Number(edge.decay_strength || 0) || 0) * 100)}%`,
      ].join("\n"),
    );
    return;
  }

  if (edge.edge_type === "transaction_keyword") {
    setDetailPanel(
      [
        "Transaction -> Merchant Keyword",
        `Keyword: ${edge.keyword}`,
        `Transaction ID: ${edge.transaction_id}`,
        `Date: ${formatDate(edge.transaction_date)}`,
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
      `First seen: ${formatDate(edge.first_seen_date)}`,
      `Weight: ${edge.weight.toFixed(2)}`,
      `Confidence: ${edge.avg_confidence.toFixed(2)}`,
      `Verified: ${(edge.verified_ratio * 100).toFixed(0)}%`,
      "",
      "Reasons:",
      reasonRollup,
    ].join("\n"),
  );
}

function focusNodeWithZoom(node) {
  if (!state.zoomBehavior || !state.selections) return;
  if (!Number.isFinite(node?.x) || !Number.isFinite(node?.y)) return;

  const width = state.selections.width;
  const height = state.selections.height;
  const targetScale = node.kind === "transaction" ? 2.8 : 2.2;

  const transform = d3.zoomIdentity
    .translate(width / 2, height / 2)
    .scale(targetScale)
    .translate(-node.x, -node.y);

  svg.transition().duration(320).call(state.zoomBehavior.transform, transform);
}

function createZoomReactiveGrid(defs, width, height) {
  const pattern = defs
    .append("pattern")
    .attr("id", "graphGridPattern")
    .attr("patternUnits", "userSpaceOnUse")
    .attr("width", 34)
    .attr("height", 34)
    .attr("patternTransform", "translate(0,0) scale(1)");

  pattern
    .append("path")
    .attr("d", "M 34 0 L 0 0 0 34")
    .attr("fill", "none")
    .attr("stroke", "rgba(114, 124, 130, 0.22)")
    .attr("stroke-width", 1);

  const gridRect = svg
    .append("rect")
    .attr("x", 0)
    .attr("y", 0)
    .attr("width", width)
    .attr("height", height)
    .attr("fill", "url(#graphGridPattern)")
    .attr("pointer-events", "none")
    .attr("opacity", 0.5);

  function updateGridTransform(transform) {
    if (!pattern) return;
    const x = Number(transform?.x || 0);
    const y = Number(transform?.y || 0);
    const k = Number(transform?.k || 1);
    pattern.attr("patternTransform", `translate(${x},${y}) scale(${k})`);
  }

  return { gridRect, updateGridTransform };
}

function clearQualityPanels(message) {
  if (qualitySummary) qualitySummary.textContent = message;
  if (qualityCategoryTable) qualityCategoryTable.innerHTML = "";
  if (qualityConfusion) qualityConfusion.innerHTML = "";
  if (qualityCalibration) qualityCalibration.innerHTML = "";
  if (qualityReplay) qualityReplay.innerHTML = "";
}

function clearInsightsPanels(message) {
  state.selectedInsightCaseId = null;
  if (insightsSummary) insightsSummary.textContent = message;
  if (insightsCaseSelect) insightsCaseSelect.innerHTML = "";
  if (insightsCaseBody) insightsCaseBody.textContent = "";
  if (insightsRiskTable) insightsRiskTable.innerHTML = "";
  if (insightsStabilityTable) insightsStabilityTable.innerHTML = "";
}

function renderInsightCaseById(insightsPayload, selectedId) {
  if (!insightsCaseBody) return;
  const cases = insightsPayload?.case_inspector || [];
  if (!cases.length) {
    insightsCaseBody.textContent = "No cases available.";
    return;
  }
  const selected = cases.find((item) => String(item.transaction_id) === String(selectedId)) || cases[0];
  if (!selected) {
    insightsCaseBody.textContent = "No case selected.";
    return;
  }
  const topMemory = (selected.signal_snapshot?.top_category_memory || [])
    .slice(0, 3)
    .map((entry) => `${shortCategoryLabel(entry.category_label)} (${formatPercent(entry.ratio)})`)
    .join(", ");
  insightsCaseBody.textContent = [
    `TX: ${selected.transaction_id} | Date: ${selected.date || "-"}`,
    `Keyword: ${selected.keyword || "(none)"}`,
    `Predicted: ${selected.predicted_category}`,
    `Resolved: ${selected.resolved_category}`,
    `Confidence: ${formatPercent(selected.confidence)} | Verified: ${selected.is_verified ? "yes" : "no"} | Correct: ${selected.was_correct === null ? "-" : selected.was_correct ? "yes" : "no"}`,
    `Keyword entropy: ${Number(selected.signal_snapshot?.keyword_entropy || 0).toFixed(3)}`,
    topMemory ? `Memory top categories: ${topMemory}` : "Memory top categories: -",
    "",
    `Reason: ${selected.reason || "-"}`,
  ].join("\n");
}

function renderInsightsReport(insightsPayload) {
  if (!insightsSummary) return;
  const summary = insightsPayload?.summary || {};
  insightsSummary.textContent = [
    `Cases: ${summary.total_cases || 0}`,
    `Risk rows: ${summary.risk_rows || 0}`,
    `Stability rows: ${summary.stability_rows || 0}`,
    `High risk (>=0.6): ${summary.risky_count || 0}`,
    `Unstable keywords: ${summary.unstable_keywords || 0}`,
  ].join(" | ");

  if (insightsCaseSelect) {
    const cases = insightsPayload?.case_inspector || [];
    if (!cases.length) {
      insightsCaseSelect.innerHTML = "";
      if (insightsCaseBody) insightsCaseBody.textContent = "No case data available.";
    } else {
      if (!state.selectedInsightCaseId || !cases.some((item) => String(item.transaction_id) === String(state.selectedInsightCaseId))) {
        state.selectedInsightCaseId = String(cases[0].transaction_id);
      }
      insightsCaseSelect.innerHTML = cases
        .slice(0, 120)
        .map((item) => {
          const selectedFlag = String(item.transaction_id) === String(state.selectedInsightCaseId) ? " selected" : "";
          const desc = item.description || `TX ${item.transaction_id}`;
          const shortDesc = desc.length > 64 ? `${desc.slice(0, 61)}...` : desc;
          return `<option value="${escapeHtml(item.transaction_id)}"${selectedFlag}>#${escapeHtml(
            item.transaction_id,
          )} | ${escapeHtml(item.date || "-")} | ${escapeHtml(shortDesc)}</option>`;
        })
        .join("");
      renderInsightCaseById(insightsPayload, state.selectedInsightCaseId);
    }
  }

  if (insightsRiskTable) {
    const rows = (insightsPayload?.risk || []).slice(0, 25);
    if (!rows.length) {
      insightsRiskTable.innerHTML = `<div class="quality-line"><div class="quality-line-label">No risk rows available.</div></div>`;
    } else {
      const body = rows
        .map(
          (row) => `
          <tr>
            <td title="${escapeHtml(row.description)}">#${escapeHtml(row.transaction_id)}</td>
            <td>${escapeHtml(row.keyword || "(none)")}</td>
            <td class="metric-cell">${formatPercent(row.risk_score)}</td>
            <td class="metric-cell">${formatPercent(row.confidence)}</td>
            <td class="metric-cell">${row.was_correct === null ? "-" : row.was_correct ? "yes" : "no"}</td>
            <td title="${escapeHtml(row.resolved_category)}">${escapeHtml(shortCategoryLabel(row.resolved_category))}</td>
          </tr>`,
        )
        .join("");
      insightsRiskTable.innerHTML = `
        <table class="quality-table">
          <thead>
            <tr>
              <th>TX</th>
              <th>Keyword</th>
              <th>Risk</th>
              <th>Conf</th>
              <th>Correct</th>
              <th>Resolved</th>
            </tr>
          </thead>
          <tbody>${body}</tbody>
        </table>`;
    }
  }

  if (insightsStabilityTable) {
    const rows = (insightsPayload?.stability || []).slice(0, 30);
    if (!rows.length) {
      insightsStabilityTable.innerHTML = `<div class="quality-line"><div class="quality-line-label">No stability rows available.</div></div>`;
    } else {
      const body = rows
        .map(
          (row) => `
          <tr>
            <td>${escapeHtml(row.keyword)}</td>
            <td class="metric-cell">${Number(row.tx_count || 0)}</td>
            <td class="metric-cell">${Number(row.flips || 0)}</td>
            <td class="metric-cell">${formatPercent(row.stability_ratio)}</td>
            <td class="metric-cell">${Number(row.corrections || 0)}</td>
            <td class="metric-cell">${row.transactions_to_stability ?? "-"}</td>
            <td class="metric-cell">${Number(row.keyword_entropy || 0).toFixed(2)}</td>
          </tr>`,
        )
        .join("");
      insightsStabilityTable.innerHTML = `
        <table class="quality-table">
          <thead>
            <tr>
              <th>Keyword</th>
              <th>Tx</th>
              <th>Flips</th>
              <th>Stability</th>
              <th>Corrections</th>
              <th>To stable</th>
              <th>Entropy</th>
            </tr>
          </thead>
          <tbody>${body}</tbody>
        </table>`;
    }
  }
}

function renderQualityReport(qualityPayload, replayPayload) {
  if (!qualitySummary) return;

  const summary = qualityPayload?.summary || {};
  const replayMonths = replayPayload?.months || qualityPayload?.replay || [];
  const bestPeriod = replayPayload?.best_period || null;
  const worstPeriod = replayPayload?.worst_period || null;
  qualitySummary.textContent = [
    `Scored: ${summary.total_scored || 0}`,
    `Accuracy: ${formatPercent(summary.accuracy)}`,
    `Macro F1: ${formatPercent(summary.macro_f1)}`,
    `Categories: ${summary.categories_covered || 0}`,
    bestPeriod ? `Best month: ${bestPeriod.period} (${formatPercent(bestPeriod.accuracy)})` : "",
    worstPeriod ? `Worst month: ${worstPeriod.period} (${formatPercent(worstPeriod.accuracy)})` : "",
  ]
    .filter(Boolean)
    .join(" | ");

  if (qualityCategoryTable) {
    const rows = (qualityPayload?.per_category || []).slice(0, 12);
    if (!rows.length) {
      qualityCategoryTable.innerHTML = `<div class="quality-line"><div class="quality-line-label">No scored category rows yet.</div></div>`;
    } else {
      const body = rows
        .map(
          (row) => `
          <tr>
            <td title="${escapeHtml(row.category_label)}">${escapeHtml(shortCategoryLabel(row.category_label))}</td>
            <td class="metric-cell">${Number(row.support || 0)}</td>
            <td class="metric-cell">${formatPercent(row.precision)}</td>
            <td class="metric-cell">${formatPercent(row.recall)}</td>
            <td class="metric-cell">${formatPercent(row.f1)}</td>
          </tr>`,
        )
        .join("");
      qualityCategoryTable.innerHTML = `
        <table class="quality-table">
          <thead>
            <tr>
              <th>Category</th>
              <th>Support</th>
              <th>Precision</th>
              <th>Recall</th>
              <th>F1</th>
            </tr>
          </thead>
          <tbody>${body}</tbody>
        </table>`;
    }
  }

  if (qualityConfusion) {
    const labels = (qualityPayload?.confusion?.labels || []).slice(0, 8);
    const rows = (qualityPayload?.confusion?.rows || []).slice(0, labels.length);
    if (!labels.length || !rows.length) {
      qualityConfusion.innerHTML = `<div class="quality-line"><div class="quality-line-label">Not enough scored data for confusion matrix.</div></div>`;
    } else {
      const maxCount = Math.max(
        1,
        ...rows.flatMap((row) => (row.counts || []).slice(0, labels.length).map((value) => Number(value || 0))),
      );
      const headerCells = labels
        .map((label) => `<th title="${escapeHtml(label.label)}">${escapeHtml(shortCategoryLabel(label.label))}</th>`)
        .join("");
      const bodyRows = rows
        .map((row) => {
          const cells = (row.counts || [])
            .slice(0, labels.length)
            .map((value) => {
              const count = Number(value || 0);
              const alpha = count > 0 ? 0.08 + (count / maxCount) * 0.52 : 0;
              return `<td class="metric-cell" style="background: rgba(95, 135, 152, ${alpha.toFixed(3)});">${count}</td>`;
            })
            .join("");
          return `
          <tr>
            <td title="${escapeHtml(row.actual_label)}">${escapeHtml(shortCategoryLabel(row.actual_label))}</td>
            ${cells}
          </tr>`;
        })
        .join("");
      qualityConfusion.innerHTML = `
        <table class="quality-table">
          <thead>
            <tr>
              <th>Actual \\ Pred</th>
              ${headerCells}
            </tr>
          </thead>
          <tbody>${bodyRows}</tbody>
        </table>`;
    }
  }

  if (qualityCalibration) {
    const bins = (qualityPayload?.calibration || []).filter((row) => Number(row.count || 0) > 0);
    if (!bins.length) {
      qualityCalibration.innerHTML = `<div class="quality-line"><div class="quality-line-label">No confidence values available for calibration.</div></div>`;
    } else {
      const maxCount = Math.max(1, ...bins.map((row) => Number(row.count || 0)));
      qualityCalibration.innerHTML = bins
        .map((row) => {
          const start = Math.round(Number(row.range_start || 0) * 100);
          const end = Math.round(Number(row.range_end || 0) * 100);
          const width = Math.max(8, Math.round((Number(row.count || 0) / maxCount) * 100));
          return `
          <div class="quality-line">
            <div class="quality-line-label">${start}-${end}% | conf ${formatPercent(row.avg_confidence)} | acc ${formatPercent(row.accuracy)}</div>
            <div class="quality-line-value">n=${Number(row.count || 0)}</div>
          </div>
          <div class="quality-bar"><div class="quality-bar-fill" style="width:${width}%;"></div></div>`;
        })
        .join("");
    }
  }

  if (qualityReplay) {
    const points = replayMonths.slice(-10);
    if (!points.length) {
      qualityReplay.innerHTML = `<div class="quality-line"><div class="quality-line-label">Replay data unavailable.</div></div>`;
    } else {
      qualityReplay.innerHTML = points
        .map((point) => {
          const width = Math.max(6, Math.round((Number(point.accuracy || 0) || 0) * 100));
          return `
          <div class="quality-line">
            <div class="quality-line-label">${escapeHtml(point.period)}</div>
            <div class="quality-line-value">${formatPercent(point.accuracy)} (${point.correct}/${point.count})</div>
          </div>
          <div class="quality-bar"><div class="quality-bar-fill" style="width:${width}%;"></div></div>`;
        })
        .join("");
    }
  }
}

async function loadQuality() {
  if (!qualitySummary) return;
  qualitySummary.textContent = "Loading quality metrics...";
  try {
    const [qualityPayload, replayPayload] = await Promise.all([
      fetchJsonOrThrow("/api/quality?confusion_limit=10&replay_months=18", "Quality API"),
      fetchJsonOrThrow("/api/replay?months=18", "Replay API"),
    ]);
    renderQualityReport(qualityPayload, replayPayload);
  } catch (error) {
    clearQualityPanels(`Could not load model quality data: ${error.message}`);
  }
}

async function loadInsights() {
  if (!insightsSummary) return;
  insightsSummary.textContent = "Loading agent insights...";
  try {
    const payload = await fetchJsonOrThrow(
      "/api/insights?case_limit=100&risk_limit=28&keyword_limit=42",
      "Insights API",
    );
    state.insightsData = payload;
    renderInsightsReport(payload);
  } catch (error) {
    state.insightsData = null;
    clearInsightsPanels(`Could not load insights: ${error.message}`);
  }
}

function renderGraph(graph) {
  const width = svg.node().clientWidth || 1200;
  const height = svg.node().clientHeight || 760;
  svg.selectAll("*").remove();

  const nodeData = graph.nodes.map((item) => ({
    ...item,
    timeline_ms: timelineMsForNode(item),
  }));
  const edgeData = graph.edges.map((item) => ({
    ...item,
    timeline_ms: timelineMsForEdge(item),
  }));

  state.focusNodeId = null;
  state.focusEdgeId = null;
  state.pinnedNodeId = null;
  state.tagNodeId = null;

  if (!nodeData.length || !edgeData.length) {
    setDetailPanel("No graph edges found. Import or review transactions to build memory links.");
    setupTimeline(graph, nodeData, edgeData);
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
  const grid = createZoomReactiveGrid(defs, width, height);

  const viewport = svg.append("g").attr("class", "viewport");

  const zoomBehavior = d3
    .zoom()
    .scaleExtent([0.25, 4.4])
    .on("zoom", (event) => {
      viewport.attr("transform", event.transform);
      if (grid?.updateGridTransform) grid.updateGridTransform(event.transform);
      updateZoomIndicator(event.transform);
    });
  state.zoomBehavior = zoomBehavior;
  svg.call(zoomBehavior).on("dblclick.zoom", null);
  if (grid?.updateGridTransform) grid.updateGridTransform(d3.zoomIdentity);
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
    .attr("r", (d) => nodeRadius(d) + (d.kind === "transaction" ? 0.95 : 2.0))
    .attr("fill", "#f9f9fa");

  const nodeCore = nodeGroup
    .append("circle")
    .attr("class", "node-core")
    .attr("r", (d) => Math.max(2.1, nodeRadius(d) - (d.kind === "transaction" ? 0.05 : 2.8)));

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

    const visibility = collectVisibilitySets();
    if (!visibility.visibleNodeIds.has(node.id)) {
      floatingTag.style("display", "none");
      return;
    }

    const label = fitTagText(node.label);
    floatingTagText.text(label);
    const bbox = floatingTagText.node().getBBox();
    const horizontalPad = 8;
    const verticalPad = 4;
    const tagWidth = bbox.width + horizontalPad * 2;
    const tagHeight = bbox.height + verticalPad * 2;
    const x = node.x - tagWidth / 2;
    const y = node.y + nodeRadius(node) + 14;

    floatingTagRect
      .attr("x", x)
      .attr("y", y)
      .attr("width", tagWidth)
      .attr("height", tagHeight);

    floatingTagText.attr("x", x + horizontalPad).attr("y", y + tagHeight - verticalPad - 1);
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
      if (state.pinnedNodeId && state.pinnedNodeId !== node.id) return;
      state.focusNodeId = node.id;
      state.focusEdgeId = null;
      state.tagNodeId = node.id;
      applyVisualState();
      const visible = collectVisibilitySets();
      renderNodeDetails(node, edgeData, visible.visibleEdgeIds);
      updateFloatingTagPosition();
    })
    .on("mouseleave", (_, node) => {
      if (state.pinnedNodeId === node.id) return;
      if (state.pinnedNodeId !== null) return;
      state.focusNodeId = null;
      state.tagNodeId = null;
      applyVisualState();
      setDefaultDetail();
      updateFloatingTagPosition();
    })
    .on("click", (event, node) => {
      event.stopPropagation();
      state.pinnedNodeId = node.id;
      state.focusNodeId = node.id;
      state.focusEdgeId = null;
      state.tagNodeId = node.id;
      applyVisualState();
      const visible = collectVisibilitySets();
      renderNodeDetails(node, edgeData, visible.visibleEdgeIds);
      updateFloatingTagPosition();
      focusNodeWithZoom(node);
    });

  link
    .on("mouseenter", (_, edge) => {
      if (state.pinnedNodeId) return;
      state.focusNodeId = null;
      state.focusEdgeId = edge.id;
      state.tagNodeId = null;
      applyVisualState();
      renderEdgeDetails(edge);
      updateFloatingTagPosition();
    })
    .on("mouseleave", () => {
      if (state.pinnedNodeId) return;
      state.focusEdgeId = null;
      applyVisualState();
      setDefaultDetail();
      updateFloatingTagPosition();
    });

  svg.on("click", () => {
    if (state.pinnedNodeId === null) return;
    state.pinnedNodeId = null;
    state.focusNodeId = null;
    state.focusEdgeId = null;
    state.tagNodeId = null;
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
    edgeById: new Map(edgeData.map((edge) => [edge.id, edge])),
    width,
    height,
  };

  setupTimeline(graph, nodeData, edgeData);
  applyVisualState();
  setDefaultDetail();
  updateFloatingTagPosition();
}

async function loadGraph() {
  stopTimelinePlayback();
  statsPill.textContent = "Loading graph...";
  setDetailPanel("Loading keyword-category memory links...");
  const query = buildQueryString();

  try {
    const payload = await fetchJsonOrThrow(`/api/graph?${query}`, "Graph API");
    state.graph = payload;
    updateStats(payload.stats || {});
    renderGraph(payload);
    loadQuality();
    loadInsights();
  } catch (error) {
    statsPill.textContent = "Failed to load graph";
    setDetailPanel(`Could not load graph data.\n${error.message}`);
    clearQualityPanels("Graph load failed. Quality metrics unavailable.");
    clearInsightsPanels("Graph load failed. Insights unavailable.");
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

if (llmMissToggle) {
  llmMissToggle.addEventListener("change", () => {
    state.showInitialMissLinks = llmMissToggle.checked;
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

if (timelineSlider) {
  timelineSlider.addEventListener("input", () => {
    stopTimelinePlayback();
    setTimelineIndex(Number(timelineSlider.value || 0));
  });
}

if (timelinePlayBtn) {
  timelinePlayBtn.addEventListener("click", () => {
    toggleTimelinePlayback();
  });
}

if (qualityRefreshBtn) {
  qualityRefreshBtn.addEventListener("click", () => {
    loadQuality();
  });
}

if (insightsRefreshBtn) {
  insightsRefreshBtn.addEventListener("click", () => {
    loadInsights();
  });
}

if (insightsCaseSelect) {
  insightsCaseSelect.addEventListener("change", () => {
    state.selectedInsightCaseId = insightsCaseSelect.value || null;
    renderInsightCaseById(state.insightsData, state.selectedInsightCaseId);
  });
}

if (drawerToggleBtn) {
  drawerToggleBtn.addEventListener("click", () => {
    setDrawerOpen(true);
    setQualityDrawerOpen(false);
    setInsightsDrawerOpen(false);
  });
}

if (drawerCloseBtn) {
  drawerCloseBtn.addEventListener("click", () => {
    setDrawerOpen(false);
  });
}

if (qualityDrawerToggleBtn) {
  qualityDrawerToggleBtn.addEventListener("click", () => {
    setQualityDrawerOpen(true);
    setDrawerOpen(false);
    setInsightsDrawerOpen(false);
  });
}

if (qualityCloseBtn) {
  qualityCloseBtn.addEventListener("click", () => {
    setQualityDrawerOpen(false);
  });
}

if (insightsDrawerToggleBtn) {
  insightsDrawerToggleBtn.addEventListener("click", () => {
    setInsightsDrawerOpen(true);
    setDrawerOpen(false);
    setQualityDrawerOpen(false);
  });
}

if (insightsCloseBtn) {
  insightsCloseBtn.addEventListener("click", () => {
    setInsightsDrawerOpen(false);
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

window.addEventListener("beforeunload", () => {
  stopTimelinePlayback();
});

if (edgeTextToggle) edgeTextToggle.checked = state.showEdgeText;
if (nodeTextToggle) nodeTextToggle.checked = state.showNodeText;
if (llmMissToggle) llmMissToggle.checked = state.showInitialMissLinks;
if (connectedNodeSizeRange) {
  connectedNodeSizeRange.value = String(Math.round(state.connectedNodeScale * 100));
}
if (timelineSlider) {
  timelineSlider.disabled = true;
  timelineSlider.value = "0";
}
if (timelinePlayBtn) timelinePlayBtn.disabled = true;
syncConnectedNodeScaleLabel();
updateTimelineLabel();
setDrawerOpen(true);
setQualityDrawerOpen(false);
setInsightsDrawerOpen(false);
clearInsightsPanels("Loading insights...");
loadGraph();
