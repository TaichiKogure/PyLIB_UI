# PyBaMM機能拡張 P3 実装と検証

実施日: 2026-10-17。対象: `G:\PyLIB_UI` / PyLiBStudy。資料11のP3までを実装し、P0〜P2と既存Step 3を回帰確認した。固定環境は
PyBaMM 26.10.1.0 / IDAKLUSolver。依存ライブラリの追加・更新はしていない。

## 操作と実装範囲

1. 起動中のサーバーを終了し、`start.cmd` で再起動してブラウザーを再読み込みする。
2. SPM/SPMe/DFNの「熱容量・冷却境界・電気接触抵抗・混合熱」を開く。
3. 文献の層別熱容量を使うか、セルの熱容量J/Kを明示する。独自の熱容量・境界・接触抵抗・面積・体積には出典または仮定を記録する。熱伝達係数は従来どおり計算入力であり、文献から自動決定した値ではない。
4. 外側温度は周囲温度境界または外側ノードの集中熱を選ぶ。後者には外側熱容量J/Kと環境熱抵抗K/Wが必要。セル側と外側は別容量で、重複しない配分を指定する。
5. 結果の「熱収支・熱物性の根拠・発熱比較」で、蓄熱・境界熱流・熱収支・物性の根拠を確認する。保存履歴のチェックで選んだ計算の条件・温度・発熱を並べ、系列メニューから温度や「接触を含む合計発熱」を重ねる。比較セットとして保存・復元できる。

| 対象                     | P3の接続状態                                                                                 |
|--------------------------|----------------------------------------------------------------------------------------------|
| Chen2020 × SPM/SPMe/DFN  | 等温・集中熱。文献層別熱容量または明示セル熱容量                                             |
| Chen2020_composite × DFN | 等温。集中熱は出典付きセル熱容量の明示入力が必須。層別の不足物性を補わない                   |
| 熱境界                   | 周囲温度境界、外側集中熱ノード、h、冷却面積、セル体積                                        |
| 電気接触抵抗             | セル全体の定数Ω。端子電圧とI²Rに反映。充放電とも対応                                         |
| 混合熱                   | 単相Chen2020のSPM/SPMe/DFN。固定版の複合負極は相別変数に未対応のためUI/APIで拒否             |
| 等温熱源                 | 有効/無効を選択。無効時の発熱系列を「未計算」とし、0として扱わない                           |
| 設計帳簿                 | 保存設計の寸法は従来どおり接続。質量×仮定比熱・接触率・ASR・端面抵抗の帳簿値は自動転用しない |

セル熱容量は0.1〜10,000 J/K、hは0〜10,000 W/ (m² K)、電気接触抵抗は0〜0.1 Ω、冷却面積は1e-6〜1 m²、体積は1e-7〜0.01
m³、外側熱容量は0.1〜10,000 J/K、環境熱抵抗は0.001〜10,000 K/W。これらはアプリの入力制約であり、対象セルの物性範囲・安全限界を検証したものではない。

## 計算・保存契約

条件スキーマは **1.3**、アダプタは **1.5.0**、結果は **3.2**、結果変数/分布契約は **1.1**
。版なし・1.0・1.1・1.2の条件は元オブジェクトを変異させず移行し、将来版は拒否する。旧結果の保存JSON・点列は書き換えない。登録組合せは8件になった。

`thermal_settings` に熱容量モード、J/K、境界モード、外側熱容量、環境熱抵抗、電気接触抵抗、混合熱、等温熱源、面積・体積、出典・仮定を保存する。明示J/Kは最終セル体積Vで割り、PyBaMMの
`Cell heat capacity [J.K-1.m-3]` に渡す。面積・体積を指定しなければ、文献形状または保存設計の寸法を使う。
`thermal_provenance` は実効形状・初期熱容量・根拠・上書きを、`initial_state` は要求温度と実際の初期温度を記録する。

接続したP3オプションは `thermal`、`calculate heat source for isothermal models`、`contact resistance`、`heat of mixing`、
`surface temperature`、`use lumped thermal capacity`
。UI、入力検証、登録表、実ワーカーで同じ設定を使う。未対応・不足・非有限値・未知項目・model_optionsとの不一致はキュー投入前に拒否する。

セル温度Tと外側温度Tsについて、集中熱は次式を解く。

```text
Ccell(T) dT/dt = Qelectrochemical + I² Rcontact + h A (Ts - T)
Csurface dTs/dt = h A (T - Ts) + (Tambient - Ts) / Renvironment
```

周囲温度境界ではTs=Tambientで、2式目を使わない。PyBaMMの `Total heating [W]` は電気化学の合計で、接触発熱を含まない。追加系列
`total_heat_with_contact_w` で接触発熱を加算する。電圧収支には `contact_voltage_loss_v=-I Rcontact`
を加える。正負極3E電位差は接触抵抗手前の電圧で、端子電圧はその差からI Rを引く。

新しい任意保存系列は、接触電圧成分、接触発熱、接触込み合計発熱、セル境界熱流、外側環境熱流、外側温度。degC変換はセル温度と外側温度に適用する。使わない熱境界や無効な等温熱源は取得不可、選択しない系列は未選択とする。出力を絞って収支成分が不足する場合は判定不可とし、偽の収支不一致にしない。

`thermal_balance` は各実行ステップ内のネイティブ解を501点で評価し、Q dtとC (T)
dTを台形積分する。ステップ間の不連続を跨がない。セル蓄熱、外側蓄熱、電気化学熱、接触熱、セル境界と環境の熱流、セル残差と系全体残差をJで保存する。熱流はノードへの流入が正。許容差は
`max(0.005 J, エネルギー尺度の0.2%)`。出力系列の間引き・未選択に依存せず、内部で数値積分する。等温では蓄熱収支を判定しない。

## 不整合確認で修正した点

| 不整合                                                   | 修正・確認                                                                                                                                                  |
|----------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 集中熱の初期温度が最初のステップの周囲温度で上書きされた | 固定版Simulationの初期化動作を確認。最初の周囲温度をパラメータから渡し、初期セル温度を独立に保持。実初期温度も保存。35°Cから25°C/20°Cへの冷却を解析解と照合 |
| 接触抵抗導入時の電圧収支と全発熱の意味                   | 接触電圧を別項にし、電気化学熱と接触込み合計を区別。3E電位差との関係を明記                                                                                  |
| 熱流の未使用・熱源未計算がゼロに見える                   | 該当系列を取得不可にし、理由を保存                                                                                                                          |
| P2で追加した発熱等の系列を比較セットに保存できない       | 比較保存の許可変数を結果カタログに合わせ、発熱比較の保存復元を実ブラウザーで確認                                                                            |
| 遅い比較・履歴応答がプロジェクト切替後に戻る             | 比較読込、履歴一覧、比較セット一覧にプロジェクト確認を追加。遅延比較応答を使うブラウザー回帰を追加                                                          |
| ブラウザー再読込時の持続接続切断が不要な例外ログになる   | ConnectionResetError/BrokenPipeErrorだけを通常切断として閉じる。他の例外を伝播するテストも追加                                                              |
| 計画表・機能カタログ・版と旧条件試験の表示差             | P2/P3完了、条件付き複合負極集中熱、設定1.3、登録8組合せ、次段階P4に合わせて更新                                                                             |

初期温度が周囲温度と異なる旧条件を再実行すると、修正後の温度結果は旧結果と変わる。旧結果は当時の計算記録として保持する。

既存の未コミット変更は保持し、反映前にハッシュ照合とバックアップを行った。途中で元ファイルの整形差分を検出したため、変更していない構文単位の整形を引き継いで統合した。試験は隔離DBで実行し、利用者の保存DB・起動済みサーバーを置き換えていない。

## 検証結果

| 検証             | 結果・証跡                                                                                                                                     |
|------------------|------------------------------------------------------------------------------------------------------------------------------------------------|
| 全unittest       | **111件成功**。P3の契約・不足物性・旧版移行・HTTP拒否・欠損成分・切断処理を含む                                                                |
| P3実ワーカー     | **28ケース成功**。[solver-integration.json](evidence/p3/solver-integration.json)                                                               |
| P1実ソルバー回帰 | **26ケースで期待状態一致**。新しい8組合せ、各制御、テンプレート、skip、設計C-rate等。[記録](evidence/p3/p1-regression/solver-integration.json) |
| P2実ソルバー回帰 | **13ケース成功**。結果、分布、電極SOH、収支、CSV再取込、初期OCV、後処理等。[記録](evidence/p3/p2-regression/solver-integration.json)           |
| 既存Step 3回帰   | **15ケースで期待状態一致**。メッシュ・許容差・再現性・設計反映等。[記録](evidence/p3/step3-regression/integration.json)                        |
| 実ワーカー寿命   | timeout/cancel/restartの**3経路成功**。結果誤保存なし。[記録](evidence/p3/worker-lifecycle.json)                                               |
| ブラウザー       | P3 **4件**、モデルナビゲーション **9件**、P2 **5件**、P1 **5件**、P0 **4件**の計**27件成功**。Edge headless、隔離保存先                        |
| 静的確認         | 変更JSの構文、Pythonコンパイル、差分空白確認。最終ハッシュと証跡は[集約記録](evidence/p3/verification-summary.json)                            |

P3の28ケースは、登録8組合せ、断熱50/100
J/K、冷却強化、放電/充電接触抵抗、解析冷却、最初のステップの周囲温度、2熱ノード、等温極限と等温基準、3モデルの混合熱、等温熱源無効、接触抵抗付き明示CP/CR、周囲温度切替、保存設計2種、明示形状を確認した。全ケースで保存再読込と有限JSON、該当ケースで熱・電圧収支、CSV、比較保存を確認。

代表値（仮定物性・短時間の数値試験）:

- 3 A・120秒・断熱の最高平均温度: 50 J/Kで25.653866°C、100 J/Kで25.327963°C。h=100 W/ (m² K)では25.375118°C。
- 接触0.01 Ω、3 A・120秒の接触熱は10.8 J。-2 A・30秒では1.2 J。充電時は接触電圧成分が正となり、発熱は正。
- 35→25°C、h=30、C=50 J/Kの無通電冷却は、rtol/atol=1e-8で解析解から約0.0000413 K差。35→20°Cの最初の周囲温度指定も解析解との差0.002
  K未満。
- 等温極限のh=10,000、1 A・30秒では平均温度の最大上昇約0.000627 K。等温基準との最終電圧差は0.0002 V未満。
- 2熱ノード試験の系全体熱収支残差は約0.000171 J。各ケースの実残差・許容差はJSONに保存している。

途中の冷却試験で初期温度上書きを再現し修正した。解析解照合は通常許容誤差の数mK差も検出したため、厳しい許容誤差で照合した。初期ブラウザー試験の失敗2件は、閉じた比較パネルの操作とテスト用関数復元の問題で、試験を修正後に成功した。P2画面で発生した通常の接続切断ログも処理を修正して再確認した。

画面: [熱収支・比較](evidence/p3/thermal-result-desktop.png) / [幅390pxの結果](evidence/p3/thermal-result-mobile.png) / [幅390pxの設定](evidence/p3/thermal-settings-mobile.png)
。画面用計算の物性は仮定値で、実測データではない。

## 再実行と根拠

```powershell
$env:TEMP='G:\PyLIB_UI\.test_tmp'
$env:TMP=$env:TEMP
Remove-Item Env:SSLKEYLOGFILE -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
.\.venv\Scripts\python.exe scripts/verify_p3_solver.py
.\.venv\Scripts\python.exe scripts/verify_p3_ui.py
.\.venv\Scripts\python.exe scripts/verify_p2_solver.py --output docs/evidence/p3/p2-regression
.\.venv\Scripts\python.exe scripts/verify_p1_solver.py --output docs/evidence/p3/p1-regression
.\.venv\Scripts\python.exe scripts/verify_step3.py --output docs/evidence/p3/step3-regression
.\.venv\Scripts\python.exe scripts/verify_step3_lifecycle.py --output docs/evidence/p3/worker-lifecycle.json
.\.venv\Scripts\python.exe scripts/verify_p2_ui.py
.\.venv\Scripts\python.exe scripts/verify_p1_ui.py
.\.venv\Scripts\python.exe scripts/verify_p0_ui.py
git diff --check
```

HTTP試験は許可されたローカル通信経路を使う。固定版の `thermal/lumped.py`、`thermal/base_thermal.py`、
`thermal/surface/lumped.py`、`thermal_parameters.py`、`simulation/simulation.py`
を確認し、[ソースハッシュ](evidence/p3/pinned-source-manifest.json)
を記録した。文献の導線は[公式熱モデル例](https://docs.pybamm.org/en/pybamm-v26.9.0.0/source/examples/notebooks/models/thermal-models.html)、[公式の集中熱実装](https://docs.pybamm.org/en/v26.3.1/_modules/pybamm/models/submodels/thermal/lumped.html)、[外側熱ノードの公式説明](https://pybamm.org/news/2024/09/03/pybamm-24.9/)
を参照。オンライン文書の版と導入版は異なる場合があり、実装・検証は導入固定版を優先した。

対象18650/21700・端面集電セルの実測校正、局所温度、熱接触抵抗分布、析出・寿命・安全限界の予測精度は未検証。P3完了は計算・来歴・収支・保存・表示の接続と短い数値検証の完了を意味する。次はP4の物性閲覧・差分、材料・複合負極・半セル・輸送設定の拡張。
