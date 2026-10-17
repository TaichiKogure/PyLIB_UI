"use strict";

const physical = {
    config: null,
    submitting: false,
    polling: false,
    timer: null,
    follow: null,
    signature: "",
    previewVersion: 0
};
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
const progressLabels = {
    experiment_start: "計算開始",
    cycle_start: "サイクル開始",
    step_start: "ステップ計算中",
    step_end: "ステップ到達",
    cycle_end: "サイクル終了",
    postprocess: "結果整理",
    solver_error: "ソルバ失敗",
    infeasible_time: "時間上限到達",
    infeasible_event: "モデル終了条件到達"
};
const physicsFields = ["name", "model", "parameter_set", "thermal", "solver", "cycles", "initial_soc", "initial_temp_c", "ambient_temp_c", "heat_transfer_w_m2_k", "min_voltage_v", "max_voltage_v", "dt_s", "mesh", "rtol", "atol", "timeout_s"];

function physicsStep(step = {kind: "rest", duration_s: 60}, parent = $("physics-steps"), depth = 0) {
    const row = element("div", undefined, "physics-step-card");
    const label = (name, input) => {
        const wrapper = element("label", name);
        wrapper.append(input);
        return wrapper;
    };
    const numeric = (value = "") => {
        const input = element("input");
        input.type = "number";
        input.step = "any";
        input.value = value;
        return input;
    };
    const remove = element("button", "削除");
    remove.type = "button";
    remove.addEventListener("click", () => {
        row.remove();
        invalidatePhysicsPreview();
    });
    if (step.kind === "repeat") {
        const count = numeric(step.count), children = element("div", undefined, "physics-repeat-children");
        count.min = "1";
        count.max = "20";
        count.step = "1";
        count.required = true;
        row.append(element("strong", "繰返しブロック"), label("繰返し回数", count), remove, children);
        for (const child of step.steps) physicsStep(child, children, depth + 1);
        const add = element("button", "＋ ステップ"), repeat = element("button", "＋ 内側の繰返し");
        for (const button of [add, repeat]) button.type = "button";
        add.addEventListener("click", () => {
            if (children.children.length < 20) physicsStep(undefined, children, depth + 1);
            invalidatePhysicsPreview();
        });
        repeat.disabled = depth >= 2;
        repeat.addEventListener("click", () => {
            if (children.children.length < 20) physicsStep({
                kind: "repeat",
                count: 2,
                steps: [{kind: "rest", duration_s: 10}]
            }, children, depth + 1);
            invalidatePhysicsPreview();
        });
        row.append(add, repeat);
        row.read = () => ({
            kind: "repeat",
            count: Number(count.value),
            steps: [...children.children].map(r => r.read())
        });
        row.sync = () => {
            for (const child of children.children) child.sync();
        };
        parent.append(row);
        return row;
    }
    const fields = element("div", undefined, "physics-step"), kind = element("select");
    kind.setAttribute("aria-label", "ステップ種類");
    for (const [key, text] of Object.entries({
        cc: "CC (A)",
        c_rate: "CC (C-rate)",
        cv: "CV (V)",
        cp: "CP (W)",
        cr: "CR (Ω)",
        rest: "休止",
        profile: "電流波形"
    })) {
        const option = element("option", text);
        option.value = key;
        kind.append(option);
    }
    kind.value = step.kind;
    const valueKey = {cc: "current_a", c_rate: "c_rate", cv: "voltage_v", cp: "power_w", cr: "resistance_ohm"};
    const amount = numeric(step[valueKey[step.kind]] ?? 0), duration = numeric(step.duration_s ?? 60);
    duration.min = ".1";
    duration.max = "21600";
    duration.required = true;
    const cutoff = numeric(step.kind === "cv" ? step.stop_current_a ?? step.stop_c_rate : step.stop_voltage_v ?? "");
    const cutoffUnit = element("select");
    for (const [key, text] of [["stop_current_a", "A"], ["stop_c_rate", "C-rate"]]) {
        const o = element("option", text);
        o.value = key;
        cutoffUnit.append(o);
    }
    cutoffUnit.value = step.stop_c_rate !== undefined ? "stop_c_rate" : "stop_current_a";
    const aLabel = label({
        cc: "電流 (A)",
        c_rate: "C-rate",
        cv: "電圧 (V)",
        cp: "電力 (W)",
        cr: "抵抗 (Ω)",
        rest: "休止",
        profile: "波形"
    }[step.kind], amount), cutLabel = label(step.kind === "cv" ? "終止電流の絶対値" : "終止電圧 (V・任意)", cutoff);
    if (step.kind === "cv") cutLabel.append(cutoffUnit);
    fields.append(label("種類", kind), aLabel, label("時間上限 (s)", duration), cutLabel, remove);
    const advanced = element("details"), advancedFields = element("div", undefined, "fields two");
    advanced.append(element("summary", "ステップの温度・出力周期・タグ・制御"), advancedFields);
    const period = numeric(step.period_s), temperature = numeric(step.temperature_c), tags = element("input"),
        skip = element("input");
    period.value = step.period_s ?? "";
    temperature.value = step.temperature_c ?? "";
    tags.value = (step.tags || []).join(", ");
    skip.type = "checkbox";
    skip.checked = step.skip_ok || false;
    advancedFields.append(label("出力周期 (s・空欄は全体設定)", period), label("周囲温度 (°C・空欄は全体設定)", temperature), label("タグ（カンマ区切り）", tags), label("初期条件で終止済みならスキップを許可", skip));
    const control = element("select"), tau = numeric(step.control_tau_s ?? 1);
    for (const [key, text] of [["implicit", "代数制御（目標を満たす）"], ["explicit", "明示制御（電圧状態変数を使用）"], ["differential", "微分制御（時定数で電流追従）"]]) {
        const o = element("option", text);
        o.value = key;
        control.append(o);
    }
    control.value = step.control || "implicit";
    const cpcr = ["cp", "cr"].includes(step.kind);
    if (cpcr) advancedFields.append(label("CP/CR制御", control), label("制御時定数 (s・微分のみ)", tau));
    control.addEventListener("change", () => {
        tau.disabled = control.value !== "differential";
    });
    const profile = element("textarea");
    profile.rows = 5;
    if (step.kind === "profile") {
        profile.value = (step.points || [[0, 1], [30, 1]]).map(p => p.join(",")).join("\n");
        row.append(label("時間 (s), 電流 (A)・0秒から", profile));
    }
    row.prepend(fields);
    row.append(advanced);
    row.sync = () => {
        kind.disabled = false;
        amount.disabled = ["rest", "profile"].includes(step.kind);
        amount.required = !amount.disabled;
        duration.disabled = step.kind === "profile";
        cutoff.disabled = ["rest", "profile"].includes(step.kind);
        cutoff.required = step.kind === "cv";
        tau.disabled = !cpcr || control.value !== "differential";
    };
    row.sync();
    kind.addEventListener("change", () => {
        const next = {kind: kind.value, duration_s: Number(duration.value)};
        if (period.value !== "") next.period_s = Number(period.value);
        if (temperature.value !== "") next.temperature_c = Number(temperature.value);
        if (tags.value.trim()) next.tags = tags.value.split(",").map(t => t.trim()).filter(Boolean);
        if (skip.checked) next.skip_ok = true;
        const defaults = {cc: 1, c_rate: .2, cv: 3.8, cp: 3.7, cr: 4};
        if (valueKey[next.kind]) next[valueKey[next.kind]] = defaults[next.kind];
        if (next.kind === "cv") next.stop_current_a = .1;
        if (next.kind === "profile") {
            delete next.duration_s;
            next.points = [[0, 1], [30, 1]];
        }
        const replacement = physicsStep(next, parent, depth);
        row.replaceWith(replacement);
        invalidatePhysicsPreview();
    });
    row.read = () => {
        const result = {kind: step.kind};
        if (step.kind === "profile") result.points = readPhysicsPoints(profile.value);
        else result.duration_s = Number(duration.value);
        if (valueKey[step.kind]) result[valueKey[step.kind]] = Number(amount.value);
        if (step.kind === "cv") result[cutoffUnit.value] = Number(cutoff.value);
        else if (!["rest", "profile"].includes(step.kind) && cutoff.value !== "") result.stop_voltage_v = Number(cutoff.value);
        if (period.value !== "") result.period_s = Number(period.value);
        if (temperature.value !== "") result.temperature_c = Number(temperature.value);
        if (tags.value.trim()) result.tags = tags.value.split(",").map(t => t.trim()).filter(Boolean);
        if (skip.checked) result.skip_ok = true;
        if (cpcr) {
            result.control = control.value;
            if (control.value === "differential") result.control_tau_s = Number(tau.value);
        }
        return result;
    };
    parent.append(row);
    return row;
}

function readPhysicsPoints(text) {
    const lines = text.trim().split(/\r?\n/);
    if (lines.length > 2000) throw new Error("電流プロファイルは2000行以内です。");
    return lines.map(line => {
        const parts = line.split(/[,\t]/).map(s => s.trim());
        if (parts.length !== 2 || parts.some(p => p === "" || !Number.isFinite(Number(p)))) throw new Error("電流波形は各行に 秒, A の2数値を指定してください。");
        return parts.map(Number);
    });
}

function invalidatePhysicsPreview() {
    physical.previewVersion = (physical.previewVersion || 0) + 1;
    $("physics-preview-status").textContent = "条件が変わりました。プレビューを更新してください。";
    $("physics-preview").replaceChildren();
}

async function previewPhysics() {
    const project = library.projectId, version = ++physical.previewVersion;
    try {
        const preview = await api("/api/physics/preview", {input: readPhysics(), project_id: project});
        if (project !== library.projectId || version !== physical.previewVersion) return;
        $("physics-preview-status").textContent = `${preview.cycles}サイクル / ${preview.total_steps}ステップ / 最大${preview.duration_upper_s} s / 出力最大${preview.output_points_upper}点。C-rate基準 ${preview.c_rate_reference_ah.toFixed(4)} Ah（${preview.capacity_source}）。${preview.note}`;
        capabilityTable("physics-preview", ["cycle/step", "制御", "電流 A / C-rate", "電力 W / 抵抗 Ω", "電圧 V / CV終止 A", "上限時間 s", "周期 s / 温度 °C", "タグ・skip"],
            preview.steps.map(s => [`${s.cycle}/${s.step_number}`, `${s.kind} ${s.control || ""}`, s.current_a === null ? "解で決定" : `${s.current_a.toFixed(4)} / ${s.c_rate.toFixed(4)}`, `${s.power_w ?? "—"} / ${s.resistance_ohm ?? "—"}`, `${s.voltage_v ?? s.stop_voltage_v ?? "—"} / ${s.stop_current_a ?? "—"}`, s.duration_s, `${s.period_s} / ${s.temperature_c}`, `${s.tags.join(", ")} / ${s.skip_ok ? "許可" : "不可"}`]));
    } catch (error) {
        if (version === physical.previewVersion) $("physics-preview-status").textContent = error.message;
    }
}

function readPhysics() {
    const input = {};
    input.config_schema_version = physical.config.defaults.config_schema_version;
    input.model_options = {};
    for (const key of physicsFields) input[key] = typeof physical.config.defaults[key] === "number" ? Number($("physics-" + key).value) : $("physics-" + key).value.trim();
    input.design_id = $("physics-design").value || null;
    input.start_time = $("physics-start_time").value.trim() || null;
    if ($("physics-protocol-mode").value === "profile") input.protocol = [{
        kind: "profile",
        points: readPhysicsPoints($("physics-profile").value)
    }];
    else input.protocol = [...$("physics-steps").children].map(row => row.read());
    readResultOutput(input);
    return input;
}

function physicsCompatibility() {
    if (!physical.config) return;
    $("physics-initial_soc").disabled = $("physics-initial_ocv_v").value !== "";
    const material = physical.config.capabilities.combinations.filter(c => c.parameter_set === $("physics-parameter_set").value);
    for (const option of $("physics-model").options) option.disabled = !material.some(c => c.model === option.value);
    if (!material.some(c => c.model === $("physics-model").value) && material.length) $("physics-model").value = material[0].model;
    const models = material.filter(c => c.model === $("physics-model").value);
    for (const option of $("physics-thermal").options) option.disabled = !models.some(c => c.thermal === option.value);
    if (!models.some(c => c.thermal === $("physics-thermal").value) && models.length) $("physics-thermal").value = models[0].thermal;
    const selected = models.find(c => c.thermal === $("physics-thermal").value && c.solver === $("physics-solver").value);
    $("physics-compatibility").textContent = `${selected?.reason || "この組合せは未接続です。"}${material.length === 1 ? " この物性はDFN・等温のみ選択できます。複合負極の集中熱用物性は未接続です。" : ""}`;
    $("physics-run").disabled = physical.submitting || !physical.config.environment.available || !selected?.compatible;
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
    invalidatePhysicsPreview();
}

function setPhysics(input) {
    input = {...physical.config.defaults, ...input};
    if (input.config_schema_version !== physical.config.defaults.config_schema_version) throw new Error("未対応の計算設定スキーマ版です。");
    if (input.design_id && !designing.records.some(r => r.id === input.design_id)) throw new Error("この設計は現在のプロジェクトにありません。");
    setResultOutput(input);
    for (const key of physicsFields) $("physics-" + key).value = input[key];
    physicsCompatibility();
    $("physics-design").value = input.design_id || "";
    $("physics-start_time").value = input.start_time || "";
    $("physics-steps").replaceChildren();
    const profile = input.protocol.length === 1 && input.protocol[0].kind === "profile" && Object.keys(input.protocol[0]).every(key => ["kind", "points"].includes(key));
    $("physics-protocol-mode").value = profile ? "profile" : "steps";
    if (profile) $("physics-profile").value = input.protocol[0].points.map(pair => pair.join(",")).join("\n");
    else for (const step of input.protocol) physicsStep(step);
    syncPhysicsEditor();
    invalidatePhysicsPreview();
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
            protocol_preview: run.protocol_preview,
            experiment_metadata: run.experiment_metadata,
            progress_events: run.progress_events,
            numerical: run.numerical,
            model_options: run.model_options,
            initial_state: run.initial_state,
            lithium_balance: run.lithium_balance,
            step_results: run.step_results,
            parameter_provenance: run.parameter_provenance,
            design_snapshot: run.design_snapshot
        }, null, 2)));
    if (run.diagnostic_summary) {
        const diagnostics = insightDetail("SPM/SPMe/DFNが計算した損失・発熱の内訳", insightTable(
                ["変数", "単位", "初期", "最終", "表示点での最小", "表示点での最大"],
                Object.values(run.diagnostic_summary).map(x => [x.label, x.unit, ...[x.initial, x.final, x.minimum, x.maximum].map(value => insightNumber(value, 6))])),
            element("p", "電圧損失はソルバの符号付き値です。等温でも熱源は計算しますが温度は固定です。最大・最小は出力表示点に限ります。混合熱・外部端面接触発熱は含みません。設計画面の集中見積りとは物性・モデルが異なります。", "field-note"));
        diagnostics.open = true;
        $("snapshot").prepend(diagnostics);
    }
    renderChart();
}

async function restorePhysics(run) {
    try {
        const project = library.projectId;
        const validated = await api("/api/physics/validate", run.input);
        if (project !== library.projectId) return;
        setPhysics(validated.input);
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
        const signature = JSON.stringify([project, jobs.map(j => [j.id, j.status, j.progress?.sequence])]);
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
                if (job.progress) {
                    const p = job.progress;
                    info.append(element("p", `サイクル ${p.cycle}/${p.cycles} · ステップ ${p.step}/${p.steps_per_cycle} · 到達 ${p.completed_steps}/${p.total_steps} · ${progressLabels[p.event] || "状態確認"} · 試験時刻 ${p.simulated_time_s.toFixed(2)} s`));
                    const meter = element("progress");
                    meter.max = p.total_steps;
                    meter.value = p.completed_steps;
                    meter.setAttribute("aria-label", "到達ステップ数（実時間の進捗率ではありません）");
                    info.append(meter);
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
    initResultSettings(physical.config.result_catalog);
    $("physics-environment").textContent = physical.config.environment.message;
    setPhysics(physical.config.defaults);
    initCapabilities();
    for (const template of physical.config.templates) {
        const o = element("option", template.label);
        o.value = template.id;
        $("physics-template").append(o);
    }
    $("physics-template-apply").addEventListener("click", () => {
        const template = physical.config.templates.find(t => t.id === $("physics-template").value);
        if (!template) return;
        $("physics-steps").replaceChildren();
        for (const step of template.protocol) physicsStep(step);
        $("physics-protocol-mode").value = "steps";
        syncPhysicsEditor();
        invalidatePhysicsPreview();
    });
    $("physics-add-repeat").addEventListener("click", () => {
        if ($("physics-steps").children.length < 20) physicsStep({
            kind: "repeat",
            count: 2,
            steps: [{kind: "rest", duration_s: 10}]
        });
        invalidatePhysicsPreview();
    });
    $("physics-preview-button").addEventListener("click", previewPhysics);
    $("physics-form").addEventListener("input", invalidatePhysicsPreview);
    $("physics-form").addEventListener("change", invalidatePhysicsPreview);
    $("physics-model").addEventListener("change", physicsCompatibility);
    $("physics-parameter_set").addEventListener("change", physicsCompatibility);
    $("physics-thermal").addEventListener("change", physicsCompatibility);
    $("physics-initial_ocv_v").addEventListener("input", physicsCompatibility);
    $("physics-solver").addEventListener("change", physicsCompatibility);
    $("physics-protocol-mode").addEventListener("change", syncPhysicsEditor);
    $("physics-add-step").addEventListener("click", () => {
        if ($("physics-steps").children.length < 20) {
            physicsStep();
            invalidatePhysicsPreview();
        } else message("ステップは20件までです。", "error");
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
            physicsCompatibility();
        }
    });
    await refreshPhysicsJobs();
    physical.timer = setInterval(refreshPhysicsJobs, 1500);
}
