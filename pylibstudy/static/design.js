"use strict";

const designing = {config: null, result: null, saved: null, records: [], revision: 0, timer: null, binding: null};
const designGroups = [
    ["寸法・巻回構造", [
        ["name", "設計名"], ["cell_format", "セル形式", {"21700": "21700", "18650": "18650"}],
        ["diameter_mm", "缶外径 (mm)"], ["height_mm", "缶全高 (mm)"], ["wall_mm", "缶壁 (mm)"],
        ["lid_total_mm", "上下蓋の合計実体厚 (mm)"],
        ["axial_reserve_mm", "上下蓋・端板等の合計予約高さ (mm)"], ["radial_gap_mm", "径方向隙間 (mm)"],
        ["core_diameter_mm", "中心空間の直径 (mm)"], ["winding_width_mm", "巻回・箔・セパレータ幅 (mm)"],
        ["positive_width_mm", "正極塗工幅 (mm)"], ["negative_width_mm", "負極塗工幅 (mm)"],
        ["length_mode", "巻回長の決め方", {
            fit: "有効径まで充填（長さを算出）",
            manual: "巻回長を指定"
        }], ["length_mm", "指定巻回長 (mm)"],
        ["positive_thickness_um", "正極片面塗工厚 (µm)"], ["negative_thickness_um", "負極片面塗工厚 (µm)"],
        ["positive_foil_um", "Al箔 (µm)"], ["negative_foil_um", "Cu箔 (µm)"], ["separator_um", "セパレータ1枚 (µm)"]]],
    ["材料と乾燥固体配合（合計1）", [
        ["positive_material", "正極材料", {
            NMC811_demo: "NCX / NMC811",
            NCA_demo: "NCX / NCA 80:15:5",
            LFP_demo: "LFP"
        }],
        ["negative_additive", "負極の第2活物質", {Si_demo: "Si", SiOx_demo: "SiOx（x未同定）"}],
        ["fraction_basis", "配合入力の基準（切替時は数値を再解釈）", {
            mass: "乾燥固体の質量分率",
            volume: "乾燥固体の体積分率"
        }],
        ["positive_active", "正極活物質"], ["positive_binder", "正極結着剤"], ["positive_carbon", "正極導電助剤"],
        ["negative_graphite", "負極黒鉛"], ["negative_si", "負極Si / SiOx（0で黒鉛単相）"],
        ["negative_binder", "負極結着剤"], ["negative_carbon", "負極導電助剤"],
        ["positive_porosity", "正極空隙率 (0–1)"], ["negative_porosity", "負極空隙率 (0–1)"], ["separator_porosity", "セパレータ空隙率 (0–1)"]]],
    ["活物質の比容量・利用率・形成損失", [
        ["positive_capacity_mah_g", "正極可逆比容量 (mAh/g・0で材料既定値)"],
        ["graphite_capacity_mah_g", "黒鉛可逆比容量 (mAh/g・0で350)"],
        ["additive_capacity_mah_g", "Si / SiOx可逆比容量 (mAh/g・0で材料既定値)"],
        ["positive_utilization", "正極の指定利用率 (0超〜1)"],
        ["negative_utilization", "負極の指定利用率 (0超〜1)"],
        ["negative_first_cycle_efficiency", "負極の初回効率 ICE (脱離/挿入・0.01〜1)"]]],
    ["初期Li帳簿・Cレート基準・質量", [
        ["lithium_fraction_positive", "正極初期Li充填率（仮定 0–1）"], ["lithium_fraction_negative", "負極初期Li充填率（仮定 0–1）"],
        ["c_rate_capacity_mode", "Cレート基準容量", {design: "設計容量を使用", rated: "指定した定格容量を使用"}],
        ["rated_capacity_ah", "指定定格容量 (Ah)"], ["electrolyte_fill", "孔隙の注液充填率 (0–1)"],
        ["electrolyte_density_g_cm3", "電解液密度 (g/cm³)"], ["hardware_mass_g", "その他端板・端子等の質量 (g)"]]],
    ["上下端面集電の接続", [
        ["positive_terminal", "正極Al箔 → 端板 → 正端子", {top: "上端面", bottom: "下端面"}],
        ["negative_terminal", "負極Cu箔 → 端板 → 負端子", {bottom: "下端面", top: "上端面"}],
        ["positive_contact_fraction", "正極端面接触面積率 (0–1)"], ["negative_contact_fraction", "負極端面接触面積率 (0–1)"],
        ["positive_contact_asr_ohm_mm2", "正極の箔端面接触ASR (Ω·mm²)"],
        ["negative_contact_asr_ohm_mm2", "負極の箔端面接触ASR (Ω·mm²)"],
        ["terminal_resistance_mohm", "端板・端子等の直列抵抗 (mΩ)"],
        ["film_asr_ohm_cm2", "正負合計の皮膜ASR (Ω·cm²・幾何面積基準)"]]],
    ["電解液輸送・電子伝導・反応・拡散の仮定", [
        ["electrolyte_conductivity_s_m", "バルク電解液導電率 κ (S/m)"],
        ["positive_bruggeman", "正極Bruggeman指数 b (1〜5)"],
        ["negative_bruggeman", "負極Bruggeman指数 b (1〜5)"],
        ["separator_bruggeman", "セパレータBruggeman指数 b (1〜5)"],
        ["positive_conductivity_s_m", "正極の有効電子伝導率 σ (S/m)"],
        ["negative_conductivity_s_m", "負極の有効電子伝導率 σ (S/m)"],
        ["positive_particle_radius_um", "正極の等価粒子半径 (µm)"],
        ["negative_particle_radius_um", "負極の等価粒子半径 (µm)"],
        ["positive_exchange_current_a_m2", "正極の交換電流密度 i₀ (A/m²・活物質表面基準)"],
        ["negative_exchange_current_a_m2", "負極の交換電流密度 i₀ (A/m²・活物質表面基準)"],
        ["positive_diffusivity_m2_s", "正極の固相拡散係数 D (m²/s)"],
        ["negative_diffusivity_m2_s", "負極の固相拡散係数 D (m²/s)"]]],
    ["性能見積りの評価点・平均熱収支", [
        ["analysis_current_mode", "設計比較時の電流条件", {fixed_a: "同じ電流Aで比較", c_rate: "同じCレートで比較"}],
        ["analysis_current_a", "評価放電電流 (A・0で微分抵抗)"],
        ["analysis_c_rate", "評価Cレート (1/h)"],
        ["analysis_ocv_v", "評価点のOCV (V・LFP等は手動調整)"],
        ["analysis_cutoff_v", "評価下限電圧 (V)"],
        ["analysis_temperature_c", "評価温度＝初期・周囲温度 (°C)"],
        ["analysis_pulse_s", "一定損失を仮定するパルス時間 (s)"],
        ["analysis_heat_capacity_j_kg_k", "セル質量基準の比熱 (J/kg/K)"],
        ["analysis_heat_transfer_w_m2_k", "外表面の熱伝達係数 h (W/m²/K・0で断熱)"]]]
];

function designInput() {
    const f = $("design-form"), input = {};
    for (const [key, val] of Object.entries(designing.config.templates["21700"])) {
        const control = f.elements.namedItem(key);
        input[key] = typeof val === "number" ? Number(control.value) : control.value.trim();
    }
    return input;
}

function fillDesign(input) {
    for (const [key, val] of Object.entries({...designing.config.templates["21700"], ...input})) {
        const control = $("design-form").elements.namedItem(key);
        if (control) control.value = val;
    }
    designChanged();
    updateConfigurationSummary();
}

function designChanged() {
    ++designing.revision;
    designing.result = null;
    designing.saved = null;
    for (const id of ["design-save", "design-apply", "design-export"]) $(id).disabled = true;
    $("design-saved").value = "";
    $("design-status").textContent = "変更あり · 収支を確認しています…";
    // Clear obsolete numbers immediately while validation is pending or fails.
    for (const id of ["design-diagram", "design-balance", "design-detail", "design-insights"]) $(id).replaceChildren();
    const f = $("design-form").elements;
    f.namedItem("length_mm").disabled = f.namedItem("length_mode").value === "fit";
    f.namedItem("rated_capacity_ah").disabled = f.namedItem("c_rate_capacity_mode").value === "design";
    f.namedItem("analysis_current_a").disabled = f.namedItem("analysis_current_mode").value !== "fixed_a";
    f.namedItem("analysis_c_rate").disabled = f.namedItem("analysis_current_mode").value !== "c_rate";
    clearTimeout(designing.timer);
    const revision = designing.revision;
    designing.timer = setTimeout(() => evaluateDesign(revision), 250);
}

async function evaluateDesign(revision) {
    const f = $("design-form");
    if (!f.checkValidity()) {
        $("design-status").textContent = "必須項目に有限の値を入力してください。";
        return;
    }
    try {
        const result = await api("/api/design/evaluate", designInput());
        if (revision !== designing.revision) return;
        designing.result = result;
        renderDesign(result);
        $("design-status").textContent = "収支確認済み · 未保存の設計見積り";
        $("design-save").disabled = false;
        $("design-export").disabled = false;
    } catch (error) {
        if (revision === designing.revision) $("design-status").textContent = `入力を修正：${error.message}`;
    }
}

function renderDesign(r) {
    const g = r.geometry, c = r.input;
    const svg = svgElement("svg", {
        viewBox: "0 0 600 340",
        role: "img",
        "aria-label": "設計寸法に比例した巻回断面と軸方向外形"
    });
    const scale = Math.min(8, 230 / c.height_mm, 165 / c.diameter_mm);
    const radialScale = 105 / (c.diameter_mm / 2);
    svg.append(svgElement("circle", {cx: 135, cy: 142, r: c.diameter_mm / 2 * radialScale, fill: "#b7c6c1"}));
    svg.append(svgElement("circle", {
        cx: 135,
        cy: 142,
        r: (c.diameter_mm / 2 - c.wall_mm) * radialScale,
        fill: "#f4f6f3"
    }));
    // Repeated layers share the same radial scale. This is an annular approximation.
    const layers = [[c.positive_thickness_um, "#b683b8"], [c.positive_foil_um, "#b9c7d6"],
        [c.positive_thickness_um, "#b683b8"], [c.separator_um, "#eee7bc"],
        [c.negative_thickness_um, "#596b74"], [c.negative_foil_um, "#c8965e"],
        [c.negative_thickness_um, "#596b74"], [c.separator_um, "#eee7bc"]];
    let radius = g.inner_radius_mm;
    for (let ring = 0; ring < Math.min(1000, Math.ceil(g.turns)); ring++) {
        for (const [um, color] of layers) {
            const end = Math.min(g.outer_radius_mm, radius + um / 1000);
            if (end > radius) svg.append(svgElement("circle", {
                cx: 135,
                cy: 142,
                r: (radius + end) / 2 * radialScale,
                fill: "none",
                stroke: color,
                "stroke-width": (end - radius) * radialScale
            }));
            radius = end;
        }
    }
    svg.append(svgElement("circle", {cx: 135, cy: 142, r: g.inner_radius_mm * radialScale, fill: "white"}));
    svg.append(svgElement("circle", {
        cx: 135,
        cy: 142,
        r: g.outer_radius_mm * radialScale,
        fill: "none",
        stroke: "#233e35",
        "stroke-width": 0.5
    }));
    const x = 360, y = 30, w = c.diameter_mm * scale, h = c.height_mm * scale;
    svg.append(svgElement("rect", {x, y, width: w, height: h, fill: "#b7c6c1"}));
    svg.append(svgElement("rect", {
        x: x + c.wall_mm * scale, y: y + c.lid_total_mm / 2 * scale,
        width: (c.diameter_mm - 2 * c.wall_mm) * scale, height: (c.height_mm - c.lid_total_mm) * scale, fill: "#f4f6f3"
    }));
    svg.append(svgElement("rect", {
        x: x + (c.diameter_mm / 2 - g.outer_radius_mm) * scale,
        y: y + (c.height_mm - c.winding_width_mm) / 2 * scale, width: g.outer_radius_mm * 2 * scale,
        height: c.winding_width_mm * scale, fill: "#879dac"
    }));
    svg.append(svgElement("rect", {
        x: x + (c.diameter_mm - c.core_diameter_mm) / 2 * scale,
        y: y + (c.height_mm - c.winding_width_mm) / 2 * scale, width: c.core_diameter_mm * scale,
        height: c.winding_width_mm * scale, fill: "white"
    }));
    const text = (tx, ty, str) => svg.append(svgElement("text", {x: tx, y: ty, fill: "#233e35", "font-size": 12}, str));
    text(20, 20, `断面 Ø${c.diameter_mm} mm / 中心 Ø${c.core_diameter_mm} mm`);
    text(20, 270, `巻回外径 ${(2 * g.outer_radius_mm).toFixed(3)} mm / 約${g.turns.toFixed(2)}周`);
    text(340, 285, `全高 ${c.height_mm} / 巻回幅 ${c.winding_width_mm} mm`);
    text(20, 300, "紫:正極塗膜 / 灰:Al / 淡黄:セパレータ / 濃灰:負極 / 茶:Cu");
    text(20, 324, `環状近似断面。断面と側面は別縮尺。${g.turns > 1000 ? "描画は内側1000周まで。" : ""}`);
    $("design-diagram").replaceChildren(svg);
    const cap = r.capacity;
    const rows = [
        ["巻回長 / 径からの最大長", `${g.length_mm.toFixed(2)} / ${g.max_length_mm.toFixed(2)} mm`],
        ["1周期厚 / 等価並列面数", `${(g.pitch_mm * 1000).toFixed(2)} µm / 2（両面）`],
        ["正極 / 負極塗工面積（両面）", `${r.positive.area_cm2.toFixed(2)} / ${r.negative.area_cm2.toFixed(2)} cm²`],
        ["正極 / 負極片面面密度（固体全量）", `${r.positive.mass_loading_mg_cm2.toFixed(3)} / ${r.negative.mass_loading_mg_cm2.toFixed(3)} mg/cm²`],
        ["正極 / 負極全体容量", `${cap.positive_ah.toFixed(4)} / ${cap.negative_total_ah.toFixed(4)} Ah`],
        ["正極 / 負極片面面積容量", `${r.positive.areal_capacity_mah_cm2.toFixed(3)} / ${r.negative.areal_capacity_mah_cm2.toFixed(3)} mAh/cm²`],
        ["重なり領域 N/P / 設計容量", `${cap.np_ratio.toFixed(4)} / ${cap.design_ah.toFixed(4)} Ah`],
        ["Cレート基準容量", `${cap.c_rate_reference_ah.toFixed(6)} Ah（${c.c_rate_capacity_mode === "design" ? "設計" : "指定定格"}）`],
        ["巻回体積 = 層体積 + 未塗工部空間", `${g.envelope_cm3.toFixed(4)} = ${g.layer_volume_cm3.toFixed(4)} + ${g.uncoated_void_cm3.toFixed(4)} cm³`],
        ["孔隙体積 / 初期Li等価量", `${g.pore_volume_cm3.toFixed(4)} cm³ / ${r.lithium_inventory.total_mol_equivalent.toFixed(5)} mol`],
        ["負極活物質相数 / 総質量見積り", `${r.negative_phase_count} / ${r.total_mass_g.toFixed(3)} g`]
    ];
    const table = element("table"), body = element("tbody");
    for (const [label, amount] of rows) {
        const tr = element("tr");
        tr.append(element("th", label), element("td", amount));
        body.append(tr);
    }
    table.append(body);
    const connection = element("p", `${c.positive_terminal === "top" ? "上" : "下"}端面：正極Al箔 → 接触 ${(c.positive_contact_fraction * 100).toFixed(1)}% → 正端板 → 正端子 ／ ${c.negative_terminal === "top" ? "上" : "下"}端面：負極Cu箔 → 接触 ${(c.negative_contact_fraction * 100).toFixed(1)}% → 負端板 → 負端子`);
    const notes = element("ul");
    for (const warning of r.warnings) notes.append(element("li", warning));
    $("design-balance").replaceChildren(table, connection, notes);
    $("design-detail").textContent = JSON.stringify({
        materials: r.materials, positive: r.positive, negative: r.negative,
        mass_g: r.mass_g, lithium_inventory: r.lithium_inventory, collector_connections: r.collector_connections,
        adapter_input: r.adapter_input, analysis: r.analysis
    }, null, 2);
    renderDesignInsights(r);
}

async function refreshDesigns() {
    const project = library.projectId, records = await api(`/api/designs?project_id=${encodeURIComponent(project)}`);
    if (project !== library.projectId) return;
    designing.records = records;
    const empty = element("option", "保存済み設計を選択");
    empty.value = "";
    $("design-saved").replaceChildren(empty, ...records.map(r => {
        const option = element("option", `${r.input.name} · ${r.created_at.slice(0, 19)} UTC · ${r.id.slice(0, 8)}`);
        option.value = r.id;
        return option;
    }));
    refreshPhysicsDesigns();
}

function designSimulationFields(r) {
    return {
        cell_format: r.input.cell_format, diameter_mm: r.input.diameter_mm, height_mm: r.input.height_mm,
        capacity_ah: r.capacity.c_rate_reference_ah, chemistry: r.input.positive_material === "LFP_demo" ? "LFP" : "NMC"
    };
}

function syncDesignBinding() {
    if (designing.binding && Object.entries(designSimulationFields(designing.binding)).some(([key, expected]) =>
        typeof expected === "number" ? Number(value(key).value) !== expected : value(key).value !== expected)) designing.binding = null;
    $("design-link").textContent = designing.binding
        ? `設計連携：${designing.binding.input.name} (${designing.binding.id.slice(0, 8)}) · 寸法・基準容量・模式曲線を反映`
        : "設計未連携 · セル設定を直接入力できます。";
}

async function designProjectChanged() {
    designing.binding = null;
    syncDesignBinding();
    designing.records = [];
    $("design-saved").replaceChildren();
    fillDesign(designing.config.templates[$("design-template").value]);
    await refreshDesigns();
}

async function initDesign() {
    designing.config = await api("/api/design/config");
    for (const [index, [title, controls]] of designGroups.entries()) {
        const detail = element("details"), grid = element("div", undefined, "fields two");
        detail.open = index === 0;
        detail.append(element("summary", title));
        for (const [key, label, choices] of controls) {
            const wrapper = element("label", label), input = element(choices ? "select" : "input");
            input.name = key;
            if (choices) for (const [id, text] of Object.entries(choices)) {
                const option = element("option", text);
                option.value = id;
                input.append(option);
            }
            else if (key === "name") {
                input.type = "text";
                input.maxLength = 100;
            } else {
                input.type = "number";
                input.step = "any";
                input.min = "0";
                input.max = "100000";
                if (key === "analysis_temperature_c") input.min = "-20";
            }
            input.required = true;
            wrapper.append(input);
            grid.append(wrapper);
        }
        detail.append(grid);
        if (title.startsWith("活物質")) detail.append(element("p", "比容量は可逆容量で、密度と独立に指定します。0は材料の仮定値を選ぶ指定です。利用率はレートから自動算出しません。比容量・利用率による設計容量の変更は、設計容量をCレート基準に選んだ場合、ソルバの公称基準容量にも影響します。ICEは独立した形成損失帳簿にのみ使用します。", "field-note"));
        if (title.startsWith("電解液")) detail.append(element("p", "物性は評価温度・SOC相当の仮定値です。導電助剤の配合からσを自動推定せず、有効σを入力します。複合負極の粒子・反応値は均質な等価値として扱います。", "field-note"));
        if (title.startsWith("上下端面")) detail.append(element("p", "接触面積は箔厚×巻回長×接触率です。端面円板全体の面積ではありません。接触率を下げても箔抵抗は自動補正しません。", "field-note"));
        $("design-fields").append(detail);
    }
    $("design-form").addEventListener("input", designChanged);
    $("design-form").addEventListener("submit", e => e.preventDefault());
    $("design-template-apply").addEventListener("click", () => fillDesign(designing.config.templates[$("design-template").value]));
    $("design-saved").addEventListener("change", () => {
        const record = designing.records.find(r => r.id === $("design-saved").value);
        if (!record) return;
        fillDesign(record.input);
        clearTimeout(designing.timer);
        ++designing.revision;
        $("design-template").value = record.input.cell_format;
        designing.result = record;
        designing.saved = record;
        $("design-saved").value = record.id;
        renderDesign(record);
        $("design-status").textContent = "保存済みの設計版を復元しました。編集すると新しい版になります。";
        $("design-apply").disabled = false;
        $("design-export").disabled = false;
    });
    $("design-save").addEventListener("click", async () => {
        if (!designing.result) return;
        const revision = designing.revision, project = library.projectId, result = designing.result;
        $("design-save").disabled = true;
        try {
            const record = await api("/api/designs", {project_id: project, input: result.input});
            if (project !== library.projectId || revision !== designing.revision) return;
            designing.result = record;
            designing.saved = record;
            await refreshDesigns();
            if (project !== library.projectId || revision !== designing.revision) return;
            $("design-saved").value = record.id;
            $("design-apply").disabled = false;
            $("design-status").textContent = "設計の入力・収支・材料物性を保存しました。試験条件へ反映できます。";
        } catch (error) {
            if (revision === designing.revision) {
                $("design-status").textContent = error.message;
                $("design-save").disabled = false;
            }
        }
    });
    $("design-apply").addEventListener("click", () => {
        if (!designing.saved || designing.saved.project_id !== library.projectId || state.busy) return;
        const record = designing.saved, input = {...readInput(), ...designSimulationFields(record)};
        const lfp = input.chemistry === "LFP";
        input.min_voltage_v = lfp ? 2.5 : 2.8;
        input.max_voltage_v = lfp ? 3.65 : 4.2;
        if (input.capacity_ah < 0.1 || input.capacity_ah > 100 || input.diameter_mm < 10 || input.diameter_mm > 50 || input.height_mm < 20 || input.height_mm > 150) {
            message("この設計は現在の合成モデル入力範囲外です。設計JSONは保存できます。", "error");
            return;
        }
        setInput(input);
        designing.binding = record;
        syncDesignBinding();
        selectModelTab("synthetic");
        message("合成モデルへ寸法・Cレート基準容量・模式曲線を反映しました。物理計算にはSPMe・DFN欄で保存設計を選択してください。");
        $("simulation-form").scrollIntoView({block: "start"});
    });
    $("design-export").addEventListener("click", () => {
        if (!designing.result) return;
        const url = URL.createObjectURL(new Blob([JSON.stringify(designing.result, null, 2)], {type: "application/json"}));
        const a = element("a");
        a.href = url;
        a.download = "pylibstudy-design.json";
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    form.addEventListener("input", syncDesignBinding);
    form.addEventListener("change", syncDesignBinding);
    fillDesign(designing.config.templates["21700"]);
    await refreshDesigns();
}
