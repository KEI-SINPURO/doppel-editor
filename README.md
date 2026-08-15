# Doppel Editor（v2）

過去に編集した動画をAIが分析し、その人らしい編集を新しい動画に自動で再現する動画編集AIアプリです。
テック甲子園2026 プロダクト部門への応募に向けて、機能を「分析→再現」に絞り込んだバージョンです。

## v1からの主な変更点

| 項目 | v1 | v2（このバージョン） |
|---|---|---|
| AI | Ollama（ローカル） | Claude API（Anthropic） |
| AIの強化方法 | Modelfile再学習（ollama create） | フィードバックのプロンプト注入（ai/learning.py） |
| ログイン | メールのみ | メール＋Googleログイン |
| 編集者の構造 | 1編集者＝1スタイル | 1編集者＝複数ジャンル別スタイル |
| 個人素材 | なし | ロゴ／フォント／BGM／効果音をアップロードして使用可能 |
| 機能範囲 | 診断・AIチャット・ミーム提案・YouTuber知識ベース等 多数 | 分析→再現・サムネ生成のみに絞り込み |

なぜOllamaをやめたか：テック甲子園の応募規約で「Webアプリはローカル環境をトンネリングサービス（ngrok等）で公開することは不可」「応募時点で公開状態であることが必須」と定められており、自分のPCでOllamaを動かす運用はこの規約と相性が悪いためです。

---

## 1. ローカルセットアップ

```bash
git clone <このリポジトリ>
cd doppel-editor
bash setup.sh
```

`setup.sh` が `.env` を自動生成するので、以下を埋めてください。

```
SUPABASE_URL=...
SUPABASE_KEY=...
ANTHROPIC_API_KEY=...
APP_PUBLIC_URL=...
```

起動:
```bash
source venv/bin/activate
streamlit run app.py
```

---

## 2. Supabaseのテーブルを作成する

Supabaseダッシュボード → SQL Editor で以下を実行してください（ログイン・データ保存に必要です）。

```sql
create table if not exists profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text
);

create table if not exists editors (
  id text primary key,
  user_id uuid references auth.users(id) on delete cascade,
  name text,
  icon text,
  theme text,
  styles jsonb,
  assets jsonb,
  feedback_count int default 0,
  created_at text,
  updated_at text
);

create table if not exists feedbacks (
  id bigint generated always as identity primary key,
  editor_id text,
  user_id uuid references auth.users(id) on delete cascade,
  content jsonb,
  created_at timestamptz default now()
);

alter table profiles enable row level security;
alter table editors enable row level security;
alter table feedbacks enable row level security;

create policy "Users manage their own profile" on profiles
  for all using (auth.uid() = id);

create policy "Users manage their own editors" on editors
  for all using (auth.uid() = user_id);

create policy "Users manage their own feedbacks" on feedbacks
  for all using (auth.uid() = user_id);
```

---

## 3. Googleログインの設定

Supabaseダッシュボード → Authentication → Providers → Google を有効化してください。
必要な手順（Google Cloud側でのOAuthクライアント発行など）は、開発チャット内で案内した手順カードを参照してください。概要:

1. Google Cloudでプロジェクトを作成
2. OAuth同意画面を設定
3. OAuthクライアントID（ウェブアプリケーション）を発行し、承認済みリダイレクトURIに
   `https://<Supabaseプロジェクトref>.supabase.co/auth/v1/callback` を登録
4. 発行されたClient ID / SecretをSupabaseのGoogleプロバイダー設定に登録
5. Supabase の Authentication → URL Configuration に、本番URL（`APP_PUBLIC_URL`と同じもの）を登録

---

## 4. Streamlit Community Cloudへのデプロイ手順

無料で最も簡単な方法です。以下の順番で進めてください。

1. **GitHubにコードをpushする**
   ```bash
   git init
   git add .
   git commit -m "Doppel Editor v2"
   git branch -M main
   git remote add origin https://github.com/<あなたのアカウント>/doppel-editor.git
   git push -u origin main
   ```
   `.env` は `.gitignore` に入っているのでpushされません（これで正解です）。

2. **share.streamlit.io にアクセスし、GitHubでログイン**

3. **「New app」→ 対象リポジトリ・ブランチ(`main`)・メインファイル(`app.py`) を選択**
   このとき「App URL」で `doppel-editor` のようなサブドメインを自分で指定できます。
   完成すると `https://doppel-editor.streamlit.app` のようなURLになります。
   → これを次の手順の `APP_PUBLIC_URL` として使います。

4. **「Advanced settings」→「Secrets」に以下を貼り付ける**（`.env`の中身をTOML形式で）
   ```toml
   SUPABASE_URL = "https://xxxxx.supabase.co"
   SUPABASE_KEY = "xxxxxxxxxxxxxxxx"
   ANTHROPIC_API_KEY = "sk-ant-xxxxxxxxxxxx"
   APP_PUBLIC_URL = "https://doppel-editor.streamlit.app"
   ```

5. **「Deploy」をクリック**。初回ビルドは `packages.txt`（ffmpeg等）と `requirements.txt`
   （Whisper・moviepy等）のインストールがあるため、数分〜十数分かかります。

6. **SupabaseのAuthentication → URL Configuration に、同じURLをRedirect URLsとして追加**
   （Googleログインのコールバックを受け取れるようにするため）

7. デプロイ後、実際にアプリを開いて一連の流れ（学習→再現）を試してください。

### 無料枠の制限（重要）

- メモリはおおよそ1GB程度です。このため、Whisperのモデルは軽量な `tiny` を既定にしています
  （`app.py` の `render_reproduce_tab` 内、`transcribe_video(..., model_size="tiny")`）。
  精度を上げたい場合は `base` に変更できますが、メモリ不足でアプリが落ちる可能性があるため、
  その場合は Render.com やVPSへの移行を検討してください。
- 12時間アクセスが無いとアプリがスリープし、次のアクセス時に起動し直すため少し時間がかかります。
  審査当日にアクセスされる可能性がある場合は、事前に一度アクセスして起こしておくと安心です。
- カスタムドメインは使えません（`*.streamlit.app` のURLがそのまま応募用の公開URLになります）。

---

## 6. テック甲子園への応募に向けた注意点（デプロイ全般）

テック甲子園の応募規約（Webアプリ部門）で特に注意が必要な点です。

- **応募時点で公開状態であることが必須**：ストア審査のような猶予はなく、審査開始までに実際にアクセスできるURLが必要です。
- **ローカル環境をngrok等でトンネリング公開するのは不可**。IP制限・VPN経由のアクセスも認められません。
- 実際のホスティング先（例：Streamlit Community Cloud、VPS等）にデプロイし、固定のURLを取得してください。
- ホスティング先の環境変数（Secrets）に `.env` と同じ内容を設定してください（`.env` はGit管理から除外しています）。
- Whisper・moviepyは動画処理のためCPU/メモリを多く使います。Streamlit Community Cloud（無料枠）では既定を軽量な `model_size="tiny"` にしていますが、精度・速度をさらに上げたい場合はRender.comやVPSなど、より高いスペックのホスティングへの移行を検討してください。

生成AIの利用について：応募フォームで「Claude API（Anthropic）を使用」「用途: 編集プランの生成・サムネイル提案・スタイルに応じたテロップ文言の調整」と明記できるよう、本READMEにも使用範囲を記録しています。

---

## 7. プロジェクト構成

```
app.py                  … メイン画面（認証／編集クローン一覧／詳細タブ）
ai/
  trainer.py             … 編集者・ジャンル別スタイル・個人素材・フィードバックの保存
  model.py                … Claude API呼び出し（編集アドバイス／サムネ提案／自動再現プラン生成）
  learning.py              … フィードバックを蓄積し、Claude APIへの強化テキストを組み立てる
  auth.py                   … Supabase認証（メール／Google）とクラウド同期
features/
  analyze.py              … 動画スタイル分析（カット・テロップ色・色調）
  transcribe.py            … Whisperによる音声文字起こし
  generate.py               … 無音カット・テロップ焼き込み・字幕出力
  effects.py                 … カラーグレーディング・ズーム・盛り上がり検出
  branding.py                 … 個人素材（ロゴ・BGM・SE）の適用
ui/
  theme.py                … カラーテーマ
  components.py             … SVGアイコン・進捗表示などのUI部品
```

---

## 8. 使い方の流れ

1. 編集クローンを作成する（名前・アイコン・テーマ）
2. 「スタイルを学習する」タブで、過去に編集した動画をアップロードし、ジャンル別にスタイルを学習させる
3. 「動画を再現する」タブで、新しい未編集の動画をアップロードし、学習したスタイルで自動編集する
   （文字起こし → AIによる編集プラン生成 → 無音カット → テロップ焼き込み → カラーグレーディング → 任意でロゴ/BGM合成）
4. 「サムネイル」タブでサムネイル案を生成する
5. 「自分の素材」タブでロゴ・フォント・BGM・効果音を登録しておくと、再現編集時に使える

---

## 9. 既知の制約・今後の改善候補

- Whisperの文字起こし・moviepyの動画書き出しは処理に時間がかかるため、長尺動画では待ち時間が発生します
- カット検出・テロップ検出はフレーム差分・色検出ベースの簡易解析のため、精度には限界があります
- 効果音（SE）の自動配置（ハイライト箇所への割り当て）は現バージョンでは未実装です（BGM/ロゴのみ自動適用）
