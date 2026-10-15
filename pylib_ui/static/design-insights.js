"use strict";

function insightNumber(value, digits = 3) {
    return Number.isFinite(value) ? value.toFixed(digits) : "—";
}

function insightTable(headers, rows) {
    const wrap = element("div", undefined, "insight-table-scroll"), table = element("table");
    const head = element("thead"), heading = element("tr");
    for (const text of headers) {
        const th = element("th", text);
        th.scope = "col";
        heading.append(th);
    }
    head.append(heading);
    const body = element("tbody");
    for (const row of rows) {
        const tr = element("tr");
        for (const text of row) tr.append(element("td", text));
        body.append(tr);
    }
    table.append(head, body);
    wrap.append(table);
    return wrap;
}

function insightDetail(title, ...children) {
    const details = element("details");
    details.append(element("summary", title), ...children);
    return details;
}

function renderDesignInsights(r) {
    const root = $("design-insights"), a = r.analysis;
    root.replaceChildren();
    if (!a) {
        const button = element("button", "この設計を新しい式で再評価");
        button.type = "button";
        button.addEventListener("click", designChanged);
        root.append(element("p", "この保存版は抵抗・性能見積りの追加前です。再評価後は新しい版として保存できます。"), button);
        return;
    }
    const c = r.input, cap = a.capacity, perf = a.performance;
    root.append(element("p", "CAPACITY → RESISTANCE → CELL PERFORMANCE", "eyebrow"),
        element("h3", "活物質容量と設計変更の影響"),
        element("p", "文献理論による静的な設計見積り · 入力物性は未校正。測定DCIRやSPMe/DFNの放電結果とは別に確認します。", "field-note"));
    const cards = element("div", undefined, "insight-metrics");
    const metrics = [
        ["利用率込み設計容量", insightNumber(r.capacity.design_ah) + " Ah", "形成損失前・小さい側の電極"],
        ["形成損失後のLi帳簿", insightNumber(cap.inventory_limited_ah) + " Ah", "指定ICE・予備Liなしの仮定"],
        ["評価点の等価抵抗", a.resistance ? insightNumber(a.resistance.total_mohm) + " mΩ" : "算出対象外", "オーム損失＋反応分極の割線値"],
        ["電圧降下 / 不可逆発熱", perf ? `${insightNumber(perf.voltage_drop_v * 1000, 1)} mV / ${insightNumber(perf.irreversible_heat_w)} W` : "—", "指定放電電流における見積り"]
    ];
    for (const [label, number, note] of metrics) {
        const card = element("div");
        card.append(element("span", label), element("strong", number), element("small", note));
        cards.append(card);
    }
    root.append(cards);
    const used = a.provenance.specific_capacities_mah_g;
    const capacityRows = [
        ["計算に使った比容量：正極 / 黒鉛 / 第2相", `${used.positive} / ${used.graphite} / ${used.additive} mAh/g`],
        ["利用率込み N/P / 容量制限側", `${insightNumber(r.capacity.usable_np_ratio)} / ${cap.limiting_electrode === "positive" ? "正極" : "負極"}`],
        ["形成時Li消費の仮定", `${insightNumber(cap.formation_loss_ah)} Ah（ICE ${insightNumber(c.negative_first_cycle_efficiency * 100, 1)}%）`],
        ["帳簿エネルギー / 質量・体積基準", `${insightNumber(cap.nominal_energy_wh)} Wh / ${insightNumber(cap.nominal_specific_energy_wh_kg, 1)} Wh/kg / ${insightNumber(cap.nominal_energy_density_wh_l, 1)} Wh/L`]
    ];
    root.append(insightTable(["容量・エネルギーの見方", "設計見積り"], capacityRows),
        element("p", "帳簿エネルギー＝形成損失後のLi帳簿容量×指定OCV。実際の放電カーブやレート別取出エネルギーではありません。初期Li充填率の帳簿とは独立です。", "field-note"));
    root.append(insightDetail("活物質別：理論比容量・指定可逆比容量・容量への寄与", insightTable(
            ["活物質", "反応式の理論上限 mAh/g", "指定可逆容量 mAh/g", "質量 g", "全塗工域への寄与 Ah", "理論上限の反応式"],
            cap.materials.map(part => [part.label, insightNumber(part.theoretical_capacity_mah_g, 1),
                insightNumber(part.reversible_capacity_mah_g, 1), insightNumber(part.mass_g),
                insightNumber(part.contribution_ah), part.reaction])),
        element("p", "理論値はnF/(3.6M)による化学量論上限。正極全1Li・黒鉛LiC₆・Si Li₁₅Si₄を仮定します。SiOxはx未指定のため理論値なし。負極寄与は余剰幅込みで、セル容量・N/Pには重なり域だけを使用します。", "field-note")));
    if (perf) {
        root.append(element("p", `評価点：${insightNumber(perf.current_a)} A / ${insightNumber(perf.reference_c_rate)} C / OCV ${c.analysis_ocv_v} V / ${c.analysis_temperature_c}°C · ${c.analysis_current_mode === "fixed_a" ? "固定Aで比較" : "固定Cレートで比較"}`, "insight-evaluation-point"));
        root.append(insightTable(["評価点での性能", "集中近似"], [
            ["端子電圧 / 瞬時出力", `${insightNumber(perf.terminal_voltage_v)} V / ${insightNumber(perf.operating_power_w)} W`],
            ["下限電圧までの余裕", `${insightNumber(perf.voltage_headroom_v)} V${perf.cutoff_reached ? " · 下限以下" : ""}`],
            [`${c.analysis_pulse_s}秒の平均温度上昇 / 温度`, `${insightNumber(perf.average_temperature_rise_k)} K / ${insightNumber(perf.temperature_after_pulse_c)}°C`],
            ["粒子拡散時間 r²/D：正極 / 負極", `${insightNumber(perf.diffusion.positive.particle_diffusion_time_s, 1)} / ${insightNumber(perf.diffusion.negative.particle_diffusion_time_s, 1)} s`],
            ["拡散時間 / 容量帳簿の放電時間：正極 / 負極", `${insightNumber(perf.diffusion.positive.diffusion_to_discharge_time_ratio)} / ${insightNumber(perf.diffusion.negative.diffusion_to_discharge_time_ratio)}（容量減少への自動換算なし）`]
        ]));
        const resistance = a.resistance;
        const breakdown = insightDetail(`抵抗内訳：オーム損失 ${insightNumber(resistance.ohmic_mohm)} mΩ ＋ 反応分極 ${insightNumber(resistance.kinetic_secant_mohm)} mΩ`,
            insightTable(["寄与", "mΩ", "電圧降下 mV", "発熱 W", "根拠ID"], resistance.components.map(x => [
                x.label, insightNumber(x.resistance_mohm, 4), insightNumber(x.voltage_drop_v * 1000),
                insightNumber(x.heat_w, 5), x.references.join(", ") || "ユーザー指定"
            ])));
        breakdown.open = true;
        root.append(breakdown);
        root.append(insightDetail("有効輸送物性・箔端面積・集電経路の比較", insightTable(
            ["領域", "κeff S/m", "屈曲度因子 τ", "有効箔端面 mm²", "理想長手集電の箔抵抗 mΩ"],
            ["positive", "negative", "separator"].map(side => {
                const t = resistance.transport[side], col = resistance.collectors[side];
                return [{positive: "正極", negative: "負極", separator: "セパレータ"}[side],
                    insightNumber(t.effective_conductivity_s_m, 5), insightNumber(t.tortuosity_factor),
                    col ? insightNumber(col.effective_contact_area_mm2) : "—",
                    col ? insightNumber(col.ideal_longitudinal_reference_mohm) : "—"];
            })), element("p", "長手集電値は連続した全幅接続の理想比較です。端面集電と同時に合計抵抗へ加算しません。離散タブ・溶接の縮流抵抗は未計算です。", "field-note")));
    } else root.append(element("p", a.reason, "insight-warning"));
    const notes = element("ul", undefined, "insight-notes");
    for (const warning of a.warnings) notes.append(element("li", warning));
    root.append(notes);
    if (a.sensitivity) renderDesignSensitivity(root, a.sensitivity);
    const theories = element("div", undefined, "insight-theories");
    for (const f of a.formulas) {
        const item = element("article");
        item.append(element("code", f.expression), element("p", `${f.units} · ${f.assumption}`),
            element("small", f.references.length ? "根拠ID：" + f.references.join(", ") : "容量収支からの工学的導出・ユーザー仮定"));
        theories.append(item);
    }
    root.append(insightDetail("計算式・単位・近似の前提", theories));
    const sources = element("ol", undefined, "insight-sources");
    for (const ref of a.references) {
        const li = element("li"), link = element("a", `${ref.authors} (${ref.year}) — ${ref.title}`);
        link.href = ref.url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        li.append(element("strong", ref.id + " · "), link, element("p", ref.use));
        sources.append(li);
    }
    root.append(insightDetail(`論文・公式資料と、この計算での使い方（${a.references.length}件）`, sources));
    const limits = element("ul");
    for (const text of a.limitations) limits.append(element("li", text));
    root.append(insightDetail("適用範囲・SPMe/DFNへの反映範囲", limits));
}

function renderDesignSensitivity(root, sensitivity) {
    const box = element("section", undefined, "insight-sensitivity");
    box.append(element("h3", "設計パラメータを1つ変えたときの影響（±10%）"),
        element("p", sensitivity.comparison_basis, "field-note"));
    const label = element("label", "比較する指標"), select = element("select");
    select.id = "design-sensitivity-metric";
    const metricChoices = {
        design_ah: ["設計容量", "Ah"], resistance_mohm: ["評価点の等価抵抗", "mΩ"],
        terminal_voltage_v: ["評価点の端子電圧", "V"], specific_energy_wh_kg: ["帳簿エネルギー密度", "Wh/kg"],
        heat_w: ["不可逆発熱", "W"], np_ratio: ["利用率込みN/P", ""]
    };
    for (const [key, [text, unit]] of Object.entries(metricChoices)) {
        const option = element("option", `${text}${unit ? " (" + unit + ")" : ""}`);
        option.value = key;
        select.append(option);
    }
    select.value = "resistance_mohm";
    label.append(select);
    const chart = element("div", undefined, "insight-sensitivity-chart");
    const draw = () => {
        const key = select.value, [name, unit] = metricChoices[key];
        const groups = [...new Set(sensitivity.rows.map(row => row.label))];
        const height = 50 + groups.length * 38;
        const svg = svgElement("svg", {
            viewBox: `0 0 900 ${height}`, role: "img",
            "aria-label": `${name}の基準値からの差。青はパラメータ−10%、紫は＋10%。範囲外は計算なし。`
        });
        const values = sensitivity.rows.map(row => row.delta?.[key]).filter(Number.isFinite);
        const maximum = Math.max(...values.map(Math.abs), 1e-12), center = 500;
        svg.append(svgElement("text", {
            x: 12,
            y: 20,
            "font-size": 13,
            fill: "#40586a"
        }, `基準 ${insightNumber(sensitivity.baseline[key])} ${unit} · 青 −10% / 紫 ＋10% · 棒は指標の差分`));
        svg.append(svgElement("line", {x1: center, x2: center, y1: 32, y2: height, stroke: "#acbbc7"}));
        groups.forEach((group, index) => {
            const y = 45 + index * 38;
            svg.append(svgElement("text", {x: 12, y: y + 12, "font-size": 12, fill: "#233e35"}, group));
            sensitivity.rows.filter(row => row.label === group).forEach((row, variant) => {
                const delta = row.delta?.[key], barY = y + variant * 14;
                if (!Number.isFinite(delta)) {
                    svg.append(svgElement("text", {
                        x: 690,
                        y: barY + 10,
                        "font-size": 10,
                        fill: "#83643b"
                    }, "計算なし・理由は表へ"));
                    return;
                }
                const width = Math.abs(delta) / maximum * 245;
                const bar = svgElement("rect", {
                    x: delta >= 0 ? center : center - width, y: barY, width: Math.max(width, 1), height: 10,
                    fill: variant ? "#9a69b1" : "#4986b4", rx: 2
                });
                bar.append(svgElement("title", {}, `${row.label} ${row.factor < 1 ? "−" : "+"}10%: ${insightNumber(row.metrics[key])} ${unit} / 差 ${insightNumber(delta, 5)}`));
                svg.append(bar, svgElement("text", {
                    x: 760,
                    y: barY + 10,
                    "font-size": 10,
                    fill: "#40586a"
                }, `${delta >= 0 ? "+" : ""}${insightNumber(delta, 5)} ${unit}`));
            });
        });
        chart.replaceChildren(svg);
    };
    select.addEventListener("change", draw);
    box.append(label, chart);
    draw();
    box.append(insightDetail("比較の数値・変更値・計算できない理由", insightTable(
        ["変更項目", "変更値", "設計Ah", "N/P", "巻回長mm", "電流A", "抵抗mΩ", "電圧V", "発熱W", "状態・理由"],
        sensitivity.rows.map(row => [
            `${row.label} ${row.factor < 1 ? "−" : "+"}10%`, insightNumber(row.value, 5),
            ...["design_ah", "np_ratio", "winding_length_mm", "current_a", "resistance_mohm", "terminal_voltage_v", "heat_w"].map(key => insightNumber(row.metrics?.[key])),
            row.reason || "見積り計算済み"
        ]))));
    root.append(box);
}
