"use strict";

const physical = {config: null, submitting: false, polling: false, timer: null, follow: null, signature: ""};
const jobLabels = {
    queued: "待機",
    running: "計算中",
    cancelling: "取消処理中",
    completed: "完了",
    partial: "一部結果",
    failed: "計算失敗",
    cancelled: "取消",
    timeout: "時間上限",
    interrupted: "中断"
};
const physicsFields = ["name", "model", "parameter_set", "thermal", "initial_soc", "initial_temp_c", "ambient_temp_c", "heat_transfer_w_m2_k", "min_voltage_v", "max_voltage_v", "dt_s", "mesh", "rtol", "atol", "timeout_s"];

function physicsStep(step = {kind: "rest", duration_s: 60}) {
    const row = element("div", undefined, "physics-step"), kind = element("select");
    kind.setAttribute("aria-label", "ステップ種類");
    for (const [key, label] of Object.entries({cc: "CC（定電流）", cv: "CV（定電圧）", rest: "休止"})) {
        const option = element("option", label);
        option.value = key;
        kind.append(option);
    }
    kind.value = step.kind;
    const amount = element("input"), duration = element("input"), cutoff = element("input");
    for (const input of [amount, duration, cutoff]) {
        input.type = "number";
        input.step = "any";
    }
    amount.value = step.kind === "cv" ? step.voltage_v : step.current_a ?? 0;
    duration.value = step.duration_s;
    duration.min = "0.1";
    duration.max = "21600";
    duration.required = true;
    cutoff.value = step.kind === "cv" ? step.stop_current_a : step.stop_voltage_v ?? "";
    const label = (name, input) => {
        const wrapper = element("label", name);
        wrapper.append(input);
        return wrapper;
    };
    const aLabel = label("電流 (A)", amount), cLabel = label("終止電圧 (V・任意)", cutoff);
    const sync = () => {
        kind.disabled = false;
        duration.disabled = false;
        aLabel.firstChild.textContent = kind.value === "cv" ? "保持電圧 (V)" : "電流 (A)";
        cLabel.firstChild.textContent = kind.value === "cv" ? "終止電流の絶対値 (A)" : "終止電圧 (V・任意)";
        amount.disabled = kind.value === "rest";
        cutoff.disabled = kind.value === "rest";
        amount.required = kind.value !== "rest";
        cutoff.required = kind.value === "cv";
    };
    kind.addEventListener("change", () => {
        amount.value = kind.value === "cv" ? 4.2 : kind.value === "cc" ? 1 : 0;
        cutoff.value = kind.value === "cv" ? .25 : "";
        sync();
    });
    const remove = element("button", "削除");
    remove.type = "button";
    remove.addEventListener("click", () => row.remove());
    row.append(label("種類", kind), aLabel, label("時間上限 (s)", duration), cLabel, remove);
    sync();
    row.read = () => {
        const result = {kind: kind.value, duration_s: Number(duration.value)};
        if (kind.value === "cc") {
            result.current_a = Number(amount.value);
            if (cutoff.value !== "") result.stop_voltage_v = Number(cutoff.value);
        }
        if (kind.value === "cv") {
            result.voltage_v = Number(amount.value);
            result.stop_current_a = Number(cutoff.value);
        }
        return result;
    };
    row.sync = sync;
    $("physics-steps").append(row);
}

function readPhysics() {
    const input = {};
    for (const key of physicsFields) input[key] = typeof physical.config.defaults[key] === "number" ? Number($("physics-" + key).value) : $("physics-" + key).value.trim();
    input.design_id = $("physics-design").value || null;
    if ($("physics-protocol-mode").value === "profile") {
        const lines = $("physics-profile").value.trim().split(/\r?\n/);
        if (lines.length > 2000) throw new Error("電流プロファイルは2000行以内です。");
        const points = lines.map(line => {
            const parts = line.split(/[,\t]/).map(s => s.trim());
            if (parts.length !== 2 || parts.some(p => p === "" || !Number.isFinite(Number(p)))) throw new Error("電流プロファイルは各行に 秒, A の2数値を入力してください。ヘッダは不要です。");
            return parts.map(Number);
        });
        input.protocol = [{kind: "profile", points}];
    } else input.protocol = [...$("physics-steps").children].map(row => row.read());
    return input;
}

function physicsCompatibility() {
    const composite = $("physics-parameter_set").value === "Chen2020_composite";
    $("physics-model").querySelector('option[value="SPMe"]').disabled = composite;
    $("physics-thermal").querySelector('option[value="lumped"]').disabled = composite;
    if (composite) {
        $("physics-model").value = "DFN";
        $("physics-thermal").value = "isothermal";
    }
    $("physics-initial_temp_c").disabled = $("physics-thermal").value === "isothermal";
    $("physics-heat_transfer_w_m2_k").disabled = $("physics-thermal").value === "isothermal";
    $("physics-thermal-note").textContent = $("physics-thermal").value === "isothermal"
        ? "等温：初期温度・熱伝達係数は使用しません。周囲温度に固定します。"
        : "集中熱：初期温度と熱伝達係数を使用し、発熱・周囲への放熱でセル温度を計算します。";
    refreshPhysicsDesigns();
    syncModelNavigation();
}

function refreshPhysicsDesigns() {
    const select = $("physics-design"), previous = select.value;
    const empty = element("option", "文献セットの基準形状");
    empty.value = "";
    const composite = $("physics-parameter_set").value === "Chen2020_composite";
    select.replaceChildren(empty, ...designing.records.map(r => {
        const d = r.input,
            compatible = d.positive_material === "NMC811_demo" && d.electrolyte_fill === 1 && (composite ? d.negative_si > 0 && d.negative_graphite > 0 && d.negative_additive === "Si_demo" : d.negative_si === 0 && d.negative_graphite > 0);
        const option = element("option", `${d.name} · ${r.id.slice(0, 8)}${compatible ? "" : "（この物性セットには未対応）"}`);
        option.value = r.id;
        option.disabled = !compatible;
        return option;
    }));
    if ([...select.options].some(o => o.value === previous && !o.disabled)) select.value = previous;
}

function setPhysics(input) {
    for (const key of physicsFields) $("physics-" + key).value = input[key];
    physicsCompatibility();
    if (input.design_id && !designing.records.some(r => r.id === input.design_id)) throw new Error("この設計は現在のプロジェクトにありません。");
    $("physics-design").value = input.design_id || "";
    $("physics-steps").replaceChildren();
    const profile = input.protocol.length === 1 && input.protocol[0].kind === "profile";
    $("physics-protocol-mode").value = profile ? "profile" : "steps";
    if (profile) $("physics-profile").value = input.protocol[0].points.map(pair => pair.join(",")).join("\n");
    else for (const step of input.protocol) physicsStep(step);
    syncPhysicsEditor();
    updateConfigurationSummary();
}

function syncPhysicsEditor() {
    const profile = $("physics-protocol-mode").value === "profile";
    $("physics-profile-editor").hidden = !profile;
    $("physics-step-editor").hidden = profile;
    $("physics-profile").disabled = !profile;
    for (const row of $("physics-steps").children) {
        row.sync();
        if (profile) for (const input of row.querySelectorAll("input,select")) input.disabled = true;
    }
}

function showPhysics(run) {
    $("metric-soc-kind").textContent = "% · 基準容量による電荷帳簿";
    $("result-title").textContent = run.name;
    $("result-meta").textContent = `${run.engine.label} / ${run.input.parameter_set} · ${run.input.thermal === "lumped" ? "集中熱" : "等温"} · ${run.termination === "partial" ? "一部結果" : "プロトコル終了"} · ${(run.summary.duration_s / 60).toFixed(2)} min · ${run.summary.point_count}点`;
    $("metric-capacity").textContent = run.summary.capacity_ah.toFixed(4);
    $("metric-energy").textContent = run.summary.energy_wh.toFixed(4);
    $("metric-temp").textContent = run.summary.max_temperature_c.toFixed(2);
    $("metric-soc").textContent = (run.summary.final_soc * 100).toFixed(2);
    for (const id of ["csv", "json", "restore"]) $(id).disabled = false;
    updateResultState();
    const notes = element("ul");
    for (const note of run.limitations) notes.append(element("li", note));
    $("snapshot").replaceChildren(element("p", `計算ID：${run.id} · ${run.engine.label} ${run.engine.version} · 文献物性／対象セル未検証。SOCは基準容量による電荷帳簿。`), notes,
        element("pre", JSON.stringify({
            input: run.input,
            numerical: run.numerical,
            model_options: run.model_options,
            initial_state: run.initial_state,
            lithium_balance: run.lithium_balance,
            step_results: run.step_results,
            parameter_provenance: run.parameter_provenance,
            design_snapshot: run.design_snapshot
        }, null, 2)));
    if (run.diagnostic_summary) {
        const diagnostics = insightDetail("SPMe/DFNが計算した損失・発熱の内訳", insightTable(
                ["変数", "単位", "初期", "最終", "表示点での最小", "表示点での最大"],
                Object.values(run.diagnostic_summary).map(x => [x.label, x.unit, ...[x.initial, x.final, x.minimum, x.maximum].map(value => insightNumber(value, 6))])),
            element("p", "電圧損失はソルバの符号付き値です。等温でも熱源は計算しますが温度は固定です。最大・最小は出力表示点に限ります。混合熱・外部端面接触発熱は含みません。設計画面の集中見積りとは物性・モデルが異なります。", "field-note"));
        diagnostics.open = true;
        $("snapshot").prepend(diagnostics);
    }
    renderChart();
}

function restorePhysics(run) {
    try {
        setPhysics(run.input);
        selectModelTab($("physics-model").value);
        message("物理計算時の条件を復元しました。再実行は新しいジョブとして保存されます。");
        $("physics-panel").scrollIntoView({block: "start"});
    } catch (error) {
        message(error.message, "error");
    }
}

async function refreshPhysicsJobs() {
    if (physical.polling) return;
    physical.polling = true;
    const project = library.projectId;
    try {
        const jobs = await api(`/api/jobs?project_id=${encodeURIComponent(project)}`);
        if (project !== library.projectId) return;
        const signature = JSON.stringify([project, jobs.map(j => [j.id, j.status])]);
        if (signature !== physical.signature) {
            physical.signature = signature;
            $("physics-jobs").replaceChildren(...(jobs.length ? jobs.slice(0, 50).map(job => {
                const row = element("div", undefined, "history-row"), info = element("div");
                info.append(element("strong", `${job.input.name} · ${jobLabels[job.status] || job.status}`), element("p", `${job.input.model} / ${job.input.parameter_set} · ${job.message}`));
                const actions = element("div", undefined, "design-actions");
                const restore = element("button", "条件を復元");
                restore.type = "button";
                restore.addEventListener("click", () => restorePhysics(job));
                actions.append(restore);
                if (["queued", "running", "cancelling"].includes(job.status)) {
                    const cancel = element("button", "取消");
                    cancel.type = "button";
                    cancel.disabled = job.status === "cancelling";
                    cancel.addEventListener("click", async () => {
                        cancel.disabled = true;
                        try {
                            await api("/api/jobs/cancel", {id: job.id, project_id: project});
                            physical.signature = "";
                            await refreshPhysicsJobs();
                        } catch (error) {
                            message(error.message, "error");
                            cancel.disabled = false;
                        }
                    });
                    actions.append(cancel);
                }
                if (["completed", "partial"].includes(job.status)) {
                    const open = element("button", "結果を表示");
                    open.type = "button";
                    open.addEventListener("click", async () => {
                        const version = ++state.viewVersion;
                        try {
                            const run = await api(`/api/results/${job.result_id}`);
                            if (project === library.projectId && version === state.viewVersion) {
                                showResult(run);
                                $("result-title").scrollIntoView({block: "center"});
                            }
                        } catch (error) {
                            message(error.message, "error");
                        }
                    });
                    actions.append(open);
                }
                row.append(element("span", jobLabels[job.status], "pill"), info, actions);
                return row;
            }) : [element("p", "まだ物理計算ジョブはありません。")]));
            await refreshHistory();
        }
        const follow = physical.follow, job = follow && jobs.find(j => j.id === follow.id);
        if (job && !["queued", "running", "cancelling"].includes(job.status)) {
            physical.follow = null;
            if (project === library.projectId && follow.version === state.viewVersion) {
                message(job.message, ["failed", "timeout", "interrupted"].includes(job.status) ? "error" : "");
                if (["completed", "partial"].includes(job.status)) {
                    const result = await api(`/api/results/${job.result_id}`);
                    if (project === library.projectId && follow.version === state.viewVersion) showResult(result);
                }
            }
        }
    } catch (error) {
        if (project === library.projectId) message(error.message, "error");
    } finally {
        physical.polling = false;
    }
}

async function initPhysics() {
    physical.config = await api("/api/physics/config");
    $("physics-environment").textContent = physical.config.environment.message;
    setPhysics(physical.config.defaults);
    $("physics-run").disabled = !physical.config.environment.available;
    $("physics-model").addEventListener("change", physicsCompatibility);
    $("physics-parameter_set").addEventListener("change", physicsCompatibility);
    $("physics-thermal").addEventListener("change", physicsCompatibility);
    $("physics-protocol-mode").addEventListener("change", syncPhysicsEditor);
    $("physics-add-step").addEventListener("click", () => {
        if ($("physics-steps").children.length < 20) physicsStep(); else message("ステップは20件までです。", "error");
    });
    $("physics-refresh").addEventListener("click", () => {
        physical.signature = "";
        refreshPhysicsJobs();
    });
    $("physics-form").addEventListener("submit", async event => {
        event.preventDefault();
        if (physical.submitting || !$("physics-form").reportValidity()) return;
        physical.submitting = true;
        $("physics-run").disabled = true;
        const project = library.projectId, version = ++state.viewVersion;
        try {
            const job = await api("/api/jobs", {project_id: project, input: readPhysics()});
            if (project === library.projectId && version === state.viewVersion) {
                physical.follow = {id: job.id, version};
                message("物理計算をキューに追加しました。完了時に結果を自動保存します。");
            }
            await refreshPhysicsJobs();
        } catch (error) {
            message(error.message, "error");
        } finally {
            physical.submitting = false;
            $("physics-run").disabled = !physical.config.environment.available;
        }
    });
    await refreshPhysicsJobs();
    physical.timer = setInterval(refreshPhysicsJobs, 1500);
}
