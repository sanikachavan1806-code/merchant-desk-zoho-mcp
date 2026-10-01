const STEPS = [
  { id: "brief", group: "today", icon: "sun", agent: "Morning brief", reads: "Orders, risks", label: "Today", question: "What needs attention today?", tool: "get_daily_operations_brief", url: "/api/brief", call: "get_daily_operations_brief()" },
  { id: "risks", group: "today", icon: "alert", agent: "Risk scan", reads: "Stock, shipments, invoices", label: "Risks", question: "Which items need a person?", tool: "detect_operational_risks", url: "/api/risks", call: "detect_operational_risks()" },
  { id: "actions", group: "today", icon: "list", agent: "Next steps", reads: "Risk findings", label: "Next steps", question: "What should I do?", tool: "recommend_next_actions", url: "/api/actions", call: "recommend_next_actions()" },
  { id: "health", group: "today", icon: "pulse", agent: "Order health", reads: "One sales order", label: "SO-1002", question: "What's wrong with SO-1002?", tool: "get_order_health", url: "/api/orders/SO-1002/health", call: "get_order_health(\"SO-1002\")" },
  { id: "payments", group: "money", icon: "receipt", agent: "Payment match", reads: "Orders, payment ids", label: "Paid, no invoice", question: "Which paid orders are not invoiced?", tool: "match_order_to_payment", url: "/api/payments?only_paid_not_invoiced=true", call: "match_order_to_payment(only_paid_not_invoiced=true)" },
  { id: "reconcile", group: "money", icon: "flag", agent: "Reconcile", reads: "Orders, invoices, payments", label: "Not shipped", question: "Which paid orders haven't shipped?", tool: "reconcile_orders", url: "/api/reconcile", call: "reconcile_orders()" },
  { id: "gst", group: "money", icon: "tax", agent: "GST", reads: "Invoices", label: "GST", question: "How much GST did September collect?", tool: "gst_summary", url: "/api/gst?period=2026-09", call: "gst_summary(period=\"2026-09\")" },
  { id: "invoices", group: "money", icon: "receipt", agent: "Invoices", reads: "Open balances", label: "Open invoices", question: "Which invoices are still open?", tool: "list_invoices", url: "/api/invoices", call: "list_invoices()" },
  { id: "dead", group: "money", icon: "cash", agent: "Cash in stock", reads: "Items, sales", label: "Cash in stock", question: "Where is cash tied up?", tool: "dead_stock", url: "/api/dead-stock?days=30", call: "dead_stock(days=30)" },
  { id: "anomalies", group: "money", icon: "alert", agent: "Anomalies", reads: "Orders, rates, payments", label: "Unusual", question: "Anything unusual lately?", tool: "detect_anomalies", url: "/api/anomalies", call: "detect_anomalies()" },
  { id: "fulfill", group: "stock", icon: "warehouse", agent: "Warehouse check", reads: "Item stock by warehouse", label: "Check a warehouse", question: "Can Bengaluru ship 6 Mini Speakers?", tool: "find_alternate_fulfillment", url: "/api/fulfillment", call: "find_alternate_fulfillment(\"SKU-SPEAKER-MINI\", 6, \"wh_blr\")", init: { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ sku: "SKU-SPEAKER-MINI", quantity: 6, source_warehouse_id: "wh_blr" }) } },
  { id: "shipments", group: "stock", icon: "truck", agent: "Shipments", reads: "Shipment records", label: "Shipments", question: "What has left the warehouses?", tool: "list_shipments", url: "/api/shipments?limit=50", call: "list_shipments()" },
  { id: "low", group: "stock", icon: "box", agent: "Low stock", reads: "Items vs reorder", label: "Low stock", question: "What is below reorder?", tool: "list_inventory", url: "/api/inventory?low_stock_only=true", call: "list_inventory(low_stock_only=true)" },
  { id: "explain", group: "stock", icon: "ear", agent: "Explain", reads: "7-day demand", label: "Why earbuds?", question: "Why replenish Mumbai earbuds?", tool: "explain_recommendation", url: "/api/explain?id=stockout%3ASKU-EARBUD-PRO%3Awh_mum", call: "explain_recommendation(\"stockout:SKU-EARBUD-PRO:wh_mum\")" },
  { id: "customer", group: "account", icon: "user", agent: "Customer", reads: "Contact, masked", label: "Customer", question: "Show Rahul's contact", tool: "get_customer", url: "/api/customer/cus_rahul?include_pii=true", call: "get_customer(\"cus_rahul\")" },
  { id: "budget", group: "account", icon: "gauge", agent: "Quota", reads: "Call counter", label: "API budget", question: "How much Zoho quota is left?", tool: "get_api_budget", url: "/api/budget", call: "get_api_budget()" },
  { id: "propose", group: "account", icon: "lock", agent: "Write guard", reads: "Nothing written", label: "Move stock", question: "Move 20 speakers to Bengaluru", tool: "propose_action", url: "/api/propose", danger: true, call: "propose_action(\"transfer_stock\")", init: { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ action_type: "transfer_stock", reason: "Bengaluru is short", payload: { sku: "SKU-SPEAKER-MINI", quantity: 20 } }) } },
];

const ICONS = {
  sun: '<circle cx="12" cy="12" r="3.2" fill="currentColor"/><path d="M12 4v2.2M12 17.8V20M4 12h2.2M17.8 12H20M6.2 6.2l1.6 1.6M16.2 16.2l1.6 1.6M17.8 6.2l-1.6 1.6M7.8 16.2l-1.6 1.6" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round"/>',
  alert: '<path d="M12 4.5 20 19H4L12 4.5Z" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M12 10v4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><circle cx="12" cy="16.2" r="0.8" fill="currentColor"/>',
  list: '<path d="M8 7h11M8 12h11M8 17h11" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><circle cx="5" cy="7" r="1" fill="currentColor"/><circle cx="5" cy="12" r="1" fill="currentColor"/><circle cx="5" cy="17" r="1" fill="currentColor"/>',
  pulse: '<path d="M3 12h4l2-5 3 10 2-5h7" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>',
  receipt: '<path d="M7 4h10v16l-2-1.4L13 20l-2-1.4L9 20l-2-1.4V4Z" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M9.5 8h5M9.5 11.5h5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
  truck: '<path d="M3 8h11v8H3V8Z" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M14 11h4l3 3v2h-7v-5Z" fill="none" stroke="currentColor" stroke-width="1.6"/><circle cx="7" cy="17.5" r="1.4" fill="currentColor"/><circle cx="17" cy="17.5" r="1.4" fill="currentColor"/>',
  tax: '<path d="M6 18V6h8l4 4v8H6Z" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M9 13h6M12 10v6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
  cash: '<rect x="3.5" y="6" width="17" height="12" rx="2" fill="none" stroke="currentColor" stroke-width="1.6"/><circle cx="12" cy="12" r="2.2" fill="none" stroke="currentColor" stroke-width="1.6"/>',
  flag: '<path d="M6 20V4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><path d="M6 5h11l-2 3.5L17 12H6" fill="currentColor"/>',
  warehouse: '<path d="M3 10.5 12 5l9 5.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M5 10.5V19h14v-8.5" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M9 19v-5h6v5" fill="none" stroke="currentColor" stroke-width="1.6"/>',
  box: '<path d="M4 8.5 12 4.5l8 4V19l-8 4-8-4V8.5Z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M4 8.5 12 13l8-4.5M12 13v10" stroke="currentColor" stroke-width="1.6"/>',
  ear: '<path d="M8 13a4 4 0 1 1 8 0c0 2.4-1.2 3.6-2.4 4.4-.8.5-1.1 1-1.1 1.8" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><path d="M10.2 13.2a1.8 1.8 0 0 1 3.2 1.1c0 .8-.5 1.3-1.2 1.7" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
  user: '<circle cx="12" cy="9" r="3" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M6 19c1.2-2.4 3.2-3.5 6-3.5s4.8 1.1 6 3.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
  gauge: '<path d="M5 16a7 7 0 1 1 14 0" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M12 16l4-4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
  lock: '<rect x="6" y="11" width="12" height="8" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M9 11V8.5a3 3 0 0 1 6 0V11" fill="none" stroke="currentColor" stroke-width="1.6"/>',
};

const PHASES = ["ask", "policy", "tool", "upstream", "answer"];
const state = { cache: new Map(), orders: [], items: [], shipments: [] };
const $ = (id) => document.getElementById(id);

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

function money(value, digits = 0) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: digits, minimumFractionDigits: digits }).format(number);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function icon(name) {
  return `<svg viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ICONS.box}</svg>`;
}

function preview(id, data) {
  if (id === "brief") return data.summary || "";
  if (id === "risks") return `${(data.risks || []).length} need a person`;
  if (id === "actions") return `${(data.actions || []).length} suggestions`;
  if (id === "health") return data.health || "";
  if (id === "payments") return (data.matches || []).map((row) => row.order_number).join(", ") || "None";
  if (id === "reconcile") return (data.buckets?.paid_not_shipped || []).map((row) => row.order_number).join(", ") || "None";
  if (id === "gst") return money(data.tax_total, 2);
  if (id === "invoices") return `${(data.invoices || []).filter((row) => Number(row.balance) > 0).length} open`;
  if (id === "dead") return `${money(data.value_tied_up, 0)} tied up`;
  if (id === "anomalies") return `${(data.flags || []).length} flags`;
  if (id === "fulfill") return data.source_can_fulfill ? "Can ship" : "Bengaluru cannot · Mumbai can";
  if (id === "shipments") return `${(data.shipments || []).length} on file`;
  if (id === "low") return (data.items || []).map((item) => item.sku).join(", ") || "None";
  if (id === "explain") return "Mumbai runs out in about 4 days";
  if (id === "customer") return "Phone and email masked";
  if (id === "budget") return `${data.daily_used ?? 0} / ${data.daily_limit ?? 1000}`;
  if (id === "propose") return "Blocked";
  return data.summary || "";
}

function paintTiles() {
  for (const group of ["today", "money", "stock", "account"]) {
    const host = document.querySelector(`[data-group="${group}"]`);
    host.innerHTML = STEPS.filter((step) => step.group === group).map((step) => {
      const data = state.cache.get(step.id);
      const line = data ? preview(step.id, data) : "";
      return `<button type="button" data-step="${esc(step.id)}" class="${step.danger ? "danger" : ""}"><span class="tile-ico">${icon(step.icon)}</span><span class="tile-copy"><b>${esc(step.label)}</b><small>${esc(line)}</small><em>${esc(step.tool)}</em></span></button>`;
    }).join("");
    host.querySelectorAll("button").forEach((button) => {
      button.addEventListener("click", () => {
        const step = STEPS.find((item) => item.id === button.dataset.step);
        if (step) runStep(step);
      });
    });
  }
}

function setBudget(data) {
  if (!data) return;
  const used = Number(data.daily_used) || 0;
  const limit = Number(data.daily_limit) || 1;
  $("budget-label").textContent = `${used} / ${limit} calls`;
  $("budget-bar").style.setProperty("--used", `${Math.min(100, (used / limit) * 100)}%`);
}

function dataLine(data) {
  const calls = data?.meta?.calls_used ?? 0;
  const source = sourceLabel(data?.meta).split(" ")[0];
  return calls ? `${source}, ${calls} calls` : `${source}, cached`;
}

function sourceLabel(meta) {
  if (!meta || meta.source === "demo") return "Demo fixture";
  if (meta.source === "zoho") return "Zoho";
  return meta.source || "Service";
}

function setStepper(step, phase, data) {
  const labels = [
    ["Question", step ? "Asked" : ""],
    ["Read-only check", phase === "ask" ? "" : data?.executed === false ? "Blocked" : "Allowed"],
    ["MCP tool", PHASES.indexOf(phase) >= 2 ? step.tool : ""],
    ["Data", PHASES.indexOf(phase) >= 3 ? dataLine(data) : ""],
    ["Answer", phase === "answer" ? "Done" : ""],
  ];
  const index = PHASES.indexOf(phase);
  $("stepper").innerHTML = labels.map(([name, detail], i) => `
    <li class="${i < index ? "done" : ""} ${i === index ? "on" : ""}">
      <strong>${esc(name)}</strong>
      <em>${esc(detail)}</em>
    </li>`).join("");
}

function rows(pairs) {
  return `<div class="rows">${pairs.map(([label, value, tone]) => `
    <div><span>${esc(label)}</span><b class="chip ${tone || ""}">${esc(value)}</b></div>`).join("")}</div>`;
}

function answerHtml(step, data) {
  if (data.error) return `<h2 class="answer-title">${esc(data.summary || "Could not answer")}</h2>`;
  if (step.id === "payments") {
    const matches = data.matches || [];
    const first = matches[0];
    const title = matches.length
      ? `${matches.length} paid order${matches.length === 1 ? "" : "s"} with no invoice: ${matches.map((row) => row.order_number).join(", ")}`
      : "No paid orders are waiting on an invoice";
    const body = first
      ? rows([
          ["Order", first.order_number, ""],
          ["Payment", (first.payment_ids || []).join(", "), "ok"],
          ["Invoice", first.invoiced ? "Present" : "Missing", first.invoiced ? "ok" : "bad"],
        ])
      : "";
    return `<h2 class="answer-title">${esc(title)}</h2><p class="muted">Matched from the Razorpay id stored on the Zoho order.</p>${body}`;
  }
  if (step.id === "reconcile") {
    const buckets = data.buckets || {};
    const labels = [["paid_and_shipped", "Shipped"], ["paid_not_invoiced", "No invoice"], ["invoiced_but_unpaid", "Unpaid"], ["refunded_stock_not_returned", "Refund, stock out"], ["paid_not_shipped", "Not shipped"]];
    return `<h2 class="answer-title">${esc(data.summary || "Reconciliation")}</h2>${rows(labels.map(([key, label]) => {
      const names = (buckets[key] || []).map((row) => row.order_number).join(", ") || "—";
      return [label, names, key === "paid_not_shipped" ? "bad" : ""];
    }))}`;
  }
  if (step.id === "gst") {
    return `<h2 class="answer-title">${money(data.tax_total, 2)} GST in September</h2><p class="muted">Tax on invoices. Not a filed return.</p>${rows((data.rates || []).map((rate) => [`${rate.tax_rate}%`, money(rate.tax_amount, 2), ""]))}`;
  }
  if (step.id === "invoices") {
    const open = (data.invoices || []).filter((row) => Number(row.balance) > 0);
    const title = open.length ? `${open.length} invoice${open.length === 1 ? "" : "s"} still have a balance` : "No open invoice balances";
    return `<h2 class="answer-title">${esc(title)}</h2><p class="muted">Shown from Zoho invoices. Nothing is collected from here.</p>${open.length ? rows(open.map((row) => [row.number, `${row.status} · ${money(row.balance, 2)}`, "bad"])) : ""}`;
  }
  if (step.id === "shipments") {
    const list = data.shipments || [];
    return `<h2 class="answer-title">${list.length} shipment${list.length === 1 ? "" : "s"} on file</h2><p class="muted">These already left a warehouse.</p>${rows(list.map((row) => [row.number, `${row.status} · ${row.warehouse_id || ""}`, row.status === "delivered" ? "ok" : ""]))}`;
  }
  if (step.id === "dead") {
    const item = (data.items || [])[0];
    return `<h2 class="answer-title">${item ? `${money(item.value_tied_up, 0)} is sitting still` : "No dead stock"}</h2><p class="muted">${item ? `${item.sku} · ${item.on_hand} on hand · no sale in 30 days` : ""}</p>`;
  }
  if (step.id === "health") {
    return `<h2 class="answer-title">${esc(data.order_number || "")} · ${esc(data.health || "")}</h2>${rows((data.reasons || []).slice(0, 3).map((reason) => ["Reason", reason, "bad"]))}`;
  }
  if (step.id === "fulfill") {
    const alt = (data.alternatives || [])[0];
    const title = data.source_can_fulfill
      ? `${data.source_warehouse_name} can ship ${data.quantity}`
      : `${data.source_warehouse_name} has ${data.source_available}. ${alt ? `${alt.warehouse_name} has ${alt.available}` : "No other warehouse can cover it"}.`;
    const stockRows = [
      [data.source_warehouse_name || "Source", `${data.source_available} available`, data.source_can_fulfill ? "ok" : "bad"],
    ];
    for (const row of data.alternatives || []) {
      stockRows.push([row.warehouse_name, `${row.available} available`, "ok"]);
    }
    return `<h2 class="answer-title">${esc(title)}</h2><p class="muted">${esc(data.sku || "")} · need ${esc(data.quantity)}. ${esc(data.note || "Availability only.")}</p>${rows(stockRows)}`;
  }
  if (step.id === "low") {
    const items = data.items || [];
    const lines = items.flatMap((item) => (item.warehouses || []).map((stock) => [
      stock.warehouse_name,
      `${item.name} · ${stock.available} available`,
      stock.available === 0 ? "bad" : "",
    ]));
    return `<h2 class="answer-title">${esc(data.summary || "Low stock")}</h2>${lines.length ? rows(lines) : ""}`;
  }
  if (step.id === "explain") {
    const evidence = (data.evidence || []).slice(0, 4).map((line) => ["Evidence", line, ""]);
    return `<h2 class="answer-title">${esc(data.title || "Why")}</h2><p class="muted">${esc(data.reason || "")}</p>${evidence.length ? rows(evidence) : ""}`;
  }
  if (step.id === "brief") {
    const highlights = (data.highlights || []).slice(0, 4).map((line) => ["Watch", line, ""]);
    return `<h2 class="answer-title">${esc(data.open_orders ?? "")} open orders · ${money(data.open_order_value, 2)}</h2><p class="muted">${esc(data.summary || "No writes were performed.")}</p>${highlights.length ? rows(highlights) : ""}`;
  }
  if (step.id === "propose") {
    return `<h2 class="answer-title">Not done</h2><p class="muted">${esc(data.refusal || data.summary || "")}</p>`;
  }
  if (step.id === "customer") {
    const customer = data.customer || {};
    return `<h2 class="answer-title">${esc(customer.name || "Contact")}</h2>${rows([["Email", customer.email || "—", ""], ["Phone", customer.phone || "—", ""]])}<p class="muted">Masked.</p>`;
  }
  if (step.id === "budget") {
    return `<h2 class="answer-title">${esc(data.daily_used ?? "–")} / ${esc(data.daily_limit ?? "–")} calls</h2><p class="muted">${esc(data.advice || "")}</p>`;
  }
  if (step.id === "risks" || step.id === "actions" || step.id === "anomalies") {
    const list = (data.risks || data.actions || data.flags || []).slice(0, 4);
    return `<h2 class="answer-title">${esc(data.summary || step.label)}</h2>${rows(list.map((item) => [item.severity || item.priority || "Note", item.title, ""]))}`;
  }
  return `<h2 class="answer-title">${esc(data.summary || data.title || step.label)}</h2>`;
}

function toolHtml(step, data) {
  const meta = data.meta || {};
  const blocked = data.executed === false;
  return `
    <div class="agent-head"><span class="tile-ico">${icon(step.icon)}</span><div><p class="eyebrow">MCP agent</p><h2>${esc(step.agent || step.label)}</h2></div></div>
    <p class="muted">Reads ${esc(step.reads || "Zoho")}. Writes nothing.</p>
    <code class="call">${esc(step.call || step.tool)}</code>
    <div class="meta-line"><span>Tool</span><b>${esc(step.tool)}</b></div>
    <div class="meta-line"><span>Source</span><b class="tag">${esc(sourceLabel(meta))}</b></div>
    <div class="meta-line"><span>Calls used</span><b>${esc((meta.calls_used ?? 0) === 0 ? "Cached" : meta.calls_used)}</b></div>
    <div class="meta-line"><span>Mode</span><b>${blocked ? "Refused" : "Read only"}</b></div>`;
}

function renderResult(step, data) {
  $("answer").innerHTML = answerHtml(step, data);
  $("toolcard").innerHTML = toolHtml(step, data);
  const focus = step.id === "fulfill" ? "SKU-SPEAKER-MINI" : step.id === "low" ? "SKU-EARBUD-PRO" : "";
  if (state.items) drawWarehouses(state.items, focus);
  document.querySelectorAll(".tiles button").forEach((button) => {
    button.classList.toggle("on", button.dataset.step === step.id);
  });
  if (step.id === "budget") setBudget(data);
}

async function runStep(step, animate = true) {
  $("ask").value = step.question;
  if (animate) {
    setStepper(step, "ask");
    await sleep(80);
    setStepper(step, "policy");
    await sleep(80);
    setStepper(step, "tool");
  }
  const response = await fetch(step.url, step.init);
  const data = await response.json();
  state.cache.set(step.id, data);
  if (animate) {
    setStepper(step, "upstream", data);
    await sleep(80);
  }
  setStepper(step, "answer", data);
  renderResult(step, data);
  paintTiles();
  if (data.daily_limit) setBudget(data);
  else if (state.cache.get("budget")) setBudget(state.cache.get("budget"));
  paintAudit();
  if (step.id === "fulfill") openFloor(data.source_warehouse_id || "wh_blr");
}

function matchQuestion(text) {
  const q = text.toLowerCase();
  const rules = [
    [/not invoiced|unbilled/, "payments"],
    [/invoice|balance/, "invoices"],
    [/shipment|left the warehouse|tracking/, "shipments"],
    [/ship|reconcil/, "reconcile"],
    [/gst|tax/, "gst"],
    [/cash|tied|dead|unsold/, "dead"],
    [/unusual|anomal|spike|discount/, "anomalies"],
    [/earbud|why|cover/, "explain"],
    [/warehouse|bengaluru|speaker|fulfill/, "fulfill"],
    [/low stock|reorder/, "low"],
    [/1002|at risk|health/, "health"],
    [/rahul|customer|phone|email/, "customer"],
    [/budget|quota|calls/, "budget"],
    [/move|transfer/, "propose"],
    [/next|should i/, "actions"],
    [/risk/, "risks"],
  ];
  const hit = rules.find(([pattern]) => pattern.test(q));
  return STEPS.find((step) => step.id === (hit ? hit[1] : "brief"));
}

function drawMonth(orders) {
  const start = new Date("2026-09-02T00:00:00Z");
  const days = [];
  for (let i = 0; i < 30; i += 1) {
    const day = new Date(start);
    day.setUTCDate(start.getUTCDate() + i);
    days.push(day.toISOString().slice(0, 10));
  }
  const series = days.map((day) => {
    const same = orders.filter((order) => order.status !== "void" && order.date === day);
    const revenue = same.reduce((sum, order) => sum + (Number(order.total) || 0), 0);
    return { day, count: same.length, revenue };
  });
  const maxCount = Math.max(...series.map((row) => row.count), 1);
  const maxRevenue = Math.max(...series.map((row) => row.revenue), 1);
  const width = 860;
  const height = 220;
  const pad = 28;
  const inner = width - pad * 2;
  const bar = inner / series.length;
  const bars = series.map((row, index) => {
    const h = (row.count / maxCount) * 140;
    const x = pad + index * bar + 2;
    const spike = row.day === "2026-10-01";
    return `<rect x="${x}" y="${170 - h}" width="${Math.max(bar - 4, 2)}" height="${h}" rx="2" fill="${spike ? "#f5b942" : "#4c8dff"}"><title>${row.day}: ${row.count} orders</title></rect>`;
  }).join("");
  const points = series.map((row, index) => {
    const x = pad + index * bar + bar / 2;
    const y = 170 - (row.revenue / maxRevenue) * 140;
    return `${x},${y}`;
  }).join(" ");
  const labels = [0, 9, 19, 29].map((index) => {
    const x = pad + index * bar;
    const month = series[index].day.slice(5, 7) === "10" ? "Oct" : "Sep";
    return `<text x="${x}" y="208" fill="#93a0b8" font-size="11">${series[index].day.slice(8)} ${month}</text>`;
  }).join("");
  $("month").innerHTML = `
    <svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Orders and revenue for the past 30 days">
      ${bars}
      <polyline points="${points}" fill="none" stroke="#f5b942" stroke-width="2" />
      ${labels}
    </svg>
    <div class="legend"><span><i></i>Orders</span><span><i class="line"></i>Revenue</span><span>1 Oct is the spike</span></div>`;
  const orderTotal = series.reduce((sum, row) => sum + row.count, 0);
  const revenueTotal = series.reduce((sum, row) => sum + row.revenue, 0);
  const busiest = series.reduce((best, row) => (row.count > best.count ? row : best), series[0]);
  $("month-stats").innerHTML = `
    <div><b>${orderTotal}</b><span>orders</span></div>
    <div><b>${money(revenueTotal, 0)}</b><span>order value</span></div>
    <div><b>${busiest.count}</b><span>busiest day, ${busiest.day.slice(8)} ${busiest.day.slice(5, 7) === "10" ? "Oct" : "Sep"}</span></div>`;
  $("month-note").textContent = "2 Sep – 1 Oct 2026 · closed history plus today’s open book";
}

function drawWarehouses(items, focusSku) {
  const places = [
    { id: "wh_mum", name: "Mumbai", city: "Mumbai" },
    { id: "wh_blr", name: "Bengaluru", city: "Bengaluru" },
  ];
  const max = Math.max(...items.flatMap((item) => (item.warehouses || []).map((stock) => stock.available)), 1);
  $("shed-grid").innerHTML = places.map((place) => {
    const rowsHtml = items.map((item) => {
      const stock = (item.warehouses || []).find((row) => row.warehouse_id === place.id);
      const available = stock ? stock.available : 0;
      const onHand = stock ? stock.on_hand : 0;
      const asked = focusSku && item.sku === focusSku;
      const tone = available === 0 ? "bad" : asked && available < 6 ? "warn" : "";
      const width = Math.round((available / max) * 100);
      return `<div class="sku-row">
        <b>${esc(item.name)}</b>
        <span class="qty">${available} <em>/ ${onHand} on hand</em></span>
        <small>${esc(item.sku)}</small>
        <span></span>
        <span class="bar ${tone}"><i style="width:${width}%"></i></span>
      </div>`;
    }).join("");
    const short = place.id === "wh_blr";
    return `<article class="shed ${short ? "short" : ""}">
      <header><strong>${esc(place.name)}</strong><button type="button" data-floor="${esc(place.id)}">Floor</button></header>
      ${rowsHtml}
    </article>`;
  }).join("");
  $("shed-grid").querySelectorAll("[data-floor]").forEach((button) => {
    button.addEventListener("click", () => openFloor(button.dataset.floor));
  });
  const speaker = items.find((item) => item.sku === "SKU-SPEAKER-MINI");
  const blr = speaker && (speaker.warehouses || []).find((row) => row.warehouse_id === "wh_blr");
  const mum = speaker && (speaker.warehouses || []).find((row) => row.warehouse_id === "wh_mum");
  if (blr && mum) {
    $("shed-note").textContent = `Bengaluru has ${blr.available} Mini Speakers, so 6 cannot ship from there. Mumbai has ${mum.available}.`;
  }
}

const RACKS = [
  { sku: "SKU-EARBUD-PRO", label: "Buds", c: 1, r: 0, w: 4, h: 4, green: [6, 1], red: [6, 2] },
  { sku: "SKU-SPEAKER-MINI", label: "Speaker", c: 8, r: 0, w: 4, h: 4, green: [12, 1], red: [12, 2] },
  { sku: "SKU-STAND-OLD", label: "Stand", c: 15, r: 0, w: 4, h: 4, green: [19, 1], red: [19, 2] },
  { sku: "SKU-CABLE-C", label: "Cable", c: 1, r: 6, w: 4, h: 4, green: [6, 7], red: [6, 8] },
  { sku: "SKU-CASE-BLK", label: "Case", c: 8, r: 6, w: 4, h: 4, green: [13, 7], red: [13, 8] },
];
const OPEN = new Set(["confirmed", "pending", "partially_shipped", "open"]);
let floorWh = "wh_mum";

function stockAt(item, warehouseId) {
  return (item.warehouses || []).find((row) => row.warehouse_id === warehouseId) || { available: 0, on_hand: 0 };
}

function openFloor(warehouseId) {
  floorWh = warehouseId || floorWh;
  renderFloor();
  const dialog = $("floor");
  if (typeof dialog.showModal === "function" && !dialog.open) dialog.showModal();
}

function renderFloor() {
  const place = floorWh === "wh_blr" ? "Bengaluru" : "Mumbai";
  $("floor-title").textContent = place;
  document.querySelectorAll("#floor-tabs button").forEach((button) => {
    button.classList.toggle("on", button.dataset.wh === floorWh);
  });
  const bits = [];
  const lines = [];
  let availableSum = 0;
  let remainingSum = 0;
  for (let r = 0; r < 11; r += 1) {
    for (let c = 0; c < 20; c += 1) bits.push(`<i class="cell" style="grid-column:${c + 1};grid-row:${r + 1}"></i>`);
  }
  for (const rack of RACKS) {
    const item = (state.items || []).find((row) => row.sku === rack.sku);
    const stock = item ? stockAt(item, floorWh) : { available: 0, on_hand: 0 };
    const available = stock.available || 0;
    const remaining = Math.max(0, (stock.on_hand || 0) - available);
    availableSum += available;
    remainingSum += remaining;
    const short = available === 0 && (stock.on_hand || 0) > 0;
    bits.push(`<div class="block ${short ? "short" : ""}" style="grid-column:${rack.c + 1} / span ${rack.w};grid-row:${rack.r + 1} / span ${rack.h}">${esc(rack.label)}</div>`);
    if (available > 0) bits.push(`<span class="pill-dot ok" style="grid-column:${rack.green[0] + 1};grid-row:${rack.green[1] + 1}">${available}</span>`);
    if (remaining > 0) bits.push(`<span class="pill-dot bad" style="grid-column:${rack.red[0] + 1};grid-row:${rack.red[1] + 1}">${remaining}</span>`);
    lines.push({ name: item ? item.name : rack.sku, sku: rack.sku, available, remaining });
  }
  $("floor-map").innerHTML = bits.join("");
  const shipped = (state.shipments || []).filter((row) => row.warehouse_id === floorWh);
  const waiting = (state.orders || []).filter((order) => OPEN.has(order.status) && (order.quantity_ordered || 0) > (order.quantity_shipped || 0) && (order.line_items || []).some((line) => line.warehouse_id === floorWh));
  const shortLine = lines.find((row) => row.sku === "SKU-SPEAKER-MINI" && floorWh === "wh_blr");
  const note = shortLine
    ? `${place}: ${availableSum} available to ship, ${remainingSum} still held. Mini Speakers have ${shortLine.available} free, so an order for 6 stays here.`
    : `${place}: ${availableSum} available to ship, ${remainingSum} still held on the racks.`;
  $("floor-note").innerHTML = `<span class="dot-key ok"></span>Available &nbsp; <span class="dot-key bad"></span>Remaining &nbsp; ${esc(note)}`;
  const shippedHtml = shipped.length
    ? shipped.map((row) => `<li><b>${esc(row.number)}</b><span>${esc(row.status)} · ${esc(row.date || "")} · ${esc(row.tracking_number || "")}</span></li>`).join("")
    : `<li><b>No shipment record</b><span>Nothing has left this warehouse in the book.</span></li>`;
  const waitingHtml = waiting.length
    ? waiting.map((order) => {
      const line = (order.line_items || []).find((item) => item.warehouse_id === floorWh) || {};
      const left = (order.quantity_ordered || 0) - (order.quantity_shipped || 0);
      return `<li><b>${esc(order.number)}</b><span>${esc(line.name || "Order")} · ${left} still to ship</span></li>`;
    }).join("")
    : `<li><b>Nothing waiting</b><span>No open quantity left in this warehouse.</span></li>`;
  $("floor-side").innerHTML = `
    <h3>On the racks</h3>
    <ul>${lines.map((row) => `<li><b>${esc(row.name)}</b><span>${row.available} available · ${row.remaining} remaining</span></li>`).join("")}</ul>
    <h3>Shipped</h3>
    <ul>${shippedHtml}</ul>
    <h3>Still to ship</h3>
    <ul>${waitingHtml}</ul>`;
}

const PROMPTS = [
  ["What needs attention today?", "brief"],
  ["Which orders are at risk?", "risks"],
  ["Which paid orders haven't shipped?", "reconcile"],
  ["Which paid orders are not invoiced?", "payments"],
];

function paintPrompts() {
  $("prompts").innerHTML = PROMPTS.map(([question, id]) => `<button type="button" data-prompt="${esc(id)}">${esc(question)}</button>`).join("");
  $("prompts").querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      const step = STEPS.find((item) => item.id === button.dataset.prompt);
      if (step) runStep(step);
    });
  });
}

async function paintAudit() {
  const payload = await fetch("/api/audit").then((response) => response.json());
  const events = (payload.events || []).slice(-8).reverse();
  $("audit").innerHTML = events.length
    ? events.map((event) => `<li><span>${esc(event.tool)}</span><b class="${event.status === "ok" ? "ok" : "bad"}">${esc(event.status)}</b><em>${esc(event.latency_ms)} ms</em><em>${esc(event.source || "")}</em></li>`).join("")
    : "<li><span>No tool calls yet</span><b></b><em></em><em></em></li>";
}

async function boot() {
  paintPrompts();
  paintTiles();
  const [orders, stock, shipments, ...rest] = await Promise.all([
    fetch("/api/orders?limit=50").then((response) => response.json()),
    fetch("/api/inventory").then((response) => response.json()),
    fetch("/api/shipments?limit=50").then((response) => response.json()),
    ...STEPS.map((step) => fetch(step.url, step.init).then((response) => response.json())),
  ]);
  STEPS.forEach((step, index) => state.cache.set(step.id, rest[index]));
  state.orders = orders.orders || [];
  state.items = stock.items || [];
  state.shipments = shipments.shipments || [];
  setBudget(state.cache.get("budget"));
  paintTiles();
  drawWarehouses(state.items, "SKU-SPEAKER-MINI");
  drawMonth(state.orders);
  paintAudit();
  const payments = STEPS.find((step) => step.id === "payments");
  $("ask").value = payments.question;
  setStepper(payments, "answer", state.cache.get("payments"));
  renderResult(payments, state.cache.get("payments"));
}

$("ask-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const step = matchQuestion($("ask").value);
  runStep(step);
});

$("open-floor").addEventListener("click", () => openFloor("wh_mum"));
$("floor-close").addEventListener("click", () => $("floor").close());
$("floor").addEventListener("click", (event) => {
  if (event.target === $("floor")) $("floor").close();
});
document.querySelectorAll("#floor-tabs button").forEach((button) => {
  button.addEventListener("click", () => openFloor(button.dataset.wh));
});

const SAMPLES = {
  search_orders: { limit: 5, status: "confirmed" },
  get_order: { order_id: "SO-1008" },
  get_inventory_item: { sku: "SKU-EARBUD-PRO" },
  list_inventory: { low_stock_only: true },
  list_invoices: { limit: 20 },
  list_shipments: { limit: 20 },
  get_customer: { customer_id: "cus_rahul" },
  get_order_health: { order_id: "SO-1002" },
  detect_operational_risks: { time_window_days: 2, horizon_days: 7 },
  find_alternate_fulfillment: { sku: "SKU-SPEAKER-MINI", quantity: 6, source_warehouse_id: "wh_blr" },
  recommend_next_actions: { time_window_days: 2 },
  explain_recommendation: { recommendation_id: "stockout:SKU-EARBUD-PRO:wh_mum" },
  match_order_to_payment: { only_paid_not_invoiced: true },
  gst_summary: { period: "2026-09" },
  dead_stock: { days: 30 },
  detect_anomalies: { window_days: 14 },
  propose_action: { action_type: "transfer_stock", reason: "Move speakers toward Bengaluru", payload: { sku: "SKU-SPEAKER-MINI", quantity: 6 } },
};

const inspector = { catalog: null, kind: "tools", selected: "match_order_to_payment", ran: false };

function inspItems() {
  const catalog = inspector.catalog || { tools: [], resources: [], prompts: [] };
  const query = ($("insp-search").value || "").trim().toLowerCase();
  const rows = inspector.kind === "resources" ? catalog.resources : inspector.kind === "prompts" ? catalog.prompts : catalog.tools;
  return rows.filter((row) => {
    const hay = `${row.name || ""} ${row.uri || ""} ${row.description || ""}`.toLowerCase();
    return !query || hay.includes(query);
  });
}

function paintInspList() {
  const rows = inspItems();
  $("insp-list").innerHTML = rows.map((row) => {
    const key = row.name || row.uri;
    const on = key === inspector.selected ? " on" : "";
    const label = inspector.kind === "resources" ? (row.name || row.uri) : row.name;
    return `<li><button type="button" class="${on.trim()}" data-key="${esc(key)}">${esc(label)}</button></li>`;
  }).join("") || "<li><button type=\"button\" disabled>Nothing matches</button></li>";
  $("insp-list").querySelectorAll("button[data-key]").forEach((button) => {
    button.addEventListener("click", () => {
      inspector.selected = button.dataset.key;
      paintInspList();
      paintInspDetail();
    });
  });
}

function paintInspDetail() {
  const catalog = inspector.catalog;
  if (!catalog) return;
  if (inspector.kind === "tools") {
    const tool = catalog.tools.find((row) => row.name === inspector.selected) || catalog.tools[0];
    if (!tool) return;
    inspector.selected = tool.name;
    const sample = SAMPLES[tool.name] || {};
    $("insp-detail").innerHTML = `
      <p class="eyebrow">Tool</p>
      <h2>${esc(tool.name)}</h2>
      <p>${esc(tool.description || "")}</p>
      <label for="insp-args">Arguments</label>
      <textarea id="insp-args">${esc(JSON.stringify(sample, null, 2))}</textarea>
      <button type="button" class="insp-run" id="insp-run">Run tool</button>
      <pre id="insp-out">Run to see the JSON the agent receives.</pre>`;
    $("insp-run").addEventListener("click", runInspTool);
    return;
  }
  if (inspector.kind === "resources") {
    const resource = catalog.resources.find((row) => (row.uri || row.name) === inspector.selected) || catalog.resources[0];
    if (!resource) return;
    inspector.selected = resource.uri || resource.name;
    $("insp-detail").innerHTML = `
      <p class="eyebrow">Resource</p>
      <h2>${esc(resource.name || resource.uri)}</h2>
      <p>${esc(resource.uri || "")}</p>
      <button type="button" class="insp-run" id="insp-read">Read resource</button>
      <pre id="insp-out">Read to load this resource.</pre>`;
    $("insp-read").addEventListener("click", () => readInspResource(resource.uri));
    return;
  }
  const prompt = catalog.prompts.find((row) => row.name === inspector.selected) || catalog.prompts[0];
  if (!prompt) return;
  inspector.selected = prompt.name;
  $("insp-detail").innerHTML = `
    <p class="eyebrow">Prompt</p>
    <h2>${esc(prompt.name)}</h2>
    <p>${esc(prompt.description || "")}</p>
    <button type="button" class="insp-run" id="insp-prompt">Get prompt</button>
    <pre id="insp-out">Get the prompt text an agent would receive.</pre>`;
  $("insp-prompt").addEventListener("click", () => readInspPrompt(prompt.name));
}

async function runInspTool() {
  const out = $("insp-out");
  let arguments_ = {};
  try {
    arguments_ = JSON.parse($("insp-args").value || "{}");
  } catch (error) {
    out.className = "bad";
    out.textContent = "Arguments must be a JSON object.";
    return;
  }
  out.className = "";
  out.textContent = "Calling…";
  const payload = await fetch("/api/mcp/call", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name: inspector.selected, arguments: arguments_ }),
  }).then((response) => response.json());
  out.className = payload.ok ? "" : "bad";
  out.textContent = JSON.stringify(payload.ok ? payload.result : payload, null, 2);
  paintAudit();
}

async function readInspResource(uri) {
  const out = $("insp-out");
  out.className = "";
  out.textContent = "Reading…";
  const payload = await fetch(`/api/mcp/resource?uri=${encodeURIComponent(uri)}`).then((response) => response.json());
  out.className = payload.ok ? "" : "bad";
  out.textContent = payload.ok ? (payload.contents || []).join("\n\n") : payload.error;
}

async function readInspPrompt(name) {
  const out = $("insp-out");
  out.className = "";
  out.textContent = "Loading…";
  const payload = await fetch(`/api/mcp/prompt?name=${encodeURIComponent(name)}`).then((response) => response.json());
  if (!payload.ok) {
    out.className = "bad";
    out.textContent = payload.error;
    return;
  }
  const messages = (payload.prompt && payload.prompt.messages) || [];
  out.textContent = messages.map((message) => {
    const content = message.content;
    if (typeof content === "string") return content;
    if (content && content.text) return content.text;
    return JSON.stringify(content);
  }).join("\n\n") || JSON.stringify(payload.prompt, null, 2);
}

async function openInspector() {
  if (!inspector.catalog) {
    inspector.catalog = await fetch("/api/mcp/catalog").then((response) => response.json());
    $("insp-server").textContent = `${inspector.catalog.server} · ${inspector.catalog.mode}`;
    $("insp-conn").textContent = inspector.catalog.connected ? "Connected" : "Offline";
  }
  paintInspList();
  paintInspDetail();
  if (!inspector.ran && inspector.kind === "tools" && inspector.selected === "match_order_to_payment") {
    inspector.ran = true;
    runInspTool();
  }
}

function showView(view) {
  document.body.classList.toggle("view-inspector", view === "inspector");
  $("inspector").hidden = view !== "inspector";
  document.querySelectorAll("#views button").forEach((button) => {
    button.classList.toggle("on", button.dataset.view === view);
  });
  if (view === "inspector") openInspector();
}

document.querySelectorAll("#views button").forEach((button) => {
  button.addEventListener("click", () => showView(button.dataset.view));
});
$("insp-search").addEventListener("input", paintInspList);
document.querySelectorAll("#insp-kinds button").forEach((button) => {
  button.addEventListener("click", () => {
    inspector.kind = button.dataset.kind;
    document.querySelectorAll("#insp-kinds button").forEach((item) => item.classList.toggle("on", item === button));
    const first = inspItems()[0];
    inspector.selected = first ? (first.name || first.uri) : "";
    paintInspList();
    paintInspDetail();
  });
});

boot();
