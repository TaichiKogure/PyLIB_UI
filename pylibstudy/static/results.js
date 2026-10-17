"use strict";

const resultView = {catalog: null, version: 0, records: [], analysis: null};
const resultStatus = {available: "取得可", unavailable: "取得不可", not_selected: "未選択", pending: "未取得"};
const resultNumber = (x, digits = 5) => Number.isFinite(x) ? (x !== 0 && (Math.abs(x) < 1e-4 || Math.abs(x) >= 1e6) ? x.toExponential(digits - 1) : x.toLocaleString("ja-JP", {maximumSignificantDigits: digits})) : "取得不可";

function initResultSettings(catalog) {
    resultView.catalog = catalog;
    for (const [name, items] of [["variables", catalog.scalars.filter(v => !v.required)], ["distributions", catalog.distributions]]) {
        $("physics-output-" + name).replaceChildren(...items.map(v => {
            const label = element("label"), input = element("input");
            input.type = "checkbox";
            input.value = v.id;
            label.append(input, document.createTextNode(`${v.label} (${v.unit})`));
            return label;
        }));
    }
}

function setResultOutput(input) {
    const output = input.output || physical.config.defaults.output;
    for (const name of ["variables", "distributions"]) for (const check of $("physics-output-" + name).querySelectorAll("input")) check.checked = output[name].includes(check.value);
    $("physics-output-frames").value = output.frames;
    $("physics-output-max_nodes").value = output.max_nodes;
    $("physics-initial_ocv_v").value = input.initial_ocv_v ?? "";
    $("physics-reference_electrode_fraction").value = input.reference_electrode_fraction ?? "";
}

function readResultOutput(input) {
    input.output = {};
    for (const name of ["variables", "distributions"]) input.output[name] = [...$("physics-output-" + name).querySelectorAll("input:checked")].map(i => i.value);
    input.output.frames = Number($("physics-output-frames").value);
    input.output.max_nodes = Number($("physics-output-max_nodes").value);
    for (const name of ["initial_ocv_v", "reference_electrode_fraction"]) input[name] = $("physics-" + name).value === "" ? null : Number($("physics-" + name).value);
}

function scientificPlot(target, rows, xKey, yKey, xLabel, yLabel, scatter = false) {
    const valid = rows.filter(p => Number.isFinite(p[xKey]) && Number.isFinite(p[yKey]));
    if (!valid.length) {
        $(target).replaceChildren(element("p", "該当するデータがありません。欠損は補いません。", "field-note"));
        return;
    }
    const width = 800, height = 300, left = 90, right = 28, top = 35, bottom = 52;
    let xmin = Math.min(...valid.map(p => p[xKey])), xmax = Math.max(...valid.map(p => p[xKey]));
    let ymin = Math.min(...valid.map(p => p[yKey])), ymax = Math.max(...valid.map(p => p[yKey]));
    if (xmin === xmax) xmax = xmin + 1;
    const pad = (ymax - ymin) * .08 || Math.max(Math.abs(ymax) * .01, .001);
    ymin -= pad;
    ymax += pad;
    const px = x => left + (x - xmin) / (xmax - xmin) * (width - left - right),
        py = y => height - bottom - (y - ymin) / (ymax - ymin) * (height - top - bottom);
    const svg = svgElement("svg", {
        viewBox: `0 0 ${width} ${height}`,
        role: "img",
        "aria-label": `${yLabel} / ${xLabel}`
    });
    svg.append(svgElement("text", {x: left, y: 18}, yLabel), svgElement("text", {
        x: width - right,
        y: height - 7,
        "text-anchor": "end"
    }, xLabel));
    for (let i = 0; i <= 4; i++) {
        const y = ymin + (ymax - ymin) * i / 4, x = xmin + (xmax - xmin) * i / 4;
        svg.append(svgElement("line", {x1: left, x2: width - right, y1: py(y), y2: py(y), stroke: "#e1e8e1"}),
            svgElement("text", {x: left - 10, y: py(y) + 4, "text-anchor": "end"}, resultNumber(y)),
            svgElement("text", {x: px(x), y: height - bottom + 23, "text-anchor": "middle"}, resultNumber(x)));
    }
    let path = "", connected = false, priorGroup = null;
    for (const p of rows) {
        if (!Number.isFinite(p[xKey]) || !Number.isFinite(p[yKey])) {
            connected = false;
            continue;
        }
        if (p.group !== priorGroup) connected = false;
        path += `${connected ? "L" : "M"}${px(p[xKey])},${py(p[yKey])} `;
        connected = true;
        priorGroup = p.group;
        if (scatter) svg.append(svgElement("circle", {cx: px(p[xKey]), cy: py(p[yKey]), r: 3, fill: "#287b56"}));
    }
    if (!scatter) svg.append(svgElement("path", {d: path, fill: "none", stroke: "#287b56", "stroke-width": 2.2}));
    $(target).replaceChildren(svg);
}

function resultVariableOptions(run) {
    const meta = run.result_variables || Object.fromEntries(Object.entries(run.units || {}).filter(([key]) => run.points.some(p => Number.isFinite(p[key]))).map(([key, unit]) => [key, {
        label: key,
        unit,
        status: "available"
    }]));
    $("result-variable").replaceChildren(...Object.entries(meta).filter(([key]) => key !== "time_s").map(([key, v]) => {
        const option = element("option", `${v.label} (${v.unit}) · ${resultStatus[v.status] || v.status}`);
        option.value = key;
        option.disabled = !run.points.some(p => Number.isFinite(p[key]));
        option.title = v.reason || "";
        return option;
    }));
    if (!run.points.some(p => Number.isFinite(p[state.variable]))) state.variable = "voltage_v";
    $("result-variable").value = state.variable;
    capabilityTable("result-variable-catalog", ["変数", "単位", "次元", "取得状態", "理由・PyBaMM変数"],
        Object.entries(meta).map(([key, v]) => [v.label || key, v.unit, v.dimensions ?? 0, resultStatus[v.status] || v.status, v.reason || v.source_variable || "アプリの帳簿値"]));
}

function showLossFrame() {
    const run = state.current, p = run?.points[Number($("result-time").value)];
    if (!p) return;
    $("result-time-label").textContent = `${resultNumber(p.time_s)} s / 区間 ${p.segment_id} · 端子電圧 ${resultNumber(p.voltage_v)} V`;
    const rows = Object.entries(run.result_variables || {}).filter(([key]) => key.endsWith("_w") || key.includes("overpotential") || key.includes("ohmic_loss") || key === "surface_ocv_v");
    capabilityTable("result-loss-table", ["成分", "値", "単位"], rows.map(([key, v]) => [v.label, resultNumber(p[key]), v.unit]));
    const losses = rows.filter(([key, v]) => v.unit === "V" && key !== "surface_ocv_v" && Number.isFinite(p[key]));
    const svg = svgElement("svg", {
        viewBox: `0 0 800 ${Math.max(80, losses.length * 35 + 35)}`,
        role: "img",
        "aria-label": "符号付き電圧損失"
    });
    const max = Math.max(...losses.map(([k]) => Math.abs(p[k])), .0001);
    losses.forEach(([key, v], i) => {
        const width = Math.abs(p[key]) / max * 180, y = i * 35 + 15;
        svg.append(svgElement("text", {
                x: 5,
                y: y + 14
            }, v.label), svgElement("rect", {
                x: p[key] >= 0 ? 450 : 450 - width,
                y,
                width,
                height: 20,
                fill: p[key] >= 0 ? "#287b56" : "#8968a6"
            }),
            svgElement("text", {x: 650, y: y + 14}, `${resultNumber(p[key])} V`));
    });
    $("result-loss-chart").replaceChildren(svg);
}

function showSpatialFrame() {
    const spatial = state.current?.distributions?.variables[$("result-spatial-variable").value];
    if (!spatial || spatial.status !== "available") {
        $("result-spatial-chart").replaceChildren();
        $("result-spatial-label").textContent = "この結果に分布がありません。旧結果や未選択の変数は再計算が必要です。";
        return;
    }
    $("result-spatial-time").max = spatial.frames.length - 1;
    const index = Math.min(Number($("result-spatial-time").value), spatial.frames.length - 1),
        frame = spatial.frames[index];
    $("result-spatial-label").textContent = `${frame.time_s.toFixed(3)} s / 区間 ${frame.segment_id} / ${spatial.coordinates.length}/${spatial.original_node_count}座標点 · 保存単位m、表示μm。${spatial.note}`;
    scientificPlot("result-spatial-chart", spatial.coordinates.map((x, i) => ({
        coordinate: x * 1e6,
        value: frame.values[i]
    })), "coordinate", "value", `${spatial.coordinate} (μm)`, `${spatial.label} (${spatial.unit})`);
}

function showPerformance(run) {
    const soh = run.electrode_soh, p = run.performance;
    const rows = [];
    if (soh?.status === "available") for (const [key, label, unit] of [["capacity_ah", "eSOH平衡容量", "Ah"], ["negative_capacity_ah", "負極理論容量", "Ah"], ["positive_capacity_ah", "正極理論容量", "Ah"], ["cyclable_lithium_ah", "粒子内Li相当容量", "Ah"], ["initial_soc", "eSOH初期SOC", "1"]]) rows.push([label, resultNumber(soh[key]), unit]);
    if (p) for (const [key, label, unit] of [["discharge_ah", "区間積分・放電容量", "Ah"], ["charge_ah", "区間積分・充電容量", "Ah"], ["discharge_wh", "区間積分・放電エネルギー", "Wh"], ["charge_wh", "区間積分・充電エネルギー", "Wh"], ["coulombic_efficiency", "条件付き帳簿効率・容量比", "1"], ["energy_efficiency", "条件付き帳簿効率・エネルギー比", "1"]]) rows.push([label, resultNumber(p[key]), unit]);
    capabilityTable("result-performance", ["指標", "値", "単位"], rows);
    $("result-performance").append(element("p", soh?.note || soh?.reason || "旧結果には電極SOHの記録がありません。", "field-note"));
    if (p) {
        $("result-performance").append(element("p", p.note, "field-note"));
        const checks = element("div");
        checks.id = "result-balance-checks";
        $("result-performance").append(checks);
        capabilityTable(checks.id, ["収支", "最大残差", "許容差", "判定"], Object.entries(p.balance_checks).map(([key, v]) => [
            key === "voltage" ? "電圧成分の合計" : "発熱成分の合計", `${resultNumber(v.max_absolute_residual)} ${v.unit}`, `${v.tolerance} ${v.unit}`,
            v.passed === null ? "必要な系列が未取得" : v.passed ? "許容差内" : "要確認"]));
    }
}

async function refreshResultSources(run, version) {
    const project = library.projectId, records = await api(`/api/runs?project_id=${encodeURIComponent(project)}`);
    if (version !== resultView.version || project !== library.projectId || state.current?.id !== run.id) return;
    resultView.records = records.filter(r => r.record_type === "dataset");
    $("result-measured").replaceChildren(...resultView.records.map(r => {
        const o = element("option", `${r.name} · ${sourceLabel(r)}`);
        o.value = r.id;
        return o;
    }));
    syncMeasuredSegments();
    $("result-postprocess").disabled = !records.some(r => r.id === run.id);
    $("result-compare").disabled = run.record_type !== "physics" || !resultView.records.length;
    await refreshResultAnalyses(project, version);
}

function syncMeasuredSegments() {
    const record = resultView.records.find(r => r.id === $("result-measured").value);
    $("result-measured-segment").replaceChildren(...Array.from({length: record?.quality?.segment_count || 0}, (_, i) => {
        const o = element("option", `区間 ${i}`);
        o.value = i;
        return o;
    }));
}

async function refreshResultAnalyses(project = library.projectId, version = resultView.version) {
    const records = await api(`/api/analyses?project_id=${encodeURIComponent(project)}`);
    if (project !== library.projectId || version !== resultView.version) return;
    $("result-analysis-history").replaceChildren(...records.map(r => {
        const o = element("option", `${r.record_type === "postprocess" ? "後処理" : "残差"} · ${r.source_names.join(" / ")} · ${r.id.slice(0, 8)}`);
        o.value = r.id;
        return o;
    }));
    $("result-analysis-open").disabled = !records.length;
}

function showResultExplorer(run) {
    const version = ++resultView.version;
    resultView.analysis = null;
    $("result-explorer").hidden = !["physics", "dataset"].includes(run.record_type);
    for (const id of ["result-analysis-json", "result-analysis-csv"]) $(id).hidden = true;
    $("result-analysis-output").replaceChildren();
    $("result-analysis-status").textContent = "";
    resultVariableOptions(run);
    for (const [id, suffix, available] of [["spatial-csv", ".spatial.csv", !!run.distributions], ["citations-bib", ".bib", run.citation_export?.status === "available"]]) {
        $(id).hidden = !available;
        $(id).href = `/api/results/${encodeURIComponent(run.id)}${suffix}`;
        $(id).setAttribute("download", "");
    }
    if ($("result-explorer").hidden) return;
    $("result-explorer-note").textContent = "取得した結果の後処理です。物性・測定条件・セルの同一性を確認するまでは実測校正済みとは扱いません。";
    $("result-loss-details").hidden = run.record_type !== "physics";
    $("result-spatial-details").hidden = run.record_type !== "physics";
    $("result-residual-details").hidden = run.record_type !== "physics";
    showPerformance(run);
    $("result-time").max = run.points.length - 1;
    $("result-time").value = 0;
    showLossFrame();
    const spatial = Object.entries(run.distributions?.variables || {});
    $("result-spatial-variable").replaceChildren(...spatial.map(([key, v]) => {
        const o = element("option", `${v.label} (${v.unit}) · ${resultStatus[v.status]}`);
        o.value = key;
        o.disabled = v.status !== "available";
        o.title = v.reason || "";
        return o;
    }));
    const first = spatial.find(([, v]) => v.status === "available");
    if (first) $("result-spatial-variable").value = first[0];
    $("result-spatial-time").value = 0;
    showSpatialFrame();
    $("result-sim-segment").replaceChildren(...[...new Set(run.points.map(p => p.segment_id ?? 0))].map(i => {
        const o = element("option", `区間 ${i}`);
        o.value = i;
        return o;
    }));
    $("result-postprocess").disabled = true;
    $("result-compare").disabled = true;
    refreshResultSources(run, version).catch(error => {
        if (version === resultView.version) $("result-analysis-status").textContent = error.message;
    });
}

function showAnalysis(record) {
    resultView.analysis = record;
    const target = $("result-analysis-output");
    target.replaceChildren();
    for (const id of ["result-analysis-json", "result-analysis-csv"]) {
        const format = id.endsWith("json") ? "json" : "csv";
        $(id).href = `/api/analyses/${record.id}.${format}?project_id=${encodeURIComponent(library.projectId)}`;
        $(id).hidden = false;
        $(id).setAttribute("download", "");
    }
    for (const note of record.limitations) target.append(element("p", note, "field-note"));
    if (record.record_type === "residual_analysis") {
        const metrics = element("div");
        metrics.id = "result-residual-metrics";
        target.append(metrics);
        capabilityTable(metrics.id, ["指標", "値"], [["比較点数", record.metrics.count], ["RMSE", `${resultNumber(record.metrics.rmse)} ${record.units}`],
            ["平均絶対誤差", `${resultNumber(record.metrics.mae)} ${record.units}`], ["平均残差（計算−測定）", `${resultNumber(record.metrics.bias)} ${record.units}`],
            ["最大絶対残差", `${resultNumber(record.metrics.max_absolute)} ${record.units}`], ["重複範囲外 / 欠損で除外", `${record.excluded.outside_overlap} / ${record.excluded.missing}`]]);
        const conditions = element("div");
        conditions.id = "result-condition-table";
        target.append(conditions);
        const labels = {matched: "許容差内", mismatch: "条件差あり", unknown: "情報不足"};
        capabilityTable(conditions.id, ["照合条件", "判定", "最大差 / 許容差"], [...[["current_a", "電流", "A"], ["temperature_c", "温度", "°C"]].map(([key, label, unit]) => [
            label, labels[record.conditions[key].status], `${resultNumber(record.conditions[key].max_absolute_difference)} / ${record.conditions[key].tolerance} ${unit}`]),
            ["温度の測定位置", "手動確認が必要", `計算: 体積平均 / 取込: ${record.conditions.temperature_basis.measured}`],
            ["初期状態・材料・設計・対象セル", "手動確認が必要", "原本・計算入力と照合してください"]]);
        target.append(element("p", `計算時刻 = 取込時刻 + ${record.config.time_offset_s} s。計算区間 ${record.config.simulation_segment} / 取込区間 ${record.config.measurement_segment}`));
        const chart = element("div", undefined, "result-scientific-chart");
        chart.id = "result-residual-chart";
        target.append(chart);
        scientificPlot(chart.id, record.rows, "time_s", "residual", "計算時刻 (s)", `計算−測定 (${record.units})`);
    } else {
        const chart = element("div", undefined, "result-scientific-chart");
        chart.id = "result-derivative-chart";
        target.append(chart);
        scientificPlot(chart.id, record.derivatives, "voltage_v", "dq_dv_ah_v", "電圧 (V)", "dQ/dV (Ah/V)");
        const reverse = element("div", undefined, "result-scientific-chart");
        reverse.id = "result-inverse-chart";
        target.append(reverse);
        scientificPlot(reverse.id, record.derivatives, "capacity_ah", "dv_dq_v_ah", "絶対通過容量 (Ah)", "dV/dQ (V/Ah)");
        const pulses = element("div");
        pulses.id = "result-pulse-table";
        target.append(pulses);
        capabilityTable(pulses.id, ["パルス時刻 s", "ΔI A", "遅延 s", "抵抗 Ω", "状態"], record.pulses.map(p => [p.time_s, p.delta_current_a, p.delay_s, resultNumber(p.resistance_ohm), p.status]));
        const gitt = element("div");
        gitt.id = "result-gitt-table";
        target.append(gitt);
        capabilityTable(gitt.id, ["パルス時刻 s", "ΔE_p V", "ΔE_rest V", "sqrt(t)傾き V/√s", "緩和指標 1/s"], record.gitt.map(p => [p.pulse_start_s, p.delta_pulse_v, p.delta_rest_v, p.sqrt_time_slope_v_sqrt_s, resultNumber(p.relaxation_index_per_s)]));
        target.append(element("pre", JSON.stringify({config: record.config, method: record.method}, null, 2)));
    }
    $("result-analysis-status").textContent = `保存済み解析 ${record.id} · ${record.source_snapshots.map(s => s.name).join(" / ")}`;
}

window.addEventListener("DOMContentLoaded", () => {
    $("result-variable").addEventListener("change", () => {
        state.variable = $("result-variable").value;
        renderChart();
    });
    $("result-time").addEventListener("input", showLossFrame);
    $("result-spatial-variable").addEventListener("change", () => {
        $("result-spatial-time").value = 0;
        showSpatialFrame();
    });
    $("result-spatial-time").addEventListener("input", showSpatialFrame);
    $("result-measured").addEventListener("change", syncMeasuredSegments);
    for (const [id, path] of [["result-postprocess", "postprocess"], ["result-compare", "compare"]]) $(id).addEventListener("click", async () => {
        const run = state.current, project = library.projectId, version = resultView.version;
        if (!run) return;
        $(id).disabled = true;
        try {
            const payload = path === "postprocess" ? {
                    run_id: run.id,
                    config: {
                        smoothing_window: Number($("result-smoothing").value),
                        min_delta_v: Number($("result-delta-v").value),
                        pulse_delay_s: Number($("result-pulse-delay").value),
                        rest_min_s: Number($("result-rest-min").value)
                    }
                } :
                {
                    simulation_id: run.id,
                    dataset_id: $("result-measured").value,
                    config: {
                        simulation_segment: Number($("result-sim-segment").value),
                        measurement_segment: Number($("result-measured-segment").value),
                        time_offset_s: Number($("result-time-offset").value),
                        variable: $("result-residual-variable").value
                    }
                };
            const record = await api(`/api/analysis/${path}`, {...payload, project_id: project});
            if (version !== resultView.version || project !== library.projectId) return;
            showAnalysis(record);
            await refreshResultAnalyses(project, version);
        } catch (error) {
            if (version === resultView.version) $("result-analysis-status").textContent = error.message;
        } finally {
            if (version === resultView.version) $(id).disabled = false;
        }
    });
    $("result-analysis-open").addEventListener("click", async () => {
        const version = resultView.version, project = library.projectId;
        try {
            const r = await api(`/api/analyses/${$("result-analysis-history").value}?project_id=${encodeURIComponent(project)}`);
            if (version === resultView.version && project === library.projectId) showAnalysis(r);
        } catch (error) {
            if (version === resultView.version) $("result-analysis-status").textContent = error.message;
        }
    });
});
