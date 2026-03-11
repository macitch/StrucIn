"use strict";

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

const state = {
  data: null,
  filteredNodes: [],
  selectedModule: null,
};

function el(id) {
  return document.getElementById(id);
}

function setSummary(data) {
  el("summary").textContent =
    `${data.file_count} Python files | ${data.module_count} modules | ` +
    `${data.edges.length} dependencies | ${data.cycles.length} cycles`;
}

function buildLookup(files) {
  const map = new Map();
  for (const file of files) {
    map.set(file.module_path, file);
  }
  return map;
}

function polarLayout(nodes, width, height) {
  const cx = width / 2;
  const cy = height / 2;
  const radius = Math.min(width, height) * 0.36;
  const positions = new Map();
  nodes.forEach((node, index) => {
    const angle = (index / Math.max(nodes.length, 1)) * Math.PI * 2;
    positions.set(node, {
      x: cx + Math.cos(angle) * radius,
      y: cy + Math.sin(angle) * radius,
    });
  });
  return positions;
}

function renderModuleList(nodes) {
  const list = el("moduleList");
  list.innerHTML = "";
  nodes.forEach((moduleName) => {
    const li = document.createElement("li");
    li.textContent = moduleName;
    if (moduleName === state.selectedModule) {
      li.classList.add("active");
    }
    li.onclick = () => {
      state.selectedModule = moduleName;
      render();
    };
    list.appendChild(li);
  });
}

function renderDetails(lookup) {
  const details = el("details");
  if (!state.selectedModule) {
    details.innerHTML = "<p>Select a module in the graph or list.</p>";
    return;
  }
  const item = lookup.get(state.selectedModule);
  if (!item) {
    details.innerHTML = `<p>No details available for ${escapeHtml(state.selectedModule)}</p>`;
    return;
  }

  const imports = item.imports.length;
  const functions = item.functions.length;
  const classes = item.classes.length;
  const doc = item.docstring ? escapeHtml(item.docstring) : "(none)";
  details.innerHTML = `
    <p><strong>Module:</strong> ${escapeHtml(item.module_path)}</p>
    <p><strong>Path:</strong> ${escapeHtml(item.path)}</p>
    <p><strong>LOC:</strong> ${item.loc}</p>
    <p><strong>Fan In / Fan Out:</strong> ${item.fan_in} / ${item.fan_out}</p>
    <p><strong>Complexity:</strong> ${item.cyclomatic_complexity}</p>
    <p><strong>Imports:</strong> ${imports}</p>
    <p><strong>Classes:</strong> ${classes}</p>
    <p><strong>Functions:</strong> ${functions}</p>
    <p><strong>Docstring:</strong> ${doc}</p>
  `;
}

function edgeIsActive(edge, selected) {
  if (!selected) {
    return false;
  }
  return edge.source === selected || edge.target === selected;
}

function renderGraph(nodes, edges) {
  const graph = el("graph");
  graph.innerHTML = "";
  const viewBox = graph.viewBox.baseVal;
  const positions = polarLayout(nodes, viewBox.width, viewBox.height);
  const activeSet = new Set(nodes);

  edges.forEach((edge) => {
    if (!activeSet.has(edge.source) || !activeSet.has(edge.target)) {
      return;
    }
    const source = positions.get(edge.source);
    const target = positions.get(edge.target);
    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", String(source.x));
    line.setAttribute("y1", String(source.y));
    line.setAttribute("x2", String(target.x));
    line.setAttribute("y2", String(target.y));
    line.classList.add("graph-edge");
    if (edgeIsActive(edge, state.selectedModule)) {
      line.classList.add("active");
    }
    graph.appendChild(line);
  });

  nodes.forEach((node) => {
    const pos = positions.get(node);
    const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    circle.setAttribute("cx", String(pos.x));
    circle.setAttribute("cy", String(pos.y));
    circle.setAttribute("r", "7");
    circle.classList.add("graph-node");
    if (state.selectedModule === node) {
      circle.classList.add("active");
    }
    circle.onclick = () => {
      state.selectedModule = node;
      render();
    };
    const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
    title.textContent = node;
    circle.appendChild(title);
    graph.appendChild(circle);
  });
}

function applyFilter(rawNodes) {
  const query = el("nodeFilter").value.trim().toLowerCase();
  if (!query) {
    return rawNodes;
  }
  return rawNodes.filter((node) => node.toLowerCase().includes(query));
}

function render() {
  const data = state.data;
  const nodes = applyFilter(data.nodes);
  state.filteredNodes = nodes;
  if (state.selectedModule && !nodes.includes(state.selectedModule)) {
    state.selectedModule = null;
  }
  renderModuleList(nodes);
  renderGraph(nodes, data.edges);
  renderDetails(buildLookup(data.files));
}

async function bootstrap() {
  const res = await fetch("./data.json");
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: failed to fetch data.json`);
  }

  let data;
  try {
    data = await res.json();
  } catch (err) {
    throw new Error(`data.json is not valid JSON: ${err}`);
  }

  const required = ["file_count", "module_count", "files", "nodes", "edges", "cycles"];
  const missing = required.filter((k) => !(k in data));
  if (missing.length > 0) {
    throw new Error(`data.json is missing required fields: ${missing.join(", ")}`);
  }

  state.data = data;
  setSummary(state.data);
  el("nodeFilter").addEventListener("input", () => render());
  render();
}

bootstrap().catch((err) => {
  console.error(err);
  el("summary").textContent = `Failed to load dashboard data: ${err}`;
});
