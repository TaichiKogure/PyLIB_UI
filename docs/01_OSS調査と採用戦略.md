# LIB関連OSS調査と採用戦略

調査日：2026-10-14／対象：18650・21700、上下端面全面集電、NCX・LFP、黒鉛・黒鉛/Si。

## 1. 結論と調査の範囲

推奨は **PyBaMM中心の複数精度モデル＋独立した円筒設計層＋データ管理＋段階的なマルチフィジックス連成** である。PyBOPを同定・最適化に利用し、分布電気化学の比較候補をBattMo.jl／PyBattMo、構造力学の第一候補をFEniCSxとする。

「すべてのOSSをインストールして選択できるUI」から始めると、パラメータの意味・単位・符号・状態量の不一致の解決が主作業になる。まず独自の共通設計データと結果形式を作り、必要性を確認したエンジンだけをアダプタ経由で追加する。

本調査では、電気化学、縮約モデル、巻回・集電・熱、力学、微細構造、電解液、同定、実験データ管理の8領域を探索した。英国・米国・ノルウェー・スペイン・イタリア・カナダ・ドイツ・中国/Hong Kong等に関連する研究実装を含むが、全世界の未公開コードやすべての個人リポジトリの網羅を保証するものではない。

検索語は `open source lithium ion battery simulation`、`DFN P2D SPM SPMe`、`cylindrical jellyroll tabless`、`lithium plating swelling stress`、`electrolyte transport` と各プロジェクト名を組み合わせた。検索で発見した候補を公式README・公式文書・原著論文で確認した。ランキングサイトや生成記事は採用判断の根拠にしていない。

表の「確認」は文書の確認であり、手元環境での動作確認ではない。GitHubに公開されていることだけで自由な再配布を認めるものとは判断しない。ライセンス表示は調査時の上流記載であり、採用するタグ・依存・データの条件は実装時に固定する。

## 2. 電気化学・劣化・縮約モデルの候補

優先度：**A＝中核候補、B＝追加検証候補、C＝研究・比較用**。評価は本プロジェクトへの適合性に関する提案であり、一般的な品質順位ではない。

| ID | プロジェクト／一次情報 | 実装・ライセンス表示 | 確認した役割 | 今回の判断・制約 |
|---|---|---|---|---|
| 01 | [PyBaMM](https://github.com/pybamm-team/PyBaMM) | Python／BSD-3-Clause | DFN・SPMe・SPM等、実験プロトコル、物理サブモデル | **A**。基準計算と軽量計算を同じ体系に置ける。巻回体・缶の力学は別途必要 |
| 02 | [PyBOP](https://github.com/pybop-team/PyBOP) | Python／BSD-3-Clause | PyBaMM等の同定・最適化、ベイズ／頻度論的手法 | **A**。独立した電池ソルバとして数えない。API改編と互換性確認が必要 |
| 03 | [BattMo MATLAB](https://github.com/BattMoTeam/BattMo) | MATLAB・MRST／GPL-3.0表示 | DFNを空間拡張したPXD | **B**。多次元比較の基準候補。MATLAB実行環境が別途必要 |
| 04 | [BattMo.jl](https://github.com/BattMoTeam/BattMo.jl) | Julia・Jutul／MIT | 有限体積・自動微分、1D/2D/3Dの連続体モデル | **B・分布系の第一比較候補**。MATLAB版の機能部分集合という明示あり |
| 05 | [PyBattMo](https://github.com/BattMoTeam/PyBattMo) | Pythonラッパー＋Julia／MIT | BattMo.jlをPythonから利用 | **B**。純Pythonソルバではない。Julia初回起動・配布・出力変換の検証が必要 |
| 06 | [cideMOD](https://github.com/cidetec-energy-storage/cideMOD) | Python・FEniCSx／AGPL-3.0-or-later | PXD、電気化学・熱・SEI | **B**。FEM連成の参考。既存メッシュ例はパウチ中心で円筒全面集電は追加検証 |
| 07 | [PETLION.jl](https://github.com/MarcBerliner/PETLION.jl) | Julia／MIT | 高速P2D、熱・agingのモード | **B**。反復同定がボトルネックになった場合の比較候補。公称速度は当システムの保証値ではない |
| 08 | [LIONSIMBA](https://github.com/lionsimbatoolbox/LIONSIMBA) | MATLAB／MIT | 有限体積法によるLIB設計・シミュレーション・制御 | **C**。独立実装との照合に有用。旧数値依存・MATLABを評価する必要 |
| 09 | [MPET](https://github.com/TRI-AMDD/mpet) | Python・DAETools／独自LICENSE要精査 | 多孔質電極と相分離の非平衡熱力学 | **B/C**。LFP・黒鉛の相分離研究に有用。READMEは温度依存が欠けると記載 |
| 10 | [Hybrid-MPET](https://arxiv.org/abs/2305.15599) | MPET拡張研究実装／利用条件未確認 | 複数活物質、並列反応、相転移、不均一性 | **C**。原著論文まで確認。採用リポジトリ・ライセンス・再現環境は追加調査 |
| 11 | [SLIDE](https://github.com/Battery-Intelligence-Lab/SLIDE) | C++＋一部MATLAB／BSD-3-Clause、第三者条項あり | SPM＋集中熱＋各種劣化、長期サイクル | **B**。多数サイクルの比較用。電解液の局所枯渇・全面集電分布の基準にはしない |
| 12 | [LiiBRA.jl](https://github.com/BradyPlanden/LiiBRA.jl) | Julia／MIT | 物理ベースの低次元状態空間モデル生成 | **B/C**。高速プレビュー・制御への後期候補。適用SOC・温度・劣化範囲を別途検証 |
| 13 | [SPMeT](https://github.com/scott-moura/SPMeT) | MATLAB／GPL-3.0 | 電解液を含むSPM、巻回体・缶の2状態熱、SEI | **C**。軽量熱連成の参考。LFP・Siの専用検証が必要 |
| 14 | [DiffLiB](https://github.com/CMSL-HKUST/DiffLiB) | Python・JAX/JAX-FEM／GPL-3.0 | 微分可能DFNと勾配計算 | **C**。将来の勾配同定候補。READMEでは現状等温で温度依存は解に連成しない |
| 15 | [BatCan](https://github.com/coresresearch/BatCan) | Python・Cantera／BSD-3-Clause | SPM/P2D電極、複数化学系、反応・輸送のモジュール化 | **C**。電解液反応拡張の参考。公開デモには未校正パラメータの明記あり |

速度の比較には同じ材料関数、初期状態、終止条件、メッシュ収束、誤差許容値を揃える必要がある。PETLION原著のms級実績を、そのまま複合負極・析出・熱・円筒連成へ外挿しない。[PETLION原著](https://doi.org/10.1149/1945-7111/ac201c)

## 3. 巻回構造・集電・熱・パック

| ID | プロジェクト／一次情報 | 実装・ライセンス表示 | 確認した役割 | 今回の判断・制約 |
|---|---|---|---|---|
| 16 | [JellyBaMM](https://github.com/TomTranter/JellyBaMM) | Python・PyBaMM・OpenPNM等／BSD-3-Clause | 円筒巻回形状、2D、タブ・熱境界・局所ばらつき | **B・早期PoC**。READMEでは3Dは将来。liionpack等の依存互換性が焦点 |
| 17 | [PyECN](https://github.com/ImperialCollegeLondon/PyECN) | Python／BSD-3-Clause | 分布等価回路ネットワークと熱・形状の入力 | **C・参考実装**。2024-09-17にarchive、開発・保守終了を明記 |
| 18 | [STEER OpenCell Design](https://github.com/stanford-developers/steer-opencell-design) | Python／AGPL-3.0表示、dual licensing案内あり | 材料→電極→巻回体→セル、タブレス部品、質量・容量・断面表示 | **B・設計層PoC**。半電池曲線の組合せと設計計算を動的DFNと混同しない。依存データも条件確認 |
| 19 | [liionpack](https://github.com/pybamm-team/liionpack) | Python／MIT | PyBaMMセルを回路網でパック化 | **C・将来パック**。保守モード・新機能追加なし。セル内の全面集電を自動で実装するものではない |
| 20 | [BatterySimulator](https://github.com/KinomotoTomoyo/BatterySimulator) | OpenFOAM関連／上流利用条件の精査が必要 | CFDと電池モデルを組み合わせるGUI系 | **C**。CFD拡張の参考。派生版の自己申告テスト数やproduction ready表記は検証証拠にしない |
| 21 | [batP2dFoam](https://github.com/redyxg/batP2dFoam) | C++・OpenFOAM／GPL-3.0 | P2Dの分離型ソルバ | **C**。冷却流体との連成時の候補。Windows本体と分離した環境を想定 |

円筒セルには、電極厚み方向、粒子半径、巻回体の半径方向・軸方向・周方向という異なる座標がある。**P2Dの「2D」は円筒の断面2Dではない。** また、PyBaMMのjelly-roll notebookは均質化した二電位抵抗モデルを示すもので、任意の全面集電・完全な動的電気化学・構造力学が一括で提供される証拠ではない。[PyBaMM jelly-roll例](https://docs.pybamm.org/en/latest/source/examples/notebooks/models/jelly-roll-model.html)

## 4. 力学・微細構造・電解液に使う周辺基盤

以下は完成済みLIBシステムではない。物理式・境界条件・材料特性・検証ケースの実装が必要となる。

| ID | プロジェクト／一次情報 | ライセンス等 | 利用候補 | 制約と優先度 |
|---|---|---|---|---|
| 22 | [FEniCSx / DOLFINx](https://github.com/FEniCS/dolfinx/blob/main/README.md) | LGPL-3.0-or-later | 軸対称熱・化学ひずみ・弾性・接触の独自FEM | **A・力学段階**。Windows native condaはbetaとの記載。WSL2/Linux workerを優先検討 |
| 23 | [CalculiX](https://www.calculix.de/) | GPL-2.0-or-later | 缶・巻回体の構造、熱、非線形解析 | **B・構造比較**。電気化学状態からの膨張荷重変換が必要 |
| 24 | [MOOSE](https://github.com/idaholab/moose) | LGPL-2.1表示 | 強連成マルチフィジックス・接触・相場等の基盤 | **C**。本格的研究拡張には有力だが初期導入負担が大きい |
| 25 | [OpenPNM](https://github.com/PMEAL/OpenPNM) | MIT | 細孔ネットワーク輸送・有効物性 | **B/C**。円筒全体より微細構造の物性推定。濡れの評価には別途条件設定 |
| 26 | [PoreSpy](https://porespy.org/autoapi/porespy/simulations/tortuosity_fd.html) | 本調査ではライセンス本文未確認 | 画像から有効空隙率・屈曲度等 | **B/C**。CT等が得られた後。画像分割・連結性の影響を管理 |
| 27 | [TauFactor](https://github.com/tldr-group/taufactor) | MIT、Python/PyTorch | ボクセル画像から屈曲度・有効拡散 | **B/C**。Python版を対象。旧MATLAB版は保守終了との記載 |
| 28 | [MATBOX](https://github.com/NREL/MATBOX_Microstructure_analysis_toolbox) | BSD記載＋第三者条項、MATLAB | 微細構造生成・分割・特徴量・メッシュ | **C**。モデル前処理に有用。公開版のモジュール完成状況を個別確認 |
| 29 | [Cantera](https://www.cantera.org/3.2/examples/input/lithium_ion_battery.html) | 本調査ではライセンス本文未確認 | 電極・電解液界面の熱力学・反応機構 | **C**。LIB入力例は存在。任意添加剤の反応データを自動で与えるものではない |
| 30 | [LAMMPS](https://docs.lammps.org/stable/) | GPLv2 | 分子動力学による電解液輸送・界面の研究 | **C・後期研究**。力場・有限サイズ・相関・連続体への変換検証が必要 |

粒子の疲労破壊に関して[FEniCS研究コード](https://github.com/noiiG/Battery-Li-Ion-Simulation-Fatigue)も見つかった。ただし、公開コードの存在と利用許諾・完全な再現性は別である。円筒缶の応力解析へ直接置き換えられるものではないため、候補本体への組込みは保留する。

## 5. データ管理・同定・交換形式

| ID | プロジェクト／一次情報 | ライセンス等 | 役割 | 判断 |
|---|---|---|---|---|
| 31 | [PyProBE](https://github.com/ImperialCollegeLondon/PyProBE) | BSD-3-Clause | サイクラーデータ取込・試験/サイクル/ステップ処理・劣化解析 | **A/B**。追加ローダー候補。配布名は `PyProBE-Data`、別の同名パッケージと区別 |
| 32 | [cellpy](https://github.com/jepegit/cellpy/blob/master/README.md) | MIT | サイクラーデータ共通化、集計、比較 | **B**。最初は一般CSV取込、機器形式が判明した後に採用を選ぶ |
| 33 | [impedance.py](https://github.com/ECSHackWeek/impedance.py) | MIT表示 | EIS処理、検証、等価回路フィット | **B**。EIS入力が得られてから追加。フルセルEISだけで全物性が一意に決まるとは限らない |
| 34 | [BPX](https://github.com/FaradayInstitution/BPX) | パーサーMIT | 電池モデルパラメータのJSON交換・検査 | **A**。内部独自スキーマの入出力境界として採用。形状・接触・曲線来歴は追加領域が必要 |
| 35 | [BattINFO](https://big-map.github.io/BattINFO/dev/how-battinfo-is-built.html) | 本調査では利用条件未確認 | 電池・材料・実験の意味付け、データ相互運用 | **C**。初期は出典・単位・材料IDで足りる。研究組織間共有で再評価 |

BPX標準は[2026年6月の1.1.1案内](https://bpxstandard.com/category/press-release/)がある。一方、標準バージョン、Pythonパーサーバージョン、PyBaMM/PyBOPの対応範囲は別なので、数値の見た目だけで互換と扱わない。

## 6. 公開・無料でも、そのままOSS中核に採用しない対象

| 対象／一次情報 | 調査で分かったこと | 取扱い |
|---|---|---|
| [SPPy](https://github.com/m0in92/SPPy) | READMEはCC BY-NC 4.0 | 非商用制限付き公開コードとして分離。中核候補から外す |
| [BMSLogic](https://github.com/m0in92/bmslogic) | READMEはCC BY-NC-SA 4.0 | 同上。一般的な許諾型OSSと同列にしない |
| [DandeLiion](https://www.dandeliion.com/about) | 技術ライセンスとVolttへの統合を案内 | 性能・設計の比較対象。再利用可能なOSSソース／ライセンスは今回未確認 |
| [BEST](https://www.batterien.fraunhofer.de/content/dam/batterien/en/documents/Fraunhofer-Battery-Alliance_Simulation-and-modelling.pdf) | Fraunhoferの電池・電気化学解析ツールとして紹介 | 技術比較用。公開OSS実装の利用条件を確認できていない |
| DUALFOIL | [MPET上流](https://github.com/TRI-AMDD/mpet)がNewmanらの先行コードとして参照 | 歴史的基準。取得可能な正式版・現行利用条件・再現環境の確認を保留 |
| DENIS | [DLRの一次資料](https://elib.dlr.de/78712/1/Bessler_KraftwerkBatterie_Modellierung_Li-S_Li-O.pdf)はin-house softwareとして説明 | 論文モデルの参考。現行OSS配布は未確認 |
| [OpenFCST](https://openfcst.org/class_documentation/v_03/index.html) | 公開ガイドは燃料電池中心。LIBへの適用は[2026年論文](https://doi.org/10.1149/1945-7111/ae7d5d)に存在 | 公開版でのLIB機能範囲を要確認。今回は選定外 |
| [fastDFN](https://github.com/scott-moura/fastDFN)、DEARLIBS | fastDFN本文取得がtimeout。DEARLIBSは[COBRAPRO論文](https://www.theoj.org/joss-papers/joss.06803/10.21105.joss.06803.pdf)から存在を確認 | 存在する比較対象として残すが、一次コード・条件の確認未完了 |
| [COBRAPRO](https://github.com/COBRAPROsimulator/COBRAPRO) | MIT、DFN＋同定＋識別可能性。MATLABの最適化等の依存あり | 有力な追加比較候補。今回のPython中心構成では初期必須にしない |

したがって、上記35件は「35種類の完成済みLIBソルバ」ではない。完成度・役割・利用条件の異なる候補を分類したもので、関連候補は別表にも残した。

## 7. 目標との適合性

記号：○＝文書に該当機能、△＝部分対応・要アダプタ・要追加検証、開発＝当プロジェクトで実装、—＝本来の用途外。○は精度保証ではない。

| エンジン／層 | 充放電 | 電解液輸送 | 析出 | 黒鉛/Si | 円筒全面集電 | 巻回体/缶応力 |
|---|---|---|---|---|---|---|
| PyBaMM | ○ | ○（DFN/SPMe） | ○ | ○ | 開発/連携 | 開発/連携 |
| PyBOP | 同定 | 同定対象 | 同定条件次第 | 同定条件次第 | 独自モデル次第 | 独自モデル次第 |
| BattMo.jl / PyBattMo | ○ | ○ | 要版別確認 | 要版別確認 | △ | 開発/連携 |
| cideMOD | ○ | ○ | 要版別確認 | 複数活物質は記載あり | △ | 開発/連携 |
| JellyBaMM | ○（PyBaMM経由） | モデル次第 | 組合せ未検証 | 組合せ未検証 | △ | 開発/連携 |
| PyECN | ○（ECN） | — | — | ECM校正で表現 | △ | — |
| STEER OpenCell | 設計曲線 | — | — | 設計配合 | 形状入力○ | — |
| FEniCSx | 開発/連携 | 開発/連携 | 開発/連携 | 開発/連携 | 開発 | 開発 |

複合負極、複合負極への析出、ヒステリシス、連成劣化については、それぞれ別の公式例を確認した。**各機能の存在から、すべての組合せが同時に動くとは推定しない。** [複合負極](https://docs.pybamm.org/en/pybamm-v26.9.0.0/source/examples/notebooks/models/composite_particle.html)、[複合負極の析出](https://docs.pybamm.org/en/pybamm-v26.9.0.0/source/examples/notebooks/models/lithium-plating-composite.html)、[ヒステリシス](https://docs.pybamm.org/en/pybamm-v26.9.0.0/source/examples/notebooks/models/hysteresis-state-models.html)、[連成劣化](https://docs.pybamm.org/en/pybamm-v26.9.0.0/source/examples/notebooks/models/coupled-degradation.html)。

## 8. 採用戦略

### 初期の必須構成

- PyBaMM：SPMeを標準操作モデル、DFNを基準モデル、SPM/ECMを用途限定の軽量モデル。
- 共通設計層：形状、材料、電極バランス、集電接続、熱・力学境界を管理。
- カーブライブラリ：合成・公開実測・ユーザー実測を区別し、取込・保存・比較を最初から実装。
- PyBOP：少数パラメータの同定から導入。全パラメータ同時フィットを既定にしない。
- UI候補：Python中心ならNiceGUI＋Plotly。計算処理はUIと独立したworker。

### 追加する順番

1. JellyBaMMとSTEER OpenCellの最小例を再現して、設計変換・円筒分割の参考にする。
2. 全面集電の分布モデルを独自アダプタで実装し、BattMo.jlと比較する。
3. FEniCSxで巻回体・缶の力学を追加。初期は一方向連成から開始。
4. 必要が出た段階でMPET、TauFactor、OpenPNM、Canteraを用途別に追加する。

### 改善優先順位

最優先は「設計変更が計算条件へ正しく伝わること」「カーブとパラメータの来歴」「全面集電の電流経路」「モデルごとの予測可能範囲」である。見た目の3D精細化、全ソルバ対応、GPU化、分子動力学との自動接続は後順位とする。

## 9. 未確認事項と再調査ゲート

すべての候補の最新commit日・CI結果・全issueは監査していない。継続保守について断定したのは上流が明示したPyECNとliionpack等に限る。実装前には採用候補のrelease tag、LICENSE、依存lock、最小例、機能組合せを記録する。

PyBaMMの一部 `/en/stable/` のnotebook URLは今回404となったため、取得できた `pybamm-v26.9.0.0` の版指定文書を用いた。`latest` を引用した箇所は開発版文書であり、採用版に機能が含まれるか再確認する。PyBOP mainで確認した `>=3.10,<3.14`、`pybamm>=25.12.0` も、release tagでの固定・実行検証を代替しない。

本調査ではライブラリのインストール・数値実行・性能測定・実機データ検証を行っていない。次のStep 0の成果物でその不足を埋める。
