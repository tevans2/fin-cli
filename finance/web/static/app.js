// Client-side account picker + keyboard shortcuts for the categorize flow.
// The account list is small (dozens), so filtering/ranking happens in the
// browser for instant feedback — mirroring the TUI's snappy picker.

let ACCOUNTS = [];
let filtered = [];
let selected = 0;

function loadAccounts() {
  const el = document.getElementById("accounts-data");
  if (el) {
    try { ACCOUNTS = JSON.parse(el.textContent) || []; } catch (e) { ACCOUNTS = []; }
  }
  // Shared datalist for split-row account inputs.
  if (!document.getElementById("accts")) {
    const dl = document.createElement("datalist");
    dl.id = "accts";
    ACCOUNTS.forEach(a => { const o = document.createElement("option"); o.value = a; dl.appendChild(o); });
    document.body.appendChild(dl);
  }
}

// --- fuzzy ranking (ports finance/services/categorize.score) ---
function bigrams(s) { const b = []; for (let i = 0; i < s.length - 1; i++) b.push(s.slice(i, i + 2)); return b; }
function dice(a, b) {
  if (a === b) return 1;
  const A = bigrams(a), B = bigrams(b);
  if (!A.length || !B.length) return 0;
  const m = new Map();
  A.forEach(x => m.set(x, (m.get(x) || 0) + 1));
  let inter = 0;
  B.forEach(x => { const v = m.get(x) || 0; if (v > 0) { inter++; m.set(x, v - 1); } });
  return (2 * inter) / (A.length + B.length);
}
function score(q, c) {
  if (!q) return 1;
  q = q.toLowerCase(); c = c.toLowerCase();
  if (c.includes(q)) return 2 + q.length / Math.max(c.length, 1);
  return dice(q, c);
}

function escapeHtml(s) {
  return s.replace(/[&<>"]/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));
}

function renderList(query) {
  const list = document.getElementById("picker-list");
  if (!list) return;
  filtered = ACCOUNTS
    .map(a => [a, score(query, a)])
    .filter(([, s]) => s > 0.25)
    .sort((x, y) => y[1] - x[1])
    .slice(0, 50)
    .map(([a]) => a);
  if (selected >= filtered.length) selected = Math.max(0, filtered.length - 1);
  const q = query.trim().toLowerCase();
  list.innerHTML = filtered.map((a, i) => {
    let label = escapeHtml(a);
    if (q) {
      const idx = a.toLowerCase().indexOf(q);
      if (idx >= 0) {
        label = escapeHtml(a.slice(0, idx)) + '<span class="match">' +
          escapeHtml(a.slice(idx, idx + q.length)) + "</span>" + escapeHtml(a.slice(idx + q.length));
      }
    }
    return `<li data-i="${i}" class="${i === selected ? "active" : ""}">${label}</li>`;
  }).join("");
}

function move(delta) {
  if (!filtered.length) return;
  selected = Math.min(filtered.length - 1, Math.max(0, selected + delta));
  const list = document.getElementById("picker-list");
  [...list.children].forEach((li, i) => li.classList.toggle("active", i === selected));
  const active = list.children[selected];
  if (active) active.scrollIntoView({ block: "nearest" });
}

function currentValue() {
  const input = document.getElementById("picker-input");
  if (filtered.length && filtered[selected]) return filtered[selected];
  return input ? input.value.trim() : "";
}

function apply() {
  const value = currentValue();
  if (!value || value === "expenses:unknown" || value === "income:unknown") return;
  document.getElementById("apply-category").value = value;
  document.getElementById("apply-form").requestSubmit();
}

function skip() {
  const f = document.getElementById("skip-form");
  if (f) f.requestSubmit();
}

// --- modals ---
function txnData() { return document.getElementById("txn")?.dataset || {}; }
function closeModal(id) { const m = document.getElementById(id); if (m) m.hidden = true; }

function openAlias() {
  const d = txnData();
  if (!d.id) return;
  document.getElementById("alias-txn").value = d.id;
  document.getElementById("alias-desc").value = d.description || "";
  document.getElementById("alias-original").textContent = d.description || "";
  const input = document.getElementById("alias-input");
  input.value = "";
  document.getElementById("alias-modal").hidden = false;
  input.focus();
}

function splitRemaining() {
  const total = Math.abs(parseFloat(txnData().amount || "0"));
  let used = 0;
  document.querySelectorAll("#split-rows .amt").forEach(i => { used += parseFloat(i.value || "0") || 0; });
  const rem = (total - used);
  document.getElementById("split-total").textContent = total.toFixed(2);
  document.getElementById("split-remaining").textContent = rem.toFixed(2);
}

function addSplitRow() {
  const rows = document.getElementById("split-rows");
  const div = document.createElement("div");
  div.className = "split-row";
  div.innerHTML =
    '<input class="acct" name="split_account" list="accts" placeholder="account" autocomplete="off">' +
    '<input class="amt" name="split_amount" placeholder="amount" inputmode="decimal" autocomplete="off">';
  rows.appendChild(div);
  div.querySelector(".amt").addEventListener("input", splitRemaining);
  div.querySelector(".acct").focus();
}

function openSplit() {
  const d = txnData();
  if (!d.id) return;
  document.getElementById("split-txn").value = d.id;
  document.getElementById("split-rows").innerHTML = "";
  addSplitRow();
  splitRemaining();
  document.getElementById("split-modal").hidden = false;
}

function anyModalOpen() {
  return [...document.querySelectorAll(".modal")].some(m => !m.hidden);
}

// --- init after each card swap ---
function initCard() {
  const input = document.getElementById("picker-input");
  if (!input) return; // done screen
  selected = 0;
  renderList(input.value);
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
}

document.addEventListener("htmx:afterSwap", e => { if (e.target.id === "card") initCard(); });
document.addEventListener("DOMContentLoaded", loadAccounts);

// picker input events
document.addEventListener("input", e => {
  if (e.target.id === "picker-input") { selected = 0; renderList(e.target.value); }
});
document.addEventListener("click", e => {
  const li = e.target.closest("#picker-list li");
  if (li) { selected = parseInt(li.dataset.i, 10); apply(); }
});

// global keyboard
document.addEventListener("keydown", e => {
  if (e.key === "Escape") { if (anyModalOpen()) { [...document.querySelectorAll(".modal")].forEach(m => m.hidden = true); e.preventDefault(); } return; }
  if (anyModalOpen()) return; // let modal inputs handle their own keys

  if (e.altKey && (e.key === "a" || e.key === "A")) { e.preventDefault(); openAlias(); return; }
  if (e.altKey && (e.key === "x" || e.key === "X")) { e.preventDefault(); openSplit(); return; }
  if (e.altKey && (e.key === "s" || e.key === "S")) { e.preventDefault(); skip(); return; }

  if (e.target.id !== "picker-input") return;
  if (e.key === "Enter") { e.preventDefault(); apply(); }
  else if (e.key === "ArrowDown" || (e.ctrlKey && e.key === "j")) { e.preventDefault(); move(1); }
  else if (e.key === "ArrowUp" || (e.ctrlKey && e.key === "k")) { e.preventDefault(); move(-1); }
});
