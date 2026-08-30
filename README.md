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

- メモリはおおよそ1GB程度です。**今回のアップデートで、Whisperの既定モデルを精度重視の
  `medium`（+ビームサーチ幅5）に引き上げました**（`features/transcribe.py` の
  `DEFAULT_MODEL_SIZE` / `DEFAULT_BEAM_SIZE`。環境変数 `WHISPER_MODEL_SIZE` /
  `WHISPER_BEAM_SIZE` で変更できます）。
  ⚠️ **`medium` 以上のモデルは、Streamlit Community Cloudの無料枠（メモリ約1GB）では
  ほぼ確実にメモリ不足でアプリが落ちます。** 無料枠のまま使う場合は、Secretsに
  `WHISPER_MODEL_SIZE = "small"`（またはbase/tiny）を追加して軽量化するか、
  Render.com やVPSへの移行を検討してください（詳しくは「10. 精度優先の追加設定」参照）。
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
- Whisper・moviepyは動画処理のためCPU/メモリを多く使います。**既定のWhisperモデルを
  精度重視の `medium` に引き上げたため**（詳しくは「10. 精度優先の追加設定」参照）、
  Streamlit Community Cloud（無料枠・メモリ約1GB）ではメモリ不足で落ちる可能性が
  以前より高くなっています。無料枠のまま応募する場合は、Secretsに
  `WHISPER_MODEL_SIZE = "small"` 等の軽量設定を追加してください。精度・速度をさらに
  上げたい場合はRender.comやVPSなど、より高いスペックのホスティングへの移行を検討してください。

生成AIの利用について：応募フォームで「Claude API（Anthropic）を使用」「用途: 編集プランの生成・サムネイル提案・スタイルに応じたテロップ文言の調整」と明記できるよう、本READMEにも使用範囲を記録しています。

---

## 7. プロジェクト構成

```
app.py                  … メイン画面（認証／編集クローン一覧／詳細タブ）
ai/
  trainer.py             … 編集者・ジャンル別スタイル・個人素材・フィードバックの保存
  model.py                … Claude API呼び出し（編集アドバイス／サムネ提案／自動再現プラン生成。
                             長尺動画の自動分割・JSON修復・最高品質モードに対応）
  learning.py              … フィードバックを蓄積し、Claude APIへの強化テキストを組み立てる
  heuristic.py              … AI未使用時のルールベース編集プラン生成
  auth.py                   … Supabase認証（メール／Google）とクラウド同期
features/
  analyze.py              … 動画スタイル分析（カット・テロップ色・色調・カットの癖の学習）
  transcribe.py            … Whisperによる音声文字起こし（精度優先設定・単語レベルタイムスタンプ）
  generate.py               … 無音カット・フィラー語自動トリム・テロップ焼き込み・字幕出力
  effects.py                 … カラーグレーディング・ズーム・盛り上がり検出
  branding.py                 … 個人素材（ロゴ・BGM・SE）の適用
pipeline.py              … 「文字起こし→編集プラン→レンダリング」の一連処理（app.pyから独立）
```

---

## 8. 使い方の流れ

1. 編集クローンを作成する（名前・アイコン・テーマ）
2. 「スタイルを学習する」タブで、過去に編集した動画をアップロードし、ジャンル別にスタイルを学習させる
3. 「動画を再現する」タブで、新しい未編集の動画をアップロードし、学習したスタイルで自動編集する
   （文字起こし → AIによる編集プラン生成 → 無音カット・フィラー語自動トリム → テロップ焼き込み → カラーグレーディング → 任意でロゴ/BGM合成）
4. 「サムネイル」タブでサムネイル案を生成する
5. 「自分の素材」タブでロゴ・フォント・BGM・効果音を登録しておくと、再現編集時に使える

---

## 9. 既知の制約・今後の改善候補

- Whisperの文字起こし・moviepyの動画書き出しは処理に時間がかかるため、長尺動画では待ち時間が発生します
  （今回のアップデートで既定のWhisperモデルを精度優先にしたため、以前よりさらに時間がかかります）
- カット検出・テロップ検出はフレーム差分・色検出ベースの簡易解析のため、精度には限界があります
- 「カットの癖」の学習における発言の並び替え検出（reordering_rate）は、参考情報としてUIに
  表示されるのみで、実際のレンダリング（並び替えの再現）には未対応です
- フィラー語の自動トリムは、日本語のWhisper単語分割の粒度に依存するため、単純な相槌
  （「えー」「あの」等）は高精度に検出できますが、複合的な言い回しは検出しきれない場合があります

---

## 10. 精度優先の追加設定（今回のアップデート）

「多少動作が重くなっても、本人が編集したと思えるレベルの再現度がほしい」という方針で、
AIまわりの精度を全体的に底上げしました。既定値のままでも効果がありますが、
`.env`（またはStreamlit CloudのSecrets）に以下を追加すると、さらに調整できます。

```
WHISPER_MODEL_SIZE=medium   # 文字起こしのWhisperモデル。tiny/base/small/medium/large-v3 等
WHISPER_BEAM_SIZE=5         # ビームサーチ幅。大きいほど精度↑・処理時間↑。0や空にすると高速デコードに戻せる
DOPPEL_QUALITY_MODE=max     # 編集プラン生成に上位モデル(Opus系)を使う「最高品質モード」。既定は未設定(balanced)
```

現在の設定は、アプリのサイドバー下部「精度設定」でいつでも確認できます。

### 主な変更点

- **文字起こしの既定モデルを `tiny` → `medium`（+ビームサーチ幅5）に引き上げ**、
  単語（トークン）レベルのタイムスタンプも常時取得するようにしました
  （`features/transcribe.py`）。「スタイルを学習する」タブで編集前/編集後の両方を
  アップロードした際の比較精度が上がり、「動画を再現する」タブでの文字起こし精度も上がります。
  ⚠️ Streamlit Community Cloudの無料枠（メモリ約1GB）では `medium` 以上はメモリ不足で
  落ちる可能性が高いです。無料枠のまま使う場合は `WHISPER_MODEL_SIZE=small` 等に
  落としてください（詳しくは「無料枠の制限」を参照）。
- **「カットの癖」の学習アルゴリズムを強化**（`features/analyze.py`）。以前は編集前後の
  発言を「編集後全文に対する緩い一致」だけで判定していましたが、個別の発言同士を
  対応付ける処理を追加したことで、動画内の位置（冒頭/中盤/終盤）ごとの残す割合や、
  発言は残しつつ冒頭・末尾のフィラー語だけをトリムする傾向まで学習できるようになりました。
  既存の学習済みスタイルにこれらの情報を反映させるには、該当スタイルを編集前/編集後の
  動画で再学習してください（学習し直さない限り、古いスタイルにはこれらの項目は追加されません）。
- **「発言は残しつつ、冒頭・末尾のフィラー語だけを自動トリム」する処理を追加**
  （`features/generate.py` の `trim_filler_word_edges`）。従来はAI/ヒューリスティックの
  「keep」判定が発言まるごとの二択でしたが、これにより「えっと、今日は」のような発言から
  「今日は」だけを残す、といった細かい編集をAIを介さず自動で再現できるようになりました。
- **音量・キーワードから機械的に検出した「盛り上がり候補」（`features/effects.py`）を、
  AIが使える場合でも常に参考情報として渡すように変更**しました（以前はAI未使用時の
  フォールバックとしてのみ使用）。ハイライト演出（ズーム・スローモーション・SE配置）の
  精度向上を狙っています。
- **長尺動画は自動的に分割してAI呼び出しを行うように変更**（`ai/model.py`）。以前は
  動画まるごと1回のAPI呼び出しで処理しており、長い動画では出力トークン上限に達して
  JSON解析に失敗 → ルールベースに丸ごとフォールバック、ということがありました。
  現在はセグメント数が多い動画を自動的にパート分割して処理し、1パートだけ解析に
  失敗しても、そのパートだけ原文のまま保持して処理を続けます。
- **AIの出力がJSONとして壊れていた場合、1回だけ「有効なJSONに直して」と頼み直す
  修復ステップを追加**しました。
- **`DOPPEL_QUALITY_MODE=max` を設定すると、編集プラン生成により高精度な上位モデル
  （Opus系・`QUALITY_MODEL`）を使う「最高品質モード」に切り替えられます。** 料金・
  レイテンシは上がるため、既定ではオフ（Sonnet系）にしています。最新の料金体系は
  Anthropicの公式ドキュメントを確認してください。

---

## 11. さらなるAI強化（映像そのものを見る・フィードバック学習の強化）

「本人が作った動画らしくする」という目的をさらに推し進めるための追加アップデートです。

```
DOPPEL_VISUAL_MODE=on   # 動画再現時に、フレーム画像もAIに見せて判断させる（任意・既定オフ）
```

### 映像そのものも判断材料にする（`DOPPEL_VISUAL_MODE=on`）

これまでのAI判断はWhisperの文字起こしテキストと数値化されたスタイルデータだけを見ており、
「実際の映像がどう映っているか」（表情・場面・テロップの実際の見た目など）は一切見ていませんでした。

`DOPPEL_VISUAL_MODE=on` を設定すると、「動画を再現する」際に `features/frames.py` で
ハイライト候補（音量・キーワード検出、無ければ動画全体から均等サンプリング）付近の
フレーム画像を最大6枚抜き出し、`ai/model.py` の `generate_edit_plan()` に文字起こしと
一緒に渡すようになります。Claude Vision が実際の映像も見た上でハイライト・強調テロップを
判断できるため、精度向上が期待できます。

⚠️ **画像はAPIのトークン消費が大きく、毎回のAPI呼び出しで発生する処理のため、
既定はオフにしています。** 有効化する場合は、無料トライアルクレジットの消費ペースに
注意してください。また、長尺動画（自動分割される動画。「10. 精度優先の追加設定」参照）
では、コスト・複雑さを抑えるためこの機能は使われません（分割されない長さの動画のみ対象）。

### テロップの文体・言い回しも学習する（既定で有効・追加設定不要）

「スタイルを学習する」タブでAIが使える状態であれば、編集後動画からテロップが写っている
タイミングのフレームを数枚自動で抜き出し、Claude Visionで「テロップの言葉遣い・語尾・
絵文字や記号の使い方・強調の仕方」を分析して言語化します（`describe_visual_editing_style`）。
結果は `style_data["subtitle_voice"]` として保存され、以降その動画を再現する際、
Claudeがテロップ文言を書く時の文体・トーンの参考にします。

1スタイルの学習につき1回だけの軽いコストのため、`DOPPEL_VISUAL_MODE` の設定に
関わらず常に実行されます（AIが使えない場合は自動的にスキップされます）。
学習結果は「スタイルを学習する」タブのスタイル一覧に表示されます。

### フィードバック学習を強化（`ai/learning.py`）

以前は「良い評価」だった提案・編集の例だけを強化データとして使っていましたが、
「改善が必要」だった例も「この傾向は避ける」という参考情報として使うように拡張しました。
また、フィードバックを選ぶ際、現在使おうとしているスタイル名に一致する例を優先し、
足りない分だけ他ジャンルの例で補うようにしました（ジャンルの違うフィードバックが
混ざって的外れな学習をしてしまうのを防ぐため）。追加設定は不要です。