# PyLIB UI — 円筒LIBシミュレーションシステム構想

更新日：2026-10-14（日本時間）。 **軽量なシミュレーションUI基本版 v0.1 を実装しました。** 下記のPyBaMM／PyBOP構成は今後の拡張計画です。

## 基本版を起動する

Python 3.10以上。基本版はPython標準ライブラリだけで動き、追加インストールは不要です。

```powershell
cd G:\PyLIB_UI
.\start.ps1
```

既存の `.venv` を優先し、なければ `py -3` を使用します。PyCharmでは `main.py` を実行してください。ブラウザーが自動で開きます。手動アクセス先は
`http://127.0.0.1:8765`、終了は起動したコンソールで `Ctrl+C` です。

```powershell
.\.venv\Scripts\python.exe main.py --no-browser --port 8765
```

18650／21700、NMC／LFPの模式OCV、定電流充電・放電・休止、電圧・SOC・平均温度・電流のグラフ、結果のSQLite保存、最大3件の保存カーブとの比較、CSV／条件付きJSON出力に対応しています。
**初期モデルは合成・未校正の1RC等価回路＋集中熱です。SPMe／DFN、実測取込・同定、局所集電・析出・力学は未実装です。**

操作・計算式・拡張方法・検証記録は [基本版の実装と操作](docs/05_基本版の実装と操作.md) を参照してください。既存のStep
0〜3すべての完了を意味するものではありません。

## 将来のシステム構想

**推奨構成は、PyBaMMを電気化学の基準エンジン、PyBOPを同定・最適化エンジンとし、円筒形状・上下端面集電・熱・構造力学を共通の設計データで接続する方式です。**

18650／21700、上下端部からの全面集電、NCX系／LFP正極、黒鉛100%／黒鉛・Si混合負極を対象とします。NCXは材料群として扱い、NMC・NCA等の具体組成は材料登録時に指定します。SiとSiOxも別材料として登録します。

## 読む順番

1. [OSS調査と採用戦略](docs/01_OSS調査と採用戦略.md)：35候補の役割・制約・出典、比較対象、採用判断。
2. [物理モデルとシステム設計](docs/02_物理モデルとシステム設計.md)：巻回構造、全面集電、簡易モデル、析出・応力・電解液、UI構成。
3. [カーブデータ管理仕様](docs/03_カーブデータ管理仕様.md)：合成／公開実測／自社実測の管理、取込・比較・同定・来歴。
4. [段階的実装と検証計画](docs/04_段階的実装と検証計画.md)：Step 0–9、各段階の成果物と完了条件、改善優先順位。

## 最初の到達点

「セルを選ぶ → 寸法・材料を設定 → 試験条件を設定 → SPMe／DFNで計算 → カーブを保存・比較 → データを取り込む」を一巡できるローカルUIを作ります。

最初のUIでも18650／21700、NCX／LFP、黒鉛／複合負極のデータ構造を持たせます。ただし、実際に計算・検証できる組合せだけを有効にし、未校正テンプレートは明示します。全面集電の局所電流分布まで解く版は、その後の分布モデル段階です。

## 調査で判明した重要事項

- 「PyBOB」は、おそらく [PyBOP](https://github.com/pybop-team/PyBOP) を指します。PyBOPはモデルの同定・最適化が主目的です。
- [PyBaMMの粒子力学](https://docs.pybamm.org/en/pybamm-v26.9.0.0/source/examples/notebooks/models/coupled-degradation.html)と、巻回体・缶の構造解析は別階層です。
- [PyECN](https://github.com/ImperialCollegeLondon/PyECN)は開発・保守終了を明記、[liionpack](https://github.com/pybamm-team/liionpack)は保守モードです。中核への必須依存にはしません。
- [JellyBaMM](https://github.com/TomTranter/JellyBaMM)は円筒巻回形状の有力参考ですが、READMEでは3Dは将来扱いです。
- [STEER OpenCell Design](https://github.com/stanford-developers/steer-opencell-design)には円筒・タブレスの設計階層があります。動的DFNの代替ではなく、設計入力・形状・質量計算の比較候補です。
- [Chenらの公開データ](https://zenodo.org/records/4032561)を初期検証に利用できます。ただし、対象の全面集電セルそのものを検証した証拠にはなりません。
- 既存 `.venv/pyvenv.cfg` はPython 3.14。確認した[PyBOPのmainの依存宣言](https://github.com/pybop-team/PyBOP/blob/main/pyproject.toml)はPython `>=3.10,<3.14`です。Step 0でPython 3.12の別環境と互換バージョンを検証する案です。

既存の調査資料01〜04は公式文書・公開リポジトリ・原著論文による比較です。基本版の実装・検証範囲は資料05に記録しています。PyBaMM／PyBOPのソルバ実行、速度測定、実測との照合は未実施です。OSS調査は世界中の全コードの完全列挙ではなく、対象要件に関係する主要な公開システムと周辺基盤を横断した調査です。
