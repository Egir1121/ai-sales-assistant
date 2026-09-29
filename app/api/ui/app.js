// Демо «карточка сделки»: слева чат, справа подсказка менеджеру.
// Сообщение клиента уходит в POST /v1/assist вместе с историей до него.
// Любой текст из чата и ответа выводится через textContent — не через innerHTML.

const $ = (id) => document.getElementById(id);

const state = {
  dialog: [],
  leadId: null,
  products: [],
  scenarios: [],
  busy: false,
};

const INTENTS = {
  product_question: "вопрос о товаре",
  price_question: "вопрос о цене",
  delivery_payment_question: "доставка / оплата",
  order_intent: "готов к заказу",
  discount_request: "просит скидку",
  price_objection: "дорого",
  complaint: "жалоба",
  refund: "возврат",
  smalltalk: "приветствие",
  unclear: "непонятно",
  other: "другое",
};
const SENTIMENTS = { positive: ["позитив", "ok"], neutral: ["нейтрально", ""], negative: ["негатив", "bad"] };

function h(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value !== false && value != null) node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child != null && child !== false) node.append(child instanceof Node ? child : String(child));
  }
  return node;
}

function chip(text, kind = "") {
  return h("span", { class: `chip ${kind}`.trim() }, text);
}

// --- сделка ---

function renderProducts() {
  $("products").replaceChildren(
    ...state.products.map((p) =>
      h(
        "label",
        { class: "chip selectable", title: p.id },
        h("input", { type: "checkbox", value: p.id }),
        p.title,
      ),
    ),
  );
}

function selectedProducts() {
  return [...$("products").querySelectorAll("input:checked")].map((i) => i.value);
}

function setLead(lead = {}) {
  state.leadId = lead.id ?? null;
  $("lead-id").textContent = state.leadId ? `#${state.leadId}` : "";
  $("client-name").value = lead.client_name ?? "";
  if (lead.stage) $("stage").value = lead.stage;
  const ids = new Set(lead.product_ids ?? []);
  for (const input of $("products").querySelectorAll("input")) input.checked = ids.has(input.value);
}

function currentLead() {
  return {
    id: state.leadId,
    stage: $("stage").value,
    client_name: $("client-name").value.trim() || null,
    product_ids: selectedProducts(),
  };
}

// --- чат ---

function renderDialog() {
  const box = $("messages");
  if (!state.dialog.length) {
    box.replaceChildren(
      h("p", { class: "empty muted" }, "Выберите сценарий сверху или напишите сообщение от лица клиента."),
    );
    return;
  }
  box.replaceChildren(
    ...state.dialog.map((turn) =>
      h(
        "div",
        { class: `msg ${turn.role}` },
        h("span", { class: "who" }, turn.role === "client" ? "Клиент" : "Менеджер"),
        turn.text,
      ),
    ),
  );
  box.scrollTop = box.scrollHeight;
}

function role() {
  return document.querySelector("input[name=role]:checked").value;
}

function setComposer(text, asRole) {
  document.querySelector(`input[name=role][value=${asRole}]`).checked = true;
  $("text").value = text;
  $("text").focus();
}

async function send(event) {
  event?.preventDefault();
  const text = $("text").value.trim();
  const who = role();
  if (state.busy || (!text && who === "manager")) return;

  const history = [...state.dialog];
  state.dialog.push({ role: who, text });
  $("text").value = "";
  renderDialog();
  if (who === "client") await requestHint(text, history);
}

async function regenerate() {
  const index = state.dialog.map((t) => t.role).lastIndexOf("client");
  if (index < 0) {
    showStatus("Нет сообщения клиента — подсказку не для чего строить.");
    return;
  }
  await requestHint(state.dialog[index].text, state.dialog.slice(0, index));
}

// --- подсказка ---

function showStatus(text, isError = false) {
  const status = $("status");
  status.hidden = false;
  status.textContent = text;
  status.classList.toggle("error", isError);
}

function setBusy(busy) {
  state.busy = busy;
  for (const button of document.querySelectorAll("#composer button")) button.disabled = busy;
}

async function requestHint(message, dialog) {
  setBusy(true);
  showStatus("Ассистент думает…");
  try {
    const response = await fetch("/v1/assist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, dialog, lead: currentLead() }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}: ${await response.text()}`);
    renderHint(await response.json());
    $("status").hidden = true;
  } catch (error) {
    $("result").hidden = true;
    showStatus(`Не удалось получить подсказку. ${error.message}`, true);
  } finally {
    setBusy(false);
  }
}

function renderHint(data) {
  const { client_reply: reply, manager_hint: hint, meta } = data;
  $("result").hidden = false;

  $("reply").textContent = reply.text;
  $("needs-manager").hidden = !reply.needs_manager;
  $("kb-refs").replaceChildren(
    ...(reply.kb_refs.length ? reply.kb_refs.map((id) => chip(id)) : [chip("без ссылок на БЗ", "warn")]),
    chip(`язык: ${reply.language}`),
  );
  $("use-reply").onclick = () => setComposer(reply.text, "manager");

  $("summary").textContent = hint.summary;
  const [sentimentText, sentimentKind] = SENTIMENTS[hint.sentiment] ?? [hint.sentiment, ""];
  $("badges").replaceChildren(
    chip(`интент: ${INTENTS[hint.intent] ?? hint.intent}`),
    chip(`тон: ${sentimentText}`, sentimentKind),
  );

  $("suppressed").hidden = !hint.upsell_suppressed_reason;
  $("suppressed").textContent = hint.upsell_suppressed_reason
    ? `Допродажа отключена: ${hint.upsell_suppressed_reason}`
    : "";

  $("upsell").replaceChildren(
    ...(hint.upsell.length || hint.upsell_suppressed_reason
      ? hint.upsell.map(renderOffer)
      : [h("p", { class: "muted small" }, "Подходящих предложений нет.")]),
  );

  $("declined").replaceChildren(
    ...(hint.declined_offer_ids.length ? hint.declined_offer_ids.map((id) => chip(titleOf(id), "bad")) : ["—"]),
  );
  $("next-action").textContent = hint.next_best_action;
  $("risks").replaceChildren(
    ...(hint.risk_flags.length ? hint.risk_flags.map((f) => chip(f, "warn")) : ["—"]),
  );

  const parts = [
    `${meta.provider} / ${meta.model}`,
    `промпт ${meta.prompt_version}`,
    `${meta.latency_ms} мс`,
    `токены ${meta.tokens_in} / ${meta.tokens_out}`,
  ];
  if (meta.cost_usd != null) parts.push(`$${meta.cost_usd.toFixed(4)}`);
  if (meta.fallback_used) parts.push("⚠ фолбэк: LLM недоступен");
  if (meta.guardrails_applied?.length) parts.push(`guardrails: ${meta.guardrails_applied.join(", ")}`);
  parts.push(`id ${data.request_id.slice(0, 8)}`);
  $("meta").textContent = parts.join(" · ");
}

function renderOffer(offer) {
  const percent = Math.round(offer.confidence * 100);
  return h(
    "article",
    { class: "offer" },
    h("div", { class: "offer-head" }, h("span", {}, offer.title), h("span", { class: "muted small" }, `${percent}%`)),
    h("p", { class: "muted" }, offer.why),
    h("p", { class: "pitch" }, `«${offer.pitch}»`),
    h("p", { class: "muted" }, `Когда: ${offer.when_to_say}`),
    h(
      "div",
      { class: "row" },
      h("div", { class: "confidence", style: "flex:1" }, h("span", { style: `width:${percent}%` })),
      h("button", { class: "ghost", type: "button", onclick: () => setComposer(offer.pitch, "manager") }, "В чат"),
    ),
  );
}

function titleOf(id) {
  return state.products.find((p) => p.id === id)?.title ?? id;
}

// --- сценарии ---

function renderScenarios() {
  $("scenario").append(
    ...state.scenarios.map((s) => h("option", { value: s.id }, `${s.id} · ${s.title}`)),
  );
}

function loadScenario(id) {
  const scenario = state.scenarios.find((s) => s.id === id);
  reset();
  if (!scenario) return;
  const { message, dialog = [], lead = {} } = scenario.request;
  state.dialog = dialog.map((t) => ({ ...t }));
  setLead(lead);
  renderDialog();
  setComposer(message, "client");
  $("expect").hidden = false;
  $("expect").textContent = `Ожидаем: ${scenario.expect}. Нажмите «Отправить».`;
}

function reset() {
  state.dialog = [];
  setLead({});
  $("stage").value = "Консультация";
  $("text").value = "";
  $("expect").hidden = true;
  $("result").hidden = true;
  showStatus("Подсказка появится после сообщения клиента.");
  renderDialog();
}

// --- запуск ---

async function init() {
  $("composer").addEventListener("submit", send);
  $("text").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) send(e);
  });
  $("regenerate").addEventListener("click", regenerate);
  $("reset").addEventListener("click", () => {
    $("scenario").value = "";
    reset();
  });
  $("scenario").addEventListener("change", (e) => loadScenario(e.target.value));

  try {
    const [products, scenarios] = await Promise.all([
      fetch("/v1/kb/products").then((r) => r.json()),
      fetch("/static/scenarios.json").then((r) => r.json()),
    ]);
    state.products = products;
    state.scenarios = scenarios;
    renderProducts();
    renderScenarios();
  } catch (error) {
    showStatus(`Не удалось загрузить данные демо: ${error.message}`, true);
  }
}

init();
