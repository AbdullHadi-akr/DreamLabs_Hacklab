// Players panel: the public link and access code (host), who holds which arm, and taking or freeing an arm.
import { h, request } from "./lib/api.js";

const ARM_NAMES = { left: "Left arm", right: "Right arm" };

// The Control panel (teammate's extension) selects an arm when its card is clicked: select the guest's own arm.
function selectInControl(side) {
  const card = document.querySelector(`.teleop-arm.${side}`);
  if (card && !card.classList.contains("selected")) card.click();
}

export function playersPanel(root, core, action) {
  const body = h("div", {});
  root.append(body);
  let state = null;

  const copy = async (text, what) => {
    try { await navigator.clipboard.writeText(text); core.toast(`${what} copied.`, "good", 1500); }
    catch { core.toast(`Copy did not work. Select the ${what.toLowerCase()} and copy it by hand.`, "error"); }
  };

  const render = () => {
    const s = state, host = s.me.role === "host";
    const parts = [];
    if (host) {
      const t = s.tunnel;
      const button = t === "open" || t === "starting"
        ? h("button", { type: "button", class: "btn-quiet small", onclick: () => action(request("POST", "/api/players/tunnel", { open: false })) }, "Close the public link")
        : h("button", { type: "button", class: "btn-quiet small", onclick: () => action(request("POST", "/api/players/tunnel", { open: true })) }, "Open a public link");
      parts.push(
        h("h4", {}, "Public link"),
        h("p", { class: "muted" }, "Opens this dashboard to a second laptop over the internet. Give the other person "
          + "the link and the access code. The link is new each time it opens."),
        t === "open" && s.link
          ? h("div", { class: "pl-share" },
            h("code", {}, s.link), h("button", { type: "button", class: "btn-quiet small", onclick: () => copy(s.link, "Link") }, "Copy"))
          : h("p", { class: "muted" }, t === "starting" ? "Opening the link..." : t === "error" ? "The link could not open. See the log." : "The link is closed."),
        h("div", { class: "pl-share" }, h("span", { class: "muted" }, "Access code"), h("code", {}, s.code),
          h("button", { type: "button", class: "btn-quiet small", onclick: () => copy(s.code, "Code") }, "Copy")),
        button,
      );
    } else {
      const name = h("input", { value: s.me.name || "", maxlength: "40", autocomplete: "off" });
      parts.push(
        h("p", { class: "muted" }, "You are a guest. Take one arm, then move it in Control. The host runs Dream-1."),
        h("label", { class: "field" }, h("span", {}, "Your name"), name),
        h("button", { type: "button", class: "btn-quiet small", onclick: () => action(request("POST", "/api/players/name", { name: name.value }), "Name saved.") }, "Save name"),
      );
    }

    parts.push(h("h4", {}, "Arms"));
    for (const side of ["left", "right"]) {
      const owner = s.owners[side];
      const mine = owner && owner.id === s.me.id;
      const label = owner ? (mine ? "you" : owner.name) : (host ? "free: you can move it" : "free");
      const buttons = [];
      if (!host && !mine && !owner) buttons.push(h("button", { type: "button", class: "btn-quiet small", onclick: () => action(request("POST", "/api/players/claim", { side })) }, "Take"));
      if (mine || (host && owner)) buttons.push(h("button", { type: "button", class: "btn-quiet small", onclick: () => action(request("POST", "/api/players/release", { side })) }, mine ? "Give back" : "Free it"));
      parts.push(h("div", { class: "pl-arm" }, h("i", { class: `teleop-dot ${side}` }), h("strong", {}, ARM_NAMES[side]),
        h("span", { class: "muted" }, label), h("span", { class: "spacer" }), ...buttons));
    }

    const guests = s.players.filter((p) => p.role === "guest");
    parts.push(h("h4", {}, "Guests"),
      guests.length
        ? h("ul", { class: "pl-list" }, guests.map((p) => h("li", {}, p.name,
          h("span", { class: "muted" }, ` ${p.arm ? ARM_NAMES[p.arm].toLowerCase() : "no arm"}${p.online ? "" : ", away"}`))))
        : h("p", { class: "muted" }, "Nobody has joined yet."));
    body.replaceChildren(...parts);
    if (s.me.arm) selectInControl(s.me.arm);
  };

  const refresh = async () => {
    try { state = await request("GET", "/api/players"); render(); }
    catch (error) { body.replaceChildren(h("p", { class: "bad" }, error.message)); }
  };
  core.events.on("players.state", refresh);
  refresh();
  setInterval(refresh, 15000); // keeps "away" up to date, and tells the host laptop this guest is still here
}
