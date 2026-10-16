"use strict";

const cathodes = {config: null, submitting: false};
const cathodeKinds = {
    finite_current: "公開数値・有限電流",
    vector_digitized: "論文図のベクトル抽出・有限電流",
    published_ocp: "公開OCP CSV",
    processed_ocp: "著者リポジトリの加工OCP"
};
const cathodeReasons = {
    duration: "設定時間に到達",
    positive_source_end: "正極曲線の収録端に到達",
    negative_source_end: "負極OCPの収録端に到達",
    positive_lower_voltage: "対Li基準の下限に到達",
    positive_upper_voltage: "対Li基準の上限に到達",
    cell_lower_voltage: "セル端子電圧の下限に到達",
    cell_upper_voltage: "セル端子電圧の上限に到達"
};
const cathodeFields = [
    ["name", "計算名", "text"],
    ["voltage_basis", "計算の電圧基準", [["vs_li", "対Li基準（Li対極）"], ["full_cell", "セル端子電圧（黒鉛OCPを差し引く近似）"]]],
    ["mode", "充放電", [["discharge", "放電"], ["charge", "充電"]]],
    ["initial_soc", "正極の初期相対座標 (0=放電端、1=充電端)", "number", 0, 1, 0.01],
    ["positive_mass_g", "正極活物質質量 (g)", "number", 0.001, 10000, "any"],
    ["ocp_capacity_mah_g", "OCP資料の仮定比容量 (mAh/g)", "number", 1, 400, "any"],
    ["current_a", "CC電流の大きさ (A)", "number", 0.00001, 1000, "any"],
    ["duration_min", "最大試験時間 (min)", "number", 0.01, 1440, "any"],
    ["dt_s", "出力間隔 (s)・曲線の節点も出力", "number", 0.1, 120, "any"],
    ["positive_min_v", "対Li基準の下限 (V vs Li/Li⁺)", "number", 1.5, 5, "any"],
    ["positive_max_v", "対Li基準の上限 (V vs Li/Li⁺)", "number", 1.5, 5, "any"],
    ["cell_min_v", "セル端子電圧の下限 (V)", "number", 1.5, 5, "any"],
    ["cell_max_v", "セル端子電圧の上限 (V)", "number", 1.5, 5, "any"],
    ["negative_capacity_ah", "負極基準容量 Qn (Ah、座標0→1)", "number", 0.00001, 10000, "any"],
    ["negative_initial_fraction", "負極の初期基準座標 (0–1、Li量の校正なし)", "number", 0, 1, "any"],
    ["additional_r_mohm", "参照曲線に追加する直列抵抗 (mΩ)", "number", 0, 10000, "any"]
];

function cathodeControl(name) {
    return $("cathode-" + name);
}

function selectedCathode() {
    return cathodes.config.catalog.curves.find(c => c.id === $("cathode-curve").value);
}

function readCathode() {
    const result = {curve_id: $("cathode-curve").value};
    for (const [name, label, type] of cathodeFields) result[name] = type === "number" ? Number(cathodeControl(name).value) : cathodeControl(name).value;
    return result;
}

function setCathode(input) {
    $("cathode-curve").value = input.curve_id;
    if (!selectedCathode()) throw new Error("この保存結果の曲線は現在のカタログにありません。");
    for (const [name] of cathodeFields) cathodeControl(name).value = input[name];
    renderCathodeSource();
}

function cathodeLink(url, text) {
    const link = element("a", text);
    if (url.startsWith("https://")) {
        link.href = url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
    }
    return link;
}

function cathodeRange(b) {
    return b.voltage_range_v.map(v => v.toFixed(3)).join("–") + " V";
}

function cathodePlot(c) {
    const w = 760, h = 350, left = 65, right = 25, top = 35, bottom = 52;
    const measured = c.branches.charge.specific_capacity_mah_g !== null;
    const maximum = measured ? Math.max(...Object.values(c.branches).map(b => b.specific_capacity_mah_g)) : 1;
    const x = v => left + v / maximum * (w - left - right);
    const y = v => h - bottom - (v - 1.5) / 3.3 * (h - top - bottom);
    const svg = svgElement("svg", {
        viewBox: `0 0 ${w} ${h}`,
        role: "img",
        "aria-label": `${c.chemistry}の公開正極参照曲線、V vs Li/Li⁺`
    });
    svg.append(svgElement("title", {}, `${c.label}。${cathodeKinds[c.kind]}。収録端より先には線を引きません。`));
    for (let i = 0; i <= 6; i++) {
        const v = 1.5 + i * .5;
        svg.append(svgElement("line", {x1: left, x2: w - right, y1: y(v), y2: y(v), stroke: "#dce7e2"}));
        svg.append(svgElement("text", {x: left - 12, y: y(v) + 4, "text-anchor": "end"}, v.toFixed(1)));
    }
    for (let i = 0; i <= 4; i++) svg.append(svgElement("text", {
        x: x(maximum * i / 4),
        y: h - bottom + 22,
        "text-anchor": "middle"
    }, (maximum * i / 4 * (measured ? 1 : 100)).toFixed(measured ? 1 : 0)));
    svg.append(svgElement("text", {x: left, y: 18}, "参照電圧 (V vs Li/Li⁺)"));
    svg.append(svgElement("text", {
        x: w - right,
        y: h - 8,
        "text-anchor": "end"
    }, measured ? "枝ごとの通過比容量 (mAh/g)" : "収録範囲内の相対充電座標 (%)"));
    Object.entries(c.branches).forEach(([mode, b], i) => {
        const color = mode === "charge" ? "#8c59a3" : "#287b56";
        const d = b.points.map(([q, v], j) => `${j ? "L" : "M"}${x(q * (measured ? b.specific_capacity_mah_g : 1)).toFixed(2)},${y(v).toFixed(2)}`).join(" ");
        svg.append(svgElement("path", {d, fill: "none", stroke: color, "stroke-width": 2.4}));
        svg.append(svgElement("text", {
            x: left + 20 + i * 230,
            y: 55,
            fill: color
        }, measured ? `${modes[mode]} · ${b.specific_capacity_mah_g.toFixed(2)} mAh/g` : "OCP参照（両方向で共用）"));
    });
    $("cathode-chart").replaceChildren(svg);
}

function syncCathodeFields() {
    if (!cathodes.config) return;
    const c = selectedCathode(), input = readCathode(), b = c.branches[input.mode] || c.branches.charge;
    const full = input.voltage_basis === "full_cell", hasCapacity = b.specific_capacity_mah_g !== null;
    for (const key of ["cell_min_v", "cell_max_v", "negative_capacity_ah", "negative_initial_fraction"]) cathodeControl(key).disabled = !full;
    cathodeControl("ocp_capacity_mah_g").disabled = hasCapacity;
    $("cathode-reference-current").disabled = c.specific_current_ma_g === null;
    const specific = hasCapacity ? b.specific_capacity_mah_g : input.ocp_capacity_mah_g;
    $("cathode-scale").textContent = `採用枝の容量スケール：${insightNumber(specific, 3)} mAh/g × ${input.positive_mass_g} g = ${insightNumber(specific * input.positive_mass_g / 1000, 4)} Ah（${hasCapacity ? "出典の枝容量" : "ユーザー仮定"}）。設定比電流 ${insightNumber(input.current_a * 1000 / input.positive_mass_g, 2)} mA/g。負極は初期座標とQnから電荷保存で更新します。`;
    const uncovered = [];
    if (input.positive_min_v < b.voltage_range_v[0]) uncovered.push(`下側 ${input.positive_min_v}–${b.voltage_range_v[0].toFixed(3)} V は未収録`);
    if (input.positive_max_v > b.voltage_range_v[1]) uncovered.push(`上側 ${b.voltage_range_v[1].toFixed(3)}–${input.positive_max_v} V は未収録`);
    $("cathode-status").textContent = `${modes[input.mode]}の収録範囲：${cathodeRange(b)}。${uncovered.join("。")} ${uncovered.length ? "収録端で停止します。" : ""}`;
    updateConfigurationSummary();
}

function renderCathodeSource() {
    const c = selectedCathode();
    const conditions = c.temperature_c === null ? (c.chemistry === "LCO" ? "室温（数値未指定）" : "温度未同定") : `${c.temperature_c}°C`;
    const source = $("cathode-source");
    source.replaceChildren(element("h3", c.composition), element("p", `${cathodeKinds[c.kind]} / ${conditions} / ${c.specific_current_ma_g === null ? "OCP参照" : c.specific_current_ma_g + " mA/g"} / ${c.license}`, "cathode-source-kind"));
    const notes = element("ul");
    for (const text of c.notes) notes.append(element("li", text));
    source.append(notes, cathodeLink(c.citation.url, c.citation.title));
    if (c.citation.original_doi) source.append(element("p", "元研究："), cathodeLink("https://doi.org/" + c.citation.original_doi, c.citation.original_doi));
    const metadata = {
        ...c,
        branches: Object.fromEntries(Object.entries(c.branches).map(([k, b]) => [k, {
            ...b,
            points: `${b.points.length}節点（数値は計算結果のJSONへ同梱）`
        }]))
    };
    $("cathode-provenance").textContent = JSON.stringify(metadata, null, 2);
    cathodePlot(c);
    syncCathodeFields();
}

function showCathodeResult(run) {
    const s = run.summary, c = run.source_snapshot.positive;
    $("result-title").textContent = run.name;
    $("result-meta").textContent = `${c.label} / ${run.voltage_reference === "Li/Li+" ? "対Li基準" : "セル端子電圧"} / ${modes[run.input.mode]} ${run.input.current_a} A · ${cathodeReasons[run.termination]} · ${(s.duration_s / 60).toFixed(2)} min · ${s.point_count}点`;
    $("metric-capacity").textContent = s.capacity_ah.toFixed(4);
    $("metric-energy").textContent = s.energy_wh.toFixed(4);
    $("metric-temp").textContent = insightNumber(c.temperature_c, 1);
    $("metric-temp-title").textContent = "参照測定温度";
    $("metric-temp-kind").textContent = "°C · 温度計算なし";
    $("metric-soc").textContent = (s.final_soc * 100).toFixed(2);
    $("metric-soc-kind").textContent = "% · 採用枝の相対座標";
    for (const id of ["csv", "json", "restore"]) $(id).disabled = false;
    const notes = element("ul");
    for (const note of run.limitations) notes.append(element("li", note));
    const snapshot = {
        input: run.input,
        mapping: run.mapping,
        catalog_version: run.source_snapshot.catalog_version,
        catalog_sha256: run.source_snapshot.catalog_sha256,
        positive: {
            ...c,
            branches: Object.fromEntries(Object.entries(c.branches).map(([k, b]) => [k, {
                ...b,
                points: `${b.points.length}節点：全数値はJSON/CSV出力に保存`
            }]))
        },
        negative: run.source_snapshot.negative ? {
            ...run.source_snapshot.negative,
            points: "全数値はJSON/CSV出力に保存"
        } : null
    };
    $("snapshot").replaceChildren(element("p", `${cathodeReasons[run.termination]}。正極参照 ${s.final_positive_v.toFixed(4)} V vs Li/Li⁺ − 負極OCP ${s.final_negative_v.toFixed(4)} V − I×追加R = 端子 ${s.final_terminal_v.toFixed(4)} V。追加抵抗のみのI²R：${s.additional_heat_w.toFixed(5)} W。`), notes, element("pre", JSON.stringify(snapshot, null, 2)));
    updateResultState();
    renderChart();
}

function restoreCathode(run) {
    try {
        setCathode(run.input);
        selectModelTab("cathodes");
        message(run.source_snapshot.catalog_sha256 === cathodes.config.catalog.sha256 ? "公開曲線計算の条件を復元しました。" : "条件を復元しました。カタログが保存時と異なります。再計算は現在のカタログを使用します。");
    } catch (error) {
        message(error.message, "error");
    }
}

async function initCathodes() {
    cathodes.config = await api("/api/cathodes");
    const fields = element("div", undefined, "fields two");
    for (const [name, text, type, min, max, step] of cathodeFields) {
        const label = element("label", text), input = element(Array.isArray(type) ? "select" : "input");
        input.id = "cathode-" + name;
        input.name = name;
        if (Array.isArray(type)) for (const [value, text] of type) {
            const option = element("option", text);
            option.value = value;
            input.append(option);
        }
        else {
            input.type = type;
            if (type === "number") {
                input.min = min;
                input.max = max;
                input.step = step;
            } else input.maxLength = 100;
        }
        input.required = true;
        label.append(input);
        fields.append(label);
    }
    $("cathode-fields").append(fields, element("p", "有限電流の枝は出典の比容量×活物質質量で計算します。OCPだけの資料は比容量を仮定します。追加Rは参照曲線に含まれる分極とは別に加算する値です（初期値0）。", "field-note"));
    $("cathode-curve").replaceChildren(...cathodes.config.catalog.curves.map(c => {
        const o = element("option", c.label);
        o.value = c.id;
        return o;
    }));
    setCathode(cathodes.config.defaults);
    $("cathode-curve").disabled = false;
    $("cathode-run").disabled = false;
    for (const format of ["csv", "json"]) $("cathode-source-" + format).addEventListener("click", () => {
        const c = selectedCathode();
        let text;
        if (format === "json") text = JSON.stringify(c, null, 2);
        else {
            const metadata = {
                ...c,
                branches: Object.fromEntries(Object.entries(c.branches).map(([key, b]) => [key, {
                    ...b,
                    points: undefined
                }]))
            };
            const rows = Object.entries(c.branches).flatMap(([mode, b]) => b.points.map(([x, v]) => [mode, x, b.specific_capacity_mah_g === null ? "" : x * b.specific_capacity_mah_g, v].join(",")));
            text = "\uFEFF# metadata: " + JSON.stringify(metadata) + "\nbranch,relative_progress,specific_throughput_mah_g,voltage_vs_li_v\n" + rows.join("\n");
        }
        const url = URL.createObjectURL(new Blob([text], {type: format === "csv" ? "text/csv;charset=utf-8" : "application/json;charset=utf-8"}));
        const link = element("a");
        link.href = url;
        link.download = c.id + "." + format;
        document.body.append(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    $("cathode-curve").addEventListener("change", () => {
        const c = selectedCathode();
        cathodeControl("positive_max_v").value = c.requested_max_v;
        cathodeControl("cell_max_v").value = c.requested_max_v;
        renderCathodeSource();
    });
    $("cathode-form").addEventListener("input", syncCathodeFields);
    $("cathode-form").addEventListener("change", event => {
        if (event.target.name === "mode") {
            const charge = cathodeControl("mode").value === "charge";
            cathodeControl("initial_soc").value = charge ? .05 : .95;
            cathodeControl("negative_initial_fraction").value = charge ? .1 : .9;
        }
        syncCathodeFields();
    });
    $("cathode-reference-current").addEventListener("click", () => {
        cathodeControl("current_a").value = selectedCathode().specific_current_ma_g * Number(cathodeControl("positive_mass_g").value) / 1000;
        syncCathodeFields();
    });
    $("cathode-inventory").replaceChildren(insightTable(["材料・出典", "データ種別", "充電容量 / 放電容量 (mAh/g)", "対Li収録範囲：充電 / 放電", "温度", "ライセンス"], cathodes.config.catalog.curves.map(c => [c.label, cathodeKinds[c.kind], ["charge", "discharge"].map(k => c.branches[k]?.specific_capacity_mah_g?.toFixed(3) || "OCPのみ").join(" / "), ["charge", "discharge"].map(k => c.branches[k] ? cathodeRange(c.branches[k]) : "同じOCPを共用").join(" / "), c.temperature_c === null ? "未指定" : `${c.temperature_c}°C`, c.license])));
    $("cathode-form").addEventListener("submit", async event => {
        event.preventDefault();
        if (cathodes.submitting || state.busy || !$("cathode-form").reportValidity()) return;
        const input = {...readCathode(), project_id: library.projectId}, version = ++state.viewVersion;
        cathodes.submitting = true;
        $("cathode-run").disabled = true;
        busy(true);
        try {
            const run = await api("/api/cathodes/simulate", input);
            if (version === state.viewVersion) {
                showResult(run);
                $("cathode-status").textContent = `${cathodeReasons[run.termination]}。${run.summary.capacity_ah.toFixed(4)} Ah。結果と来歴はCURVE VIEWから保存できます。`;
                message(`公開曲線計算：${cathodeReasons[run.termination]}。収録範囲と採用した測定条件を詳細欄で確認できます。`);
            }
        } catch (error) {
            message(error.message, "error");
            $("cathode-status").textContent = error.message;
        } finally {
            cathodes.submitting = false;
            $("cathode-run").disabled = false;
            busy(false);
            if (state.current) updateResultState();
        }
    });
}
