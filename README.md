# line-stamp-maker2

## AI仕上げ

生成済みの `main.png` を入力にして、OpenAI Images APIでLINEプロフィール向けの1024x1024 PNGを作成できます。

1. OpenAI SDKを含めて依存関係をインストールします。

   ```bash
   pip install -e .
   ```

2. APIキーを環境変数に設定します。

   macOS/Linux:

   ```bash
   export OPENAI_API_KEY="sk-..."
   ```

   Windows PowerShell:

   ```powershell
   $env:OPENAI_API_KEY="sk-..."
   ```

3. 通常どおりスタンプセットを生成したあと、詳細画面の「AI仕上げ」ボタンを押します。

出力は `output/set_XXXX/ai_finish/` に保存されます。

- `natural.png`: 自然光・背景ボケ・写真風
- `storybook.png`: 絵本風・やわらかい色味
- `premium.png`: 北欧風・ミニマル・高級感

APIキー未設定、OpenAI SDK未導入、画像生成前などの場合は、詳細画面上部にエラーメッセージを表示します。

## ChatGPT仕上げ準備

OpenAI APIを使わず、ChatGPTの画像編集画面に手動で渡すための素材とプロンプトを出力できます。

1. 通常どおりスタンプセットを生成します。
2. 詳細画面で「ChatGPT仕上げ用に出力」を押します。
3. `output/chatgpt-ready/` に以下が作成されます。
   - `icon_natural_source.png`
   - `icon_storybook_source.png`
   - `icon_premium_source.png`
   - `prompt.txt`
4. 可能な環境では `prompt.txt` の内容がクリップボードにもコピーされます。
5. 「フォルダを開く」から出力フォルダを開き、PNGとプロンプトをChatGPTの画像編集に貼り付けます。

生成されるプロンプトは、子供の顔・表情・髪型・服装を変更せず、背景だけをLINEプロフィールアイコン向けに整える内容です。
## Windowsで起動する

リポジトリ直下の `start.bat` からLINEアイコンメーカーを起動できます。

初回だけ、仮想環境と依存関係を準備してください。

```bat
py -m venv .venv
.venv\Scripts\python.exe -m pip install -e .[dev]
```

起動するには、リポジトリ直下で `start.bat` をダブルクリックします。

- `.venv\Scripts\python.exe run.py` でアプリを起動します。
- ブラウザで `http://127.0.0.1:5000/` を自動で開きます。
- 既に起動中の場合は、その旨を表示してブラウザだけ開きます。
- アプリ利用中は `start.bat` の黒いウィンドウを閉じないでください。

デスクトップショートカットを作る場合は、`create_desktop_shortcut.bat` をダブルクリックします。デスクトップに `LINEアイコンメーカー.lnk` が作成され、リンク先はリポジトリ直下の `start.bat`、作業フォルダはこのリポジトリになります。

最低限の確認方法:

1. `start.bat` を実行する。
2. ブラウザで `http://127.0.0.1:5000/` が開くことを確認する。
3. もう一度 `start.bat` を実行し、既に起動中という案内が出ることを確認する。
4. `create_desktop_shortcut.bat` を実行し、デスクトップの `LINEアイコンメーカー.lnk` から起動できることを確認する。
