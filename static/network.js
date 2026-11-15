"use strict";

let networkQuery = "";
let networkResult = null;
let networkLoading = false;
let networkError = "";
let profileRequest = 0;

function networkBadge() {
  return '<span class="network-badge">Fictional profiles</span>';
}

function profileButton(person, filingId = "", label = "View profile") {
  return `<button type="button" class="button network-link" data-network-person="${e(person)}"${filingId ? ` data-network-filing="${e(filingId)}"` : ""}>${e(label)} <span aria-hidden="true">↗</span></button>`;
}

function networkHint(context, filingId) {
  const match = context?.matches?.[0];
  if (!match) return "";
  const title = `${context.reconnect === match.id ? "Reconnect with" : "Get context from"} ${match.name}`;
  return `<div class="network-hint">
    <div><span class="network-hint-label">Network · fictional</span>
    ${profileButton(match.id, filingId, title)}</div>
    <small>${e(match.kind)} · ${e(match.evidence)}</small>
  </div>`;
}

function networkMatch(match, filingId = "") {
  const initials = match.name
    .split(/\s+/)
    .map((part) => part[0])
    .slice(0, 2)
    .join("");
  const lastSpoke =
    match.days_since === 0
      ? "Spoke today"
      : match.days_since != null
        ? `Last spoke ${match.days_since} days ago`
        : "No conversation logged";
  return `<article class="network-match">
    <div class="network-match-top">
      <span class="network-avatar" aria-hidden="true">${e(initials)}</span>
      <div><h4>${e(match.name)}</h4><small>${e(match.relationship)} · ${lastSpoke}</small></div>
      ${profileButton(match.id, filingId, "Profile")}
    </div>
    ${match.target ? `<ol class="network-path" aria-label="Possible introduction path"><li>You</li><li>${e(match.name)}</li><li>${e(match.target)}</li></ol>` : ""}
    <p class="network-evidence"><strong>${e(match.kind)}</strong> · ${e(match.evidence)}</p>
    ${(match.support || []).map((item) => `<p class="network-support">${e(item)}</p>`).join("")}
    ${match.perspective ? `<p class="network-support">${e(match.perspective)}</p>` : ""}
    ${match.filing ? `<div class="network-trigger"><span>${e(match.filing.symbol)} · ${e(match.filing.title)}</span><button type="button" class="button network-link" data-filing="${e(match.filing.id)}">Open filing ↗</button><p>${e(match.question)}</p></div>` : ""}
  </article>`;
}

function networkContext(context, filingId = "") {
  if (!context?.matches?.length) return "";
  const match = context.matches.find(
    (person) => person.id === context.reconnect,
  );
  return `<section class="network-context">
    <div class="network-heading"><h3>Who can give you context?</h3>${networkBadge()}</div>
    ${context.matches.map((person) => networkMatch(person, filingId)).join("")}
    <div class="network-question"><strong>${match ? `Reconnect with ${e(match.name)}` : "A question to ask"}</strong><p>${e(context.question)}</p></div>
  </section>`;
}

function networkProfile(profile, filingId = "", editable = false) {
  return `
    <div class="network-heading"><h3 ${editable ? 'id="dialog-title"' : ""}>${e(profile.name)}</h3>${networkBadge()}</div>
    <p>${e(profile.bio)}</p>
    ${profile.relationship ? `<p class="network-support">${e(profile.relationship)} · ${profile.last_spoke ? `Last conversation ${e(profile.last_spoke)}` : "No conversation logged"}</p>` : ""}
    <h4>Career path</h4>
    <ol class="network-career">${profile.roles.map((role) => `<li><div><strong>${e(role.title)}</strong><span>${e(role.company)}</span></div><time>${e(role.years)}</time></li>`).join("")}</ol>
    ${profile.education.map((item) => `<p class="network-support">${e(item.programme)} · ${e(item.school)} · ${e(item.years)}</p>`).join("")}
    <div class="network-themes">${profile.themes.map((theme) => `<span class="tag">${e(theme)}</span>`).join("")}</div>
    ${profile.watchlist_connections?.length ? `<details class="network-watchlist">
      <summary>Watchlist connections · ${profile.watchlist_connections.length}</summary>
      <ul>${profile.watchlist_connections.map((connection) => `<li>
        <strong>${e(connection.symbol)} · ${e(connection.kind)}</strong>
        <p>${e(connection.evidence)}</p>
        <button type="button" class="button network-link" data-network-query="${e(connection.symbol)}">See connections for ${e(connection.symbol)} ↗</button>
      </li>`).join("")}</ul>
    </details>` : ""}
    ${profile.paths.length ? `<h4>Paths through your network</h4><p class="network-support">A shared employer or school indicates possible overlap. Reported collaboration comes from the mock contact record.</p>${profile.paths.map((path) => networkMatch(path, filingId)).join("")}` : ""}
    ${profile.meeting_question ? `<div class="network-question"><strong>Before the meeting</strong><p>${e(profile.meeting_question)}</p></div>` : ""}
    <div class="network-profile-actions">
      ${profile.relationship ? (editable ? `<button type="button" class="button" data-network-spoken="${e(profile.id)}" data-spoken="${profile.days_since !== 0}" data-network-filing="${e(filingId)}">${profile.days_since === 0 ? "Undo today’s conversation" : "Log conversation today"}</button>` : profileButton(profile.id, filingId, "Open contact")) : ""}
      ${editable && filingId ? `<button type="button" class="button" data-filing="${e(filingId)}">Back to filing</button>` : ""}
    </div>`;
}

function renderNetworkResults() {
  const output = $("#network-results");
  if (!output) return;
  if (networkLoading) {
    output.innerHTML =
      '<div class="loading">Looking through the mock network…</div>';
    return;
  }
  if (networkError) {
    output.innerHTML = empty("Network search could not run", networkError);
    return;
  }
  if (!networkResult) {
    output.innerHTML = "";
    return;
  }
  const groups = networkResult.groups || [];
  const profiles = networkResult.profiles || [];
  output.innerHTML =
    profiles.length || groups.length
      ? profiles
          .map(
            (profile) =>
              `<section class="panel network-context">${networkProfile(profile)}</section>`,
          )
          .join("") +
        groups
          .map(
            (group) =>
              `<section class="panel network-context"><h3>${e(group.title)}</h3>${
                group.matches.length
                  ? group.matches.map((match) => networkMatch(match)).join("")
                  : empty(
                      "No matches",
                      networkResult.kind === "reconnect"
                        ? "A recent material filing can surface a former employee you last spoke to at least 90 days ago."
                        : "The sample network has no contacts with a recorded connection here.",
                    )
              }</section>`,
          )
          .join("")
      : empty(
          "No matching profile, company or theme",
          "Try a full name, an NSE ticker or one of the example questions.",
        );
}

function renderNetwork() {
  $("#content").innerHTML = `<section class="panel network-search">
    <div class="network-heading"><h2>Who should I call?</h2>${networkBadge()}</div>
    <form id="network-form" class="network-form">
      <label class="field" for="network-query">Ask about a person, company or theme
        <input type="search" id="network-query" name="q" value="${e(networkQuery)}" maxlength="160" placeholder="Who knows Ananya Rao?" required autocomplete="off">
      </label>
      <button class="button primary" type="submit">Find connections</button>
    </form>
    <div class="suggestions">${(state.data.network_starters || []).map((question) => `<button type="button" class="chip" data-network-query="${e(question)}">${e(question)}</button>`).join("")}</div>
  </section><div id="network-results" aria-live="polite"></div>`;
  renderNetworkResults();
}

async function runNetwork(query) {
  const question = query.trim();
  if (!question) return;
  networkQuery = question;
  networkLoading = true;
  networkError = "";
  if (state.view !== "network") setView("network");
  else {
    $("#network-query").value = question;
    renderNetworkResults();
  }
  const request = ++runNetwork.sequence;
  try {
    const params = digestParams();
    params.set("q", question);
    const result = await api(`/api/network?${params}`);
    if (request === runNetwork.sequence) networkResult = result;
  } catch (error) {
    if (request === runNetwork.sequence) networkError = error.message;
  } finally {
    if (request === runNetwork.sequence) {
      networkLoading = false;
      if (state.view === "network") renderNetworkResults();
    }
  }
}
runNetwork.sequence = 0;

async function openNetworkProfile(identity, filingId = "") {
  const request = ++profileRequest;
  showDialog('<h2 id="dialog-title">Opening profile…</h2>');
  try {
    const profile = await api(
      `/api/network/people/${encodeURIComponent(identity)}`,
    );
    if (request === profileRequest && $("#detail-dialog").open) {
      showDialog(
        `<section class="network-profile">${networkProfile(profile, filingId, true)}</section>`,
      );
      $("#close-dialog").focus();
    }
  } catch (error) {
    if (request === profileRequest && $("#detail-dialog").open)
      showDialog(
        `<h2 id="dialog-title">Profile unavailable</h2><p>${e(error.message)}</p>`,
      );
  }
}

async function logNetworkConversation(button) {
  const {
    networkSpoken: identity,
    spoken,
    networkFiling: filingId,
  } = button.dataset;
  button.disabled = true;
  try {
    const contact = await post(
      `/api/network/contacts/${encodeURIComponent(identity)}/history`,
      { spoken: spoken === "true" },
      "PUT",
    );
    if (state.report?.network) {
      const match = state.report.network.matches.find(
        (person) => person.id === identity,
      );
      if (match) Object.assign(match, contact);
    }
    if (button.isConnected) await openNetworkProfile(identity, filingId);
    if (state.view === "network" && networkQuery)
      await runNetwork(networkQuery);
    else await loadData();
    toast(
      spoken === "true" ? "Conversation logged." : "Conversation log restored.",
    );
  } finally {
    button.disabled = false;
  }
}
