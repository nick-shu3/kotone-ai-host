# ライセンス・第三者コンポーネント

## 独自のソース

所有者がMITを選択。LICENSEを保持してください。コードで描く幾何学的な代替司会者も独自のソースとしてMITに含みます。以下の第三者物・個人用画像の権利をMITで上書きしません。

## NotoSansCJKjp-Regular.otf

著作権はフォント内にAdobeの通知があります。SIL Open Font License 1.1。FONT-LICENSE.txtと元のメタデータを保持してください。元プロジェクト：https://github.com/notofonts/noto-cjk 。Windows Meiryo/Yu Gothicはローカル参照のみで、ファイルを再配布しません。

## Pillow 12.3.0

setupが公式PyPIからwheelを取得し、固定SHA-256を検証します。wheelや仮想環境はソースZIPに含めません。Pillowの実際の配布物に入っているライセンスとネイティブライブラリの通知が適用されます。
https://pillow.readthedocs.io/en/stable/about.html
https://github.com/python-pillow/Pillow/security/advisories

## FFmpeg 9.0.2 Windows x86_64 — gyan.dev essentials static build

FFmpeg公式ダウンロードページが紹介するWindowsビルド提供者から取得します。バイナリはソースZIPに含めません。install_ffmpeg.pyは特定バージョンURL、配布ZIPのSHA-256、抽出する実行ファイル・LICENSE・READMEのSHA-256を検証し、runtime/へ導入します。native-runtime.jsonに記録があります。

提供者は静的ビルドをGPLv3としています。ソース参照はFFmpeg commit 946fcce07b（9.0.2）で、ビルドにはlibx264など外部ライブラリも含まれます。保存したFFMPEG-LICENSE.txtとFFMPEG-README.txtを参照してください。

https://ffmpeg.org/download.html
https://www.gyan.dev/ffmpeg/builds/
https://github.com/FFmpeg/FFmpeg/commit/946fcce07b
https://ffmpeg.org/legal.html
https://ffmpeg.org/security.html

このプログラムは外部プロセスとして実行します。独自PythonソースにMITを適用することと、別のFFmpeg実行ファイルのGPL条件は区別します。runtime/やインストール済み仮想環境を再配布する場合には、通知だけでなく実際の構成に対応するソース提供等の義務を満たす必要があります。提供者のリンクとハッシュだけで再配布義務が自動的に完了するとは扱いません。

旧imageio-ffmpeg 0.6.0は新しい実行経路で使用・導入しません。旧仮想環境を引き継がず、新しいフォルダーに展開してください。

## presenter.png（本人用ZIPのみ）

以前の本人用画像を変更せず保持しています。来歴情報には生成日時・識別子・生成サービス・公開証明書等があり、生成プロンプト・ユーザーのAPIキーやメールは確認されていません。来歴検査は著作権・再配布許諾を証明しません。MITの対象から除外し、公開準備用ZIPには含めません。

バージョン固定・SHA-256・動作試験は、全ての未知の脆弱性や全第三者ライブラリをクリアした認証ではありません。Windows実機と実際に再配布する物を確認してください。
