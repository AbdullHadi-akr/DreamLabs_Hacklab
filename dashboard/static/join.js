// Join page for guests: sends the access code, then opens the dashboard.
const form = document.getElementById("join-form");
const error = document.getElementById("join-error");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  error.hidden = true;
  const body = { code: document.getElementById("code").value, name: document.getElementById("name").value };
  try {
    const response = await fetch("/api/join", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (response.ok) { location.href = "/"; return; }
    const data = await response.json().catch(() => ({}));
    error.textContent = data.detail || "The code was not accepted.";
  } catch (e) {
    error.textContent = "The host laptop cannot be reached.";
  }
  error.hidden = false;
});
