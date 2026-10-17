"use strict";

// Carry the selected project forward from the previous application name.
const savedProject = localStorage.getItem("pylibstudy-project") ?? localStorage.getItem("pylib-project");
if (savedProject !== null) localStorage.setItem("pylibstudy-project", savedProject);
const library = {projectId: savedProject || "default", revision: 0, inspectedRevision: -1};
const importLabels = {
    time_s: "時間",
    voltage_v: "電圧",
    current_a: "電流",
    capacity_ah: "容量",
    soc: "SOC",
    temperature_c: "温度",
    step: "ステップ／区間",
    direction: "充放電の区分"
};
const importUnits = {
    time_s: ["s", "min", "h"],
    voltage_v: ["V", "mV"],
    current_a: ["A", "mA"],
    capacity_ah: ["Ah", "mAh"],
    soc: ["1", "%"],
    temperature_c: ["degC", "K"],
    step: ["—"],
    direction: ["—"]
};

function sourceLabel(run) {
    if (run.record_type === "reference_curve") return `公開曲線の参照計算 / ${run.voltage_reference === "Li/Li+" ? "対Li基準" : "セル端子電圧"}`;
    return {
        synthetic: "合成モデル・未校正",
        synthetic_demo: "合成デモ・未校正",
        simulation: "計算結果・実測未検証",
        simulation_import: "計算CSV再取込・元計算未確認",
        public_measured: "公開実測・未検証",
        user_measured: "ユーザー実測・未検証",
        digitized: "図読取・未検証"
    }[run.source_type] || "種別不明";
}

function showDataset(run) {
    $("result-title").textContent = run.name;
    $("result-meta").textContent = `${sourceLabel(run)} · ${run.quality.row_count}点 · ${run.quality.segment_count}区間 · ${run.quality.issue_count}件の品質記録 · 自動整列なし`;
    for (const id of ["metric-capacity", "metric-energy", "metric-temp", "metric-soc"]) $(id).textContent = "—";
    for (const id of ["csv", "json"]) $(id).disabled = false;
    $("restore").disabled = true;
    updateResultState();
    const details = element("pre", JSON.stringify({
        id: run.id,
        source_type: run.source_type,
        validation_status: run.validation_status,
        source: run.source,
        license: run.license,
        specimen_id: run.specimen_id,
        temperature_position: run.temperature_position,
        original: run.original,
        transform: run.transform,
        notes: run.notes,
        quality: run.quality
    }, null, 2));
    $("snapshot").replaceChildren(element("p", "取込条件・出典・原本ハッシュ。実測の検証や計算完了を意味しません。"), details);
    renderChart();
}

async function loadProjects() {
    const projects = await api("/api/projects");
    if (!projects.some(p => p.id === library.projectId)) library.projectId = "default";
    $("project").replaceChildren(...projects.map(project => {
        const option = element("option", project.name);
        option.value = project.id;
        return option;
    }));
    $("project").value = library.projectId;
}

async function switchProject() {
    library.projectId = $("project").value;
    physical.follow = null;
    physical.signature = "";
    $("physics-jobs").replaceChildren(element("p", "このプロジェクトのジョブを読み込んでいます…"));
    localStorage.setItem("pylibstudy-project", library.projectId);
    ++state.viewVersion;
    state.current = null;
    ++resultView.version;
    $("result-explorer").hidden = true;
    for (const id of ['spatial-csv', 'citations-bib', 'result-analysis-json', 'result-analysis-csv']) $(id).hidden = true;
    state.comparisons.clear();
    for (const id of ["save", "csv", "json", "restore", "original"]) $(id).disabled = true;
    $("result-title").textContent = "カーブを選択・計算・取込";
    $("result-state").textContent = "未選択";
    $("result-meta").textContent = "プロジェクトを切り替えました。";
    $("result-origin").textContent = "表示中の結果：なし。保存一覧から表示、または計算・取込してください。";
    for (const id of ["metric-capacity", "metric-energy", "metric-temp", "metric-soc"]) $(id).textContent = "—";
    $("snapshot").replaceChildren();
    $("chart").replaceChildren(element("p", "保存一覧から表示、または新たに計算・取込してください。", "chart-empty"));
    $("legend").replaceChildren();
    $("import-quality").replaceChildren();
    if (designing.config) await designProjectChanged();
    if (physical.config) await refreshPhysicsJobs();
    await refreshHistory();
    await refreshComparisons();
}

$("project").addEventListener("change", () => switchProject().catch(e => message(e.message, "error")));
$("create-project").addEventListener("click", async () => {
    try {
        const project = await api("/api/projects", {name: $("project-name").value});
        library.projectId = project.id;
        await loadProjects();
        await switchProject();
        $("project-name").value = "";
        message("プロジェクトを作成しました。");
    } catch (error) {
        message(error.message, "error");
    }
});

async function importOriginal() {
    const file = $("import-file").files[0];
    const data = {
        encoding: $("import-encoding").value,
        delimiter: $("import-delimiter").value === "tab" ? "\t" : $("import-delimiter").value,
        decimal: $("import-decimal").value,
        header_row: Number($("import-header").value)
    };
    if (file) {
        if (file.size > 2 * 1024 * 1024) throw new Error("原本は2 MiB以内です。");
        const bytes = new Uint8Array(await file.arrayBuffer());
        let binary = "";
        for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
        data.content_base64 = btoa(binary);
        data.filename = file.name;
    } else {
        data.text = $("import-text").value;
        data.filename = "pasted.csv";
        data.encoding = "utf-8-sig";
    }
    return data;
}

function renderTable(target, headers, rows) {
    const table = element("table"), head = element("tr");
    for (const header of headers) head.append(element("th", header));
    const thead = element("thead");
    thead.append(head);
    table.append(thead);
    const body = element("tbody");
    for (const row of rows) {
        const tr = element("tr");
        for (const val of row) tr.append(element("td", val === null ? "欠損" : String(val)));
        body.append(tr);
    }
    table.append(body);
    $(target).replaceChildren(table);
}

function rawChanged() {
    ++library.revision;
    library.inspectedRevision = -1;
    $("preview-import").disabled = true;
    $("column-mapping").replaceChildren();
    $("raw-preview").replaceChildren();
}

for (const id of ["import-file", "import-text", "import-encoding", "import-delimiter", "import-header"]) $(id).addEventListener("input", rawChanged);
$("import-text").addEventListener("input", () => {
    $("import-file").value = "";
});
$("import-file").addEventListener("change", () => {
    if ($("import-file").files[0]) $("import-text").value = "";
});
$("inspect-import").addEventListener("click", async () => {
    const revision = library.revision;
    try {
        message("原本の列を読み込んでいます…", "busy");
        const result = await api("/api/import/inspect", await importOriginal());
        if (revision !== library.revision) return;
        renderTable("raw-preview", result.headers, result.sample);
        const controls = [];
        for (const [key, label] of Object.entries(importLabels)) {
            const row = element("div", undefined, "mapping-row"), title = element("label", label);
            const column = element("select");
            column.id = `map-${key}`;
            column.setAttribute("aria-label", `${label}の列`);
            const empty = element("option", "未指定");
            empty.value = "";
            column.append(empty);
            for (const header of result.headers) {
                const opt = element("option", header);
                opt.value = header;
                column.append(opt);
            }
            const unit = element("select");
            unit.id = `unit-${key}`;
            unit.setAttribute("aria-label", `${label}の単位`);
            for (const u of importUnits[key]) {
                const opt = element("option", u);
                opt.value = u;
                unit.append(opt);
            }
            title.append(column);
            row.append(title, unit);
            controls.push(row);
        }
        $("column-mapping").replaceChildren(...controls);
        library.inspectedRevision = revision;
        $("preview-import").disabled = false;
        message(`${result.row_count}行を読み込みました。列・単位・符号を指定してください。`);
    } catch (error) {
        message(error.message, "error");
    }
});

function displayImport(run) {
    ++state.viewVersion;
    showResult(run);
    const notes = run.quality.issues.map(i => element("li", `${i.row ? i.row + "行目：" : ""}${i.message}`));
    const list = element("ul");
    list.append(...notes);
    $("import-quality").replaceChildren(element("p", `${run.quality.row_count}点／${run.quality.segment_count}区間。${run.duplicate_ids.length ? "同じ原本が保存済みです（別登録として保存可能）。" : "原本ハッシュの重複なし。"}保存前にグラフと来歴を確認してください。`), list);
    const preview = element("div", undefined, "table-scroll");
    preview.id = "normalized-preview";
    $("import-quality").append(preview);
    const fields = ["source_row", "segment_id", "time_s", "voltage_v", "current_a", "capacity_ah", "soc", "temperature_c"];
    renderTable("normalized-preview", fields, run.points.slice(0, 8).map(p => fields.map(f => p[f])));
    message("取込プレビューを表示しました。「結果を保存」で確定できます。");
    $("result-title").scrollIntoView({behavior: "smooth", block: "start"});
}

$("import-form").addEventListener("submit", async event => {
    event.preventDefault();
    if (state.busy || library.inspectedRevision !== library.revision) return;
    const revision = library.revision, projectId = library.projectId;
    try {
        const request = await importOriginal(), mapping = {};
        for (const key of Object.keys(importLabels)) if ($(`map-${key}`).value) mapping[key] = {
            column: $(`map-${key}`).value,
            unit: $(`unit-${key}`).value
        };
        Object.assign(request, {
            mapping,
            project_id: projectId,
            name: $("import-name").value,
            source_type: $("import-type").value,
            shape: $("import-shape").value,
            mode: $("import-mode").value,
            current_sign: $("import-sign").value,
            source: $("import-source").value,
            license: $("import-license").value,
            notes: $("import-notes").value,
            specimen_id: $("import-specimen").value,
            temperature_position: $("import-position").value || "unknown",
            charge_value: $("charge-value").value,
            discharge_value: $("discharge-value").value,
            rest_value: $("rest-value").value
        });
        busy(true, "取込処理");
        message("単位変換と品質検査をしています…", "busy");
        const run = await api("/api/import/preview", request);
        if (revision === library.revision && projectId === library.projectId) displayImport(run);
    } catch (error) {
        message(error.message, "error");
    } finally {
        busy(false);
    }
});

$("demo-import").addEventListener("click", async () => {
    if (state.busy) return;
    const projectId = library.projectId;
    busy(true, "デモ生成");
    try {
        const run = await api("/api/import/demo", {project_id: projectId, seed: Number($("demo-seed").value)});
        if (projectId === library.projectId) displayImport(run);
    } catch (error) {
        message(error.message, "error");
    } finally {
        busy(false);
    }
});
$("original").addEventListener("click", () => {
    if (state.current?.original) {
        const link = element("a");
        link.href = `/api/results/${state.current.id}/original`;
        link.download = "";
        document.body.append(link);
        link.click();
        link.remove();
    }
});

async function refreshComparisons() {
    const project = library.projectId;
    const records = await api(`/api/comparisons?project_id=${encodeURIComponent(project)}`);
    if (project !== library.projectId) return;
    $("comparison-list").replaceChildren(...records.map(record => {
        const row = element("div", undefined, "comparison-row"), open = element("button", "復元");
        open.type = "button";
        open.addEventListener("click", async () => {
            const version = ++state.viewVersion;
            try {
                const runs = await Promise.all(record.dataset_ids.map(id => api(`/api/results/${id}`)));
                if (version !== state.viewVersion) return;
                state.comparisons = new Map(runs.slice(1).map(run => [run.id, run]));
                $("x-axis").value = record.x_axis;
                state.variable = record.variable;
                for (const tab of document.querySelectorAll("[data-chart]")) tab.setAttribute("aria-pressed", String(tab.dataset.chart === state.variable));
                $("comparison-name").value = record.name;
                $("comparison-notes").value = record.notes;
                showResult(runs[0]);
                await refreshHistory();
                message("比較セットと注釈を復元しました。自動整列・正規化なし。");
            } catch (error) {
                message(error.message, "error");
            }
        });
        row.append(element("span", `${record.name} · ${record.dataset_ids.length}件`), open);
        return row;
    }));
}

$("save-comparison").addEventListener("click", async () => {
    const ids = [...new Set([state.current?.id, ...[...state.comparisons].filter(([, run]) => run).map(([id]) => id)].filter(Boolean))];
    try {
        await api("/api/comparisons", {
            project_id: library.projectId, dataset_ids: ids, name: $("comparison-name").value,
            notes: $("comparison-notes").value, x_axis: $("x-axis").value, variable: state.variable
        });
        await refreshComparisons();
        message("比較セットと注釈を保存しました。");
    } catch (error) {
        message(error.message, "error");
    }
});
