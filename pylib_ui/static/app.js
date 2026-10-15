"use strict";

const $ = (id) => document.getElementById(id);
const form = $("simulation-form");
const state = {
    defaults: null,
    current: null,
    savedIds: new Set(),
    comparisons: new Map(),
    variable: "voltage_v",
    busy: false,
    viewVersion: 0,
    nameEdited: false
};
const modes = {discharge: "放電", charge: "充電", rest: "休止"};
const reasons = {
    duration: "設定時間に到達",
    lower_voltage: "下限電圧に到達",
    upper_voltage: "上限電圧に到達",
    soc_empty: "SOC 0%に到達",
    soc_full: "SOC 100%に到達"
};
const colors = ["#287b56", "#bb842e", "#577bb3", "#b96589"];
const fieldNames = {
    name: "計算名",
    model: "モデル",
    cell_format: "セル形式",
    chemistry: "模式曲線",
    capacity_ah: "基準容量 (Ah)",
    diameter_mm: "外径 (mm)",
    height_mm: "全高 (mm)",
    initial_soc: "初期SOC (0–1)",
    mode: "試験",
    c_rate: "Cレート",
    duration_min: "試験時間 (min)",
    dt_s: "出力間隔 (s)",
    initial_temp_c: "初期温度 (°C)",
    ambient_temp_c: "周囲温度 (°C)",
    r0_mohm: "R₀ (mΩ)",
    r1_mohm: "R₁ (mΩ)",
    tau_s: "時定数 (s)",
    thermal_capacity_j_k: "熱容量 (J/K)",
    heat_transfer_w_m2_k: "熱伝達率 (W/m²/K)",
    min_voltage_v: "下限電圧 (V)",
    max_voltage_v: "上限電圧 (V)"
};

function message(text, kind = "") {
    $("message").textContent = text;
    $("message").className = `message ${kind}`;
}

function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
}

function value(name) {
    return form.elements.namedItem(name);
}

function readInput() {
    const result = {};
    for (const [key, defaultValue] of Object.entries(state.defaults)) {
        result[key] = typeof defaultValue === "number" ? Number(value(key).value) : value(key).value.trim();
    }
    return result;
}

function setInput(input) {
    for (const [key, val] of Object.entries(input)) if (value(key)) value(key).value = val;
    syncInput();
}

function syncInput() {
    if (designing.config) syncDesignBinding();
    $("cell-title").textContent = value("cell_format").value;
    $("cell-size").textContent = `Ø${value("diameter_mm").value} × ${value("height_mm").value} mm`;
    $("soc-output").textContent = `${Math.round(Number(value("initial_soc").value) * 100)}%`;
    const mode = value("mode").value;
    value("c_rate").disabled = mode === "rest";
    const current = Number(value("capacity_ah").value) * Number(value("c_rate").value) * ({
        discharge: 1,
        charge: -1,
        rest: 0
    }[mode]);
    $("current-preview").textContent = `電流：${current.toFixed(2)} A （放電＋／充電−）`;
    if (state.current) updateResultState();
    updateConfigurationSummary();
}

function updateResultState() {
    if (state.current.record_type === "reference_curve") {
        const saved = state.savedIds.has(state.current.id);
        $("result-state").textContent = `${saved ? "保存済み" : "未保存"} · 公開曲線の参照計算 · 実測未検証`;
        $("result-state").className = `pill ${saved ? "saved" : ""}`;
        $("save").textContent = saved ? "✓ 保存済み" : "＋ 結果と出典を保存";
        $("save").disabled = state.busy || saved;
        return;
    }
    if (state.current.record_type === "physics") {
        $("result-state").textContent = `${state.current.termination === "partial" ? "一部結果" : "保存済み"} · ${state.current.engine.label} · 実測未検証`;
        $("result-state").className = "pill saved";
        $("save").textContent = "✓ ジョブ結果は保存済み";
        $("save").disabled = true;
        return;
    }
    if (state.current.record_type === "dataset") {
        const saved = state.savedIds.has(state.current.id);
        $("result-state").textContent = `${saved ? "保存済み" : "未保存プレビュー"} · ${sourceLabel(state.current)}`;
        $("result-state").className = `pill ${saved ? "saved" : ""}`;
        $("save").textContent = saved ? "✓ 保存済み" : "＋ このプレビューを保存";
        $("save").disabled = state.busy || saved;
        return;
    }
    const dirty = Object.keys(state.defaults).some(key => readInput()[key] !== state.current.input[key]);
    const saved = state.savedIds.has(state.current.id);
    $("result-state").textContent = dirty ? "条件変更あり · 再計算待ち" : saved ? "保存済み · 合成" : "未保存 · 合成";
    $("result-state").className = `pill ${!dirty && saved ? "saved" : ""}`;
    $("save").textContent = saved ? "✓ 保存済み" : "＋ 結果を保存";
    $("save").disabled = state.busy || saved;
}

async function api(path, body) {
    const response = await fetch(path, body === undefined ? {} : {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body)
    });
    let data;
    try {
        data = await response.json();
    } catch {
        throw new Error("サーバーの応答を読み取れません。起動状態を確認してください。");
    }
    if (!response.ok) throw new Error(data.error || "処理に失敗しました。");
    return data;
}

function busy(enabled, operation = "計算") {
    state.busy = enabled;
    $("run").disabled = enabled;
    $("run").textContent = enabled ? `${operation}中…` : "▶ シミュレーションを実行";
    $("save").disabled = enabled || !state.current || state.savedIds.has(state.current.id);
    for (const id of ["project", "create-project", "demo-import"]) $(id).disabled = enabled;
}

function showResult(run) {
    state.current = run;
    $("original").disabled = !run.original;
    $("metric-soc-kind").textContent = "% · 推定状態";
    if (run.record_type === "reference_curve") {
        showCathodeResult(run);
        return;
    }
    if (run.record_type === "physics") {
        showPhysics(run);
        return;
    }
    if (run.record_type === "dataset") {
        showDataset(run);
        return;
    }
    $("result-title").textContent = run.name;
    const cfg = run.input, s = run.summary;
    $("result-meta").textContent = `${cfg.cell_format} / ${cfg.chemistry} / ${modes[cfg.mode]} ${cfg.mode === "rest" ? "0 A" : `${cfg.c_rate}C`} · ${reasons[run.termination]} · ${(s.duration_s / 60).toFixed(2)} min · ${s.point_count.toLocaleString()}点`;
    $("metric-capacity").textContent = s.capacity_ah.toFixed(3);
    $("metric-energy").textContent = s.energy_wh.toFixed(2);
    $("metric-temp").textContent = s.max_temperature_c.toFixed(1);
    $("metric-soc").textContent = (s.final_soc * 100).toFixed(1);
    for (const id of ["csv", "json", "restore"]) $(id).disabled = false;
    updateResultState();
    const grid = element("div", undefined, "snapshot-grid");
    for (const [key, val] of Object.entries(cfg)) {
        const row = element("div");
        row.append(element("strong", `${fieldNames[key] || key}：`), document.createTextNode(key === "mode" ? modes[val] : key === "model" ? run.engine.label : String(val)));
        grid.append(row);
    }
    const limitations = element("ul");
    for (const note of run.limitations) limitations.append(element("li", note));
    $("snapshot").replaceChildren(element("p", `計算ID：${run.id} · ${run.engine.id} v${run.engine.version} · 合成／未校正`), grid, limitations);
    if (run.design_snapshot) $("snapshot").append(element("pre", JSON.stringify({design_snapshot: run.design_snapshot}, null, 2)));
    renderChart();
}

function svgElement(tag, attrs = {}, text) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [key, val] of Object.entries(attrs)) node.setAttribute(key, val);
    if (text !== undefined) node.textContent = text;
    return node;
}

function renderChart() {
    const runs = new Map();
    if (state.current) runs.set(state.current.id, state.current);
    for (const [id, run] of state.comparisons) if (run) runs.set(id, run);
    if (!runs.size) {
        $("chart").replaceChildren(element("p", "表示・比較するカーブを選択してください。", "chart-empty"));
        $("legend").replaceChildren();
        return;
    }
    const allSeries = [...runs.values()], variable = state.variable, xKey = $("x-axis").value;
    const valid = p => Number.isFinite(p[xKey]) && Number.isFinite(p[variable]);
    const series = allSeries.filter(run => run.points.some(valid));
    if (!series.length) {
        $("chart").replaceChildren(element("p", "この軸に対応するデータがありません。欠損は補完していません。", "chart-empty"));
        $("legend").replaceChildren();
        return;
    }
    const yFactor = variable === "soc" ? 100 : 1, xFactor = xKey === "time_s" ? 1 / 60 : xKey === "soc" ? 100 : 1;
    const labels = {
        voltage_v: allSeries.some(r => r.record_type === "reference_curve") ? "電圧 (V) · 対Li/セルの基準は凡例を確認" : "電圧 (V)",
        positive_reference_v: "正極参照電圧 (V vs Li/Li⁺)",
        negative_reference_v: "負極OCP (V vs Li/Li⁺)",
        soc: allSeries.some(r => r.record_type === "physics") ? "SOC / 基準容量による電荷帳簿 (%)" : "SOC (%)",
        temperature_c: "温度 (°C) · 測定位置は来歴参照",
        current_a: "電流 (A)"
    };
    let yMin = Infinity, yMax = -Infinity, xMax = 0, xMin = 0;
    for (const run of series) for (const p of run.points) {
        if (!valid(p)) continue;
        const y = p[variable] * yFactor;
        yMin = Math.min(yMin, y);
        yMax = Math.max(yMax, y);
        xMax = Math.max(xMax, p[xKey] * xFactor);
        xMin = Math.min(xMin, p[xKey] * xFactor);
    }
    const margin = Math.max((yMax - yMin) * 0.12, variable === "soc" ? 2 : 0.05);
    yMin -= margin;
    yMax += margin;
    xMax = xMax || 1;
    const width = Math.max(260, $("chart").clientWidth), height = $("chart").clientHeight, left = 52, right = 16,
        top = 30, bottom = 44;
    const px = (x) => left + (x - xMin) / (xMax - xMin || 1) * (width - left - right);
    const py = (y) => height - bottom - (y - yMin) / (yMax - yMin) * (height - top - bottom);
    const svg = svgElement("svg", {
        viewBox: `0 0 ${width} ${height}`,
        role: "img",
        "aria-label": `${labels[variable]}の比較グラフ。${series.length}本。`
    });
    svg.append(svgElement("title", {}, `${labels[variable]}。凡例で種別を確認。自動整列・正規化なし`));
    for (let i = 0; i <= 5; i++) {
        const y = yMin + (yMax - yMin) * i / 5, x = xMin + (xMax - xMin) * i / 5;
        svg.append(svgElement("line", {
            x1: left,
            x2: width - right,
            y1: py(y),
            y2: py(y),
            stroke: "#e6ede6",
            "stroke-width": 1
        }));
        svg.append(svgElement("text", {
            x: left - 12,
            y: py(y) + 4,
            "text-anchor": "end",
            fill: "#809087",
            "font-size": 11
        }, y.toFixed(variable === "voltage_v" ? 2 : 1)));
        svg.append(svgElement("text", {
            x: px(x),
            y: height - bottom + 22,
            "text-anchor": "middle",
            fill: "#809087",
            "font-size": 11
        }, x.toFixed(1)));
    }
    svg.append(svgElement("text", {x: left, y: 13, fill: "#708078", "font-size": 11}, labels[variable]));
    svg.append(svgElement("text", {
        x: width - right,
        y: height - 4,
        "text-anchor": "end",
        fill: "#708078",
        "font-size": 11
    }, xKey === "time_s" ? "記録時間 (min)" : xKey === "soc" ? "SOC (%)" : "容量 (Ah) · 原本指定／区間通過容量"));
    const legend = [];
    series.forEach((run, index) => {
        // Preserve gaps and reset boundaries, including when values are absent.
        let connected = false, previousSegment = null;
        const commands = [];
        for (const p of run.points) {
            if (!valid(p)) {
                connected = false;
                continue;
            }
            if (p.segment_id !== previousSegment) connected = false;
            commands.push(`${connected ? "L" : "M"}${px(p[xKey] * xFactor).toFixed(2)},${py(p[variable] * yFactor).toFixed(2)}`);
            connected = true;
            previousSegment = p.segment_id;
        }
        const path = commands.join(" ");
        const line = svgElement("path", {
            d: path,
            fill: "none",
            stroke: colors[index],
            "stroke-width": 2.5,
            "stroke-linecap": "round",
            "stroke-linejoin": "round"
        });
        line.append(svgElement("title", {}, `${run.name}（${sourceLabel(run)}）`));
        svg.append(line);
        const last = run.points.filter(valid).at(-1);
        svg.append(svgElement("circle", {
            cx: px(last[xKey] * xFactor),
            cy: py(last[variable] * yFactor),
            r: 4,
            fill: colors[index],
            stroke: "white",
            "stroke-width": 2
        }));
        const entry = element("span"), swatch = element("i", undefined, `series-${index}`);
        entry.append(swatch, document.createTextNode(`${run.name} · ${sourceLabel(run)}${state.current?.id === run.id ? "（表示中）" : ""}`));
        legend.push(entry);
    });
    for (const run of allSeries.filter(run => !series.includes(run))) legend.push(element("span", `${run.name}：この軸のデータなし`));
    $("chart").replaceChildren(svg);
    $("legend").replaceChildren(...legend);
}

async function refreshHistory() {
    const history = await api(`/api/runs?project_id=${encodeURIComponent(library.projectId)}`);
    state.savedIds = new Set(history.map(run => run.id));
    if (state.current) updateResultState();
    if (!history.length) {
        $("history").replaceChildren(element("p", "まだ保存した結果はありません。計算後に「結果を保存」で追加できます。", "empty-history"));
        return;
    }
    const rows = history.map(run => {
        const row = element("div", undefined, "history-row"), checkbox = element("input");
        checkbox.type = "checkbox";
        checkbox.checked = state.comparisons.has(run.id);
        checkbox.setAttribute("aria-label", `${run.name}を比較`);
        checkbox.addEventListener("change", async () => {
            if (!checkbox.checked) {
                state.comparisons.delete(run.id);
                renderChart();
                return;
            }
            if (state.comparisons.size >= 3) {
                checkbox.checked = false;
                message("比較は最大3件です。先に他のチェックを外してください。", "error");
                return;
            }
            checkbox.disabled = true;
            // Reserve the slot during fetch so rapid checks cannot exceed the limit.
            state.comparisons.set(run.id, null);
            try {
                state.comparisons.set(run.id, await api(`/api/results/${run.id}`));
                renderChart();
                message("保存カーブを重ね合わせました。各カーブの凡例を確認してください。");
            } catch (error) {
                state.comparisons.delete(run.id);
                checkbox.checked = false;
                message(error.message, "error");
            } finally {
                checkbox.disabled = false;
            }
        });
        const info = element("div");
        info.append(element("div", run.name, "history-name"));
        const date = new Date(run.created_at).toLocaleString("ja-JP", {
            timeZone: "Asia/Tokyo",
            month: "2-digit",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit"
        });
        info.append(element("p", run.record_type === "physics"
            ? `${run.engine.label} / ${run.input.parameter_set} · ${run.summary.capacity_ah.toFixed(3)} Ah · ${date} JST · 実測未検証`
            : run.record_type === "reference_curve"
            ? `${run.source_snapshot.positive.chemistry} / ${run.voltage_reference === "Li/Li+" ? "対Li基準" : "セル端子電圧"} / ${modes[run.input.mode]} · ${run.summary.capacity_ah.toFixed(3)} Ah · ${date} JST · 参照計算`
            : run.record_type === "dataset"
            ? `${sourceLabel(run)} · ${run.quality.row_count}点／${run.quality.segment_count}区間 · ${run.specimen_id || "個体不明"} · ${date} JST`
            : `${run.input.cell_format} / ${run.input.chemistry} · ${modes[run.input.mode]} ${run.input.mode === "rest" ? "0 A" : run.input.c_rate + "C"} · ${run.summary.capacity_ah.toFixed(3)} Ah · ${date} JST · ${sourceLabel(run)}`));
        const open = element("button", "表示");
        open.type = "button";
        open.addEventListener("click", async () => {
            const version = ++state.viewVersion;
            try {
                const result = await api(`/api/results/${run.id}`);
                if (version !== state.viewVersion) return;
                showResult(result);
                message(result.record_type === "dataset"
                    ? "保存カーブを表示しました。取込条件・出典は詳細欄、原本は「取込原本」で確認できます。"
                    : "保存結果を表示しました。入力は「この結果の条件を復元」で戻せます。");
            } catch (error) {
                message(error.message, "error");
            }
        });
        row.append(checkbox, info, open);
        return row;
    });
    $("history").replaceChildren(...rows);
}

function suggestName(field) {
    if (!state.nameEdited && ["cell_format", "c_rate", "mode", "chemistry"].includes(field)) value("name").value = `${value("cell_format").value} · ${value("chemistry").value} · ${value("mode").value === "rest" ? "" : value("c_rate").value + "C "}${modes[value("mode").value]}`;
}

form.addEventListener("input", (event) => {
    if (event.target.name === "name") state.nameEdited = true;
    suggestName(event.target.name);
    syncInput();
});
form.addEventListener("change", (event) => {
    const field = event.target.name;
    if (field === "cell_format") {
        const small = value("cell_format").value === "18650";
        for (const [key, val] of Object.entries({
            diameter_mm: small ? 18 : 21,
            height_mm: small ? 65 : 70,
            capacity_ah: small ? 3 : 5,
            thermal_capacity_j_k: small ? 50 : 70,
            r0_mohm: small ? 35 : 25,
            r1_mohm: small ? 12 : 10
        })) value(key).value = val;
        message("セル形式の初期値を適用しました。寸法・容量・抵抗・熱容量は編集できます。");
    }
    if (field === "chemistry") {
        const lfp = value("chemistry").value === "LFP";
        value("min_voltage_v").value = lfp ? 2.5 : 2.8;
        value("max_voltage_v").value = lfp ? 3.65 : 4.2;
        message("模式曲線と電圧範囲の初期値を変更しました。実測パラメータではありません。");
    }
    if (field === "mode") {
        if (value("mode").value === "charge") value("initial_soc").value = 0.2;
        if (value("mode").value === "discharge") value("initial_soc").value = 0.95;
    }
    if (!state.nameEdited && ["cell_format", "c_rate", "mode", "chemistry"].includes(field)) value("name").value = `${value("cell_format").value} · ${value("chemistry").value} · ${value("mode").value === "rest" ? "" : value("c_rate").value + "C "}${modes[value("mode").value]}`;
    syncInput();
});
form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (state.busy || !form.reportValidity()) return;
    const input = {...readInput(), project_id: library.projectId}, version = ++state.viewVersion;
    syncDesignBinding();
    if (designing.binding) input.design_id = designing.binding.id;
    busy(true);
    message("シミュレーションを計算しています…", "busy");
    try {
        const run = await api("/api/simulate", input);
        if (version === state.viewVersion) {
            showResult(run);
            message(`計算完了：${reasons[run.termination]}。結果を残す場合は「結果を保存」を押してください。`);
        }
    } catch (error) {
        message(error.message || "サーバーに接続できません。", "error");
    } finally {
        busy(false);
    }
});
$("reset").addEventListener("click", () => {
    state.nameEdited = false;
    setInput(state.defaults);
    message("入力を初期値に戻しました。表示中の結果は計算時の条件のままです。");
});
$("restore").addEventListener("click", () => {
    if (state.current?.record_type === "reference_curve") {
        restoreCathode(state.current);
        return;
    }
    if (state.current?.record_type === "physics") {
        restorePhysics(state.current);
        return;
    }
    if (!state.current || state.current.record_type === "dataset") return;
    state.nameEdited = true;
    setInput(state.current.input);
    designing.binding = state.current.design_snapshot || null;
    syncDesignBinding();
    selectModelTab("synthetic");
    message("表示中の結果の入力を復元しました。変更後に再計算できます。");
});
$("save").addEventListener("click", async () => {
    if (!state.current || state.busy) return;
    const run = state.current;
    busy(true, "保存処理");
    try {
        await api("/api/save", {id: run.id});
        state.savedIds.add(run.id);
        message("カーブと来歴を保存しました。");
        await refreshHistory();
    } catch (error) {
        message(error.message, "error");
    } finally {
        busy(false);
        if (state.current) updateResultState();
    }
});
for (const format of ["csv", "json"]) $(format).addEventListener("click", () => {
    if (state.current) {
        const link = element("a");
        link.href = `/api/results/${state.current.id}.${format}`;
        link.download = `lib-${state.current.id}.${format}`;
        document.body.append(link);
        link.click();
        link.remove();
    }
});
$("refresh").addEventListener("click", () => refreshHistory().catch(error => message(error.message, "error")));
$("x-axis").addEventListener("change", renderChart);
for (const button of document.querySelectorAll("[data-chart]")) button.addEventListener("click", () => {
    state.variable = button.dataset.chart;
    for (const tab of document.querySelectorAll("[data-chart]")) tab.setAttribute("aria-pressed", String(tab === button));
    renderChart();
});

async function init() {
    try {
        const config = await api("/api/config");
        state.defaults = config.defaults;
        await loadProjects();
        const options = config.models.map(model => {
            const option = element("option", model.label);
            option.value = model.id;
            return option;
        });
        value("model").replaceChildren(...options);
        setInput(config.defaults);
        await initDesign();
        await initPhysics();
        await initCathodes();
        await refreshHistory();
        await refreshComparisons();
        $("run").disabled = false;
        message("準備完了。円筒設計・物理計算・データ取込から作業を選べます。");
    } catch (error) {
        message(error.message || "サーバーに接続できません。", "error");
    }
}

window.addEventListener("resize", renderChart);
window.addEventListener("DOMContentLoaded", init);
