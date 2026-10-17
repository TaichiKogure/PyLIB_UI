# Windows起動再構築の状況

2026-10-16。利用者からNorton対策済みとして再構築を依頼された。

## 完了した変更

- `pylibstudy/launcher.py`: Python標準ライブラリだけの起動処理。プロジェクト一致を確認した既存サーバーだけを再利用する。
- `start.ps1`: 上記Pythonへの引数受け渡しだけに簡略化。実行ポリシー変更、ダウンロード、保護機能変更は行わない。
- `server.main(argv=None)`: 起動引数を明示して呼び出せるようにした。従来のmain.py実行方法も維持。
- `start.cmd`は`.venv`のPython（なければ`py -3`）で直接起動する形に修正した。PowerShellは経由せず、ExecutionPolicy
  Bypass指定はない。

## 権限調査と復旧

当初`G:\PyLIB_UI\start.cmd`の作成が **Access denied**
で拒否された。利用者からNorton履歴に記録がないとの回答後に再確認したところ、旧バッチが存在していた。フォルダーと当該ファイルのACLにはユーザーおよびCodexSandboxUsersの変更権限があり、読み取り専用属性はなかった。ファイルを書き換えたところ今回は成功した。以前の拒否原因・ファイルが再び存在した経緯は確定できない。

アクセス権の変更・管理者権限の恒久付与・Nortonの除外や無効化は行っていない。`PyLiBStudy.lnk`のリンク先が
`G:\PyLIB_UI\start.cmd`、作業フォルダーが`G:\PyLIB_UI`、アイコンが`scripts\PyLiBStudy.ico`であることを確認した。

## 検証結果

- 起動関連5件成功。別ディレクトリからバッチ初回起動、一時DBの作成とHTTP応答、2回連続の既存サーバー再利用を確認。
- 起動判定の単体チェックでは他アプリを再利用しないことと、明示したデータディレクトリの引数受け渡しを確認。
- 全体の回帰テスト **79件成功（12.723秒）**。プロジェクト内TEMP/TMP、SSLKEYLOGFILE解除、許可されたローカルHTTP実行経路を使用。
- `start.ps1`構文解析、`git diff --check`成功。起動ファイル内にExecutionPolicy/Bypass/EncodedCommand指定がないことを確認。
- 起動検証では一時DBを使い、テストが起動したプロセスだけを終了。ブラウザーは開かない条件で検証した。ユーザーの実データDBを検証起動に使っていない。

フォルダー直下の`PyLiBStudy.lnk`または`start.cmd`
をダブルクリックして利用する。終了はコンソールでCtrl+C。Explorerの実クリック・既定ブラウザーの表示と、Nortonのスキャン/履歴による無検知の確認は今回の自動検証には含まれない。
