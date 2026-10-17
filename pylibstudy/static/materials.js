"use strict";
let materialBPX = null;
let materialBPXText = null;

function initMaterialSettings(catalog) {
    physical.materials = catalog;
    const select = $("physics-parameter_set");
    select.replaceChildren(...Object.entries(catalog.sets).map(([id, item]) => {
        const option = element("option", `${id} · ${item.label}`);
        option.value = id;
        return option;
    }));
    for (const [key, choices] of Object.entries(catalog.choices)) {
        $("material-" + key).replaceChildren(...choices.map(value => {
            const option = element("option", value);
            option.value = value;
            return option;
        }));
    }
    const names = Object.keys(catalog.inventory.sets);
    for (const id of ["material-view", "material-compare"]) $(id).replaceChildren(...names.map(name => {
        const option = element("option", name);
        option.value = name;
        return option;
    }));
    $("material-view").value = "Chen2020";
    $("material-compare").value = "Prada2013";
    for (const id of ["material-view", "material-compare", "material-filter"]) $(id).addEventListener("input", renderMaterialInventory);
    $("material-bpx-status").textContent = catalog.bpx.reason;
    $("material-bpx-file").addEventListener("change", async () => {
        const file = $("material-bpx-file").files[0];
        if (!file) return;
        try {
            if (file.size > 500000) throw new Error("BPXは500KB以内のJSONです。");
            const raw = await file.text(), data = JSON.parse(raw);
            if (!data.Header || !data.Parameterisation) throw new Error("BPXのHeaderとParameterisationが必要です。");
            materialBPX = data;
            materialBPXText = raw;
            $("physics-parameter_set").value = "BPX";
            applyMaterialSelection();
            $("material-source").value = data.Header.References || data.Header.Description || file.name;
            $("material-bpx-status").textContent = `${file.name} · ${data.Header.Title || "BPX"}。計算後に元データとハッシュを保存します。`;
            invalidatePhysicsPreview();
        } catch (error) {
            $("material-bpx-status").textContent = error.message;
        }
    });
    $("material-bpx-clear").addEventListener("click", () => {
        materialBPX = null;
        materialBPXText = null;
        $("material-bpx-file").value = "";
        $("material-bpx-status").textContent = "BPX入力を解除しました。";
        invalidatePhysicsPreview();
    });
    $("material-add-override").addEventListener("click", () => materialOverrideRow());
    renderMaterialInventory();
}

function renderMaterialInventory() {
    const sets = physical.materials.inventory.sets;
    const name = $("material-view").value, compare = $("material-compare").value;
    const a = sets[name], b = sets[compare];
    const filter = $("material-filter").value.toLowerCase();
    const display = v => !v ? "未収録" : v.kind === "number" ? v.value : v.kind === "bundled_function" ? `同梱関数 ${v.name} / ${v.source_sha256.slice(0, 12)}` : JSON.stringify(v.value ?? v.type);
    const keys = [...new Set([...Object.keys(a.parameters), ...Object.keys(b.parameters)])].sort();
    capabilityTable("material-inventory", ["物性・単位", name, compare, "差分"], keys.filter(k => k.toLowerCase().includes(filter)).map(k => [k, display(a.parameters[k]), display(b.parameters[k]), JSON.stringify(a.parameters[k]) === JSON.stringify(b.parameters[k]) ? "同じ" : "異なる / 片側未収録"]));
    $("material-description").textContent = `${a.description}\n出典ID: ${a.citations.join(", ") || "未収録"}`;
}

function materialOverrideRow(key = "Nominal cell capacity [A.h]", value = "") {
    const row = element("div", undefined, "fields two"), input = element("input"), amount = element("textarea"),
        remove = element("button", "この差分を削除");
    input.setAttribute("aria-label", "物性名（PyBaMM単位付き）");
    input.value = key;
    input.setAttribute("list", "material-parameter-keys");
    amount.rows = 2;
    amount.setAttribute("aria-label", "物性値またはOCP曲線JSON");
    amount.value = value === "" ? "" : JSON.stringify(value);
    remove.type = "button";
    remove.addEventListener("click", () => {
        row.remove();
        invalidatePhysicsPreview();
    });
    row.append(input, amount, remove);
    row.read = () => [input.value.trim(), JSON.parse(amount.value)];
    $("material-overrides").append(row);
}

function setMaterialSettings(input) {
    const s = {...physical.materials.defaults, ...input.material_settings};
    for (const key of Object.keys(physical.materials.choices)) $("material-" + key).value = s[key];
    $("material-source").value = s.source;
    materialBPX = s.bpx;
    materialBPXText = s.bpx_original_text;
    $("material-bpx-status").textContent = materialBPX ? `復元したBPX: ${materialBPX.Header?.Title || "保存入力"}` : physical.materials.bpx.reason;
    $("material-overrides").replaceChildren();
    for (const [key, value] of Object.entries(s.overrides)) materialOverrideRow(key, value);
    syncMaterialKeys(input.parameter_set);
}

function syncMaterialKeys(name) {
    const values = physical.materials.inventory.sets[name]?.parameters || {};
    $("material-parameter-keys").replaceChildren(...Object.keys(values).map(key => {
        const option = element("option");
        option.value = key;
        return option;
    }));
}

function readMaterialSettings() {
    const usesBPX = $("physics-parameter_set").value === "BPX";
    const s = {
        ...physical.materials.defaults,
        overrides: {},
        source: $("material-source").value.trim(),
        bpx: usesBPX ? materialBPX : null,
        bpx_original_text: usesBPX ? materialBPXText : null
    };
    for (const key of Object.keys(physical.materials.choices)) s[key] = $("material-" + key).value;
    for (const row of $("material-overrides").children) {
        const [key, value] = row.read();
        if (Object.hasOwn(s.overrides, key)) throw new Error("同じ物性の差分が重複しています。");
        s.overrides[key] = value;
    }
    return s;
}

function applyMaterialSelection() {
    const name = $("physics-parameter_set").value, info = physical.materials.sets[name];
    $("physics-min_voltage_v").value = materialBPX && name === "BPX" ? materialBPX.Parameterisation.Cell["Lower voltage cut-off [V]"] : info.voltage[0];
    $("physics-max_voltage_v").value = materialBPX && name === "BPX" ? materialBPX.Parameterisation.Cell["Upper voltage cut-off [V]"] : info.voltage[1];
    $("physics-reference_electrode_fraction").value = name === "Xu2019" ? "" : ".5";
    if (["Prada2013", "Xu2019"].includes(name)) {
        $("thermal-isothermal_heat_source").checked = false;
        $("thermal-heat_of_mixing").checked = false;
    }
    $("material-silicon_ocp").value = "current sigmoid";
    syncMaterialKeys(name);
    $("material-selection-note").textContent = "物性セットを変更しました。電圧窓を文献値に更新しました。既存の差分・試験条件は確認してください。LFPとXu半セルは熱源未接続です。";
    physicsCompatibility();
}

function renderMaterialProvenance(run) {
    const p = run.material_provenance;
    $("result-material-source").textContent = p ? `${p.base_set} / ${p.source} / SHA-256 ${p.snapshot_sha256}。${p.note}` : "旧結果には材料差分の詳細記録がありません。";
    capabilityTable("result-material-differences", ["物性", "基準", "採用値"], Object.entries(p?.differences || {}).map(([key, v]) => [key, JSON.stringify(v.before), JSON.stringify(v.after)]));
    const balance = run.lithium_balance;
    if (balance?.check_status) $("result-material-source").append(element("p", `Li在庫集計: ${balance.scope} / ${balance.check_status} / 相対変化 ${balance.relative_change.toExponential(3)} / 許容差 ${balance.relative_tolerance ?? "全セル保存則の対象外"}。${balance.note}`));
}
