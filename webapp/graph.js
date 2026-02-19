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
  nodeDrawerOpen: true,
  drawerOpen: true,
  qualityDrawerOpen: false,
  insightsDrawerOpen: false,
  activeView: "graph",
  insightsData: null,
  selectedInsightCaseId: null,
  timelinePoints: [],
  timelineIndex: 0,
  isTimelinePlaying: false,
  timelineTimer: null,
  lastVisibleNodeIds: new Set(),
  lastVisibleEdgeIds: new Set(),
  currentZoomTransform: null,
  animationFrameId: null,
  timelinePulse: 0,
  interactionPulseByNode: new Map(),
  backgroundFieldLastUpdateMs: 0,
  nodeDetailRows: [],
  nodeDetailPage: 0,
  nodeDetailPageSize: 8,
  sankeyFilters: {
    search: "",
    field: "all",
    outcome: "all",
    verifiedOnly: false,
  },
  sankeyMode: "volume",
  sankeyCategoryLens: "",
  sankeyThresholds: {
    minPathCases: 1,
    topPaths: 80,
  },
  sankeyKeywordGroups: new Map(),
  sankeyPinnedKeyword: null,
  sankeyPathRows: [],
  sankeySelectedPathKey: null,
  sankeyZoom: {
    stage: null,
    label: null,
  },
  breathe: {
    enabled: true,
    globalPulse: true,
    globalPulseIntensity: 0.34,
    globalPulseSpeed: 0.62,
    phaseLag: true,
    edgeShimmer: true,
    edgeShimmerIntensity: 0.3,
    interactionRipple: true,
    interactionRippleStrength: 0.86,
    ambientDrift: true,
    ambientDriftStrength: 0.22,
    confidencePulse: true,
    timelineHeartbeat: true,
    timelineHeartbeatStrength: 0.62,
    backgroundField: true,
    backgroundFieldIntensity: 0.28,
  },
};
const GRAPH_SETTINGS_STORAGE_KEY = "bluecoins.graph.settings.v1";
const MOTION_EASE = d3.easeCubicInOut;

const svg = d3.select("#graphSvg");
const graphWrap = document.querySelector(".graph-wrap");
const statsPill = document.getElementById("statsPill");
const graphViewTabBtn = document.getElementById("graphViewTabBtn");
const sankeyViewTabBtn = document.getElementById("sankeyViewTabBtn");
const sankeyViewPanel = document.getElementById("sankeyViewPanel");
const nodeDetailPanel = document.getElementById("nodeDetailPanel");
const nodeDetailTitle = document.getElementById("nodeDetailTitle");
const nodeDetailSubtitle = document.getElementById("nodeDetailSubtitle");
const nodeDetailMeta = document.getElementById("nodeDetailMeta");
const nodeDetailBody = document.getElementById("nodeDetailBody");
const nodeTxPanel = document.getElementById("nodeTxPanel");
const nodeTxCount = document.getElementById("nodeTxCount");
const nodeTxTableBody = document.getElementById("nodeTxTableBody");
const nodeTxPrevBtn = document.getElementById("nodeTxPrevBtn");
const nodeTxNextBtn = document.getElementById("nodeTxNextBtn");
const nodeTxPageInfo = document.getElementById("nodeTxPageInfo");
const detailPanel = document.getElementById("detailPanel");
const workspace = document.getElementById("workspace");
const externalPanels = document.getElementById("externalPanels");
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
const breatheEnabledToggle = document.getElementById("breatheEnabledToggle");
const globalPulseToggle = document.getElementById("globalPulseToggle");
const globalPulseIntensityRange = document.getElementById("globalPulseIntensityRange");
const globalPulseIntensityValue = document.getElementById("globalPulseIntensityValue");
const globalPulseSpeedRange = document.getElementById("globalPulseSpeedRange");
const globalPulseSpeedValue = document.getElementById("globalPulseSpeedValue");
const phaseLagToggle = document.getElementById("phaseLagToggle");
const edgeShimmerToggle = document.getElementById("edgeShimmerToggle");
const edgeShimmerIntensityRange = document.getElementById("edgeShimmerIntensityRange");
const edgeShimmerIntensityValue = document.getElementById("edgeShimmerIntensityValue");
const interactionRippleToggle = document.getElementById("interactionRippleToggle");
const interactionRippleStrengthRange = document.getElementById("interactionRippleStrengthRange");
const interactionRippleStrengthValue = document.getElementById("interactionRippleStrengthValue");
const ambientDriftToggle = document.getElementById("ambientDriftToggle");
const ambientDriftStrengthRange = document.getElementById("ambientDriftStrengthRange");
const ambientDriftStrengthValue = document.getElementById("ambientDriftStrengthValue");
const confidencePulseToggle = document.getElementById("confidencePulseToggle");
const timelineHeartbeatToggle = document.getElementById("timelineHeartbeatToggle");
const timelineHeartbeatStrengthRange = document.getElementById("timelineHeartbeatStrengthRange");
const timelineHeartbeatStrengthValue = document.getElementById("timelineHeartbeatStrengthValue");
const backgroundFieldToggle = document.getElementById("backgroundFieldToggle");
const backgroundFieldIntensityRange = document.getElementById("backgroundFieldIntensityRange");
const backgroundFieldIntensityValue = document.getElementById("backgroundFieldIntensityValue");
const drawerToggleBtn = document.getElementById("drawerToggleBtn");
const drawerCloseBtn = document.getElementById("drawerCloseBtn");
const nodeDrawerToggleBtn = document.getElementById("nodeDrawerToggleBtn");
const nodeDetailCloseBtn = document.getElementById("nodeDetailCloseBtn");
const qualityDrawerToggleBtn = document.getElementById("qualityDrawerToggleBtn");
const qualityCloseBtn = document.getElementById("qualityCloseBtn");
const insightsDrawerToggleBtn = document.getElementById("insightsDrawerToggleBtn");
const insightsCloseBtn = document.getElementById("insightsCloseBtn");
const sankeySummary = document.getElementById("sankeySummary");
const sankeySvgEl = document.getElementById("sankeySvg");
const sankeyEmptyState = document.getElementById("sankeyEmptyState");
const sankeyZoomState = document.getElementById("sankeyZoomState");
const sankeyZoomResetBtn = document.getElementById("sankeyZoomResetBtn");
const sankeyModeSelect = document.getElementById("sankeyModeSelect");
const sankeyCategoryLensSelect = document.getElementById("sankeyCategoryLensSelect");
const sankeyMinCasesInput = document.getElementById("sankeyMinCasesInput");
const sankeyTopPathsInput = document.getElementById("sankeyTopPathsInput");
const sankeyPathTable = document.getElementById("sankeyPathTable");
const sankeyKeywordDetailPanel = document.getElementById("sankeyKeywordDetailPanel");
const sankeyKeywordDetailTitle = document.getElementById("sankeyKeywordDetailTitle");
const sankeyKeywordDetailMeta = document.getElementById("sankeyKeywordDetailMeta");
const sankeyKeywordDetailBody = document.getElementById("sankeyKeywordDetailBody");
const sankeyKeywordDetailCloseBtn = document.getElementById("sankeyKeywordDetailCloseBtn");
const sankeyLinkDetailPanel = document.getElementById("sankeyLinkDetailPanel");
const sankeyLinkDetailTitle = document.getElementById("sankeyLinkDetailTitle");
const sankeyLinkDetailMeta = document.getElementById("sankeyLinkDetailMeta");
const sankeyLinkDetailBody = document.getElementById("sankeyLinkDetailBody");
const sankeyLinkDetailCloseBtn = document.getElementById("sankeyLinkDetailCloseBtn");
const sankeySearchInput = document.getElementById("sankeySearchInput");
const sankeyFieldFilter = document.getElementById("sankeyFieldFilter");
const sankeyOutcomeFilter = document.getElementById("sankeyOutcomeFilter");
const sankeyVerifiedOnlyToggle = document.getElementById("sankeyVerifiedOnlyToggle");
const sankeyFilterResetBtn = document.getElementById("sankeyFilterResetBtn");

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
const graphSectionSummary = document.getElementById("graphSectionSummary");
const motionSectionSummary = document.getElementById("motionSectionSummary");
const displaySectionSummary = document.getElementById("displaySectionSummary");
const helpPopover = document.getElementById("helpPopover");
const helpPopoverTitle = document.getElementById("helpPopoverTitle");
const helpPopoverBody = document.getElementById("helpPopoverBody");
const helpPopoverClose = document.getElementById("helpPopoverClose");

const HELP_CONTENT = {
  selection_panel: {
    title: "Selection Panel",
    does: "Shows contextual details for the currently hovered or pinned node/edge.",
    analysis: "Reads live graph context (edge type, dates, confidence, reason rollups, and linked transactions).",
    meaning: "Use it to validate why a category was chosen and which signals are driving memory strength.",
  },
  settings_overview: {
    title: "Graph Settings",
    does: "Controls how the knowledge graph is rendered and animated.",
    analysis: "Applies display/motion toggles on top of the same underlying graph payload.",
    meaning: "Change visual emphasis without altering any model decisions or stored categorization data.",
  },
  settings_graph: {
    title: "Graph Group",
    does: "Adjusts structural visibility for core graph interpretation.",
    analysis: "Toggles initial-miss links and scales merchant-connected nodes.",
    meaning: "Use this when comparing stable category memory versus correction history.",
  },
  settings_motion: {
    title: "Motion Group",
    does: "Controls breathing and ambient animation effects.",
    analysis: "Animates graph layers using confidence, interaction, and timeline heartbeat signals.",
    meaning: "Useful for pattern perception, but not a source of model truth on its own.",
  },
  settings_display: {
    title: "Display Group",
    does: "Enables optional text overlays for node and edge labels.",
    analysis: "Shows/hides labels while preserving node/edge geometry and weights.",
    meaning: "Helpful for explanation mode; disable for cleaner structural inspection.",
  },
  quality_overview: {
    title: "Model Quality",
    does: "Summarizes aggregate classification performance over reviewed/scored transactions.",
    analysis: "Computes accuracy, macro-F1, calibration, and confusion distributions from scored history.",
    meaning: "Use this panel to measure whether categorization is improving globally over time.",
  },
  quality_metrics: {
    title: "Quality Metrics",
    does: "Shows overall precision-quality indicators for the model.",
    analysis: "Combines scored outcome counts and category-level metrics into top-line KPIs.",
    meaning: "Treat this as your primary health check before drilling into edge cases.",
  },
  quality_per_category: {
    title: "Per-category Performance",
    does: "Breaks quality metrics down by category label.",
    analysis: "Calculates support, precision, recall, and F1 for each category.",
    meaning: "Highlights which categories are strong, weak, or under-trained.",
  },
  quality_confusion: {
    title: "Confusion Matrix",
    does: "Shows where predictions are being confused between categories.",
    analysis: "Counts actual-vs-predicted outcomes for the most represented classes.",
    meaning: "Use strong off-diagonal cells to identify recurring misclassification patterns.",
  },
  quality_calibration: {
    title: "Confidence Calibration",
    does: "Compares predicted confidence against actual correctness.",
    analysis: "Bins confidence ranges and computes realized accuracy per bin.",
    meaning: "If confidence > accuracy consistently, the model is overconfident.",
  },
  quality_replay: {
    title: "Replay Backtest Trend",
    does: "Tracks performance progression across recent time windows.",
    analysis: "Replays historical periods and reports monthly/periodic accuracy.",
    meaning: "Use this to confirm learning trend direction, not just snapshot quality.",
  },
  insights_overview: {
    title: "Agent Insights",
    does: "Surfaces ambiguity, instability, and correction dynamics in agent behavior.",
    analysis: "Combines case-level outcomes with keyword-level stability signals.",
    meaning: "Use this panel to inspect how the agent learns, not just whether it is accurate.",
  },
  insights_diagnostics: {
    title: "Diagnostics",
    does: "Provides live summary counts for risk and stability dimensions.",
    analysis: "Aggregates case inspector + risk + stability datasets from insights API.",
    meaning: "A quick triage view before drilling into specific cases.",
  },
  insights_case_inspector: {
    title: "Case Inspector",
    does: "Shows transaction-by-transaction reasoning snapshots.",
    analysis: "Includes keyword, predicted/resolved category, confidence, and memory context.",
    meaning: "Best tool for auditing an individual categorization decision end-to-end.",
  },
  insights_risk: {
    title: "Ambiguity & Risk",
    does: "Lists high-risk transactions likely to be misclassified.",
    analysis: "Ranks items using risk score, confidence, correctness, and resolved outcomes.",
    meaning: "Use top rows as priority candidates for review or memory rule updates.",
  },
  insights_stability: {
    title: "Stability & Learning Velocity",
    does: "Shows how quickly keywords converge to stable categorization.",
    analysis: "Measures flips, corrections, entropy, and time-to-stability by keyword.",
    meaning: "Low stability suggests unresolved ambiguity or insufficient feedback cycles.",
  },
  insights_sankey: {
    title: "Decision Path Sankey",
    does: "Visualizes flow from keyword to predicted category to resolved category.",
    analysis: "Aggregates case-inspector rows into weighted transition paths between decision stages.",
    meaning: "Wider paths indicate repeated behavior patterns, including persistent correction routes.",
  },
  dock_query: {
    title: "Query & Filters",
    does: "Controls graph retrieval scope and filtering before rendering.",
    analysis: "Applies min-weight, record limit, verification filter, and text query matching.",
    meaning: "Use this to narrow investigation to stronger evidence or specific keywords/categories.",
  },
  dock_timeline: {
    title: "Timeline Controls",
    does: "Replays graph growth over time with manual and auto playback.",
    analysis: "Shows only nodes/edges available up to the selected time cutoff.",
    meaning: "Use this to study how agent memory evolves as new transactions arrive.",
  },
  dock_zoom: {
    title: "Zoom & Focus",
    does: "Adjusts viewport magnification for structural inspection.",
    analysis: "Applies D3 zoom transforms without changing graph data.",
    meaning: "Use high zoom for local reasoning paths and reset for global cluster context.",
  },
};

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

function closeHelpPopover() {
  if (!helpPopover) return;
  helpPopover.classList.add("hidden");
  helpPopover.dataset.key = "";
  helpPopover.dataset.anchor = "";
}

function renderHelpBody(helpItem) {
  if (!helpPopoverBody) return;
  const does = escapeHtml(helpItem?.does || "No help content available.");
  const analysis = escapeHtml(helpItem?.analysis || "No analysis details available.");
  const meaning = escapeHtml(helpItem?.meaning || "No interpretation guidance available.");
  helpPopoverBody.innerHTML = [
    `<p><strong>What it does:</strong> ${does}</p>`,
    `<p><strong>What it analyzes:</strong> ${analysis}</p>`,
    `<p><strong>What it means:</strong> ${meaning}</p>`,
  ].join("");
}

function openHelpPopover(helpKey, anchorEl) {
  if (!helpPopover || !helpPopoverTitle || !anchorEl) return;
  const item = HELP_CONTENT[helpKey] || {
    title: "Help",
    does: "No help content available for this control yet.",
    analysis: "No analysis details available.",
    meaning: "No interpretation guidance available.",
  };
  helpPopoverTitle.textContent = item.title;
  renderHelpBody(item);

  const anchorRect = anchorEl.getBoundingClientRect();
  helpPopover.classList.remove("hidden");
  helpPopover.dataset.key = helpKey;

  const popRect = helpPopover.getBoundingClientRect();
  const gap = 10;
  let left = anchorRect.right + gap;
  let top = anchorRect.top - 8;

  if (left + popRect.width > window.innerWidth - 8) {
    left = anchorRect.left - popRect.width - gap;
  }
  if (left < 8) {
    left = Math.max(8, Math.min(window.innerWidth - popRect.width - 8, anchorRect.left));
    top = anchorRect.bottom + gap;
  }
  if (top + popRect.height > window.innerHeight - 8) {
    top = Math.max(8, window.innerHeight - popRect.height - 8);
  }
  if (top < 8) top = 8;

  helpPopover.style.left = `${Math.round(left)}px`;
  helpPopover.style.top = `${Math.round(top)}px`;
  helpPopover.dataset.anchor = helpKey;
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

function resetNodeTable() {
  state.nodeDetailRows = [];
  state.nodeDetailPage = 0;
  if (nodeTxPanel) nodeTxPanel.classList.add("hidden");
  if (nodeTxTableBody) nodeTxTableBody.innerHTML = "";
  if (nodeTxCount) nodeTxCount.textContent = "0";
  if (nodeTxPageInfo) nodeTxPageInfo.textContent = "Page 1 / 1";
  if (nodeTxPrevBtn) nodeTxPrevBtn.disabled = true;
  if (nodeTxNextBtn) nodeTxNextBtn.disabled = true;
}

function sortRowsByDateDesc(rows) {
  return rows.sort((a, b) => {
    const left = timelineMsFromDate(a.date) || 0;
    const right = timelineMsFromDate(b.date) || 0;
    return right - left;
  });
}

function renderNodeTablePage() {
  if (!nodeTxPanel || !nodeTxTableBody) return;
  const rows = state.nodeDetailRows || [];
  if (!rows.length) {
    resetNodeTable();
    return;
  }

  const pageSize = Math.max(1, Number(state.nodeDetailPageSize) || 8);
  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
  state.nodeDetailPage = Math.max(0, Math.min(state.nodeDetailPage, totalPages - 1));
  const start = state.nodeDetailPage * pageSize;
  const pageRows = rows.slice(start, start + pageSize);

  nodeTxPanel.classList.remove("hidden");
  nodeTxTableBody.innerHTML = pageRows
    .map((row) => {
      return `<tr>
        <td>${escapeHtml(row.tx_id || "-")}</td>
        <td>${escapeHtml(formatDate(row.date))}</td>
        <td title="${escapeHtml(row.label || "-")}">${escapeHtml(row.label || "-")}</td>
        <td>${row.amount === null || row.amount === undefined ? "-" : escapeHtml(formatAmount(Number(row.amount)))}</td>
        <td>${escapeHtml(Number(row.weight || 0).toFixed(2))}</td>
      </tr>`;
    })
    .join("");
  if (nodeTxCount) nodeTxCount.textContent = `${rows.length}`;
  if (nodeTxPageInfo) nodeTxPageInfo.textContent = `Page ${state.nodeDetailPage + 1} / ${totalPages}`;
  if (nodeTxPrevBtn) nodeTxPrevBtn.disabled = state.nodeDetailPage <= 0;
  if (nodeTxNextBtn) nodeTxNextBtn.disabled = state.nodeDetailPage >= totalPages - 1;
}

function setDetailPanel(payload) {
  const safe = payload || {};
  if (nodeDetailTitle) nodeDetailTitle.textContent = safe.title || "Selection";
  if (nodeDetailSubtitle) nodeDetailSubtitle.textContent = safe.subtitle || "";
  if (nodeDetailMeta) {
    const chips = (safe.chips || []).slice(0, 8);
    nodeDetailMeta.innerHTML = chips.map((item) => `<span class="node-detail-chip">${escapeHtml(item)}</span>`).join("");
  }
  if (nodeDetailBody) {
    const paragraphs = (safe.body || []).filter(Boolean);
    nodeDetailBody.innerHTML = paragraphs.map((line) => `<div>${escapeHtml(line)}</div>`).join("");
  }

  const txRows = safe.txRows || [];
  if (!txRows.length) {
    resetNodeTable();
  } else {
    state.nodeDetailRows = sortRowsByDateDesc(txRows.slice());
    state.nodeDetailPage = 0;
    renderNodeTablePage();
  }
}

function setDefaultDetail() {
  setDetailPanel({
    title: "Selection",
    subtitle: "Hover a node or edge to inspect details.",
    chips: ["Graph Explorer", "Read-only Analysis"],
    body: [
      "Click a node to lock focus and zoom. Click blank canvas to clear focus.",
      "Merchant nodes connect to categories.",
      "Small satellite nodes are transactions linked by keyword.",
      "Subtle red links show initial LLM category guesses that were later corrected.",
    ],
    txRows: [],
  });
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

function clampNumber(value, min, max, fallback) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return fallback;
  return Math.max(min, Math.min(max, numeric));
}

function persistSettings() {
  try {
    const payload = {
      showEdgeText: state.showEdgeText,
      showNodeText: state.showNodeText,
      showInitialMissLinks: state.showInitialMissLinks,
      connectedNodeScale: state.connectedNodeScale,
      nodeDrawerOpen: state.nodeDrawerOpen,
      drawerOpen: state.drawerOpen,
      qualityDrawerOpen: state.qualityDrawerOpen,
      insightsDrawerOpen: state.insightsDrawerOpen,
      activeView: state.activeView,
      sankeyFilters: { ...state.sankeyFilters },
      sankeyMode: state.sankeyMode,
      sankeyCategoryLens: state.sankeyCategoryLens,
      sankeyThresholds: { ...state.sankeyThresholds },
      breathe: { ...state.breathe },
    };
    window.localStorage.setItem(GRAPH_SETTINGS_STORAGE_KEY, JSON.stringify(payload));
  } catch (_error) {
    // Ignore storage failures (private mode / quota / disabled).
  }
}

function loadPersistedSettings() {
  try {
    const raw = window.localStorage.getItem(GRAPH_SETTINGS_STORAGE_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return;

    if (typeof parsed.showEdgeText === "boolean") state.showEdgeText = parsed.showEdgeText;
    if (typeof parsed.showNodeText === "boolean") state.showNodeText = parsed.showNodeText;
    if (typeof parsed.showInitialMissLinks === "boolean") state.showInitialMissLinks = parsed.showInitialMissLinks;
    if (typeof parsed.nodeDrawerOpen === "boolean") state.nodeDrawerOpen = parsed.nodeDrawerOpen;
    if (typeof parsed.drawerOpen === "boolean") state.drawerOpen = parsed.drawerOpen;
    if (typeof parsed.qualityDrawerOpen === "boolean") state.qualityDrawerOpen = parsed.qualityDrawerOpen;
    if (typeof parsed.insightsDrawerOpen === "boolean") state.insightsDrawerOpen = parsed.insightsDrawerOpen;
    if (parsed.activeView === "graph" || parsed.activeView === "sankey") state.activeView = parsed.activeView;
    if (parsed.sankeyFilters && typeof parsed.sankeyFilters === "object") {
      const input = parsed.sankeyFilters;
      if (typeof input.search === "string") state.sankeyFilters.search = input.search.slice(0, 140);
      if (input.field === "all" || input.field === "keyword" || input.field === "predicted" || input.field === "resolved") {
        state.sankeyFilters.field = input.field;
      }
      if (input.outcome === "all" || input.outcome === "mismatch" || input.outcome === "match") {
        state.sankeyFilters.outcome = input.outcome;
      }
      if (typeof input.verifiedOnly === "boolean") state.sankeyFilters.verifiedOnly = input.verifiedOnly;
    }
    if (parsed.sankeyMode === "volume" || parsed.sankeyMode === "error" || parsed.sankeyMode === "confidence") {
      state.sankeyMode = parsed.sankeyMode;
    }
    if (typeof parsed.sankeyCategoryLens === "string") {
      state.sankeyCategoryLens = parsed.sankeyCategoryLens;
    }
    if (parsed.sankeyThresholds && typeof parsed.sankeyThresholds === "object") {
      const input = parsed.sankeyThresholds;
      state.sankeyThresholds.minPathCases = clampNumber(input.minPathCases, 1, 10000, state.sankeyThresholds.minPathCases);
      state.sankeyThresholds.topPaths = clampNumber(input.topPaths, 5, 200, state.sankeyThresholds.topPaths);
    }
    state.connectedNodeScale = clampNumber(parsed.connectedNodeScale, 0.55, 1.3, state.connectedNodeScale);

    if (parsed.breathe && typeof parsed.breathe === "object") {
      const input = parsed.breathe;
      if (typeof input.enabled === "boolean") state.breathe.enabled = input.enabled;
      if (typeof input.globalPulse === "boolean") state.breathe.globalPulse = input.globalPulse;
      if (typeof input.phaseLag === "boolean") state.breathe.phaseLag = input.phaseLag;
      if (typeof input.edgeShimmer === "boolean") state.breathe.edgeShimmer = input.edgeShimmer;
      if (typeof input.interactionRipple === "boolean") state.breathe.interactionRipple = input.interactionRipple;
      if (typeof input.ambientDrift === "boolean") state.breathe.ambientDrift = input.ambientDrift;
      if (typeof input.confidencePulse === "boolean") state.breathe.confidencePulse = input.confidencePulse;
      if (typeof input.timelineHeartbeat === "boolean") state.breathe.timelineHeartbeat = input.timelineHeartbeat;
      if (typeof input.backgroundField === "boolean") state.breathe.backgroundField = input.backgroundField;
      state.breathe.globalPulseIntensity = clampNumber(input.globalPulseIntensity, 0, 1, state.breathe.globalPulseIntensity);
      state.breathe.globalPulseSpeed = clampNumber(input.globalPulseSpeed, 0.2, 1.8, state.breathe.globalPulseSpeed);
      state.breathe.edgeShimmerIntensity = clampNumber(input.edgeShimmerIntensity, 0, 1, state.breathe.edgeShimmerIntensity);
      state.breathe.interactionRippleStrength = clampNumber(
        input.interactionRippleStrength,
        0.1,
        2,
        state.breathe.interactionRippleStrength,
      );
      state.breathe.ambientDriftStrength = clampNumber(input.ambientDriftStrength, 0, 1.2, state.breathe.ambientDriftStrength);
      state.breathe.timelineHeartbeatStrength = clampNumber(
        input.timelineHeartbeatStrength,
        0,
        1.8,
        state.breathe.timelineHeartbeatStrength,
      );
      state.breathe.backgroundFieldIntensity = clampNumber(
        input.backgroundFieldIntensity,
        0,
        1.2,
        state.breathe.backgroundFieldIntensity,
      );
    }

    // Ensure at most one drawer opens at startup.
    if (state.qualityDrawerOpen && state.insightsDrawerOpen) state.insightsDrawerOpen = false;
    if (state.drawerOpen && state.qualityDrawerOpen) state.drawerOpen = false;
    if (state.drawerOpen && state.insightsDrawerOpen) state.drawerOpen = false;
  } catch (_error) {
    // Ignore malformed local storage values.
  }
}

function hashToUnit(value) {
  const text = String(value || "");
  let hash = 2166136261;
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  const positive = hash >>> 0;
  return (positive % 10000) / 10000;
}

function syncBreathingLabels() {
  if (globalPulseIntensityValue) {
    globalPulseIntensityValue.textContent = state.breathe.globalPulseIntensity.toFixed(2);
  }
  if (globalPulseSpeedValue) {
    globalPulseSpeedValue.textContent = `${state.breathe.globalPulseSpeed.toFixed(2)}x`;
  }
  if (edgeShimmerIntensityValue) {
    edgeShimmerIntensityValue.textContent = state.breathe.edgeShimmerIntensity.toFixed(2);
  }
  if (interactionRippleStrengthValue) {
    interactionRippleStrengthValue.textContent = `${state.breathe.interactionRippleStrength.toFixed(2)}x`;
  }
  if (ambientDriftStrengthValue) {
    ambientDriftStrengthValue.textContent = state.breathe.ambientDriftStrength.toFixed(2);
  }
  if (timelineHeartbeatStrengthValue) {
    timelineHeartbeatStrengthValue.textContent = state.breathe.timelineHeartbeatStrength.toFixed(2);
  }
  if (backgroundFieldIntensityValue) {
    backgroundFieldIntensityValue.textContent = state.breathe.backgroundFieldIntensity.toFixed(2);
  }
}

function updateSettingsSectionSummaries() {
  if (graphSectionSummary) {
    graphSectionSummary.textContent = `${state.showInitialMissLinks ? "Miss links on" : "Miss links off"} | ${state.connectedNodeScale.toFixed(2)}x`;
  }
  if (motionSectionSummary) {
    const motionToggles = [
      state.breathe.enabled,
      state.breathe.globalPulse,
      state.breathe.phaseLag,
      state.breathe.edgeShimmer,
      state.breathe.interactionRipple,
      state.breathe.ambientDrift,
      state.breathe.confidencePulse,
      state.breathe.timelineHeartbeat,
      state.breathe.backgroundField,
    ];
    const enabledCount = motionToggles.filter(Boolean).length;
    motionSectionSummary.textContent = `${enabledCount}/${motionToggles.length} enabled`;
  }
  if (displaySectionSummary) {
    const textCount = [state.showEdgeText, state.showNodeText].filter(Boolean).length;
    displaySectionSummary.textContent = `${textCount}/2 text overlays`;
  }
}

function triggerTimelineHeartbeatPulse() {
  if (!state.breathe.enabled || !state.breathe.timelineHeartbeat) return;
  const strength = Math.max(0, state.breathe.timelineHeartbeatStrength || 0);
  state.timelinePulse = Math.min(2, state.timelinePulse + 0.65 * strength);
}

function setDrawerOpen(isOpen) {
  state.drawerOpen = Boolean(isOpen);
  if (!detailPanel || !drawerToggleBtn) return;
  detailPanel.classList.toggle("collapsed", !state.drawerOpen);
  updateWorkspaceLayout();
  persistSettings();
}

function setNodeDrawerOpen(isOpen) {
  state.nodeDrawerOpen = Boolean(isOpen);
  if (!nodeDetailPanel || !nodeDrawerToggleBtn) return;
  nodeDetailPanel.classList.toggle("collapsed", !state.nodeDrawerOpen);
  persistSettings();
}

function setQualityDrawerOpen(isOpen) {
  state.qualityDrawerOpen = Boolean(isOpen);
  if (!qualityPanel || !qualityDrawerToggleBtn) return;
  qualityPanel.classList.toggle("collapsed", !state.qualityDrawerOpen);
  updateWorkspaceLayout();
  persistSettings();
}

function setInsightsDrawerOpen(isOpen) {
  state.insightsDrawerOpen = Boolean(isOpen);
  if (!insightsPanel || !insightsDrawerToggleBtn) return;
  insightsPanel.classList.toggle("collapsed", !state.insightsDrawerOpen);
  updateWorkspaceLayout();
  persistSettings();
}

function setActiveView(viewName) {
  state.activeView = viewName === "sankey" ? "sankey" : "graph";
  if (graphViewTabBtn) {
    const active = state.activeView === "graph";
    graphViewTabBtn.classList.toggle("is-active", active);
    graphViewTabBtn.setAttribute("aria-selected", active ? "true" : "false");
  }
  if (sankeyViewTabBtn) {
    const active = state.activeView === "sankey";
    sankeyViewTabBtn.classList.toggle("is-active", active);
    sankeyViewTabBtn.setAttribute("aria-selected", active ? "true" : "false");
  }
  if (graphWrap) graphWrap.classList.toggle("sankey-active", state.activeView === "sankey");
  if (sankeyViewPanel) sankeyViewPanel.classList.toggle("hidden", state.activeView !== "sankey");
  if (state.activeView === "sankey") {
    setDrawerOpen(false);
    setQualityDrawerOpen(false);
    setInsightsDrawerOpen(false);
    stopTimelinePlayback();
    renderDecisionPathSankey(state.insightsData);
  } else if (state.graph) {
    hideSankeyKeywordDetail();
    hideSankeyLinkDetail();
    renderGraph(state.graph);
  }
  persistSettings();
}

function applySankeyFilterControls() {
  if (sankeyModeSelect) sankeyModeSelect.value = state.sankeyMode || "volume";
  if (sankeySearchInput) sankeySearchInput.value = state.sankeyFilters.search || "";
  if (sankeyFieldFilter) sankeyFieldFilter.value = state.sankeyFilters.field || "all";
  if (sankeyOutcomeFilter) sankeyOutcomeFilter.value = state.sankeyFilters.outcome || "all";
  if (sankeyCategoryLensSelect) sankeyCategoryLensSelect.value = state.sankeyCategoryLens || "";
  if (sankeyVerifiedOnlyToggle) sankeyVerifiedOnlyToggle.checked = Boolean(state.sankeyFilters.verifiedOnly);
  if (sankeyMinCasesInput) sankeyMinCasesInput.value = String(Math.round(state.sankeyThresholds.minPathCases || 1));
  if (sankeyTopPathsInput) sankeyTopPathsInput.value = String(Math.round(state.sankeyThresholds.topPaths || 80));
}

function syncSankeyCategoryLensOptions(rows) {
  if (!sankeyCategoryLensSelect) return;
  const resolvedValues = Array.from(
    new Set(
      (rows || [])
        .map((row) => String(row?.resolved_category || "").trim())
        .filter(Boolean),
    ),
  ).sort((a, b) => a.localeCompare(b));
  const selected = state.sankeyCategoryLens || "";
  const stillExists = !selected || resolvedValues.includes(selected);
  if (!stillExists) {
    state.sankeyCategoryLens = "";
  }
  const options = [
    `<option value="">All resolved categories</option>`,
    ...resolvedValues.map((label) => `<option value="${escapeHtml(label)}"${label === state.sankeyCategoryLens ? " selected" : ""}>${escapeHtml(label)}</option>`),
  ];
  sankeyCategoryLensSelect.innerHTML = options.join("");
}

function clearSankeyZoom() {
  state.sankeyZoom.stage = null;
  state.sankeyZoom.label = null;
}

function updateSankeyZoomControls() {
  if (!sankeyZoomState || !sankeyZoomResetBtn) return;
  const stage = state.sankeyZoom.stage;
  const label = state.sankeyZoom.label;
  if (!stage || !label) {
    sankeyZoomState.classList.add("hidden");
    sankeyZoomState.textContent = "";
    sankeyZoomResetBtn.classList.add("hidden");
    return;
  }
  sankeyZoomState.classList.remove("hidden");
  sankeyZoomState.textContent = `Zoom: ${stage} = ${label}`;
  sankeyZoomResetBtn.classList.remove("hidden");
}

function updateWorkspaceLayout() {
  if (!workspace) return;
  const hasExternal = state.drawerOpen || state.qualityDrawerOpen || state.insightsDrawerOpen;
  workspace.classList.toggle("has-side-panel", hasExternal);
  if (externalPanels) {
    externalPanels.classList.toggle("hidden", !hasExternal);
  }
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
  const changed = clamped !== state.timelineIndex;
  state.timelineIndex = clamped;
  if (timelineSlider) timelineSlider.value = String(clamped);
  updateTimelineLabel();
  if (changed) triggerTimelineHeartbeatPulse();
  if (shouldApply) {
    applyVisualState({ animateTimeline: true });
    if (state.activeView === "sankey") {
      renderDecisionPathSankey(state.insightsData);
    }
  }
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
    .ease(MOTION_EASE)
    .attr("r", (d) => ringTargetRadius(d) * 1.08)
    .transition()
    .duration(130)
    .ease(MOTION_EASE)
    .attr("r", ringTargetRadius);

  nodeCore
    .filter((d) => idSet.has(d.id))
    .interrupt()
    .attr("r", (d) => coreTargetRadius(d) * 0.62)
    .transition()
    .duration(170)
    .ease(MOTION_EASE)
    .attr("r", (d) => coreTargetRadius(d) * 1.1)
    .transition()
    .duration(130)
    .ease(MOTION_EASE)
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

  const { nodeGroup, nodeHit, nodeRing, nodeCore, nodeLabel, link, edgeLabel, strokeScale } = selections;
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
      if (!filtered) return d.kind === "transaction" ? 0.88 : 0.99;
      if (activeNodeIds.has(d.id)) return 1;
      return d.kind === "transaction" ? 0.14 : 0.16;
    });

  if (nodeHit) {
    nodeHit.attr("r", (d) => {
      const base = nodeRadius(d);
      if (d.kind === "transaction") return Math.max(8, base + 3.5);
      return Math.max(14, base + 8.5);
    });
  }

  nodeRing
    .attr("stroke", (d) => {
      if (d.id === state.focusNodeId) return "#21445d";
      if (d.kind === "keyword") return filtered && activeNodeIds.has(d.id) ? "#3e81a7" : "#6f99b2";
      if (d.kind === "transaction") return "#7396ad";
      return filtered && activeNodeIds.has(d.id) ? "#5e7388" : "#90a2b2";
    })
    .attr("stroke-width", (d) => {
      if (d.kind === "transaction") return 1.05;
      if (d.id === state.focusNodeId) return 2.6;
      if (filtered && activeNodeIds.has(d.id)) return 1.8;
      return 1.25;
    });

  nodeCore.attr("fill", (d) => {
    if (d.kind === "keyword") {
      if (d.id === state.focusNodeId) return "#2b6f95";
      if (filtered && activeNodeIds.has(d.id)) return "#4f87aa";
      return "#5d92b0";
    }
    if (d.kind === "category") {
      if (d.id === state.focusNodeId) return "#51697d";
      if (filtered && activeNodeIds.has(d.id)) return "#6a8397";
      return "#7c93a6";
    }
    if (filtered && activeNodeIds.has(d.id)) return "#88a8ba";
    return "#98b7c8";
  });

  link
    .style("display", (d) => (visibility.visibleEdgeIds.has(d.id) ? null : "none"))
    .style("pointer-events", (d) => (visibility.visibleEdgeIds.has(d.id) ? null : "none"))
    .attr("stroke", (d) => {
      if (d.id === state.focusEdgeId) return "#2f80aa";
      if (d.edge_type === "llm_initial_category") {
        return filtered && activeEdgeIds.has(d.id) ? "#c34053" : "#cf5d6d";
      }
      if (d.edge_type === "transaction_keyword") {
        return filtered && activeEdgeIds.has(d.id) ? "#6f93a9" : "#aebfcc";
      }
      return filtered && activeEdgeIds.has(d.id) ? "#5f8fab" : "#9fb5c4";
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
        if (d.edge_type === "transaction_keyword") return 0.54;
        if (d.edge_type === "llm_initial_category") return 0.72;
        return 0.64;
      }
      if (activeEdgeIds.has(d.id)) return 0.95;
      if (d.edge_type === "transaction_keyword") return 0.2;
      if (d.edge_type === "llm_initial_category") return 0.34;
      return 0.1;
    });

  edgeLabel
    .style("display", (d) => {
      if (!state.showEdgeText || d.edge_type === "transaction_keyword") return "none";
      return visibility.visibleEdgeIds.has(d.id) ? null : "none";
    })
    .style("opacity", (d) => {
      if (!state.showEdgeText || !visibility.visibleEdgeIds.has(d.id)) return 0;
      if (!filtered) return 0.56;
      return activeEdgeIds.has(d.id) ? 0.82 : 0.03;
    });

  nodeLabel
    .style("display", (d) => {
      if (!state.showNodeText || d.kind === "transaction") return "none";
      return visibility.visibleNodeIds.has(d.id) ? null : "none";
    })
    .style("opacity", (d) => {
      if (!state.showNodeText || d.kind === "transaction" || !visibility.visibleNodeIds.has(d.id)) return 0;
      if (!filtered) return 0.8;
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
  const selections = state.selections;
  const nodeById = new Map((selections?.nodeData || []).map((item) => [item.id, item]));
  const nodeEdges = edgeData.filter((edge) => {
    if (visibleEdgeIds && !visibleEdgeIds.has(edge.id)) return false;
    return sourceId(edge) === node.id || targetId(edge) === node.id;
  });
  const txRows = [];
  nodeEdges.forEach((edge) => {
    if (edge.edge_type !== "transaction_keyword") return;
    const sid = sourceId(edge);
    const tid = targetId(edge);
    const txNodeId = sid === node.id ? tid : sid;
    const txNode = nodeById.get(txNodeId);
    txRows.push({
      tx_id: edge.transaction_id || txNode?.transaction_id || txNode?.id || "-",
      date: edge.transaction_date || txNode?.date || null,
      label: edge.transaction_label || txNode?.label || "",
      amount: txNode?.amount ?? null,
      weight: edge.weight || 0,
    });
  });

  if (node.kind === "transaction") {
    setDetailPanel({
      title: node.label || "Transaction",
      subtitle: "Transaction Node",
      chips: ["Transaction", `Date ${formatDate(node.date)}`],
      body: [`Amount: ${formatAmount(node.amount)}`, `Type: ${node.tx_type || "unknown"}`],
      txRows: [
        {
          tx_id: node.id,
          date: node.date || null,
          label: node.label || "",
          amount: node.amount ?? null,
          weight: 1,
        },
      ],
    });
    return;
  }

  if (node.kind === "category") {
    const keywordEdges = nodeEdges.filter((edge) => {
      return edge.edge_type === "keyword_category" || edge.edge_type === "llm_initial_category";
    });
    const keywordNodeIds = new Set();
    const merchantRollups = new Map();
    let confTotal = 0;
    let confCount = 0;
    let verifiedTotal = 0;
    let verifiedCount = 0;
    let initialMissTotal = 0;

    keywordEdges.forEach((edge) => {
      const sid = sourceId(edge);
      const tid = targetId(edge);
      const keywordNodeId = sid === node.id ? tid : sid;
      keywordNodeIds.add(keywordNodeId);
      const keywordNode = nodeById.get(keywordNodeId);
      const label = edge.keyword || keywordNode?.label || keywordNodeId || "Unknown";
      const entry = merchantRollups.get(keywordNodeId) || {
        label,
        weight: 0,
        txCount: 0,
        missCount: 0,
      };
      entry.weight += Number(edge.weight || 0);
      if (edge.edge_type === "llm_initial_category") {
        entry.missCount += Number(edge.miss_count || edge.count || 0);
        initialMissTotal += Number(edge.miss_count || edge.count || 0);
      }
      if (edge.edge_type === "keyword_category") {
        confTotal += Number(edge.avg_confidence || 0);
        confCount += 1;
        verifiedTotal += Number(edge.verified_ratio || 0);
        verifiedCount += 1;
      }
      merchantRollups.set(keywordNodeId, entry);
    });

    const categoryTxEdges = edgeData.filter((edge) => {
      if (visibleEdgeIds && !visibleEdgeIds.has(edge.id)) return false;
      if (edge.edge_type !== "transaction_keyword") return false;
      const sid = sourceId(edge);
      const tid = targetId(edge);
      const keywordNodeId = sid.startsWith?.("keyword::") ? sid : tid.startsWith?.("keyword::") ? tid : null;
      return keywordNodeId && keywordNodeIds.has(keywordNodeId);
    });

    categoryTxEdges.forEach((edge) => {
      const sid = sourceId(edge);
      const tid = targetId(edge);
      const keywordNodeId = sid.startsWith?.("keyword::") ? sid : tid.startsWith?.("keyword::") ? tid : null;
      const txNodeId = keywordNodeId === sid ? tid : sid;
      const txNode = nodeById.get(txNodeId);
      const rollup = keywordNodeId ? merchantRollups.get(keywordNodeId) : null;
      if (rollup) rollup.txCount += 1;
      txRows.push({
        tx_id: edge.transaction_id || txNode?.transaction_id || txNode?.id || "-",
        date: edge.transaction_date || txNode?.date || null,
        label: edge.transaction_label || txNode?.label || "",
        amount: txNode?.amount ?? null,
        weight: edge.weight || 0,
      });
    });

    const topMerchants = Array.from(merchantRollups.values())
      .sort((a, b) => b.weight - a.weight)
      .slice(0, 6)
      .map((entry) => `${entry.label} (w ${entry.weight.toFixed(2)} | tx ${entry.txCount})`);
    const avgConfidence = confCount ? confTotal / confCount : 0;
    const avgVerified = verifiedCount ? verifiedTotal / verifiedCount : 0;

    setDetailPanel({
      title: node.label,
      subtitle: "CATEGORY NODE",
      chips: [
        `Keywords ${merchantRollups.size}`,
        `Transactions ${txRows.length}`,
        `Avg conf ${avgConfidence.toFixed(2)}`,
        `Verified ${(avgVerified * 100).toFixed(0)}%`,
        initialMissTotal > 0 ? `Initial misses ${initialMissTotal}` : "",
      ].filter(Boolean),
      body: [
        topMerchants.length ? `Top merchants: ${topMerchants.join(" | ")}` : "No merchant links in this time window.",
        initialMissTotal > 0
          ? "Initial miss links represent early wrong categories that decayed as corrections accumulated."
          : "No residual initial-miss pressure currently visible.",
      ],
      txRows,
    });
    return;
  }

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
  setDetailPanel({
    title: node.label,
    subtitle: `${node.kind.toUpperCase()} NODE`,
    chips: [
      `Connections ${nodeEdges.length}`,
      `Transactions ${txCount}`,
      initialMissEdges.length > 0 ? `Initial misses ${initialMissEdges.length}` : "",
    ].filter(Boolean),
    body: [
      topEdges.length ? `Top links: ${topEdges.join(" | ")}` : "No category connections in this time window.",
      initialMissEdges.length ? `Initial LLM links: ${initialMissEdges.join(" | ")}` : "",
    ].filter(Boolean),
    txRows,
  });
}

function renderEdgeDetails(edge) {
  if (edge.edge_type === "llm_initial_category") {
    setDetailPanel({
      title: "Initial LLM Category Guess",
      subtitle: edge.keyword || "Unknown keyword",
      chips: [`Misses ${edge.miss_count || edge.count || 0}`, `Residual ${Math.round((Number(edge.decay_strength || 0) || 0) * 100)}%`],
      body: [
        `Suggested category: ${edge.category_label}`,
        `First seen: ${formatDate(edge.first_seen_date)}`,
        `Corrective decisions: ${edge.correction_count || 0}`,
      ],
      txRows: [],
    });
    return;
  }

  if (edge.edge_type === "transaction_keyword") {
    setDetailPanel({
      title: "Transaction -> Merchant Keyword",
      subtitle: edge.keyword || "Keyword link",
      chips: [`Weight ${edge.weight.toFixed(2)}`],
      body: [`Transaction ID: ${edge.transaction_id}`, `Date: ${formatDate(edge.transaction_date)}`],
      txRows: [
        {
          tx_id: edge.transaction_id || "-",
          date: edge.transaction_date || null,
          label: edge.transaction_label || "",
          amount: null,
          weight: edge.weight || 0,
        },
      ],
    });
    return;
  }

  const reasonRollup =
    (edge.reasons || [])
      .map((item) => `- (${item.count}) ${item.text}`)
      .join("\n") || "- No explicit reason captured.";

  setDetailPanel({
    title: `${edge.keyword} -> ${edge.category_label}`,
    subtitle: "Keyword -> Category Link",
    chips: [
      `Weight ${edge.weight.toFixed(2)}`,
      `Confidence ${edge.avg_confidence.toFixed(2)}`,
      `Verified ${(edge.verified_ratio * 100).toFixed(0)}%`,
    ],
    body: [`First seen: ${formatDate(edge.first_seen_date)}`, `Reasons: ${reasonRollup}`],
    txRows: [],
  });
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

function createBackgroundField(width, height) {
  const fieldLayer = svg
    .append("g")
    .attr("class", "graph-field-layer")
    .attr("pointer-events", "none");

  const auraA = fieldLayer
    .append("ellipse")
    .attr("cx", width * 0.24)
    .attr("cy", height * 0.31)
    .attr("rx", Math.max(180, width * 0.18))
    .attr("ry", Math.max(120, height * 0.16))
    .attr("fill", "rgba(128, 164, 181, 0.16)");

  const auraB = fieldLayer
    .append("ellipse")
    .attr("cx", width * 0.78)
    .attr("cy", height * 0.63)
    .attr("rx", Math.max(220, width * 0.2))
    .attr("ry", Math.max(140, height * 0.18))
    .attr("fill", "rgba(116, 151, 166, 0.14)");

  return { fieldLayer, auraA, auraB };
}

function emitInteractionRipple(node) {
  const selections = state.selections;
  if (!selections || !state.breathe.enabled || !state.breathe.interactionRipple) return;
  if (!Number.isFinite(node?.x) || !Number.isFinite(node?.y)) return;

  const base = nodeRadius(node);
  const strength = Math.max(0.2, state.breathe.interactionRippleStrength || 0);
  const burstRadius = Math.max(16, (base + 22) * (0.85 + strength * 0.55));
  const ripple = selections.viewport
    .append("circle")
    .attr("class", "interaction-ripple")
    .attr("cx", node.x)
    .attr("cy", node.y)
    .attr("r", Math.max(3, base * 0.65))
    .attr("fill", "none")
    .attr("stroke", "rgba(94, 142, 166, 0.42)")
    .attr("stroke-width", Math.max(0.8, 1.35 * strength))
    .style("opacity", 0.8);

  ripple
    .transition()
    .duration(680)
    .ease(MOTION_EASE)
    .attr("r", burstRadius)
    .style("opacity", 0)
    .remove();

  const previous = state.interactionPulseByNode.get(node.id) || 0;
  state.interactionPulseByNode.set(node.id, Math.min(1.5, previous + 0.78 * strength));
}

function stopBreathingLoop() {
  if (state.animationFrameId !== null) {
    window.cancelAnimationFrame(state.animationFrameId);
    state.animationFrameId = null;
  }
}

function startBreathingLoop() {
  stopBreathingLoop();
  const selections = state.selections;
  if (!selections) return;

  const { nodeRing, nodeCore, link, edgeData, nodeData, simulation, fieldLayer, auraA, auraB, gridRect } = selections;
  const baseRingRadius = (node) => nodeRadius(node) + (node.kind === "transaction" ? 0.95 : 2.0);
  const baseCoreRadius = (node) => Math.max(2.1, nodeRadius(node) - (node.kind === "transaction" ? 0.05 : 2.8));

  function frame(nowMs) {
    const breathe = state.breathe;
    if (!state.selections || selections !== state.selections) return;
    const t = nowMs * 0.001;

    state.timelinePulse *= 0.945;
    state.interactionPulseByNode.forEach((value, key) => {
      const next = value * 0.93;
      if (next < 0.02) {
        state.interactionPulseByNode.delete(key);
      } else {
        state.interactionPulseByNode.set(key, next);
      }
    });

    if (!breathe.enabled) {
      nodeRing.attr("r", (d) => baseRingRadius(d));
      nodeCore.attr("r", (d) => baseCoreRadius(d));
      link.attr("stroke-dasharray", null).attr("stroke-dashoffset", null);
      if (fieldLayer) fieldLayer.style("opacity", 0);
      if (gridRect) gridRect.attr("opacity", 0.5);
      state.animationFrameId = window.requestAnimationFrame(frame);
      return;
    }

    const globalAmp = breathe.globalPulse ? breathe.globalPulseIntensity * 0.19 : 0;
    const pulseSpeed = Math.max(0.08, breathe.globalPulseSpeed || 0.72);
    const heartbeatBoost = breathe.timelineHeartbeat ? state.timelinePulse * 0.16 : 0;
    const maxCompositeAmp = 0.22;

    nodeRing.attr("r", (d) => {
      const base = baseRingRadius(d);
      const phaseLag = breathe.phaseLag ? d.phase_lag : 0;
      const confidencePulse = breathe.confidencePulse ? d.confidence_pulse : 1;
      const interactionPulse = state.interactionPulseByNode.get(d.id) || 0;
      const wave = Math.sin(t * pulseSpeed * 2.9 + d.phase_seed + phaseLag);
      const rawAmp = (globalAmp + heartbeatBoost + interactionPulse * 0.055) * confidencePulse;
      const amp = Math.min(maxCompositeAmp, rawAmp);
      return Math.max(1.3, base * (1 + wave * amp));
    });

    nodeCore.attr("r", (d) => {
      const base = baseCoreRadius(d);
      const phaseLag = breathe.phaseLag ? d.phase_lag : 0;
      const confidencePulse = breathe.confidencePulse ? d.confidence_pulse : 1;
      const interactionPulse = state.interactionPulseByNode.get(d.id) || 0;
      const wave = Math.sin(t * pulseSpeed * 2.9 + d.phase_seed + phaseLag + 0.45);
      const rawAmp = (globalAmp * 0.74 + heartbeatBoost * 0.92 + interactionPulse * 0.046) * confidencePulse;
      const amp = Math.min(maxCompositeAmp * 0.9, rawAmp);
      return Math.max(1.1, base * (1 + wave * amp));
    });

    if (breathe.edgeShimmer) {
      const shimmer = Math.max(0.02, breathe.edgeShimmerIntensity || 0);
      link
        .attr("stroke-dasharray", (d) => {
          if (d.edge_type === "transaction_keyword") return `${2 + shimmer * 4} ${6 + shimmer * 11}`;
          if (d.edge_type === "llm_initial_category") return `${4 + shimmer * 5} ${8 + shimmer * 8}`;
          return `${4 + shimmer * 4} ${8 + shimmer * 7}`;
        })
        .attr("stroke-dashoffset", (d) => {
          const direction = d.edge_type === "llm_initial_category" ? 1 : -1;
          const speed = 18 + shimmer * 70;
          return direction * ((t * speed + d.phase_seed * 34) % 480);
        });
    } else {
      link.attr("stroke-dasharray", null).attr("stroke-dashoffset", null);
    }

    if (breathe.ambientDrift && simulation) {
      const driftStrength = Math.max(0, breathe.ambientDriftStrength || 0);
      if (driftStrength > 0) {
        nodeData.forEach((node) => {
          if (node.fx !== null || node.fy !== null) return;
          if (node.kind === "transaction") return;
          const drift = driftStrength * 0.00062;
          node.vx += Math.sin(t * 0.74 + node.phase_seed * 3.2) * drift;
          node.vy += Math.cos(t * 0.67 + node.phase_seed * 4.1) * drift;
        });
        simulation.alpha(Math.max(simulation.alpha(), 0.035));
      }
    }

    if (fieldLayer && auraA && auraB) {
      if (breathe.backgroundField) {
        const intensity = Math.max(0, breathe.backgroundFieldIntensity || 0);
        fieldLayer.style("opacity", Math.min(0.58, 0.12 + intensity * 0.33));
        if (nowMs - state.backgroundFieldLastUpdateMs >= 66) {
          state.backgroundFieldLastUpdateMs = nowMs;
          auraA
            .attr("cx", selections.width * (0.23 + Math.sin(t * 0.1) * 0.009))
            .attr("cy", selections.height * (0.3 + Math.cos(t * 0.11) * 0.009));
          auraB
            .attr("cx", selections.width * (0.78 + Math.cos(t * 0.09) * 0.011))
            .attr("cy", selections.height * (0.64 + Math.sin(t * 0.1) * 0.009));
        }
      } else {
        fieldLayer.style("opacity", 0);
      }
    }

    if (gridRect) {
      if (breathe.backgroundField) {
        const gridPulse = 0.46 + Math.sin(t * 0.35) * 0.04 * Math.max(0.1, breathe.backgroundFieldIntensity || 0);
        gridRect.attr("opacity", Math.max(0.34, gridPulse));
      } else {
        gridRect.attr("opacity", 0.5);
      }
    }

    state.animationFrameId = window.requestAnimationFrame(frame);
  }

  state.animationFrameId = window.requestAnimationFrame(frame);
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

function clearSankeyPanel(message) {
  if (sankeySummary) sankeySummary.textContent = message;
  if (sankeySvgEl) d3.select(sankeySvgEl).selectAll("*").remove();
  if (sankeyPathTable) sankeyPathTable.innerHTML = "";
  if (sankeyEmptyState) sankeyEmptyState.classList.remove("hidden");
  state.sankeyPathRows = [];
  state.sankeyKeywordGroups = new Map();
  state.sankeyPinnedKeyword = null;
  state.sankeySelectedPathKey = null;
  clearSankeyZoom();
  updateSankeyZoomControls();
  hideSankeyKeywordDetail();
  hideSankeyLinkDetail();
}

function compactSankeyLabel(value, maxLen = 24) {
  const text = String(value || "").trim();
  if (!text) return "(none)";
  return text.length <= maxLen ? text : `${text.slice(0, maxLen - 3)}...`;
}

function topLabelSet(rows, accessor, limit) {
  const counts = new Map();
  rows.forEach((row) => {
    const label = String(accessor(row) || "").trim() || "(none)";
    counts.set(label, (counts.get(label) || 0) + 1);
  });
  return new Set(
    [...counts.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, limit)
      .map(([label]) => label),
  );
}

function caseMatchesSankeyFilters(row) {
  const filters = state.sankeyFilters || {};
  if (filters.verifiedOnly && !row?.is_verified) return false;

  const predicted = String(row?.predicted_category || "").trim();
  const resolved = String(row?.resolved_category || "").trim();
  const isMatch = predicted && resolved && predicted === resolved;
  if (filters.outcome === "mismatch" && isMatch) return false;
  if (filters.outcome === "match" && !isMatch) return false;

  const term = String(filters.search || "").trim().toLowerCase();
  if (!term) return true;
  const keyword = String(row?.keyword || "").toLowerCase();
  const predictedText = predicted.toLowerCase();
  const resolvedText = resolved.toLowerCase();
  if (filters.field === "keyword") return keyword.includes(term);
  if (filters.field === "predicted") return predictedText.includes(term);
  if (filters.field === "resolved") return resolvedText.includes(term);
  return keyword.includes(term) || predictedText.includes(term) || resolvedText.includes(term);
}

function hideSankeyKeywordDetail() {
  if (!sankeyKeywordDetailPanel) return;
  sankeyKeywordDetailPanel.classList.add("hidden");
}

function hideSankeyLinkDetail() {
  if (!sankeyLinkDetailPanel) return;
  sankeyLinkDetailPanel.classList.add("hidden");
}

function topBuckets(rows, accessor, limit = 3) {
  const counts = new Map();
  rows.forEach((row) => {
    const key = String(accessor(row) || "").trim() || "Unknown";
    counts.set(key, (counts.get(key) || 0) + 1);
  });
  return [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, limit);
}

function renderSankeyKeywordDetail(keywordLabel, rows) {
  if (!sankeyKeywordDetailPanel || !sankeyKeywordDetailTitle || !sankeyKeywordDetailMeta || !sankeyKeywordDetailBody) return;
  if (!rows || !rows.length) {
    hideSankeyKeywordDetail();
    return;
  }
  const total = rows.length;
  const mismatchCount = rows.filter((row) => {
    const predicted = String(row?.predicted_category || "").trim();
    const resolved = String(row?.resolved_category || "").trim();
    return predicted && resolved && predicted !== resolved;
  }).length;
  const verifiedCount = rows.filter((row) => Boolean(row?.is_verified)).length;
  const confRows = rows
    .map((row) => Number(row?.confidence))
    .filter((value) => Number.isFinite(value));
  const avgConfidence = confRows.length ? confRows.reduce((acc, value) => acc + value, 0) / confRows.length : null;
  const topPredicted = topBuckets(rows, (row) => row?.predicted_category, 3)
    .map(([label, count]) => `${shortCategoryLabel(label)} (${count})`)
    .join(", ");
  const topResolved = topBuckets(rows, (row) => row?.resolved_category, 3)
    .map(([label, count]) => `${shortCategoryLabel(label)} (${count})`)
    .join(", ");
  const recentRows = rows
    .slice()
    .sort((a, b) => (timelineMsFromDate(b?.date) || 0) - (timelineMsFromDate(a?.date) || 0))
    .slice(0, 4)
    .map((row) => {
      const tx = row?.transaction_id ?? "-";
      const date = formatDate(row?.date);
      const resolved = shortCategoryLabel(row?.resolved_category || "Unknown");
      return `#${tx} ${date} -> ${resolved}`;
    });

  sankeyKeywordDetailTitle.textContent = keywordLabel || "Keyword";
  sankeyKeywordDetailMeta.innerHTML = [
    `<span class="node-detail-chip">Cases ${total}</span>`,
    `<span class="node-detail-chip">Mismatch ${formatPercent(total ? mismatchCount / total : 0)}</span>`,
    `<span class="node-detail-chip">Verified ${formatPercent(total ? verifiedCount / total : 0)}</span>`,
    `<span class="node-detail-chip">Avg conf ${formatPercent(avgConfidence)}</span>`,
  ].join("");
  sankeyKeywordDetailBody.textContent = [
    `Top predicted: ${topPredicted || "-"}`,
    `Top resolved: ${topResolved || "-"}`,
    "",
    "Recent transactions:",
    ...(recentRows.length ? recentRows : ["-"]),
  ].join("\n");
  sankeyKeywordDetailPanel.classList.remove("hidden");
}

function pathKey(keyword, predicted, resolved) {
  return `${keyword}|||${predicted}|||${resolved}`;
}

function pathParts(key) {
  const [keyword = "", predicted = "", resolved = ""] = String(key || "").split("|||");
  return { keyword, predicted, resolved };
}

function renderSankeyPathTable(pathRows) {
  if (!sankeyPathTable) return;
  if (!pathRows.length) {
    sankeyPathTable.innerHTML = `<div class="quality-line"><div class="quality-line-label">No ranked paths available for current mode/filters.</div></div>`;
    return;
  }
  const rowsHtml = pathRows
    .slice(0, 28)
    .map((row) => {
      const selected = state.sankeySelectedPathKey === row.key ? " class=\"is-selected\"" : "";
      const pathText = `${compactSankeyLabel(row.keyword, 16)} -> ${compactSankeyLabel(row.predicted, 16)} -> ${compactSankeyLabel(row.resolved, 16)}`;
      return `
        <tr data-path-key="${escapeHtml(row.key)}"${selected}>
          <td title="${escapeHtml(pathText)}">${escapeHtml(pathText)}</td>
          <td class="metric-cell">${row.count}</td>
          <td class="metric-cell">${formatPercent(row.count ? row.mismatchCount / row.count : 0)}</td>
          <td class="metric-cell">${formatPercent(row.avgConfidence)}</td>
          <td class="metric-cell">${escapeHtml(formatDate(row.lastSeenDate))}</td>
        </tr>`;
    })
    .join("");
  sankeyPathTable.innerHTML = `
    <table class="quality-table">
      <thead>
        <tr>
          <th>Path</th>
          <th>Count</th>
          <th>Mismatch</th>
          <th>Avg Conf</th>
          <th>Last Seen</th>
        </tr>
      </thead>
      <tbody>${rowsHtml}</tbody>
    </table>`;

  sankeyPathTable.querySelectorAll("tbody tr[data-path-key]").forEach((rowEl) => {
    rowEl.addEventListener("click", () => {
      const key = rowEl.getAttribute("data-path-key") || "";
      if (!key) return;
      state.sankeySelectedPathKey = key;
      state.sankeyPinnedKeyword = null;
      renderDecisionPathSankey(state.insightsData);
    });
  });
}

function renderSankeyLinkDetail(pathRow) {
  if (!sankeyLinkDetailPanel || !sankeyLinkDetailTitle || !sankeyLinkDetailMeta || !sankeyLinkDetailBody || !pathRow) return;
  const samples = (pathRow.rows || [])
    .slice()
    .sort((a, b) => (timelineMsFromDate(b?.date) || 0) - (timelineMsFromDate(a?.date) || 0))
    .slice(0, 6)
    .map((row) => {
      const txId = row?.transaction_id ?? "-";
      const date = formatDate(row?.date);
      const conf = formatPercent(row?.confidence);
      const reason = (row?.reason || "-").replace(/\s+/g, " ").trim();
      const shortReason = reason.length > 88 ? `${reason.slice(0, 85)}...` : reason;
      return `#${txId} ${date} | conf ${conf}\n${shortReason}`;
    });
  sankeyLinkDetailTitle.textContent = `${pathRow.keyword} -> ${shortCategoryLabel(pathRow.predicted)} -> ${shortCategoryLabel(pathRow.resolved)}`;
  sankeyLinkDetailMeta.innerHTML = [
    `<span class="node-detail-chip">Cases ${pathRow.count}</span>`,
    `<span class="node-detail-chip">Mismatch ${formatPercent(pathRow.count ? pathRow.mismatchCount / pathRow.count : 0)}</span>`,
    `<span class="node-detail-chip">Avg conf ${formatPercent(pathRow.avgConfidence)}</span>`,
    `<span class="node-detail-chip">Last seen ${escapeHtml(formatDate(pathRow.lastSeenDate))}</span>`,
  ].join("");
  sankeyLinkDetailBody.textContent = ["Sample transactions:", ...(samples.length ? samples : ["-"])].join("\n\n");
  sankeyLinkDetailPanel.classList.remove("hidden");
}

function findPathRowForLink(linkDatum) {
  const rows = state.sankeyPathRows || [];
  if (!rows.length || !linkDatum) return null;
  if (linkDatum.type === "kw-pred") {
    return (
      rows.find((row) => row.keyword === linkDatum.source.label && row.predicted === linkDatum.target.label) || null
    );
  }
  if (linkDatum.type === "pred-res") {
    return (
      rows.find((row) => row.predicted === linkDatum.source.label && row.resolved === linkDatum.target.label) || null
    );
  }
  return null;
}

function applySelectedPathHighlight(allLinks) {
  if (!allLinks) return;
  const selectedKey = state.sankeySelectedPathKey;
  if (!selectedKey) {
    allLinks.classed("is-selected-path", false).classed("is-dimmed-path", false);
    return;
  }
  const parts = pathParts(selectedKey);
  const belongs = (link) => {
    if (link.type === "kw-pred") {
      return link.source.label === parts.keyword && link.target.label === parts.predicted;
    }
    if (link.type === "pred-res") {
      return link.source.label === parts.predicted && link.target.label === parts.resolved;
    }
    return false;
  };
  allLinks.classed("is-selected-path", (link) => belongs(link)).classed("is-dimmed-path", (link) => !belongs(link));
}

function renderDecisionPathSankey(insightsPayload) {
  if (!sankeySvgEl || !sankeySummary) return;
  hideSankeyKeywordDetail();
  const sankeyFactory = d3.sankey;
  if (typeof sankeyFactory !== "function") {
    clearSankeyPanel("Sankey renderer failed to load (d3-sankey unavailable).");
    return;
  }

  const allCases = Array.isArray(insightsPayload?.case_inspector) ? insightsPayload.case_inspector : [];
  const cutoff = getTimelineCutoffMs();
  const hasTimeline = cutoff !== null;
  const timelineCases = allCases.filter((row) => {
    if (!hasTimeline) return true;
    const rowMs = timelineMsFromDate(row?.date);
    if (rowMs === null) return true;
    return rowMs <= cutoff;
  });
  const filteredCases = timelineCases.filter(caseMatchesSankeyFilters);
  const rawKeywordLabel = (row) => String(row?.keyword || "").trim() || "(none)";
  const rawPredictedLabel = (row) => String(row?.predicted_category || "").trim() || "Unknown";
  const rawResolvedLabel = (row) => String(row?.resolved_category || "").trim() || "Unknown";

  if (!filteredCases.length) {
    const term = String(state.sankeyFilters.search || "").trim();
    const hasUserFilters =
      term.length > 0 ||
      state.sankeyFilters.field !== "all" ||
      state.sankeyFilters.outcome !== "all" ||
      state.sankeyFilters.verifiedOnly;
    if (hasUserFilters) {
      clearSankeyPanel("No rows match the current Sankey filters.");
      return;
    }
    if (hasTimeline) {
      clearSankeyPanel(`No case inspector rows available up to ${timelinePointLabel(cutoff)}.`);
      return;
    }
    clearSankeyPanel("No case inspector rows available.");
    return;
  }

  syncSankeyCategoryLensOptions(filteredCases);
  const lensCases = state.sankeyCategoryLens
    ? filteredCases.filter((row) => rawResolvedLabel(row) === state.sankeyCategoryLens)
    : filteredCases;
  if (!lensCases.length) {
    clearSankeyPanel("No rows available for the selected category lens.");
    return;
  }

  const baseKeywordSet = topLabelSet(lensCases, rawKeywordLabel, 24);
  const basePredictedSet = topLabelSet(lensCases, rawPredictedLabel, 10);
  const baseResolvedSet = topLabelSet(lensCases, rawResolvedLabel, 10);

  let zoomedCases = lensCases;
  if (state.sankeyZoom.stage && state.sankeyZoom.label) {
    if (state.sankeyZoom.stage === "keyword") {
      if (state.sankeyZoom.label === "Other keywords") {
        zoomedCases = lensCases.filter((row) => !baseKeywordSet.has(rawKeywordLabel(row)));
      } else {
        zoomedCases = lensCases.filter((row) => rawKeywordLabel(row) === state.sankeyZoom.label);
      }
    } else if (state.sankeyZoom.stage === "predicted") {
      if (state.sankeyZoom.label === "Other predicted") {
        zoomedCases = lensCases.filter((row) => !basePredictedSet.has(rawPredictedLabel(row)));
      } else {
        zoomedCases = lensCases.filter((row) => rawPredictedLabel(row) === state.sankeyZoom.label);
      }
    } else if (state.sankeyZoom.stage === "resolved") {
      if (state.sankeyZoom.label === "Other resolved") {
        zoomedCases = lensCases.filter((row) => !baseResolvedSet.has(rawResolvedLabel(row)));
      } else {
        zoomedCases = lensCases.filter((row) => rawResolvedLabel(row) === state.sankeyZoom.label);
      }
    }
    if (!zoomedCases.length) {
      clearSankeyZoom();
      zoomedCases = lensCases;
    }
  }
  updateSankeyZoomControls();

  const mode = state.sankeyMode || "volume";
  const flowCases =
    mode === "error"
      ? zoomedCases.filter((row) => {
          const predicted = String(row?.predicted_category || "").trim();
          const resolved = String(row?.resolved_category || "").trim();
          return predicted && resolved && predicted !== resolved;
        })
      : zoomedCases;
  if (!flowCases.length) {
    clearSankeyPanel("No rows available for current Sankey mode.");
    return;
  }

  const keywordLimit = state.sankeyZoom.stage === "keyword" ? 46 : 24;
  const predictedLimit = state.sankeyZoom.stage === "predicted" ? 22 : 10;
  const resolvedLimit = state.sankeyZoom.stage === "resolved" ? 22 : 10;
  const keywords = topLabelSet(flowCases, (row) => row.keyword, keywordLimit);
  const predicted = topLabelSet(flowCases, (row) => row.predicted_category, predictedLimit);
  const resolved = topLabelSet(flowCases, (row) => row.resolved_category, resolvedLimit);

  const keywordCaseGroups = new Map();
  const pathMap = new Map();
  const normalizedRows = flowCases.map((row) => {
    const rawKeyword = String(row.keyword || "").trim() || "(none)";
    const rawPredicted = String(row.predicted_category || "").trim() || "Unknown";
    const rawResolved = String(row.resolved_category || "").trim() || "Unknown";
    const normalized = {
      keyword: keywords.has(rawKeyword) ? rawKeyword : "Other keywords",
      predicted: predicted.has(rawPredicted) ? rawPredicted : "Other predicted",
      resolved: resolved.has(rawResolved) ? rawResolved : "Other resolved",
    };
    const bucket = normalized.keyword;
    if (!keywordCaseGroups.has(bucket)) keywordCaseGroups.set(bucket, []);
    keywordCaseGroups.get(bucket).push(row);
    const pKey = pathKey(normalized.keyword, normalized.predicted, normalized.resolved);
    const entry = pathMap.get(pKey) || {
      key: pKey,
      keyword: normalized.keyword,
      predicted: normalized.predicted,
      resolved: normalized.resolved,
      count: 0,
      mismatchCount: 0,
      confTotal: 0,
      confCount: 0,
      lastSeenDate: null,
      rows: [],
    };
    entry.count += 1;
    const mismatch = rawPredicted && rawResolved && rawPredicted !== rawResolved;
    if (mismatch) entry.mismatchCount += 1;
    const conf = Number(row?.confidence);
    if (Number.isFinite(conf)) {
      entry.confTotal += conf;
      entry.confCount += 1;
    }
    const rowMs = timelineMsFromDate(row?.date);
    const lastMs = timelineMsFromDate(entry.lastSeenDate);
    if (rowMs !== null && (lastMs === null || rowMs > lastMs)) {
      entry.lastSeenDate = row?.date || null;
    }
    entry.rows.push(row);
    pathMap.set(pKey, entry);
    return normalized;
  });
  state.sankeyKeywordGroups = keywordCaseGroups;
  state.sankeyPathRows = [...pathMap.values()]
    .map((entry) => ({
      ...entry,
      avgConfidence: entry.confCount ? entry.confTotal / entry.confCount : null,
    }))
    .sort((a, b) => b.count - a.count);
  const minPathCases = Math.max(1, Math.round(Number(state.sankeyThresholds.minPathCases || 1)));
  const topPaths = Math.max(5, Math.min(200, Math.round(Number(state.sankeyThresholds.topPaths || 80))));
  const visiblePathRows = state.sankeyPathRows.filter((row) => row.count >= minPathCases).slice(0, topPaths);
  const visiblePathKeySet = new Set(visiblePathRows.map((row) => row.key));
  if (state.sankeySelectedPathKey && !visiblePathKeySet.has(state.sankeySelectedPathKey)) {
    state.sankeySelectedPathKey = null;
  }
  renderSankeyPathTable(visiblePathRows);

  const nodeMap = new Map();
  const linksMap = new Map();
  const ensureNode = (prefix, stage, label) => {
    const id = `${prefix}::${label}`;
    if (!nodeMap.has(id)) nodeMap.set(id, { id, stage, label });
    return id;
  };
  const linkContribution = (row) => {
    if (mode === "confidence") {
      const conf = Number(row?.confidence);
      return Number.isFinite(conf) ? Math.max(0.05, conf) : 0.2;
    }
    return 1;
  };
  const addLink = (source, target, type, contribution) => {
    const key = `${source}->${target}::${type}`;
    const current = linksMap.get(key) || { source, target, value: 0, type };
    current.value += contribution;
    linksMap.set(key, current);
  };

  normalizedRows.forEach((row, index) => {
    const sourceRow = flowCases[index];
    const pKey = pathKey(row.keyword, row.predicted, row.resolved);
    if (!visiblePathKeySet.has(pKey)) return;
    const keywordId = ensureNode("kw", "keyword", row.keyword);
    const predictedId = ensureNode("pred", "predicted", row.predicted);
    const resolvedId = ensureNode("res", "resolved", row.resolved);
    const contribution = linkContribution(sourceRow);
    addLink(keywordId, predictedId, "kw-pred", contribution);
    addLink(predictedId, resolvedId, "pred-res", contribution);
  });

  const nodes = [...nodeMap.values()];
  const links = [...linksMap.values()].filter((item) => item.value > 0);
  if (!nodes.length || !links.length) {
    clearSankeyPanel("Decision path data is insufficient for rendering.");
    return;
  }

  const chartRect = sankeySvgEl.getBoundingClientRect();
  const width = Math.max(320, Math.round(chartRect.width || sankeySvgEl.clientWidth || 720));
  const height = Math.max(260, Math.round(chartRect.height || sankeySvgEl.clientHeight || 420));

  const svgSankey = d3.select(sankeySvgEl);
  svgSankey.selectAll("*").remove();
  svgSankey.attr("viewBox", `0 0 ${width} ${height}`);
  svgSankey.classed("error-mode", mode === "error");

  const sankey = sankeyFactory()
    .nodeId((d) => d.id)
    .nodeWidth(14)
    .nodePadding(16)
    .extent([
      [12, 30],
      [width - 12, height - 14],
    ]);

  const layout = sankey({
    nodes: nodes.map((item) => ({ ...item })),
    links: links.map((item) => ({ ...item })),
  });

  svgSankey
    .append("g")
    .attr("fill", "none")
    .selectAll("path")
    .data(layout.links)
    .join("path")
    .attr("class", (d) => `sankey-link ${d.type}`)
    .attr("d", d3.sankeyLinkHorizontal())
    .attr("stroke-width", (d) => Math.max(1.2, d.width))
    .append("title")
    .text((d) => `${d.source.label} -> ${d.target.label}\n${d.value} decisions`);

  const nodeGroup = svgSankey.append("g").selectAll("g").data(layout.nodes).join("g");
  nodeGroup
    .append("rect")
    .attr("class", (d) => `sankey-node-rect is-${d.stage}${String(d.label || "").startsWith("Other ") ? " is-other" : ""}`)
    .attr("x", (d) => d.x0)
    .attr("y", (d) => d.y0)
    .attr("height", (d) => Math.max(1, d.y1 - d.y0))
    .attr("width", (d) => d.x1 - d.x0)
    .attr("rx", 3)
    .append("title")
    .text((d) => `${d.label}\n${d.value} cases`);

  const labelMinCases = Math.max(2, Math.round(flowCases.length * 0.03));
  const labelMinHeight = 14;
  nodeGroup
    .append("text")
    .attr("class", "sankey-label")
    .attr("x", (d) => (d.x0 < width / 2 ? d.x1 + 6 : d.x0 - 6))
    .attr("y", (d) => (d.y0 + d.y1) / 2)
    .attr("dy", "0.35em")
    .attr("text-anchor", (d) => (d.x0 < width / 2 ? "start" : "end"))
    .text((d) => {
      const heightPx = d.y1 - d.y0;
      if (d.stage === "keyword") return compactSankeyLabel(d.label, 26);
      if (Number(d.value || 0) < labelMinCases || heightPx < labelMinHeight) return "";
      return compactSankeyLabel(d.label, 22);
    });

  const stageX = {
    keyword: d3.min(layout.nodes.filter((n) => n.stage === "keyword"), (n) => n.x0) || 0,
    predicted: d3.min(layout.nodes.filter((n) => n.stage === "predicted"), (n) => n.x0) || width / 2,
    resolved: d3.min(layout.nodes.filter((n) => n.stage === "resolved"), (n) => n.x0) || width - 110,
  };
  svgSankey
    .append("g")
    .selectAll("text")
    .data([
      { key: "keyword", label: "Keywords" },
      { key: "predicted", label: "LLM Predicted" },
      { key: "resolved", label: "Resolved Category" },
    ])
    .join("text")
    .attr("class", "sankey-stage-label")
    .attr("x", (d) => stageX[d.key] + 2)
    .attr("y", 17)
    .text((d) => d.label);

  const allLinks = svgSankey.selectAll(".sankey-link");
  applySelectedPathHighlight(allLinks);
  nodeGroup
    .on("mouseenter", (_, node) => {
      allLinks.classed("is-muted", true).classed("is-active", false);
      allLinks
        .filter((l) => l.source.id === node.id || l.target.id === node.id)
        .classed("is-muted", false)
        .classed("is-active", true);
      if (state.sankeyPinnedKeyword || state.sankeySelectedPathKey) return;
      if (node.stage === "keyword") {
        renderSankeyKeywordDetail(node.label, state.sankeyKeywordGroups.get(node.label) || []);
      } else {
        hideSankeyKeywordDetail();
      }
    })
    .on("mouseleave", () => {
      allLinks.classed("is-muted", false).classed("is-active", false);
      if (!state.sankeyPinnedKeyword && !state.sankeySelectedPathKey) hideSankeyKeywordDetail();
    });

  allLinks
    .on("mouseenter", function () {
      allLinks.classed("is-muted", true).classed("is-active", false);
      d3.select(this).classed("is-muted", false).classed("is-active", true);
      if (!state.sankeyPinnedKeyword && !state.sankeySelectedPathKey) hideSankeyKeywordDetail();
    })
    .on("mouseleave", () => {
      allLinks.classed("is-muted", false).classed("is-active", false);
      applySelectedPathHighlight(allLinks);
    })
    .on("click", (event, linkDatum) => {
      event.stopPropagation();
      const row = findPathRowForLink(linkDatum);
      if (!row) return;
      state.sankeyPinnedKeyword = null;
      state.sankeySelectedPathKey = row.key;
      hideSankeyKeywordDetail();
      renderSankeyLinkDetail(row);
      applySelectedPathHighlight(allLinks);
      renderSankeyPathTable(visiblePathRows);
    });

  nodeGroup.on("click", (event, node) => {
    if (event.detail && event.detail > 1) return;
    event.stopPropagation();
    if (node.stage !== "keyword") return;
    if (state.sankeySelectedPathKey) {
      state.sankeySelectedPathKey = null;
      hideSankeyLinkDetail();
      applySelectedPathHighlight(allLinks);
      renderSankeyPathTable(visiblePathRows);
    }
    if (state.sankeyPinnedKeyword === node.label) {
      state.sankeyPinnedKeyword = null;
      hideSankeyKeywordDetail();
      return;
    }
    state.sankeyPinnedKeyword = node.label;
    renderSankeyKeywordDetail(node.label, state.sankeyKeywordGroups.get(node.label) || []);
  });

  nodeGroup.on("dblclick", (event, node) => {
    event.stopPropagation();
    if (node.stage !== "keyword" && node.stage !== "predicted" && node.stage !== "resolved") return;
    if (state.sankeyZoom.stage === node.stage && state.sankeyZoom.label === node.label) {
      clearSankeyZoom();
    } else {
      state.sankeyZoom.stage = node.stage;
      state.sankeyZoom.label = node.label;
    }
    state.sankeyPinnedKeyword = null;
    state.sankeySelectedPathKey = null;
    hideSankeyKeywordDetail();
    hideSankeyLinkDetail();
    renderDecisionPathSankey(state.insightsData);
  });

  svgSankey.on("click", () => {
    state.sankeyPinnedKeyword = null;
    state.sankeySelectedPathKey = null;
    hideSankeyKeywordDetail();
    hideSankeyLinkDetail();
    applySelectedPathHighlight(allLinks);
    renderSankeyPathTable(visiblePathRows);
  });

  if (state.sankeyPinnedKeyword) {
    const rows = state.sankeyKeywordGroups.get(state.sankeyPinnedKeyword) || [];
    if (!rows.length) {
      state.sankeyPinnedKeyword = null;
      hideSankeyKeywordDetail();
    } else {
      renderSankeyKeywordDetail(state.sankeyPinnedKeyword, rows);
    }
  }
  if (state.sankeySelectedPathKey) {
    const selected = state.sankeyPathRows.find((row) => row.key === state.sankeySelectedPathKey) || null;
    if (selected) {
      renderSankeyLinkDetail(selected);
    } else {
      hideSankeyLinkDetail();
    }
  } else {
    hideSankeyLinkDetail();
  }

  const rangeText = hasTimeline ? ` | through ${timelinePointLabel(cutoff)}` : "";
  const filteredText = timelineCases.length === filteredCases.length ? "" : ` | filtered ${filteredCases.length}/${timelineCases.length}`;
  const modeText = mode === "error" ? "Error flow" : mode === "confidence" ? "Confidence-weighted" : "Flow volume";
  const lensText = state.sankeyCategoryLens ? ` | lens ${shortCategoryLabel(state.sankeyCategoryLens)}` : "";
  const zoomText = state.sankeyZoom.stage ? ` | zoom ${state.sankeyZoom.stage}:${state.sankeyZoom.label}` : "";
  const thresholdText = ` | threshold >=${minPathCases}, top ${topPaths}`;
  sankeySummary.textContent =
    `${flowCases.length}/${allCases.length} cases${filteredText}${lensText}${thresholdText} | ${nodes.length} nodes | ${links.length} paths | ${modeText}${zoomText} | top ${keywordLimit}/${predictedLimit}/${resolvedLimit} buckets${rangeText}`;
  if (sankeyEmptyState) sankeyEmptyState.classList.add("hidden");
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
  if (sankeySummary) sankeySummary.textContent = "Loading decision paths...";
  try {
    const payload = await fetchJsonOrThrow(
      "/api/insights?case_limit=100&risk_limit=28&keyword_limit=42",
      "Insights API",
    );
    state.insightsData = payload;
    renderInsightsReport(payload);
    renderDecisionPathSankey(payload);
  } catch (error) {
    state.insightsData = null;
    clearInsightsPanels(`Could not load insights: ${error.message}`);
    clearSankeyPanel(`Could not load decision paths: ${error.message}`);
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
  const edgeData = graph.edges.map((item) => {
    const sid = typeof item.source === "object" ? item.source.id : item.source;
    const tid = typeof item.target === "object" ? item.target.id : item.target;
    return {
      ...item,
      source: sid,
      target: tid,
      timeline_ms: timelineMsForEdge(item),
      phase_seed: hashToUnit(`${sid}->${tid}:${item.edge_type}`) * Math.PI * 2,
    };
  });

  const nodeConfidence = new Map();
  edgeData.forEach((edge) => {
    const conf = Number(edge.avg_confidence);
    if (!Number.isFinite(conf)) return;
    const sid = sourceId(edge);
    const tid = targetId(edge);
    const left = nodeConfidence.get(sid) || { total: 0, count: 0 };
    const right = nodeConfidence.get(tid) || { total: 0, count: 0 };
    left.total += conf;
    left.count += 1;
    right.total += conf;
    right.count += 1;
    nodeConfidence.set(sid, left);
    nodeConfidence.set(tid, right);
  });
  nodeData.forEach((node) => {
    const confEntry = nodeConfidence.get(node.id);
    const avgConf = confEntry?.count ? confEntry.total / confEntry.count : 0.62;
    node.phase_seed = hashToUnit(node.id) * Math.PI * 2;
    node.phase_lag = node.kind === "category" ? 0 : node.kind === "keyword" ? 0.92 : 1.72;
    node.confidence_score = Math.max(0, Math.min(1, avgConf));
    node.confidence_pulse = 0.64 + (1 - node.confidence_score) * 0.92;
  });

  state.focusNodeId = null;
  state.focusEdgeId = null;
  state.pinnedNodeId = null;
  state.tagNodeId = null;
  state.backgroundFieldLastUpdateMs = 0;
  state.currentZoomTransform = d3.zoomIdentity;

  if (!nodeData.length || !edgeData.length) {
    setDetailPanel({
      title: "Selection",
      subtitle: "No graph edges found",
      chips: ["Empty graph"],
      body: ["Import or review transactions to build memory links."],
      txRows: [],
    });
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
  const field = createBackgroundField(width, height);

  const viewport = svg.append("g").attr("class", "viewport");

  const zoomBehavior = d3
    .zoom()
    .scaleExtent([0.25, 4.4])
    .on("zoom", (event) => {
      state.currentZoomTransform = event.transform;
      viewport.attr("transform", event.transform);
      if (grid?.updateGridTransform) grid.updateGridTransform(event.transform);
      updateZoomIndicator(event.transform);
      updateFloatingTagPosition();
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

  const nodeHit = nodeGroup
    .append("circle")
    .attr("class", "node-hit")
    .attr("r", (d) => {
      if (d.kind === "transaction") return Math.max(8, nodeRadius(d) + 3.5);
      return Math.max(14, nodeRadius(d) + 8.5);
    })
    .attr("fill", "transparent")
    .style("pointer-events", "all");

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

  const floatingTag = svg
    .append("g")
    .attr("class", "floating-node-tag")
    .style("display", null)
    .style("visibility", "hidden");
  const floatingTagRect = floatingTag.append("rect").attr("rx", 3).attr("ry", 3);
  const floatingTagText = floatingTag.append("text");

  function fitTagText(raw) {
    const text = (raw || "").trim().toUpperCase();
    if (text.length <= 34) return text;
    return `${text.slice(0, 31)}...`;
  }

  function fitTagTextToWidth(raw, maxWidth) {
    const base = fitTagText(raw);
    floatingTagText.text(base);
    if (!Number.isFinite(maxWidth) || maxWidth <= 40) return base;
    let next = base;
    while (next.length > 4 && floatingTagText.node().getComputedTextLength() > maxWidth) {
      next = `${next.slice(0, -4)}...`;
      floatingTagText.text(next);
    }
    return next;
  }

  function updateFloatingTagPosition() {
    if (!state.tagNodeId) {
      floatingTag.style("visibility", "hidden");
      return;
    }

    const node = nodeData.find((row) => row.id === state.tagNodeId);
    if (!node || !Number.isFinite(node.x) || !Number.isFinite(node.y)) {
      floatingTag.style("visibility", "hidden");
      return;
    }

    const visibility = collectVisibilitySets();
    if (!visibility.visibleNodeIds.has(node.id)) {
      floatingTag.style("visibility", "hidden");
      return;
    }

    floatingTag.style("visibility", "hidden");
    const label = fitTagTextToWidth(node.label, Math.max(56, width - 36));
    floatingTagText.text(label);
    const bbox = floatingTagText.node().getBBox();
    const horizontalPad = 8;
    const verticalPad = 4;
    const tagWidth = bbox.width + horizontalPad * 2;
    const tagHeight = bbox.height + verticalPad * 2;
    const transform = state.currentZoomTransform || d3.zoomIdentity;
    const sx = transform.applyX(node.x);
    const sy = transform.applyY(node.y);
    const visualNodeRadius = nodeRadius(node) * transform.k;
    let x = sx - tagWidth / 2;
    let y = sy + Math.max(12, visualNodeRadius + 10);

    const padding = 6;
    x = Math.max(padding, Math.min(width - tagWidth - padding, x));
    if (y + tagHeight > height - padding) {
      y = sy - tagHeight - Math.max(10, visualNodeRadius + 6);
    }
    y = Math.max(padding, Math.min(height - tagHeight - padding, y));

    floatingTagRect
      .attr("x", x)
      .attr("y", y)
      .attr("width", tagWidth)
      .attr("height", tagHeight);

    floatingTagText.attr("x", x + horizontalPad).attr("y", y + tagHeight - verticalPad - 1);
    floatingTag.style("visibility", null);
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
      emitInteractionRipple(node);
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
      emitInteractionRipple(node);
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
    viewport,
    nodeGroup,
    nodeHit,
    nodeRing,
    nodeCore,
    nodeLabel,
    link,
    edgeLabel,
    strokeScale,
    edgeById: new Map(edgeData.map((edge) => [edge.id, edge])),
    width,
    height,
    simulation,
    gridRect: grid?.gridRect || null,
    fieldLayer: field?.fieldLayer || null,
    auraA: field?.auraA || null,
    auraB: field?.auraB || null,
  };

  setupTimeline(graph, nodeData, edgeData);
  applyVisualState();
  startBreathingLoop();
  setDefaultDetail();
  updateFloatingTagPosition();
}

async function loadGraph() {
  stopTimelinePlayback();
  stopBreathingLoop();
  statsPill.textContent = "Loading graph...";
  setDetailPanel({
    title: "Selection",
    subtitle: "Loading keyword-category memory links...",
    chips: ["Loading"],
    body: [],
    txRows: [],
  });
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
    setDetailPanel({
      title: "Selection",
      subtitle: "Could not load graph data.",
      chips: ["Load error"],
      body: [error.message],
      txRows: [],
    });
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
    persistSettings();
    updateSettingsSectionSummaries();
    applyVisualState();
  });
}

if (nodeTextToggle) {
  nodeTextToggle.addEventListener("change", () => {
    state.showNodeText = nodeTextToggle.checked;
    persistSettings();
    updateSettingsSectionSummaries();
    applyVisualState();
  });
}

if (llmMissToggle) {
  llmMissToggle.addEventListener("change", () => {
    state.showInitialMissLinks = llmMissToggle.checked;
    persistSettings();
    updateSettingsSectionSummaries();
    applyVisualState();
  });
}

if (connectedNodeSizeRange) {
  connectedNodeSizeRange.addEventListener("input", () => {
    state.connectedNodeScale = Number(connectedNodeSizeRange.value) / 100;
    syncConnectedNodeScaleLabel();
    persistSettings();
    updateSettingsSectionSummaries();
    if (state.graph) renderGraph(state.graph);
  });
}

function refreshBreathingRuntime() {
  syncBreathingLabels();
  updateSettingsSectionSummaries();
  persistSettings();
  if (!state.selections) return;
  startBreathingLoop();
}

if (breatheEnabledToggle) {
  breatheEnabledToggle.addEventListener("change", () => {
    state.breathe.enabled = breatheEnabledToggle.checked;
    refreshBreathingRuntime();
  });
}

if (globalPulseToggle) {
  globalPulseToggle.addEventListener("change", () => {
    state.breathe.globalPulse = globalPulseToggle.checked;
    refreshBreathingRuntime();
  });
}

if (globalPulseIntensityRange) {
  globalPulseIntensityRange.addEventListener("input", () => {
    state.breathe.globalPulseIntensity = Number(globalPulseIntensityRange.value || 0) / 100;
    syncBreathingLabels();
    persistSettings();
  });
}

if (globalPulseSpeedRange) {
  globalPulseSpeedRange.addEventListener("input", () => {
    state.breathe.globalPulseSpeed = Number(globalPulseSpeedRange.value || 0) / 100;
    syncBreathingLabels();
    persistSettings();
  });
}

if (phaseLagToggle) {
  phaseLagToggle.addEventListener("change", () => {
    state.breathe.phaseLag = phaseLagToggle.checked;
    refreshBreathingRuntime();
  });
}

if (edgeShimmerToggle) {
  edgeShimmerToggle.addEventListener("change", () => {
    state.breathe.edgeShimmer = edgeShimmerToggle.checked;
    refreshBreathingRuntime();
  });
}

if (edgeShimmerIntensityRange) {
  edgeShimmerIntensityRange.addEventListener("input", () => {
    state.breathe.edgeShimmerIntensity = Number(edgeShimmerIntensityRange.value || 0) / 100;
    syncBreathingLabels();
    persistSettings();
  });
}

if (interactionRippleToggle) {
  interactionRippleToggle.addEventListener("change", () => {
    state.breathe.interactionRipple = interactionRippleToggle.checked;
    refreshBreathingRuntime();
  });
}

if (interactionRippleStrengthRange) {
  interactionRippleStrengthRange.addEventListener("input", () => {
    state.breathe.interactionRippleStrength = Number(interactionRippleStrengthRange.value || 0) / 100;
    syncBreathingLabels();
    persistSettings();
  });
}

if (ambientDriftToggle) {
  ambientDriftToggle.addEventListener("change", () => {
    state.breathe.ambientDrift = ambientDriftToggle.checked;
    refreshBreathingRuntime();
  });
}

if (ambientDriftStrengthRange) {
  ambientDriftStrengthRange.addEventListener("input", () => {
    state.breathe.ambientDriftStrength = Number(ambientDriftStrengthRange.value || 0) / 100;
    syncBreathingLabels();
    persistSettings();
  });
}

if (confidencePulseToggle) {
  confidencePulseToggle.addEventListener("change", () => {
    state.breathe.confidencePulse = confidencePulseToggle.checked;
    refreshBreathingRuntime();
  });
}

if (timelineHeartbeatToggle) {
  timelineHeartbeatToggle.addEventListener("change", () => {
    state.breathe.timelineHeartbeat = timelineHeartbeatToggle.checked;
    if (!state.breathe.timelineHeartbeat) state.timelinePulse = 0;
    refreshBreathingRuntime();
  });
}

if (timelineHeartbeatStrengthRange) {
  timelineHeartbeatStrengthRange.addEventListener("input", () => {
    state.breathe.timelineHeartbeatStrength = Number(timelineHeartbeatStrengthRange.value || 0) / 100;
    syncBreathingLabels();
    persistSettings();
  });
}

if (backgroundFieldToggle) {
  backgroundFieldToggle.addEventListener("change", () => {
    state.breathe.backgroundField = backgroundFieldToggle.checked;
    refreshBreathingRuntime();
  });
}

if (backgroundFieldIntensityRange) {
  backgroundFieldIntensityRange.addEventListener("input", () => {
    state.breathe.backgroundFieldIntensity = Number(backgroundFieldIntensityRange.value || 0) / 100;
    syncBreathingLabels();
    persistSettings();
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

if (nodeDrawerToggleBtn) {
  nodeDrawerToggleBtn.addEventListener("click", () => {
    setNodeDrawerOpen(!state.nodeDrawerOpen);
  });
}

if (nodeDetailCloseBtn) {
  nodeDetailCloseBtn.addEventListener("click", () => {
    setNodeDrawerOpen(false);
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

if (graphViewTabBtn) {
  graphViewTabBtn.addEventListener("click", () => {
    setActiveView("graph");
  });
}

if (sankeyViewTabBtn) {
  sankeyViewTabBtn.addEventListener("click", () => {
    setActiveView("sankey");
  });
}

if (sankeyModeSelect) {
  sankeyModeSelect.addEventListener("change", () => {
    state.sankeyMode = sankeyModeSelect.value || "volume";
    state.sankeySelectedPathKey = null;
    persistSettings();
    if (state.activeView === "sankey") renderDecisionPathSankey(state.insightsData);
  });
}

if (sankeyZoomResetBtn) {
  sankeyZoomResetBtn.addEventListener("click", () => {
    clearSankeyZoom();
    state.sankeyPinnedKeyword = null;
    state.sankeySelectedPathKey = null;
    hideSankeyKeywordDetail();
    hideSankeyLinkDetail();
    if (state.activeView === "sankey") renderDecisionPathSankey(state.insightsData);
  });
}

if (sankeySearchInput) {
  sankeySearchInput.addEventListener("input", () => {
    state.sankeyFilters.search = sankeySearchInput.value || "";
    state.sankeySelectedPathKey = null;
    persistSettings();
    if (state.activeView === "sankey") renderDecisionPathSankey(state.insightsData);
  });
}

if (sankeyFieldFilter) {
  sankeyFieldFilter.addEventListener("change", () => {
    state.sankeyFilters.field = sankeyFieldFilter.value || "all";
    state.sankeySelectedPathKey = null;
    persistSettings();
    if (state.activeView === "sankey") renderDecisionPathSankey(state.insightsData);
  });
}

if (sankeyOutcomeFilter) {
  sankeyOutcomeFilter.addEventListener("change", () => {
    state.sankeyFilters.outcome = sankeyOutcomeFilter.value || "all";
    state.sankeySelectedPathKey = null;
    persistSettings();
    if (state.activeView === "sankey") renderDecisionPathSankey(state.insightsData);
  });
}

if (sankeyCategoryLensSelect) {
  sankeyCategoryLensSelect.addEventListener("change", () => {
    state.sankeyCategoryLens = sankeyCategoryLensSelect.value || "";
    clearSankeyZoom();
    state.sankeyPinnedKeyword = null;
    state.sankeySelectedPathKey = null;
    persistSettings();
    if (state.activeView === "sankey") renderDecisionPathSankey(state.insightsData);
  });
}

if (sankeyVerifiedOnlyToggle) {
  sankeyVerifiedOnlyToggle.addEventListener("change", () => {
    state.sankeyFilters.verifiedOnly = sankeyVerifiedOnlyToggle.checked;
    state.sankeySelectedPathKey = null;
    persistSettings();
    if (state.activeView === "sankey") renderDecisionPathSankey(state.insightsData);
  });
}

if (sankeyMinCasesInput) {
  sankeyMinCasesInput.addEventListener("change", () => {
    state.sankeyThresholds.minPathCases = clampNumber(sankeyMinCasesInput.value, 1, 10000, 1);
    state.sankeySelectedPathKey = null;
    persistSettings();
    if (state.activeView === "sankey") renderDecisionPathSankey(state.insightsData);
  });
}

if (sankeyTopPathsInput) {
  sankeyTopPathsInput.addEventListener("change", () => {
    state.sankeyThresholds.topPaths = clampNumber(sankeyTopPathsInput.value, 5, 200, 80);
    state.sankeySelectedPathKey = null;
    persistSettings();
    if (state.activeView === "sankey") renderDecisionPathSankey(state.insightsData);
  });
}

if (sankeyFilterResetBtn) {
  sankeyFilterResetBtn.addEventListener("click", () => {
    state.sankeyFilters.search = "";
    state.sankeyFilters.field = "all";
    state.sankeyFilters.outcome = "all";
    state.sankeyFilters.verifiedOnly = false;
    state.sankeyCategoryLens = "";
    state.sankeyThresholds.minPathCases = 1;
    state.sankeyThresholds.topPaths = 80;
    state.sankeySelectedPathKey = null;
    clearSankeyZoom();
    applySankeyFilterControls();
    persistSettings();
    if (state.activeView === "sankey") renderDecisionPathSankey(state.insightsData);
  });
}

if (sankeyKeywordDetailCloseBtn) {
  sankeyKeywordDetailCloseBtn.addEventListener("click", () => {
    state.sankeyPinnedKeyword = null;
    hideSankeyKeywordDetail();
  });
}

if (sankeyLinkDetailCloseBtn) {
  sankeyLinkDetailCloseBtn.addEventListener("click", () => {
    state.sankeySelectedPathKey = null;
    hideSankeyLinkDetail();
    if (state.activeView === "sankey") renderDecisionPathSankey(state.insightsData);
  });
}

if (nodeTxPrevBtn) {
  nodeTxPrevBtn.addEventListener("click", () => {
    state.nodeDetailPage = Math.max(0, state.nodeDetailPage - 1);
    renderNodeTablePage();
  });
}

if (nodeTxNextBtn) {
  nodeTxNextBtn.addEventListener("click", () => {
    state.nodeDetailPage += 1;
    renderNodeTablePage();
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

if (helpPopoverClose) {
  helpPopoverClose.addEventListener("click", () => {
    closeHelpPopover();
  });
}

document.addEventListener("click", (event) => {
  const trigger = event.target.closest(".help-trigger");
  const clickedPopover = event.target.closest("#helpPopover");
  if (trigger) {
    event.preventDefault();
    event.stopPropagation();
    const key = trigger.dataset.helpKey || "";
    if (!key) return;
    const isSame = !helpPopover?.classList.contains("hidden") && helpPopover?.dataset.key === key;
    if (isSame) {
      closeHelpPopover();
      return;
    }
    openHelpPopover(key, trigger);
    return;
  }
  if (!clickedPopover) {
    closeHelpPopover();
  }
});

window.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeHelpPopover();
  }
});

window.addEventListener("resize", () => {
  closeHelpPopover();
});

window.addEventListener("resize", () => {
  if (state.activeView === "graph" && state.graph) renderGraph(state.graph);
  if (state.activeView === "sankey" && state.insightsData) renderDecisionPathSankey(state.insightsData);
});

window.addEventListener("beforeunload", () => {
  stopTimelinePlayback();
  stopBreathingLoop();
});

loadPersistedSettings();

if (edgeTextToggle) edgeTextToggle.checked = state.showEdgeText;
if (nodeTextToggle) nodeTextToggle.checked = state.showNodeText;
if (llmMissToggle) llmMissToggle.checked = state.showInitialMissLinks;
if (connectedNodeSizeRange) {
  connectedNodeSizeRange.value = String(Math.round(state.connectedNodeScale * 100));
}
if (breatheEnabledToggle) breatheEnabledToggle.checked = state.breathe.enabled;
if (globalPulseToggle) globalPulseToggle.checked = state.breathe.globalPulse;
if (globalPulseIntensityRange) {
  globalPulseIntensityRange.value = String(Math.round(state.breathe.globalPulseIntensity * 100));
}
if (globalPulseSpeedRange) {
  globalPulseSpeedRange.value = String(Math.round(state.breathe.globalPulseSpeed * 100));
}
if (phaseLagToggle) phaseLagToggle.checked = state.breathe.phaseLag;
if (edgeShimmerToggle) edgeShimmerToggle.checked = state.breathe.edgeShimmer;
if (edgeShimmerIntensityRange) {
  edgeShimmerIntensityRange.value = String(Math.round(state.breathe.edgeShimmerIntensity * 100));
}
if (interactionRippleToggle) interactionRippleToggle.checked = state.breathe.interactionRipple;
if (interactionRippleStrengthRange) {
  interactionRippleStrengthRange.value = String(Math.round(state.breathe.interactionRippleStrength * 100));
}
if (ambientDriftToggle) ambientDriftToggle.checked = state.breathe.ambientDrift;
if (ambientDriftStrengthRange) {
  ambientDriftStrengthRange.value = String(Math.round(state.breathe.ambientDriftStrength * 100));
}
if (confidencePulseToggle) confidencePulseToggle.checked = state.breathe.confidencePulse;
if (timelineHeartbeatToggle) timelineHeartbeatToggle.checked = state.breathe.timelineHeartbeat;
if (timelineHeartbeatStrengthRange) {
  timelineHeartbeatStrengthRange.value = String(Math.round(state.breathe.timelineHeartbeatStrength * 100));
}
if (backgroundFieldToggle) backgroundFieldToggle.checked = state.breathe.backgroundField;
if (backgroundFieldIntensityRange) {
  backgroundFieldIntensityRange.value = String(Math.round(state.breathe.backgroundFieldIntensity * 100));
}
if (timelineSlider) {
  timelineSlider.disabled = true;
  timelineSlider.value = "0";
}
if (timelinePlayBtn) timelinePlayBtn.disabled = true;
syncConnectedNodeScaleLabel();
syncBreathingLabels();
applySankeyFilterControls();
updateSettingsSectionSummaries();
updateTimelineLabel();
setNodeDrawerOpen(state.nodeDrawerOpen);
setDrawerOpen(state.drawerOpen);
setQualityDrawerOpen(state.qualityDrawerOpen);
setInsightsDrawerOpen(state.insightsDrawerOpen);
setActiveView(state.activeView);
clearInsightsPanels("Loading insights...");
if (sankeySummary) sankeySummary.textContent = "Loading decision paths...";
loadGraph();
