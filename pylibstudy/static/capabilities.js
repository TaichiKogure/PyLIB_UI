"use strict";

let capabilityCatalog = null;
const capabilityLabels = {executable: "実行可（登録値のみ）", unconnected: "未接続", out_of_scope: "対象外"};

function capabilityTable(target, headers, rows) {
    const wrapper = element("div", undefined, "insight-table-scroll capability-table"), table = element("table");
    const head = element("thead"), tr = element("tr");
    for (const header of headers) {
        const th = element("th", header);
        th.scope = "col";
        tr.append(th);
    }
    head.append(tr);
    const body = element("tbody");
    for (const row of rows) {
        const line = element("tr");
        for (const cell of row) line.append(element("td", String(cell)));
        body.append(line);
    }
    table.append(head, body);
    wrapper.append(table);
    $(target).replaceChildren(wrapper);
}

function renderCapabilityFeatures() {
    const query = $("capabilities-search").value.trim().toLowerCase(), filter = $("capabilities-filter").value;
    const rows = capabilityCatalog.features.filter(f => (filter === "all" || f.status.startsWith(filter)) &&
        [f.id, f.label, f.phase, f.status].join(" ").toLowerCase().includes(query));
    $("capabilities-feature-count").textContent = `${rows.length} / ${capabilityCatalog.features.length}項目`;
    capabilityTable("capabilities-features", ["ID", "機能・API", "現在の状態", "実装段階", "実装計画の依存"],
        rows.map(f => [f.id, f.label, f.status, f.phase, f.planned_dependencies.join(" / ")]));
}

function renderCapabilities(catalog) {
    capabilityCatalog = catalog;
    const connected = catalog.options.filter(o => o.status === "executable").length;
    $("capabilities-summary").textContent = `PyBaMM ${catalog.pybamm_version} / カタログ ${catalog.catalog_version} / 設定スキーマ ${catalog.config_schema_version} · ${catalog.features.length}機能・${catalog.options.length}設定キー（実行可${connected}・未接続${catalog.options.filter(o => o.status === "unconnected").length}・対象外${catalog.options.filter(o => o.status === "out_of_scope").length}）`;
    $("capabilities-limitation").textContent = catalog.limitation;
    $("capabilities-environment").textContent = `${catalog.environment.message} OS: ${catalog.os.current} / 対応確認: ${catalog.os.supported.join(", ")}${catalog.environment.checked_at ? " / 診断: " + new Date(catalog.environment.checked_at).toLocaleString() : ""}`;
    capabilityTable("capabilities-checks", ["診断項目", "期待値", "実際", "結果"],
        (catalog.environment.checks || []).map(c => [c.id, JSON.stringify(c.expected), JSON.stringify(c.actual), c.ok ? "確認済み" : "不一致"]));
    capabilityTable("capabilities-combinations", ["モデル", "物性", "熱", "ソルバ", "状態・理由"],
        catalog.combinations.map(c => [c.model, c.parameter_set, c.thermal, c.solver, c.reason]));
    capabilityTable("capabilities-options", ["設定キー", "状態", "理由・依存", "段階", "固定版の候補値"],
        catalog.options.map(o => [o.key, capabilityLabels[o.status], o.reason, o.phase, o.candidates.join(", ")]));
    capabilityTable("capabilities-candidates", ["種類", "名前", "接続状態・理由"], [
        ...catalog.models.map(m => [m.family, m.id, m.connected ? "登録済み組合せのみ" : "未接続・補助モデルを含む"]),
        ...catalog.parameter_sets.map(p => ["物性", p.id, p.reason]),
        ...catalog.solvers.map(s => ["ソルバ", s.id, s.reason])
    ]);
    $("capabilities-next").textContent = `次の追加単位：${catalog.next_increment}。`;
    renderCapabilityFeatures();
}

function initCapabilities() {
    renderCapabilities(physical.config.capabilities);
    $("capabilities-link").addEventListener("click", () => {
        $("capabilities-details").open = true;
    });
    if (location.hash === "#capabilities-panel") $("capabilities-details").open = true;
    $("capabilities-search").addEventListener("input", renderCapabilityFeatures);
    $("capabilities-filter").addEventListener("change", renderCapabilityFeatures);
    $("capabilities-probe").addEventListener("click", async () => {
        $("capabilities-probe").disabled = true;
        try {
            const catalog = await api("/api/physics/environment", {});
            physical.config.environment = catalog.environment;
            physical.config.capabilities = catalog;
            renderCapabilities(catalog);
            $("physics-environment").textContent = catalog.environment.message;
            physicsCompatibility();
        } catch (error) {
            $("capabilities-environment").textContent = error.message;
        } finally {
            $("capabilities-probe").disabled = false;
        }
    });
}
