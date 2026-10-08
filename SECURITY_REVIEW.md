# v0.3.4 Windowsフォルダー保護の修正記録

2026-10-08：v0.3.3のWindows実機回帰テストは31成功・1失敗・5未実施。test_windows_parent_rename_blockedで名前変更が成功してしまい、共有削除拒否の前提が成立していないことが判明しました。下記のv0.3.3記録をWindowsの実証と扱わないでください。

修正：ディレクトリをFILE_READ_ATTRIBUTESのみからFILE_LIST_DIRECTORY | FILE_READ_ATTRIBUTESへ変更。共有モードはFILE_SHARE_READ | FILE_SHARE_WRITEのままでFILE_SHARE_DELETEを許可しません。リパースポイント拒否、全祖先ハンドル保持、ACL、通常権限限定、メディア検査は維持。アクセス権不足時に属性のみのハンドルへフォールバックしません。

テスト：ジョブ・親の名前変更に共有違反32を要求し、ハンドル解除後の名前変更成功と原稿内容保持も検査。Windowsチェッカーは正規表現で抽出した失敗テスト識別子のみ表示し、生のパス・例外を出しません。

こちらのLinux検証は37件中36成功・Windows限定1件未実施。2026-10-08、利用者が修正版を適用したWindows実機のcheck_windows.bat PASS画面を確認しました。実APIを使用する紹介原稿・音声作成とMP4書き出しの完了報告を受け、提供されたMP4（144.21秒、1280×720、24fps、H.264/AAC）の全体デコードはエラーなし。2秒・72秒・142秒の画像で表示と2行以内の字幕を確認しました。これらは利用者実機の自己検証と提出物の確認であり、独立した認証ではありません。Windowsテストの個別件数・スキップ件数は今回のPASS画面からは取得していません。音声の自然さと字幕同期の聴取確認、全内蔵依存のCVEクリアランス、他のWindows環境の検証は未完了です。未知の脆弱性や同一ユーザー権限マルウェアへの耐性を保証しません。

参考：Microsoft CreateFileW dwShareModeおよびFile Access Rights Constants。
https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew
https://learn.microsoft.com/en-us/windows/win32/fileio/file-access-rights-constants

---

# 修正・公開準備の検証記録 — v0.3.3

この文書はGitHub登録前に作成した検証・準備記録です。以降はv0.3.3登録前の履歴であり、現在の状態は冒頭のv0.3.4記録を参照してください。
日付：2026-10-08（日本）。v0.3.2を基にした実装検証であり、独立した第三者認証ではありません。外部への公開は行っていません。

## 今回の確認と対応

- 所有者の選択により独自ソースへMITを適用。第三者フォント・ネイティブバイナリ・本人用画像とは分ける。
- コトネ画像の再配布権を推測で承認せず、公開準備用ZIPから除外。画像なしではオリジナルの幾何学的な代替表示を使う。本人用では既存画像とC2PA来歴を保持。
- Windows用imageio-ffmpeg 0.6.0のwheelを取得・照合し、内部にffmpeg-win-x86_64-v7.1.exeがあることを確認。後続の公式修正があるため、旧ランタイムを新しい経路で導入・使用しない。
- FFmpeg公式が紹介するgyan.devの9.0.2 Windows静的ビルドへ切り替える。指定したバージョンURLのみ許可し、リダイレクトを拒否。ダウンロードサイズ・時間・空き容量を制限。
- 実際の配布ZIPを取得し、提供者のSHA-256と一致を確認。ZIP全体とffmpeg.exe・LICENSE・READMEのサイズ/SHA-256を照合。PEヘッダーはAMD64。Windows上での実行は未実施。
- extractallを使わず、選択した3ファイルだけをランダムな排他的一時ファイルへ書き、全て検証した後に実行ファイルを最後に置き換える。GPLライセンス/READMEをruntime/へ保持する。ソースZIPにはruntime/やバイナリを含めない。
- 生成時はruntime/ffmpeg.exeのサイズ/ハッシュを検査。PATH、conda、環境変数による外部実行ファイルの上書きを使わない。入力形式/プロトコルもrawvideo/pipeとwav/fileへ制限。
- 公開準備用ZIPの明示的allowlistを追加。個人画像・秘密設定・出力・ログ・native runtime・仮想環境・ローカルチェック結果・Git履歴を含めない。秘密情報候補の検出時は作成を止める。ローカル作成のみでGit/通信/公開操作なし。
- check_windows.bat/check_windows.pyを追加。回帰テスト、出力ACL、Windows rename-lock、mock PCMからのMP4、デコード、字幕/サムネイル/生成物取得をAPIキーなしで確認する。結果に利用者名・パス・キーを保存しない。

## 維持した対策

Host/Origin/session/bootstrap制御、localhost限定、API/文字数/ジョブ数制限、読み替え膨張対策、FD/Windowsハンドルで固定したファイル処理、本人用出力権限、動画容量の開始前・実行中検査、総HTTP応答時間、秘密のない子プロセス環境、固定エラー、Serverヘッダー非表示を維持。

定期容量検査はOSの厳密なハードクォータではなく、一時的超過はあり得る。同じユーザー権限のマルウェア、悪意あるインストール所有者、LAN/Web/複数利用者への公開は対象外。

## 検証

- オフライン回帰テスト：37件中36件成功、Windows限定1件はLinux環境のため未実施。
- 新規検査：画像なし代替表示、口の2状態・720p合成、公開ZIPへの秘密設定/画像/出力/runtime/自己検証結果の非混入、主要キー・リンク・上書き拒否、ネイティブZIP/メンバーの検証失敗と旧実行ファイル保持。
- 実際のFFmpeg 9.0.2 Windows ZIPを使った検証・選択抽出・メンバー照合：成功。実行はしていない。
- 変更後の描画/入力ホワイトリスト/MP4デコード回帰試験：Linux環境のPillow 12.3.0と既存FFmpeg 7.0.2で成功。新しいWindows 9.0.2の動作確認とは区別する。旧バイナリを製品の実行経路に戻していない。
- Python/JavaScript構文、公開ZIPのファイル構成・manifest・主要秘密情報候補を検査。
- 実OpenAI API送信なし。Windows GUI/自然音声、setup/start/native実行と全内蔵ライブラリのCVE/ライセンス条件の独立認証は未完了。

## 残件

Windows実機でsetup.bat → check_windows.bat → start.batを確認する。自己検証結果は編集可能であり独立認証ではない。実際の利用者PC上の最新版ソース・将来のGit履歴は別途確認する。このベースには以前のスライド/拡大機能がない。既存フル機能版へ上書きしない。

Public公開準備用のソースは個人画像・ネイティブバイナリを含まない。本人用画像やruntimeを後から加える場合は、権利・再配布義務・秘密情報を再確認する。SHA256SUMSは整合性検査用で、独立した配布元署名ではない。PUBLIC_RELEASE_CHECKLIST.mdを参照。

GitHubへのアップロード・リポジトリ作成・コミット・公開：未実施。
