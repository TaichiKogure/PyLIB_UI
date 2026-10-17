# PyBaMM機能拡張 P0実装と検証

実施日: 2026-10-16。対象: PyLiBStudy / PyBaMM 26.10.1.0。資料11のP0を実装した。P1の最初の追加単位は
**SPM＋C-rate＋CCCVテンプレート** とし、今回の計算機能には含めない。

## 利用方法

既存の `PyLiBStudy.lnk` または `start.cmd` で起動し、画面上部の **利用可能な機能・環境診断**
を開く。既に起動中のサーバーは再利用されるため、更新前のサーバーが動いている場合は起動コンソールで終了して起動し直す。

- 機能83項目はID・機能名・段階で検索でき、現在の状態でも絞り込める。実装計画上の依存を併記する。
- 設定39キーは **実行可5・未接続32・対象外2** に分類する。「実行可」は登録された固定値・物性連動値・温度選択のみを指し、候補値を自由に組み合わせる意味ではない。
- モデル・19物性セット・10ソルバの公開候補を閲覧できる。補助クラスも候補に含まれる。未接続の候補を実行できる表示にはしない。
- 固定Python・PyBaMM・pybammsolvers・NumPy・CasADi・OSと、依存読込／IDAKLU構築の結果を表示する。「環境を再診断」で更新でき、環境が使えない場合もカタログは閲覧できる。

登録した計算経路は次の5組合せ。OSは実行確認済みのWindowsに限定し、未確認OSは理由付きで拒否する。

| モデル | 物性               | 熱     | ソルバ |
|--------|--------------------|--------|--------|
| SPMe   | Chen2020           | 等温   | IDAKLU |
| SPMe   | Chen2020           | 集中熱 | IDAKLU |
| DFN    | Chen2020           | 等温   | IDAKLU |
| DFN    | Chen2020           | 集中熱 | IDAKLU |
| DFN    | Chen2020_composite | 等温   | IDAKLU |

複合負極を選ぶとDFN・等温に連動し、SPMe・集中熱は選択不可になる。理由も試験条件の上に表示する。保存設計のNMC811・孔隙充填率・黒鉛／Si条件の既存検証も継続する。CasADiは依存として診断するが、実行ソルバの選択肢には追加していない。資料11の旧「Casadi固定」表記は実コードに合わせて訂正した。

## 入力・保存契約

`pylibstudy/capabilities.py` が互換表とモデル／ソルバ構築を所有し、HTTP入力・ワーカー・UIは同じ登録内容を使う。アプリ起動時に研究環境を自動更新・インストールしない。カタログの元データはパッケージ内の
`data/pybamm_catalog.v1.json` に保持し、実行時に開発文書を解析しない。

| API                             | 役割                                             |
|---------------------------------|--------------------------------------------------|
| GET `/api/capabilities`         | 機能、設定状態、公開候補、組合せ、環境診断を返す |
| GET `/api/physics/config`       | 既存defaults・environmentにカタログを追加        |
| POST `/api/physics/environment` | 空オブジェクトで研究環境を再診断                 |
| POST `/api/physics/validate`    | 条件を検証・正規化して返す。ジョブは作成しない   |
| POST `/api/jobs`                | 同じ条件検証と保存設計の検証後にジョブを作成     |

条件に `config_schema_version: "1.0"`、`solver: "IDAKLUSolver"`、`model_options: {}`
を追加した。版のない旧条件には現在の版と既存のソルバ既定値を補う。旧結果の保存JSON・点列は書き換えず、そのまま表示・JSON出力できる。復元時だけAPIで検証・移行し、新しい実行は新ジョブになる。

未知の版、未登録モデル・物性・ソルバ、複合負極の集中熱、未接続オプションはHTTP 400で拒否し、キューに入れない。`model_options`
を明示する場合も登録値と一致する値だけ許可する。例えばトップレベルが等温なのにオプションだけ集中熱にする入力は拒否する。任意コードの実行経路は追加していない。

結果にはカタログ版、条件スキーマ版、ソルバ、全39キーのモデル構築時の有効オプション、正規化入力のSHA-256を保存する。入力ハッシュは
`json.dumps(input, sort_keys=True, allow_nan=False)`
のUTF-8に対するSHA-256で、元CSVのハッシュとは別物。物性出典・上書き・設計スナップショット・終了理由等の既存保存を継続する。Experimentによるステップ別制御はプロトコルとstep_resultsに記録する。

復元APIの入力上限はジョブ作成と同じ256
KiBにし、2000点の有効な電流波形も復元できる。診断中はHTTPポートの予約だけ行い、準備完了後に受付を始める。これにより初回起動時に受付待ちソケットへ接続して応答待ちになる問題を修正した。

## 検証

- 全体回帰: **87件成功**（39.795秒）。初回起動、起動済み再利用、旧結果のJSON読込／復元、未対応入力拒否、大きな電流波形の復元を含む。
- P0ブラウザー: **4件成功**
  。カタログ・検索・絞込み・再診断、旧条件の復元と未知版拒否、環境なし表示、390px幅の横はみ出しなしを確認。環境なしの画面試験はHTTP応答を差し替えるテストであり、実環境の欠損を発生させたものではない。
- 既存モデルタブのブラウザー回帰: **9件成功**。方式切替、入力保持、設計反映、旧条件復元、モバイル表示を確認。
- [登録表の5組合せ](evidence/p0/registered-combinations.json): 全件で実ワーカーを通した20秒CC計算、電流符号、設定版、ソルバ、温度設定、入力ハッシュを確認。
- [既存の実ソルバ回帰15ケース](evidence/p0/integration.json):
  粗・標準・細メッシュ、再実行、厳しい許容誤差、DFN、集中熱、複合負極、CV、手組みCCCV、電流波形、保存設計3ケース、初期条件不成立の拒否、再起動後の結果再読込を確認。手組みCCCVは既存機能で、P1のテンプレート追加とは別。
- [実ワーカーの取消・時間上限・再起動](evidence/p0/worker-lifecycle.json): 3経路成功。取消・時間上限・中断で偽の結果を保存しないことを確認。
- JavaScript構文と `git diff --check` を確認。

通常の制限付き経路ではHTTPテスト2件がWinError
10013になったため、既定のプロジェクト内TEMP/TMP・SSLKEYLOGFILE解除と、許可されたローカル実行経路で再検証した。途中の全体回帰では初回起動テストが診断待ちでタイムアウトし、受付開始時期の修正後に初回起動2件と全87件が成功した。途中のP0ブラウザーテストではoption要素のdisabled判定方法を修正し、4件を再実行して成功した。

画面確認: [デスクトップ](evidence/p0/catalog-desktop.png) / [モバイル](evidence/p0/catalog-mobile.png)
。表は小さい画面では表の領域内を横スクロールする。

## 再実行

PowerShellでプロジェクト直下から実行する。HTTP／ブラウザーテストにはローカル通信の許可が必要。

```powershell
$env:TEMP='G:\PyLIB_UI\.test_tmp'
$env:TMP=$env:TEMP
Remove-Item Env:SSLKEYLOGFILE -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
.\.venv\Scripts\python.exe scripts/verify_p0_ui.py
.\.venv\Scripts\python.exe scripts/verify_model_tabs.py
.\.venv\Scripts\python.exe scripts/verify_p0_solver.py
.\.venv\Scripts\python.exe scripts/verify_step3.py --output .test_tmp/p0-solver-results
.\.venv\Scripts\python.exe scripts/verify_step3_lifecycle.py --output docs/evidence/p0/worker-lifecycle.json
node --check pylibstudy/static/capabilities.js
node --check pylibstudy/static/physics.js
git diff --check
```

既存の未コミット変更を保持し、検証は隔離DBで行った。利用者の保存DBや起動済みサーバーを置き換えていない。ソルバの実行成功・短い数値回帰は、対象18650/21700セルの実測校正や寿命・析出・局所温度の予測精度を示すものではない。
