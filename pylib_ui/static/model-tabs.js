"use strict";

const modelNavigation = {active: "SPMe"};

function updateConfigurationSummary() {
    const active = modelNavigation.active;
    if (active === "design") {
        const name = $("design-form").elements.namedItem("name")?.value || "円筒設計";
        $("active-configuration").textContent = `編集中：共通の円筒設計 / ${name}。保存後、各方式で選択・反映してください。`;
    } else if (active === "synthetic") {
        $("active-configuration").textContent = `設定中：合成 1RC / ${value("cell_format").value} / ${value("chemistry").value} / ${value("capacity_ah").value} Ah / 初期SOC ${Math.round(Number(value("initial_soc").value) * 100)}% / 周囲 ${value("ambient_temp_c").value} °C。物理計算の設定とは独立です。`;
    } else {
        const design = $("physics-design").selectedOptions[0]?.textContent || "文献セットの基準形状";
        $("active-configuration").textContent = `設定中：${$("physics-model").value} / ${$("physics-parameter_set").value} / ${$("physics-thermal").value === "lumped" ? "集中熱" : "等温"} / 初期SOC ${Math.round(Number($("physics-initial_soc").value) * 100)}% / 周囲 ${$("physics-ambient_temp_c").value} °C / ${design}。SPMeとDFNで条件を共用します。`;
    }
}

function syncModelNavigation() {
    const model = $("physics-model").value;
    if (["SPMe", "DFN"].includes(modelNavigation.active)) modelNavigation.active = model;
    const active = modelNavigation.active;
    $("tab-SPMe").disabled = $("physics-model").querySelector('option[value="SPMe"]').disabled;
    $("tab-SPMe").title = $("tab-SPMe").disabled ? "Chen2020_compositeはDFN・等温のみ対応です。Chen2020を選ぶとSPMeを使用できます。" : "";
    for (const tab of document.querySelectorAll("[data-model-tab]")) {
        const selected = tab.dataset.modelTab === active;
        tab.setAttribute("aria-selected", String(selected));
        tab.tabIndex = selected ? 0 : -1;
    }
    $("physics-panel").hidden = !["SPMe", "DFN"].includes(active);
    $("synthetic-panel").hidden = active !== "synthetic";
    $("design-panel").hidden = active !== "design";
    $("physics-panel").setAttribute("aria-labelledby", "tab-" + model);
    $("physics-title").textContent = `${model}で充放電を計算`;
    const resultsOnly = active !== "synthetic";
    const layoutChanged = $("curve-workspace").classList.contains("results-only") !== resultsOnly;
    $("curve-workspace").classList.toggle("results-only", resultsOnly);
    updateConfigurationSummary();
    if (layoutChanged) renderChart();
}

function selectModelTab(model) {
    const tab = $("tab-" + model);
    if (!tab || tab.disabled) return;
    if (["SPMe", "DFN"].includes(model)) {
        $("physics-model").value = model;
        physicsCompatibility();
    }
    modelNavigation.active = model;
    syncModelNavigation();
}

function revealModelPanel(hash) {
    const model = {
        "#design-panel": "design",
        "#synthetic-panel": "synthetic",
        "#physics-panel": $("physics-model").value
    }[hash];
    if (!model) return;
    selectModelTab(model);
    $(hash.slice(1)).scrollIntoView({block: "start"});
}

function initModelNavigation() {
    for (const tab of document.querySelectorAll("[data-model-tab]")) {
        tab.addEventListener("click", () => selectModelTab(tab.dataset.modelTab));
        tab.addEventListener("keydown", event => {
            if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
            event.preventDefault();
            const tabs = [...document.querySelectorAll("[data-model-tab]")].filter(button => !button.disabled);
            const index = tabs.indexOf(tab);
            const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1
                : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
            selectModelTab(tabs[next].dataset.modelTab);
            tabs[next].focus();
        });
    }
    for (const id of ["simulation-form", "physics-form", "design-form"]) {
        $(id).addEventListener("input", updateConfigurationSummary);
        $(id).addEventListener("change", updateConfigurationSummary);
    }
    for (const link of document.querySelectorAll('a[href="#design-panel"], a[href="#physics-panel"], a[href="#synthetic-panel"]')) {
        link.addEventListener("click", () => revealModelPanel(link.hash));
    }
    window.addEventListener("hashchange", () => revealModelPanel(location.hash));
    syncModelNavigation();
    revealModelPanel(location.hash);
}

window.addEventListener("DOMContentLoaded", initModelNavigation);