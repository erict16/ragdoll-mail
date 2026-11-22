// UI text in each language. English is complete; a missing key in another language falls back to it.
// %s marks a value filled in at run time.

export const LANG_NAMES = [
  ["en", "English"], ["zh-Hans", "简体中文"], ["zh-Hant", "繁體中文"], ["ja", "日本語"],
  ["ko", "한국어"], ["es", "Español"], ["fr", "Français"], ["de", "Deutsch"],
];

export const LANGS = {};

LANGS.en = {
  inbox: "Inbox", drafts: "Drafts", scheduled: "Scheduled", sent: "Sent", archive: "Archive", trash: "Trash",
  compose: "New mail", search: "Search", reply: "Reply", replyall: "Reply all", forward: "Forward",
  archive_it: "Archive", trash_it: "Move to Trash", restore: "Move to Inbox", unread: "Mark as unread",
  read: "Mark as read", send: "Send", attach: "Attach files", discard: "Delete draft",
  to: "To", cc: "Cc", bcc: "Bcc", subject: "Subject", write: "Write your message…",
  no_mail: "No mail here", no_results: "Nothing found", syncing: "Getting your mail…",
  loading: "Loading…", me: "me", to_x: "To: %s", draft: "Draft", no_subject: "(no subject)",
  saved: "Saved", saving: "Saving…", draft_saved: "Draft saved", draft_deleted: "Draft deleted",
  sending: "Sending…", sent_ok: "Sent", undo: "Undo", archived: "Archived", trashed: "Moved to Trash",
  restored: "Moved to Inbox", saved_to: "Saved to Downloads", show: "Show", images_hidden: "Images from the web are hidden.",
  show_images: "Show images", problems: "Check before sending", send_anyway: "Send anyway",
  keep_editing: "Keep editing", settings: "Settings", sync_now: "Sync now", demo: "Demo mailbox",
  account: "Account", signature: "Signature", appearance: "Appearance", name: "Your name",
  email: "Email address", password: "Password", pw_saved: "Saved in the system keychain",
  incoming: "Incoming server (IMAP)", outgoing: "Outgoing server (SMTP)", port: "Port",
  test: "Test connection", testing: "Testing…", test_ok: "Signed in to both servers.",
  save: "Save", cancel: "Cancel", system: "System", light: "Light", dark: "Dark",
  setup_title: "Add your mail account", servers: "Server settings", sign_in: "Sign in", signing_in: "Signing in…",
  update_to: "Update to %s", run_update: "Run in a terminal: ragdoll update", yesterday: "Yesterday", tomorrow: "Tomorrow",
  pw_env: "The password comes from the %s environment variable. A password saved here is used only when that variable is not set.",
  remove: "Remove", open: "Open", download: "Save to Downloads", drop_files: "Drop files to attach",
  sig_none: "No signature", remove_sig: "Leave out the signature", conn_lost: "Can't reach the server",
  error: "Something went wrong", recipients_more: "and %s more", version: "Version %s", uploading: "Uploading…",
  show_quote: "Show quoted text", copy: "Copy",

  // scheduled send and undo send
  send_later: "Send later", this_evening: "This evening", tomorrow_morning: "Tomorrow morning",
  tomorrow_afternoon: "Tomorrow afternoon", monday_morning: "Monday morning", pick_time: "Pick a date and time…",
  schedule: "Schedule", scheduled_for: "Scheduled for %s", sends_at: "Sends %s", send_now: "Send now", edit: "Edit",
  dont_send: "Don't send", moved_to_drafts: "Moved to Drafts", not_sent: "Not sent: %s", date: "Date", time: "Time",
  pick_future: "Pick a time in the future.", keep_open: "ragdoll-mail sends it while the app is open.",
  sending_tab: "Sending", undo_send: "Undo send", undo_off: "Off", seconds: "%s s",
  undo_note: "How long you can stop a mail after you press Send. Once it has gone out, a mail can't be called back.",

  // language and time zone
  region: "Language & time", language: "Language", time_zone: "Time zone", system_x: "System (%s)",

  // messages from the mail server and checks before sending
  err_bg: "The app's background service is not answering. Reopen ragdoll-mail.",
  err_signin: "Sign-in failed. Check the email address and password in Settings.",
  err_no_pw: "No password saved. Add it in Settings.", err_no_account: "No account yet. Add one in Settings.",
  err_dns: "Can't find the mail server. Check the server name and the internet connection.",
  err_timeout: "The mail server did not answer in time.",
  err_ssl: "Secure connection failed (%s). Check the server name and port.",
  err_refused: "The mail server refused the connection. Check the port.",
  err_reach: "Can't reach the mail server (%s).", err_server: "The mail server said: %s",
  err_gone: "This mail is no longer here. It may have been moved or deleted.", err_draft_gone: "The draft is gone.",
  err_att_missing: "An attachment is missing: %s", err_past: "That time has already passed.",
  p_to_empty: "To is empty.", p_self: "You are also a recipient.", p_not_cc: "%s is not in To or Cc.",
  p_no_subject: "The subject is empty.", p_garbled: "Garbled characters (�) in: %s",
  p_holes: "Placeholders left in the text: %s", p_att: "The text mentions an attachment, but nothing is attached.",
  p_img: "%s image(s) in the mail are missing.",
};

LANGS["zh-Hans"] = {
  inbox: "收件箱", drafts: "草稿箱", scheduled: "定时发送", sent: "已发送", archive: "归档", trash: "已删除",
  compose: "写邮件", search: "搜索", reply: "回复", replyall: "回复全部", forward: "转发",
  archive_it: "归档", trash_it: "删除", restore: "移回收件箱", unread: "标为未读", read: "标为已读",
  send: "发送", attach: "添加附件", discard: "删除草稿", to: "收件人", cc: "抄送", bcc: "密送",
  subject: "主题", write: "写点什么…", no_mail: "这里没有邮件", no_results: "没有找到",
  syncing: "正在收取邮件…", loading: "加载中…", me: "我", to_x: "致：%s", draft: "草稿",
  no_subject: "（无主题）", saved: "已保存", saving: "保存中…", draft_saved: "草稿已保存",
  draft_deleted: "草稿已删除", sending: "正在发送…", sent_ok: "已发送", undo: "撤销", archived: "已归档",
  trashed: "已删除", restored: "已移回收件箱", saved_to: "已存到“下载”", show: "显示",
  images_hidden: "已隐藏网络图片。", show_images: "显示图片", problems: "发送前请检查",
  send_anyway: "仍然发送", keep_editing: "继续编辑", settings: "设置", sync_now: "立即同步",
  demo: "演示邮箱", account: "账户", signature: "签名", appearance: "外观", name: "你的名字",
  email: "邮箱地址", password: "密码", pw_saved: "已存在系统钥匙串", incoming: "收信服务器（IMAP）",
  outgoing: "发信服务器（SMTP）", port: "端口", test: "测试连接",
  testing: "测试中…", test_ok: "两个服务器都登录成功。", save: "保存", cancel: "取消", system: "跟随系统",
  light: "浅色", dark: "深色", setup_title: "添加邮箱账户", servers: "服务器设置", sign_in: "登录",
  signing_in: "登录中…", update_to: "更新到 %s", run_update: "在终端运行：ragdoll update",
  yesterday: "昨天", tomorrow: "明天", pw_env: "密码来自环境变量 %s。只有这个变量没设置时，才会用这里保存的密码。",
  remove: "移除", open: "打开", download: "存到“下载”", drop_files: "松开即可添加附件",
  sig_none: "没有签名", remove_sig: "这封不带签名", conn_lost: "连不上服务器", error: "出错了",
  recipients_more: "等 %s 人", version: "版本 %s", uploading: "上传中…", show_quote: "显示引用内容",
  copy: "复制",

  send_later: "定时发送", this_evening: "今天傍晚", tomorrow_morning: "明天上午",
  tomorrow_afternoon: "明天下午", monday_morning: "周一上午", pick_time: "选择日期和时间…",
  schedule: "定时发送", scheduled_for: "将于 %s 发送", sends_at: "%s 发送", send_now: "立即发送", edit: "编辑",
  dont_send: "取消发送", moved_to_drafts: "已移回草稿箱", not_sent: "没有发出：%s", date: "日期", time: "时间",
  pick_future: "请选一个以后的时间。", keep_open: "app 开着时会按时发出。",
  sending_tab: "发送", undo_send: "撤回发送", undo_off: "关闭", seconds: "%s 秒",
  undo_note: "按下发送后，在这段时间内可以撤回。邮件一旦发出，就无法撤回。",

  region: "语言和时间", language: "语言", time_zone: "时区", system_x: "跟随系统（%s）",

  err_bg: "app 的后台没有响应。请重新打开 ragdoll-mail。",
  err_signin: "登录失败。请在“设置”里检查邮箱地址和密码。",
  err_no_pw: "还没有保存密码。请在“设置”里添加。", err_no_account: "还没有账户。请在“设置”里添加。",
  err_dns: "找不到邮件服务器。请检查服务器名称和网络。",
  err_timeout: "邮件服务器没有及时响应。",
  err_ssl: "安全连接失败（%s）。请检查服务器名称和端口。",
  err_refused: "邮件服务器拒绝了连接。请检查端口。",
  err_reach: "连不上邮件服务器（%s）。", err_server: "邮件服务器返回：%s",
  err_gone: "这封邮件已经不在这里，可能被移动或删除了。", err_draft_gone: "草稿已经不在了。",
  err_att_missing: "缺少附件：%s", err_past: "这个时间已经过了。",
  p_to_empty: "收件人是空的。", p_self: "你自己也在收件人里。", p_not_cc: "%s 不在收件人或抄送里。",
  p_no_subject: "主题是空的。", p_garbled: "有乱码（�）：%s",
  p_holes: "正文里还有占位符：%s", p_att: "正文提到了附件，但没有添加附件。",
  p_img: "邮件里有 %s 张图片缺失。",
};

LANGS["zh-Hant"] = {
  inbox: "收件匣", drafts: "草稿匣", scheduled: "已排程", sent: "寄件備份", archive: "封存", trash: "垃圾桶",
  compose: "撰寫郵件", search: "搜尋", reply: "回覆", replyall: "全部回覆", forward: "轉寄",
  archive_it: "封存", trash_it: "移到垃圾桶", restore: "移回收件匣", unread: "標示為未讀",
  read: "標示為已讀", send: "寄出", attach: "附加檔案", discard: "刪除草稿",
  to: "收件者", cc: "副本", bcc: "密件副本", subject: "主旨", write: "寫點什麼…",
  no_mail: "這裡沒有郵件", no_results: "找不到結果", syncing: "正在接收郵件…",
  loading: "載入中…", me: "我", to_x: "收件者：%s", draft: "草稿", no_subject: "（無主旨）",
  saved: "已儲存", saving: "儲存中…", draft_saved: "草稿已儲存", draft_deleted: "草稿已刪除",
  sending: "寄出中…", sent_ok: "已寄出", undo: "復原", archived: "已封存", trashed: "已移到垃圾桶",
  restored: "已移回收件匣", saved_to: "已儲存到「下載項目」", show: "顯示", images_hidden: "已隱藏網路圖片。",
  show_images: "顯示圖片", problems: "寄出前請檢查", send_anyway: "仍要寄出",
  keep_editing: "繼續編輯", settings: "設定", sync_now: "立即同步", demo: "示範信箱",
  account: "帳號", signature: "簽名檔", appearance: "外觀", name: "你的名字",
  email: "電子郵件地址", password: "密碼", pw_saved: "已存在系統鑰匙圈",
  incoming: "內送伺服器（IMAP）", outgoing: "外寄伺服器（SMTP）", port: "連接埠",
  test: "測試連線", testing: "測試中…", test_ok: "兩個伺服器都已登入成功。",
  save: "儲存", cancel: "取消", system: "跟隨系統", light: "淺色", dark: "深色",
  setup_title: "新增郵件帳號", servers: "伺服器設定", sign_in: "登入", signing_in: "登入中…",
  update_to: "更新到 %s", run_update: "在終端機執行：ragdoll update", yesterday: "昨天", tomorrow: "明天",
  pw_env: "密碼來自環境變數 %s。只有在未設定該變數時，才會使用這裡儲存的密碼。",
  remove: "移除", open: "打開", download: "儲存到「下載項目」", drop_files: "放開即可附加檔案",
  sig_none: "沒有簽名檔", remove_sig: "這封不加簽名檔", conn_lost: "無法連上伺服器",
  error: "發生錯誤", recipients_more: "等 %s 人", version: "版本 %s", uploading: "上傳中…",
  show_quote: "顯示引用內容", copy: "拷貝",

  send_later: "稍後寄出", this_evening: "今天傍晚", tomorrow_morning: "明天上午",
  tomorrow_afternoon: "明天下午", monday_morning: "週一上午", pick_time: "選擇日期和時間…",
  schedule: "排程", scheduled_for: "排定於 %s 寄出", sends_at: "%s 寄出", send_now: "立即寄出", edit: "編輯",
  dont_send: "不要寄出", moved_to_drafts: "已移到草稿匣", not_sent: "未寄出：%s", date: "日期", time: "時間",
  pick_future: "請選擇未來的時間。", keep_open: "App 開啟時，ragdoll-mail 才會寄出。",
  sending_tab: "寄件", undo_send: "復原寄件", undo_off: "關閉", seconds: "%s 秒",
  undo_note: "按下「寄出」後，在這段時間內可以取消寄件。郵件一旦寄出，就無法收回。",

  region: "語言與時間", language: "語言", time_zone: "時區", system_x: "跟隨系統（%s）",

  err_bg: "App 的背景服務沒有回應。請重新開啟 ragdoll-mail。",
  err_signin: "登入失敗。請在「設定」中檢查電子郵件地址和密碼。",
  err_no_pw: "尚未儲存密碼。請在「設定」中新增。", err_no_account: "尚未有帳號。請在「設定」中新增。",
  err_dns: "找不到郵件伺服器。請檢查伺服器名稱和網路連線。",
  err_timeout: "郵件伺服器沒有及時回應。",
  err_ssl: "安全連線失敗（%s）。請檢查伺服器名稱和連接埠。",
  err_refused: "郵件伺服器拒絕了連線。請檢查連接埠。",
  err_reach: "無法連上郵件伺服器（%s）。", err_server: "郵件伺服器回應：%s",
  err_gone: "這封郵件已不在這裡，可能已被移動或刪除。", err_draft_gone: "草稿已不存在。",
  err_att_missing: "缺少附件：%s", err_past: "這個時間已經過了。",
  p_to_empty: "收件者是空的。", p_self: "你自己也是收件者。", p_not_cc: "%s 不在收件者或副本中。",
  p_no_subject: "主旨是空的。", p_garbled: "有亂碼（�）：%s",
  p_holes: "內文中還有未填的預留位置：%s", p_att: "內文提到附件，但沒有附加任何檔案。",
  p_img: "郵件中有 %s 張圖片遺失。",
};

LANGS.ja = {
  inbox: "受信トレイ", drafts: "下書き", scheduled: "送信予約", sent: "送信済み", archive: "アーカイブ", trash: "ゴミ箱",
  compose: "新規メール", search: "検索", reply: "返信", replyall: "全員に返信", forward: "転送",
  archive_it: "アーカイブ", trash_it: "ゴミ箱に移動", restore: "受信トレイに戻す", unread: "未開封にする",
  read: "開封済みにする", send: "送信", attach: "ファイルを添付", discard: "下書きを削除",
  to: "宛先", cc: "CC", bcc: "BCC", subject: "件名", write: "メッセージを入力…",
  no_mail: "メールはありません", no_results: "見つかりませんでした", syncing: "メールを取得中…",
  loading: "読み込み中…", me: "自分", to_x: "宛先: %s", draft: "下書き", no_subject: "（件名なし）",
  saved: "保存しました", saving: "保存中…", draft_saved: "下書きを保存しました", draft_deleted: "下書きを削除しました",
  sending: "送信中…", sent_ok: "送信しました", undo: "元に戻す", archived: "アーカイブしました", trashed: "ゴミ箱に移動しました",
  restored: "受信トレイに戻しました", saved_to: "ダウンロードに保存しました", show: "表示", images_hidden: "Web 上の画像は非表示です。",
  show_images: "画像を表示", problems: "送信前に確認してください", send_anyway: "このまま送信",
  keep_editing: "編集を続ける", settings: "設定", sync_now: "今すぐ同期", demo: "デモ用メールボックス",
  account: "アカウント", signature: "署名", appearance: "外観", name: "名前",
  email: "メールアドレス", password: "パスワード", pw_saved: "システムのキーチェーンに保存済み",
  incoming: "受信サーバ（IMAP）", outgoing: "送信サーバ（SMTP）", port: "ポート",
  test: "接続をテスト", testing: "テスト中…", test_ok: "両方のサーバにサインインできました。",
  save: "保存", cancel: "キャンセル", system: "システム", light: "ライト", dark: "ダーク",
  setup_title: "メールアカウントを追加", servers: "サーバ設定", sign_in: "サインイン", signing_in: "サインイン中…",
  update_to: "%s にアップデート", run_update: "ターミナルで実行: ragdoll update", yesterday: "昨日", tomorrow: "明日",
  pw_env: "パスワードは環境変数 %s から取得します。ここで保存したパスワードは、その変数が未設定の場合のみ使われます。",
  remove: "削除", open: "開く", download: "ダウンロードに保存", drop_files: "ドロップして添付",
  sig_none: "署名なし", remove_sig: "署名を付けない", conn_lost: "サーバに接続できません",
  error: "問題が発生しました", recipients_more: "ほか %s 件", version: "バージョン %s", uploading: "アップロード中…",
  show_quote: "引用を表示", copy: "コピー",

  send_later: "あとで送信", this_evening: "今日の夕方", tomorrow_morning: "明日の朝",
  tomorrow_afternoon: "明日の午後", monday_morning: "月曜の朝", pick_time: "日時を選択…",
  schedule: "予約", scheduled_for: "%s に送信予定", sends_at: "%s に送信", send_now: "今すぐ送信", edit: "編集",
  dont_send: "送信しない", moved_to_drafts: "下書きに移動しました", not_sent: "送信されませんでした: %s", date: "日付", time: "時刻",
  pick_future: "未来の日時を選んでください。", keep_open: "アプリを開いている間に ragdoll-mail が送信します。",
  sending_tab: "送信", undo_send: "送信を取り消す", undo_off: "オフ", seconds: "%s 秒",
  undo_note: "「送信」を押してから、メールの送信を止められる時間です。送信されたメールは取り消せません。",

  region: "言語と時刻", language: "言語", time_zone: "タイムゾーン", system_x: "システム（%s）",

  err_bg: "アプリのバックグラウンドサービスが応答しません。ragdoll-mail を開き直してください。",
  err_signin: "サインインに失敗しました。設定でメールアドレスとパスワードを確認してください。",
  err_no_pw: "パスワードが保存されていません。設定で追加してください。", err_no_account: "アカウントがありません。設定で追加してください。",
  err_dns: "メールサーバが見つかりません。サーバ名とインターネット接続を確認してください。",
  err_timeout: "メールサーバから時間内に応答がありませんでした。",
  err_ssl: "セキュア接続に失敗しました（%s）。サーバ名とポートを確認してください。",
  err_refused: "メールサーバに接続を拒否されました。ポートを確認してください。",
  err_reach: "メールサーバに接続できません（%s）。", err_server: "メールサーバからのメッセージ: %s",
  err_gone: "このメールはもうここにありません。移動または削除された可能性があります。", err_draft_gone: "下書きが見つかりません。",
  err_att_missing: "添付ファイルが見つかりません: %s", err_past: "その時刻はすでに過ぎています。",
  p_to_empty: "宛先が空です。", p_self: "自分も宛先に入っています。", p_not_cc: "%s は宛先にも CC にも入っていません。",
  p_no_subject: "件名が空です。", p_garbled: "文字化け（�）があります: %s",
  p_holes: "本文にプレースホルダが残っています: %s", p_att: "本文に添付の記載がありますが、ファイルが添付されていません。",
  p_img: "メール内の画像 %s 件が見つかりません。",
};

LANGS.ko = {
  inbox: "받은편지함", drafts: "임시보관함", scheduled: "예약됨", sent: "보낸편지함", archive: "보관함", trash: "휴지통",
  compose: "새 메일", search: "검색", reply: "답장", replyall: "전체 답장", forward: "전달",
  archive_it: "보관", trash_it: "휴지통으로 이동", restore: "받은편지함으로 이동", unread: "읽지 않음으로 표시",
  read: "읽음으로 표시", send: "보내기", attach: "파일 첨부", discard: "임시 보관 메일 삭제",
  to: "받는 사람", cc: "참조", bcc: "숨은참조", subject: "제목", write: "메시지를 입력하세요…",
  no_mail: "메일이 없습니다", no_results: "검색 결과가 없습니다", syncing: "메일을 가져오는 중…",
  loading: "불러오는 중…", me: "나", to_x: "받는 사람: %s", draft: "임시 보관", no_subject: "(제목 없음)",
  saved: "저장됨", saving: "저장 중…", draft_saved: "임시 보관 메일을 저장했습니다", draft_deleted: "임시 보관 메일을 삭제했습니다",
  sending: "보내는 중…", sent_ok: "보냈습니다", undo: "실행 취소", archived: "보관했습니다", trashed: "휴지통으로 이동했습니다",
  restored: "받은편지함으로 이동했습니다", saved_to: "다운로드에 저장했습니다", show: "보기", images_hidden: "웹 이미지가 숨겨져 있습니다.",
  show_images: "이미지 표시", problems: "보내기 전에 확인하세요", send_anyway: "그래도 보내기",
  keep_editing: "계속 편집", settings: "설정", sync_now: "지금 동기화", demo: "데모 메일함",
  account: "계정", signature: "서명", appearance: "화면 스타일", name: "이름",
  email: "이메일 주소", password: "비밀번호", pw_saved: "시스템 키체인에 저장됨",
  incoming: "수신 서버(IMAP)", outgoing: "발신 서버(SMTP)", port: "포트",
  test: "연결 테스트", testing: "테스트 중…", test_ok: "두 서버에 모두 로그인했습니다.",
  save: "저장", cancel: "취소", system: "시스템", light: "라이트", dark: "다크",
  setup_title: "메일 계정 추가", servers: "서버 설정", sign_in: "로그인", signing_in: "로그인 중…",
  update_to: "%s(으)로 업데이트", run_update: "터미널에서 실행: ragdoll update", yesterday: "어제", tomorrow: "내일",
  pw_env: "비밀번호는 환경 변수 %s에서 가져옵니다. 여기에 저장한 비밀번호는 해당 변수가 설정되지 않았을 때만 사용됩니다.",
  remove: "제거", open: "열기", download: "다운로드에 저장", drop_files: "파일을 놓아 첨부",
  sig_none: "서명 없음", remove_sig: "서명 넣지 않기", conn_lost: "서버에 연결할 수 없습니다",
  error: "문제가 발생했습니다", recipients_more: "외 %s명", version: "버전 %s", uploading: "업로드 중…",
  show_quote: "인용 텍스트 표시", copy: "복사",

  send_later: "나중에 보내기", this_evening: "오늘 저녁", tomorrow_morning: "내일 오전",
  tomorrow_afternoon: "내일 오후", monday_morning: "월요일 오전", pick_time: "날짜 및 시간 선택…",
  schedule: "예약", scheduled_for: "%s에 보내도록 예약됨", sends_at: "%s에 발송", send_now: "지금 보내기", edit: "편집",
  dont_send: "보내지 않기", moved_to_drafts: "임시보관함으로 이동했습니다", not_sent: "보내지 못했습니다: %s", date: "날짜", time: "시간",
  pick_future: "미래의 시간을 선택하세요.", keep_open: "앱이 열려 있는 동안 ragdoll-mail이 보냅니다.",
  sending_tab: "보내기", undo_send: "보내기 취소", undo_off: "끔", seconds: "%s초",
  undo_note: "보내기를 누른 뒤 메일 발송을 멈출 수 있는 시간입니다. 이미 발송된 메일은 되돌릴 수 없습니다.",

  region: "언어 및 시간", language: "언어", time_zone: "시간대", system_x: "시스템(%s)",

  err_bg: "앱의 백그라운드 서비스가 응답하지 않습니다. ragdoll-mail을 다시 여세요.",
  err_signin: "로그인하지 못했습니다. 설정에서 이메일 주소와 비밀번호를 확인하세요.",
  err_no_pw: "저장된 비밀번호가 없습니다. 설정에서 추가하세요.", err_no_account: "계정이 없습니다. 설정에서 추가하세요.",
  err_dns: "메일 서버를 찾을 수 없습니다. 서버 이름과 인터넷 연결을 확인하세요.",
  err_timeout: "메일 서버가 제때 응답하지 않았습니다.",
  err_ssl: "보안 연결에 실패했습니다(%s). 서버 이름과 포트를 확인하세요.",
  err_refused: "메일 서버가 연결을 거부했습니다. 포트를 확인하세요.",
  err_reach: "메일 서버에 연결할 수 없습니다(%s).", err_server: "메일 서버 응답: %s",
  err_gone: "이 메일은 더 이상 여기에 없습니다. 이동되었거나 삭제되었을 수 있습니다.", err_draft_gone: "임시 보관 메일이 없습니다.",
  err_att_missing: "첨부 파일이 없습니다: %s", err_past: "이미 지난 시간입니다.",
  p_to_empty: "받는 사람이 비어 있습니다.", p_self: "나도 받는 사람에 포함되어 있습니다.", p_not_cc: "%s이(가) 받는 사람이나 참조에 없습니다.",
  p_no_subject: "제목이 비어 있습니다.", p_garbled: "깨진 문자(�)가 있습니다: %s",
  p_holes: "본문에 채우지 않은 자리표시자가 있습니다: %s", p_att: "본문에 첨부 파일이 언급되어 있지만 첨부된 파일이 없습니다.",
  p_img: "메일의 이미지 %s개가 없습니다.",
};

LANGS.es = {
  inbox: "Recibidos", drafts: "Borradores", scheduled: "Programados", sent: "Enviados", archive: "Archivados", trash: "Papelera",
  compose: "Nuevo correo", search: "Buscar", reply: "Responder", replyall: "Responder a todos", forward: "Reenviar",
  archive_it: "Archivar", trash_it: "Mover a la papelera", restore: "Mover a Recibidos", unread: "Marcar como no leído",
  read: "Marcar como leído", send: "Enviar", attach: "Adjuntar archivos", discard: "Eliminar borrador",
  to: "Para", cc: "Cc", bcc: "Cco", subject: "Asunto", write: "Escribe tu mensaje…",
  no_mail: "No hay correos aquí", no_results: "No se encontró nada", syncing: "Obteniendo tu correo…",
  loading: "Cargando…", me: "yo", to_x: "Para: %s", draft: "Borrador", no_subject: "(sin asunto)",
  saved: "Guardado", saving: "Guardando…", draft_saved: "Borrador guardado", draft_deleted: "Borrador eliminado",
  sending: "Enviando…", sent_ok: "Enviado", undo: "Deshacer", archived: "Archivado", trashed: "Movido a la papelera",
  restored: "Movido a Recibidos", saved_to: "Guardado en Descargas", show: "Mostrar", images_hidden: "Las imágenes de la web están ocultas.",
  show_images: "Mostrar imágenes", problems: "Revisa antes de enviar", send_anyway: "Enviar de todos modos",
  keep_editing: "Seguir editando", settings: "Ajustes", sync_now: "Sincronizar ahora", demo: "Buzón de demostración",
  account: "Cuenta", signature: "Firma", appearance: "Apariencia", name: "Tu nombre",
  email: "Dirección de correo", password: "Contraseña", pw_saved: "Guardada en el llavero del sistema",
  incoming: "Servidor de entrada (IMAP)", outgoing: "Servidor de salida (SMTP)", port: "Puerto",
  test: "Probar conexión", testing: "Probando…", test_ok: "Sesión iniciada en ambos servidores.",
  save: "Guardar", cancel: "Cancelar", system: "Sistema", light: "Claro", dark: "Oscuro",
  setup_title: "Añade tu cuenta de correo", servers: "Ajustes del servidor", sign_in: "Iniciar sesión", signing_in: "Iniciando sesión…",
  update_to: "Actualizar a %s", run_update: "Ejecuta en una terminal: ragdoll update", yesterday: "Ayer", tomorrow: "Mañana",
  pw_env: "La contraseña viene de la variable de entorno %s. La contraseña guardada aquí solo se usa cuando esa variable no está definida.",
  remove: "Quitar", open: "Abrir", download: "Guardar en Descargas", drop_files: "Suelta los archivos para adjuntarlos",
  sig_none: "Sin firma", remove_sig: "Omitir la firma", conn_lost: "No se puede conectar con el servidor",
  error: "Algo salió mal", recipients_more: "y %s más", version: "Versión %s", uploading: "Subiendo…",
  show_quote: "Mostrar texto citado", copy: "Copiar",

  send_later: "Enviar más tarde", this_evening: "Esta tarde", tomorrow_morning: "Mañana por la mañana",
  tomorrow_afternoon: "Mañana por la tarde", monday_morning: "El lunes por la mañana", pick_time: "Elegir fecha y hora…",
  schedule: "Programar", scheduled_for: "Programado para %s", sends_at: "Se envía %s", send_now: "Enviar ahora", edit: "Editar",
  dont_send: "No enviar", moved_to_drafts: "Movido a Borradores", not_sent: "No enviado: %s", date: "Fecha", time: "Hora",
  pick_future: "Elige una hora futura.", keep_open: "ragdoll-mail lo envía mientras la app esté abierta.",
  sending_tab: "Envío", undo_send: "Deshacer envío", undo_off: "No", seconds: "%s s",
  undo_note: "Tiempo que tienes para detener un correo después de pulsar Enviar. Una vez enviado, un correo no se puede recuperar.",

  region: "Idioma y hora", language: "Idioma", time_zone: "Zona horaria", system_x: "Sistema (%s)",

  err_bg: "El servicio en segundo plano de la app no responde. Vuelve a abrir ragdoll-mail.",
  err_signin: "No se pudo iniciar sesión. Revisa la dirección de correo y la contraseña en Ajustes.",
  err_no_pw: "No hay contraseña guardada. Añádela en Ajustes.", err_no_account: "Aún no hay ninguna cuenta. Añade una en Ajustes.",
  err_dns: "No se encuentra el servidor de correo. Revisa el nombre del servidor y la conexión a internet.",
  err_timeout: "El servidor de correo no respondió a tiempo.",
  err_ssl: "Falló la conexión segura (%s). Revisa el nombre del servidor y el puerto.",
  err_refused: "El servidor de correo rechazó la conexión. Revisa el puerto.",
  err_reach: "No se puede conectar con el servidor de correo (%s).", err_server: "El servidor de correo dijo: %s",
  err_gone: "Este correo ya no está aquí. Puede que se haya movido o eliminado.", err_draft_gone: "El borrador ya no existe.",
  err_att_missing: "Falta un archivo adjunto: %s", err_past: "Esa hora ya ha pasado.",
  p_to_empty: "El campo Para está vacío.", p_self: "Tú también eres destinatario.", p_not_cc: "%s no está en Para ni en Cc.",
  p_no_subject: "El asunto está vacío.", p_garbled: "Caracteres ilegibles (�) en: %s",
  p_holes: "Quedan marcadores de posición en el texto: %s", p_att: "El texto menciona un archivo adjunto, pero no hay ninguno.",
  p_img: "Faltan %s imagen(es) del correo.",
};

LANGS.fr = {
  inbox: "Boîte de réception", drafts: "Brouillons", scheduled: "Programmés", sent: "Envoyés", archive: "Archives", trash: "Corbeille",
  compose: "Nouveau message", search: "Rechercher", reply: "Répondre", replyall: "Répondre à tous", forward: "Transférer",
  archive_it: "Archiver", trash_it: "Mettre à la corbeille", restore: "Remettre dans la boîte de réception", unread: "Marquer comme non lu",
  read: "Marquer comme lu", send: "Envoyer", attach: "Joindre des fichiers", discard: "Supprimer le brouillon",
  to: "À", cc: "Cc", bcc: "Cci", subject: "Objet", write: "Écrivez votre message…",
  no_mail: "Aucun message ici", no_results: "Aucun résultat", syncing: "Récupération de vos messages…",
  loading: "Chargement…", me: "moi", to_x: "À : %s", draft: "Brouillon", no_subject: "(sans objet)",
  saved: "Enregistré", saving: "Enregistrement…", draft_saved: "Brouillon enregistré", draft_deleted: "Brouillon supprimé",
  sending: "Envoi…", sent_ok: "Envoyé", undo: "Annuler", archived: "Archivé", trashed: "Mis à la corbeille",
  restored: "Remis dans la boîte de réception", saved_to: "Enregistré dans Téléchargements", show: "Afficher", images_hidden: "Les images du web sont masquées.",
  show_images: "Afficher les images", problems: "À vérifier avant l’envoi", send_anyway: "Envoyer quand même",
  keep_editing: "Continuer la rédaction", settings: "Réglages", sync_now: "Synchroniser", demo: "Boîte de démonstration",
  account: "Compte", signature: "Signature", appearance: "Apparence", name: "Votre nom",
  email: "Adresse e-mail", password: "Mot de passe", pw_saved: "Enregistré dans le trousseau du système",
  incoming: "Serveur entrant (IMAP)", outgoing: "Serveur sortant (SMTP)", port: "Port",
  test: "Tester la connexion", testing: "Test en cours…", test_ok: "Connexion réussie aux deux serveurs.",
  save: "Enregistrer", cancel: "Annuler", system: "Système", light: "Clair", dark: "Sombre",
  setup_title: "Ajouter votre compte de messagerie", servers: "Réglages des serveurs", sign_in: "Se connecter", signing_in: "Connexion…",
  update_to: "Mettre à jour vers %s", run_update: "Dans un terminal, lancez : ragdoll update", yesterday: "Hier", tomorrow: "Demain",
  pw_env: "Le mot de passe provient de la variable d’environnement %s. Un mot de passe enregistré ici n’est utilisé que si cette variable n’est pas définie.",
  remove: "Retirer", open: "Ouvrir", download: "Enregistrer dans Téléchargements", drop_files: "Déposez les fichiers pour les joindre",
  sig_none: "Aucune signature", remove_sig: "Sans signature", conn_lost: "Impossible de joindre le serveur",
  error: "Une erreur s’est produite", recipients_more: "et %s autres", version: "Version %s", uploading: "Envoi du fichier…",
  show_quote: "Afficher le texte cité", copy: "Copier",

  send_later: "Envoyer plus tard", this_evening: "Ce soir", tomorrow_morning: "Demain matin",
  tomorrow_afternoon: "Demain après-midi", monday_morning: "Lundi matin", pick_time: "Choisir la date et l’heure…",
  schedule: "Programmer", scheduled_for: "Programmé pour %s", sends_at: "Envoi %s", send_now: "Envoyer maintenant", edit: "Modifier",
  dont_send: "Ne pas envoyer", moved_to_drafts: "Remis dans les brouillons", not_sent: "Non envoyé : %s", date: "Date", time: "Heure",
  pick_future: "Choisissez un moment dans le futur.", keep_open: "ragdoll-mail l’envoie tant que l’app est ouverte.",
  sending_tab: "Envoi", undo_send: "Annuler l’envoi", undo_off: "Désactivé", seconds: "%s s",
  undo_note: "Délai pendant lequel vous pouvez arrêter un message après avoir cliqué sur Envoyer. Une fois parti, un message ne peut plus être rappelé.",

  region: "Langue et heure", language: "Langue", time_zone: "Fuseau horaire", system_x: "Système (%s)",

  err_bg: "Le service en arrière-plan de l’app ne répond pas. Rouvrez ragdoll-mail.",
  err_signin: "Échec de la connexion. Vérifiez l’adresse e-mail et le mot de passe dans les Réglages.",
  err_no_pw: "Aucun mot de passe enregistré. Ajoutez-le dans les Réglages.", err_no_account: "Aucun compte pour l’instant. Ajoutez-en un dans les Réglages.",
  err_dns: "Serveur de messagerie introuvable. Vérifiez le nom du serveur et la connexion internet.",
  err_timeout: "Le serveur de messagerie n’a pas répondu à temps.",
  err_ssl: "Échec de la connexion sécurisée (%s). Vérifiez le nom du serveur et le port.",
  err_refused: "Le serveur de messagerie a refusé la connexion. Vérifiez le port.",
  err_reach: "Impossible de joindre le serveur de messagerie (%s).", err_server: "Le serveur de messagerie a répondu : %s",
  err_gone: "Ce message n’est plus ici. Il a peut-être été déplacé ou supprimé.", err_draft_gone: "Le brouillon n’existe plus.",
  err_att_missing: "Une pièce jointe est introuvable : %s", err_past: "Cette heure est déjà passée.",
  p_to_empty: "Le champ À est vide.", p_self: "Vous êtes aussi destinataire.", p_not_cc: "%s n’est ni dans À ni dans Cc.",
  p_no_subject: "L’objet est vide.", p_garbled: "Caractères illisibles (�) dans : %s",
  p_holes: "Il reste des espaces réservés dans le texte : %s", p_att: "Le texte mentionne une pièce jointe, mais rien n’est joint.",
  p_img: "%s image(s) du message sont manquantes.",
};

LANGS.de = {
  inbox: "Posteingang", drafts: "Entwürfe", scheduled: "Geplant", sent: "Gesendet", archive: "Archiv", trash: "Papierkorb",
  compose: "Neue E-Mail", search: "Suchen", reply: "Antworten", replyall: "Allen antworten", forward: "Weiterleiten",
  archive_it: "Archivieren", trash_it: "In den Papierkorb", restore: "In den Posteingang", unread: "Als ungelesen markieren",
  read: "Als gelesen markieren", send: "Senden", attach: "Dateien anhängen", discard: "Entwurf löschen",
  to: "An", cc: "Cc", bcc: "Bcc", subject: "Betreff", write: "Nachricht schreiben…",
  no_mail: "Keine E-Mails", no_results: "Nichts gefunden", syncing: "E-Mails werden abgerufen…",
  loading: "Wird geladen…", me: "Ich", to_x: "An: %s", draft: "Entwurf", no_subject: "(kein Betreff)",
  saved: "Gesichert", saving: "Wird gesichert…", draft_saved: "Entwurf gesichert", draft_deleted: "Entwurf gelöscht",
  sending: "Wird gesendet…", sent_ok: "Gesendet", undo: "Widerrufen", archived: "Archiviert", trashed: "In den Papierkorb verschoben",
  restored: "In den Posteingang verschoben", saved_to: "In Downloads gesichert", show: "Anzeigen", images_hidden: "Bilder aus dem Internet sind ausgeblendet.",
  show_images: "Bilder anzeigen", problems: "Vor dem Senden prüfen", send_anyway: "Trotzdem senden",
  keep_editing: "Weiter bearbeiten", settings: "Einstellungen", sync_now: "Jetzt abgleichen", demo: "Demo-Postfach",
  account: "Account", signature: "Signatur", appearance: "Erscheinungsbild", name: "Dein Name",
  email: "E-Mail-Adresse", password: "Passwort", pw_saved: "Im Schlüsselbund des Systems gesichert",
  incoming: "Eingangsserver (IMAP)", outgoing: "Ausgangsserver (SMTP)", port: "Port",
  test: "Verbindung testen", testing: "Wird getestet…", test_ok: "Bei beiden Servern angemeldet.",
  save: "Sichern", cancel: "Abbrechen", system: "System", light: "Hell", dark: "Dunkel",
  setup_title: "E-Mail-Account hinzufügen", servers: "Servereinstellungen", sign_in: "Anmelden", signing_in: "Anmeldung läuft…",
  update_to: "Auf %s aktualisieren", run_update: "Im Terminal ausführen: ragdoll update", yesterday: "Gestern", tomorrow: "Morgen",
  pw_env: "Das Passwort stammt aus der Umgebungsvariable %s. Ein hier gesichertes Passwort wird nur verwendet, wenn diese Variable nicht gesetzt ist.",
  remove: "Entfernen", open: "Öffnen", download: "In Downloads sichern", drop_files: "Dateien zum Anhängen hier ablegen",
  sig_none: "Keine Signatur", remove_sig: "Ohne Signatur senden", conn_lost: "Server nicht erreichbar",
  error: "Es ist ein Fehler aufgetreten", recipients_more: "und %s weitere", version: "Version %s", uploading: "Wird hochgeladen…",
  show_quote: "Zitierten Text anzeigen", copy: "Kopieren",

  send_later: "Später senden", this_evening: "Heute Abend", tomorrow_morning: "Morgen früh",
  tomorrow_afternoon: "Morgen Nachmittag", monday_morning: "Montag früh", pick_time: "Datum und Uhrzeit wählen…",
  schedule: "Planen", scheduled_for: "Geplant für %s", sends_at: "Wird %s gesendet", send_now: "Jetzt senden", edit: "Bearbeiten",
  dont_send: "Nicht senden", moved_to_drafts: "In die Entwürfe verschoben", not_sent: "Nicht gesendet: %s", date: "Datum", time: "Uhrzeit",
  pick_future: "Wähle einen Zeitpunkt in der Zukunft.", keep_open: "ragdoll-mail sendet die E-Mail, solange die App geöffnet ist.",
  sending_tab: "Senden", undo_send: "Senden widerrufen", undo_off: "Aus", seconds: "%s Sek.",
  undo_note: "So lange kannst du eine E-Mail nach dem Klick auf Senden noch anhalten. Eine gesendete E-Mail lässt sich nicht zurückholen.",

  region: "Sprache und Zeit", language: "Sprache", time_zone: "Zeitzone", system_x: "System (%s)",

  err_bg: "Der Hintergrunddienst der App antwortet nicht. Öffne ragdoll-mail erneut.",
  err_signin: "Anmeldung fehlgeschlagen. Prüfe E-Mail-Adresse und Passwort in den Einstellungen.",
  err_no_pw: "Kein Passwort gesichert. Füge es in den Einstellungen hinzu.", err_no_account: "Noch kein Account. Füge in den Einstellungen einen hinzu.",
  err_dns: "Mailserver nicht gefunden. Prüfe den Servernamen und die Internetverbindung.",
  err_timeout: "Der Mailserver hat nicht rechtzeitig geantwortet.",
  err_ssl: "Sichere Verbindung fehlgeschlagen (%s). Prüfe Servernamen und Port.",
  err_refused: "Der Mailserver hat die Verbindung abgelehnt. Prüfe den Port.",
  err_reach: "Mailserver nicht erreichbar (%s).", err_server: "Der Mailserver meldet: %s",
  err_gone: "Diese E-Mail ist nicht mehr hier. Sie wurde vielleicht verschoben oder gelöscht.", err_draft_gone: "Der Entwurf existiert nicht mehr.",
  err_att_missing: "Ein Anhang fehlt: %s", err_past: "Dieser Zeitpunkt ist bereits vorbei.",
  p_to_empty: "Das Feld „An“ ist leer.", p_self: "Du bist auch Empfänger.", p_not_cc: "%s steht weder in „An“ noch in Cc.",
  p_no_subject: "Der Betreff ist leer.", p_garbled: "Unleserliche Zeichen (�) in: %s",
  p_holes: "Im Text sind noch Platzhalter: %s", p_att: "Im Text wird ein Anhang erwähnt, aber es ist nichts angehängt.",
  p_img: "%s Bild(er) in der E-Mail fehlen.",
};

// formatting, flags, several mails at once, keyboard shortcuts
const MORE = {
  en: {
    back: "Back", ok: "OK", close: "Close", font_sample: "The quick brown fox jumps over the lazy dog. 你好，世界。",
    flagged: "Starred", flag: "Star", unflag: "Remove star", formatting: "Formatting", font: "Font", font_size: "Size",
    size_small: "Small", size_normal: "Normal", size_large: "Large", size_huge: "Huge",
    bold: "Bold", italic: "Italic", underline: "Underline", strike: "Strikethrough", bullets: "Bulleted list",
    numbers: "Numbered list", quote_block: "Quote", link: "Link", link_url: "Link address", clear_fmt: "Clear formatting",
    composing: "Composing", default_font: "Default font", default_size: "Default size", text_size: "Text size",
    n_selected: "%s selected", select_all: "Select all", shortcuts: "Keyboard shortcuts", next_mail: "Next mail",
    prev_mail: "Previous mail", close_clear: "Close or clear", bigger: "Bigger text", smaller: "Smaller text",
    actual_size: "Default text size", save_draft: "Save draft", add_select: "Add to selection",
    range_select: "Select a range", mailbox: "Mailbox", writing: "Writing", reading: "Reading",
  },
  "zh-Hans": {
    back: "返回", ok: "确定", close: "关闭", font_sample: "这是新邮件的默认字体。The quick brown fox.",
    flagged: "星标邮件", flag: "加星标", unflag: "取消星标", formatting: "格式", font: "字体", font_size: "字号",
    size_small: "小", size_normal: "正常", size_large: "大", size_huge: "特大",
    bold: "粗体", italic: "斜体", underline: "下划线", strike: "删除线", bullets: "项目符号列表",
    numbers: "编号列表", quote_block: "引用", link: "链接", link_url: "链接地址", clear_fmt: "清除格式",
    composing: "写邮件", default_font: "默认字体", default_size: "默认字号", text_size: "文字大小",
    n_selected: "已选 %s 封", select_all: "全选", shortcuts: "键盘快捷键", next_mail: "下一封",
    prev_mail: "上一封", close_clear: "关闭或清除", bigger: "放大文字", smaller: "缩小文字",
    actual_size: "默认文字大小", save_draft: "保存草稿", add_select: "加入选择",
    range_select: "连续选择", mailbox: "邮箱", writing: "写邮件", reading: "阅读",
  },
  "zh-Hant": {
    back: "返回", ok: "確定", close: "關閉", font_sample: "這是新郵件的預設字型。The quick brown fox.",
    flagged: "星號郵件", flag: "加上星號", unflag: "移除星號", formatting: "格式", font: "字型", font_size: "字級",
    size_small: "小", size_normal: "標準", size_large: "大", size_huge: "特大",
    bold: "粗體", italic: "斜體", underline: "底線", strike: "刪除線", bullets: "項目符號清單",
    numbers: "編號清單", quote_block: "引言", link: "連結", link_url: "連結網址", clear_fmt: "清除格式",
    composing: "撰寫郵件", default_font: "預設字型", default_size: "預設字級", text_size: "文字大小",
    n_selected: "已選 %s 封", select_all: "全選", shortcuts: "鍵盤快速鍵", next_mail: "下一封",
    prev_mail: "上一封", close_clear: "關閉或清除", bigger: "放大文字", smaller: "縮小文字",
    actual_size: "預設文字大小", save_draft: "儲存草稿", add_select: "加入選取",
    range_select: "連續選取", mailbox: "信箱", writing: "撰寫", reading: "閱讀",
  },
  ja: {
    back: "戻る", ok: "OK", close: "閉じる", font_sample: "新規メールの既定のフォントです。The quick brown fox.",
    flagged: "スター付き", flag: "スターを付ける", unflag: "スターを外す", formatting: "書式", font: "フォント", font_size: "サイズ",
    size_small: "小", size_normal: "標準", size_large: "大", size_huge: "特大",
    bold: "太字", italic: "斜体", underline: "下線", strike: "取り消し線", bullets: "箇条書き",
    numbers: "番号付きリスト", quote_block: "引用", link: "リンク", link_url: "リンク先", clear_fmt: "書式をクリア",
    composing: "作成", default_font: "標準のフォント", default_size: "標準のサイズ", text_size: "文字サイズ",
    n_selected: "%s 件を選択", select_all: "すべて選択", shortcuts: "キーボードショートカット", next_mail: "次のメール",
    prev_mail: "前のメール", close_clear: "閉じる・クリア", bigger: "文字を大きく", smaller: "文字を小さく",
    actual_size: "標準の文字サイズ", save_draft: "下書きを保存", add_select: "選択に追加",
    range_select: "範囲を選択", mailbox: "メールボックス", writing: "作成", reading: "閲覧",
  },
  ko: {
    back: "뒤로", ok: "확인", close: "닫기", font_sample: "새 메일의 기본 글꼴입니다. The quick brown fox.",
    flagged: "별표편지함", flag: "별표", unflag: "별표 해제", formatting: "서식", font: "글꼴", font_size: "크기",
    size_small: "작게", size_normal: "보통", size_large: "크게", size_huge: "아주 크게",
    bold: "굵게", italic: "기울임꼴", underline: "밑줄", strike: "취소선", bullets: "글머리 기호 목록",
    numbers: "번호 목록", quote_block: "인용", link: "링크", link_url: "링크 주소", clear_fmt: "서식 지우기",
    composing: "작성", default_font: "기본 글꼴", default_size: "기본 크기", text_size: "글자 크기",
    n_selected: "%s개 선택됨", select_all: "모두 선택", shortcuts: "키보드 단축키", next_mail: "다음 메일",
    prev_mail: "이전 메일", close_clear: "닫기 또는 지우기", bigger: "글자 크게", smaller: "글자 작게",
    actual_size: "기본 글자 크기", save_draft: "임시 저장", add_select: "선택에 추가",
    range_select: "범위 선택", mailbox: "메일함", writing: "작성", reading: "읽기",
  },
  es: {
    back: "Atrás", ok: "Aceptar", close: "Cerrar", font_sample: "Así se verá el texto de sus nuevos correos.",
    flagged: "Destacados", flag: "Destacar", unflag: "Quitar destacado", formatting: "Formato", font: "Fuente", font_size: "Tamaño",
    size_small: "Pequeño", size_normal: "Normal", size_large: "Grande", size_huge: "Enorme",
    bold: "Negrita", italic: "Cursiva", underline: "Subrayado", strike: "Tachado", bullets: "Lista con viñetas",
    numbers: "Lista numerada", quote_block: "Cita", link: "Enlace", link_url: "Dirección del enlace", clear_fmt: "Borrar formato",
    composing: "Redacción", default_font: "Fuente predeterminada", default_size: "Tamaño predeterminado", text_size: "Tamaño del texto",
    n_selected: "%s seleccionados", select_all: "Seleccionar todo", shortcuts: "Atajos de teclado", next_mail: "Correo siguiente",
    prev_mail: "Correo anterior", close_clear: "Cerrar o borrar", bigger: "Texto más grande", smaller: "Texto más pequeño",
    actual_size: "Tamaño de texto predeterminado", save_draft: "Guardar borrador", add_select: "Añadir a la selección",
    range_select: "Seleccionar un rango", mailbox: "Buzón", writing: "Redactar", reading: "Lectura",
  },
  fr: {
    back: "Retour", ok: "OK", close: "Fermer", font_sample: "Voici l’apparence du texte de vos nouveaux e-mails.",
    flagged: "Suivis", flag: "Suivre", unflag: "Ne plus suivre", formatting: "Mise en forme", font: "Police", font_size: "Taille",
    size_small: "Petite", size_normal: "Normale", size_large: "Grande", size_huge: "Très grande",
    bold: "Gras", italic: "Italique", underline: "Souligné", strike: "Barré", bullets: "Liste à puces",
    numbers: "Liste numérotée", quote_block: "Citation", link: "Lien", link_url: "Adresse du lien", clear_fmt: "Effacer la mise en forme",
    composing: "Rédaction", default_font: "Police par défaut", default_size: "Taille par défaut", text_size: "Taille du texte",
    n_selected: "%s sélectionnés", select_all: "Tout sélectionner", shortcuts: "Raccourcis clavier", next_mail: "E-mail suivant",
    prev_mail: "E-mail précédent", close_clear: "Fermer ou effacer", bigger: "Agrandir le texte", smaller: "Réduire le texte",
    actual_size: "Taille de texte par défaut", save_draft: "Enregistrer le brouillon", add_select: "Ajouter à la sélection",
    range_select: "Sélectionner une plage", mailbox: "Boîte mail", writing: "Rédaction", reading: "Lecture",
  },
  de: {
    back: "Zurück", ok: "OK", close: "Schließen", font_sample: "So sieht der Text Ihrer neuen E-Mails aus.",
    flagged: "Markiert", flag: "Markieren", unflag: "Markierung entfernen", formatting: "Formatierung", font: "Schrift", font_size: "Größe",
    size_small: "Klein", size_normal: "Normal", size_large: "Groß", size_huge: "Sehr groß",
    bold: "Fett", italic: "Kursiv", underline: "Unterstrichen", strike: "Durchgestrichen", bullets: "Aufzählung",
    numbers: "Nummerierte Liste", quote_block: "Zitat", link: "Link", link_url: "Linkadresse", clear_fmt: "Formatierung entfernen",
    composing: "Verfassen", default_font: "Standardschrift", default_size: "Standardgröße", text_size: "Textgröße",
    n_selected: "%s ausgewählt", select_all: "Alle auswählen", shortcuts: "Tastenkürzel", next_mail: "Nächste E-Mail",
    prev_mail: "Vorherige E-Mail", close_clear: "Schließen oder leeren", bigger: "Text größer", smaller: "Text kleiner",
    actual_size: "Standard-Textgröße", save_draft: "Entwurf speichern", add_select: "Zur Auswahl hinzufügen",
    range_select: "Bereich auswählen", mailbox: "Postfach", writing: "Verfassen", reading: "Lesen",
  },
};
for (const [k, v] of Object.entries(MORE)) Object.assign(LANGS[k], v);

// filters, other folders, junk, new mail
const MORE2 = {
  "en": {
    junk: "Junk", not_junk: "Not junk", moved_to: "Moved to %s", move_to: "Move to…", filter: "Filter", f_unread: "Unread", f_att: "With attachments", f_clear: "Clear filter", n_new_mail: "%s new messages", notifications: "Notifications", new_mail: "New mail", on: "On", err_no_folder: "The folder %s is no longer on the server.",
    new_folder: "New folder", rename_folder: "Rename", delete_folder: "Delete folder", folder_menu: "Folder options", err_folder_name: "Give the folder a name.", err_folder_long: "That folder name is too long.", err_folder_char: "A folder name can't have %s in it.", err_folder_exists: "There is already a folder called %s.", err_folder_mail: "%s still has mail in it. Move the mail out first.", err_folder_kids: "%s has folders inside it. Delete those first.",
  },
  "zh-Hans": {
    junk: "垃圾邮件", not_junk: "不是垃圾邮件", moved_to: "已移到“%s”", move_to: "移到…", filter: "筛选", f_unread: "未读", f_att: "有附件", f_clear: "清除筛选", n_new_mail: "%s 封新邮件", notifications: "通知", new_mail: "新邮件", on: "开启", err_no_folder: "服务器上已经没有“%s”这个文件夹。",
    new_folder: "新建文件夹", rename_folder: "重命名", delete_folder: "删除文件夹", folder_menu: "文件夹选项", err_folder_name: "请给文件夹起个名字。", err_folder_long: "文件夹名字太长了。", err_folder_char: "文件夹名字里不能有 %s。", err_folder_exists: "已经有一个叫“%s”的文件夹。", err_folder_mail: "“%s”里还有邮件，请先把邮件移走。", err_folder_kids: "“%s”里还有文件夹，请先删除它们。",
  },
  "zh-Hant": {
    junk: "垃圾郵件", not_junk: "不是垃圾郵件", moved_to: "已移到「%s」", move_to: "移到…", filter: "篩選", f_unread: "未讀", f_att: "有附件", f_clear: "清除篩選", n_new_mail: "%s 封新郵件", notifications: "通知", new_mail: "新郵件", on: "開啟", err_no_folder: "伺服器上已經沒有「%s」這個檔案夾。",
    new_folder: "新增檔案夾", rename_folder: "重新命名", delete_folder: "刪除檔案夾", folder_menu: "檔案夾選項", err_folder_name: "請為檔案夾取個名稱。", err_folder_long: "檔案夾名稱太長了。", err_folder_char: "檔案夾名稱裡不能有 %s。", err_folder_exists: "已經有一個叫「%s」的檔案夾。", err_folder_mail: "「%s」裡還有郵件，請先把郵件移走。", err_folder_kids: "「%s」裡還有檔案夾，請先刪除它們。",
  },
  "ja": {
    junk: "迷惑メール", not_junk: "迷惑メールではない", moved_to: "%s に移動しました", move_to: "移動…", filter: "フィルタ", f_unread: "未開封", f_att: "添付ファイルあり", f_clear: "フィルタを解除", n_new_mail: "新着メール %s 件", notifications: "通知", new_mail: "新着メール", on: "オン", err_no_folder: "フォルダ「%s」はサーバーにありません。",
    new_folder: "新規フォルダ", rename_folder: "名前を変更", delete_folder: "フォルダを削除", folder_menu: "フォルダのオプション", err_folder_name: "フォルダ名を入力してください。", err_folder_long: "フォルダ名が長すぎます。", err_folder_char: "フォルダ名に %s は使えません。", err_folder_exists: "「%s」というフォルダはすでにあります。", err_folder_mail: "「%s」にはまだメールがあります。先にメールを移動してください。", err_folder_kids: "「%s」の中にフォルダがあります。先にそれらを削除してください。",
  },
  "ko": {
    junk: "스팸", not_junk: "스팸 아님", moved_to: "%s(으)로 이동했습니다", move_to: "이동…", filter: "필터", f_unread: "읽지 않음", f_att: "첨부 파일 있음", f_clear: "필터 지우기", n_new_mail: "새 메일 %s개", notifications: "알림", new_mail: "새 메일", on: "켬", err_no_folder: "서버에 %s 폴더가 더 이상 없습니다.",
    new_folder: "새 폴더", rename_folder: "이름 변경", delete_folder: "폴더 삭제", folder_menu: "폴더 옵션", err_folder_name: "폴더 이름을 입력하세요.", err_folder_long: "폴더 이름이 너무 깁니다.", err_folder_char: "폴더 이름에 %s 은(는) 쓸 수 없습니다.", err_folder_exists: "%s 폴더가 이미 있습니다.", err_folder_mail: "%s 폴더에 아직 메일이 있습니다. 먼저 메일을 옮기세요.", err_folder_kids: "%s 폴더 안에 폴더가 있습니다. 먼저 그 폴더를 삭제하세요.",
  },
  "es": {
    junk: "Correo no deseado", not_junk: "No es correo no deseado", moved_to: "Movido a %s", move_to: "Mover a…", filter: "Filtrar", f_unread: "No leídos", f_att: "Con adjuntos", f_clear: "Quitar filtro", n_new_mail: "%s correos nuevos", notifications: "Notificaciones", new_mail: "Correo nuevo", on: "Sí", err_no_folder: "La carpeta %s ya no está en el servidor.",
    new_folder: "Nueva carpeta", rename_folder: "Cambiar nombre", delete_folder: "Eliminar carpeta", folder_menu: "Opciones de carpeta", err_folder_name: "Ponle un nombre a la carpeta.", err_folder_long: "El nombre de la carpeta es demasiado largo.", err_folder_char: "El nombre de una carpeta no puede contener %s.", err_folder_exists: "Ya hay una carpeta llamada %s.", err_folder_mail: "%s todavía tiene correos. Muévelos primero.", err_folder_kids: "%s tiene carpetas dentro. Elimínalas primero.",
  },
  "fr": {
    junk: "Indésirables", not_junk: "Pas indésirable", moved_to: "Déplacé vers %s", move_to: "Déplacer vers…", filter: "Filtrer", f_unread: "Non lus", f_att: "Avec pièces jointes", f_clear: "Effacer le filtre", n_new_mail: "%s nouveaux e-mails", notifications: "Notifications", new_mail: "Nouveaux e-mails", on: "Activé", err_no_folder: "Le dossier %s n’est plus sur le serveur.",
    new_folder: "Nouveau dossier", rename_folder: "Renommer", delete_folder: "Supprimer le dossier", folder_menu: "Options du dossier", err_folder_name: "Donnez un nom au dossier.", err_folder_long: "Ce nom de dossier est trop long.", err_folder_char: "Un nom de dossier ne peut pas contenir %s.", err_folder_exists: "Il existe déjà un dossier nommé %s.", err_folder_mail: "%s contient encore des e-mails. Déplacez-les d’abord.", err_folder_kids: "%s contient des dossiers. Supprimez-les d’abord.",
  },
  "de": {
    junk: "Spam", not_junk: "Kein Spam", moved_to: "In %s verschoben", move_to: "Verschieben nach…", filter: "Filtern", f_unread: "Ungelesen", f_att: "Mit Anhängen", f_clear: "Filter löschen", n_new_mail: "%s neue E-Mails", notifications: "Mitteilungen", new_mail: "Neue E-Mails", on: "Ein", err_no_folder: "Der Ordner %s ist nicht mehr auf dem Server.",
    new_folder: "Neuer Ordner", rename_folder: "Umbenennen", delete_folder: "Ordner löschen", folder_menu: "Ordneroptionen", err_folder_name: "Gib dem Ordner einen Namen.", err_folder_long: "Der Ordnername ist zu lang.", err_folder_char: "Ein Ordnername darf %s nicht enthalten.", err_folder_exists: "Es gibt bereits einen Ordner namens %s.", err_folder_mail: "%s enthält noch E-Mails. Verschiebe sie zuerst.", err_folder_kids: "%s enthält Ordner. Lösche diese zuerst.",
  },
};
for (const [k, v] of Object.entries(MORE2)) Object.assign(LANGS[k], v);

// links and pictures inside a mail, a whole folder read, all attachments saved
const MORE3 = {
  "en": { open_link: "Open link", copy_link: "Copy link address", copy_addr: "Copy address", open_picture: "Open picture", copied: "Copied", read_all: "Mark all as read", save_all: "Save all to Downloads", saved_n: "%s files saved to Downloads" },
  "zh-Hans": { open_link: "打开链接", copy_link: "复制链接地址", copy_addr: "复制邮箱地址", open_picture: "打开图片", copied: "已复制", read_all: "全部标为已读", save_all: "全部存到“下载”", saved_n: "%s 个文件已存到“下载”" },
  "zh-Hant": { open_link: "打開連結", copy_link: "拷貝連結位址", copy_addr: "拷貝郵件位址", open_picture: "打開圖片", copied: "已拷貝", read_all: "全部標為已讀", save_all: "全部儲存到「下載項目」", saved_n: "%s 個檔案已儲存到「下載項目」" },
  "ja": { open_link: "リンクを開く", copy_link: "リンクのアドレスをコピー", copy_addr: "アドレスをコピー", open_picture: "画像を開く", copied: "コピーしました", read_all: "すべて既読にする", save_all: "すべてダウンロードに保存", saved_n: "%s 個のファイルをダウンロードに保存しました" },
  "ko": { open_link: "링크 열기", copy_link: "링크 주소 복사", copy_addr: "주소 복사", open_picture: "이미지 열기", copied: "복사했습니다", read_all: "모두 읽음으로 표시", save_all: "모두 다운로드에 저장", saved_n: "파일 %s개를 다운로드에 저장했습니다" },
  "es": { open_link: "Abrir enlace", copy_link: "Copiar dirección del enlace", copy_addr: "Copiar dirección", open_picture: "Abrir imagen", copied: "Copiado", read_all: "Marcar todo como leído", save_all: "Guardar todo en Descargas", saved_n: "%s archivos guardados en Descargas" },
  "fr": { open_link: "Ouvrir le lien", copy_link: "Copier l’adresse du lien", copy_addr: "Copier l’adresse", open_picture: "Ouvrir l’image", copied: "Copié", read_all: "Tout marquer comme lu", save_all: "Tout enregistrer dans Téléchargements", saved_n: "%s fichiers enregistrés dans Téléchargements" },
  "de": { open_link: "Link öffnen", copy_link: "Linkadresse kopieren", copy_addr: "Adresse kopieren", open_picture: "Bild öffnen", copied: "Kopiert", read_all: "Alle als gelesen markieren", save_all: "Alle in Downloads sichern", saved_n: "%s Dateien in Downloads gesichert" },
};
for (const [k, v] of Object.entries(MORE3)) Object.assign(LANGS[k], v);

// macOS has this app's notifications switched off: say so in Settings, with the way to the switch
const MORE4 = {
  "en": { notice_off: "macOS has notifications turned off for Ragdoll Mail. Turn on “Allow notifications” in System Settings.", notice_open: "Open System Settings" },
  "zh-Hans": { notice_off: "macOS 里 Ragdoll Mail 的通知是关着的。请在“系统设置”里打开“允许通知”。", notice_open: "打开系统设置" },
  "zh-Hant": { notice_off: "macOS 裡 Ragdoll Mail 的通知是關閉的。請在「系統設定」裡打開「允許通知」。", notice_open: "打開系統設定" },
  "ja": { notice_off: "macOS で Ragdoll Mail の通知がオフになっています。「システム設定」で「通知を許可」をオンにしてください。", notice_open: "システム設定を開く" },
  "ko": { notice_off: "macOS에서 Ragdoll Mail의 알림이 꺼져 있습니다. ‘시스템 설정’에서 ‘알림 허용’을 켜세요.", notice_open: "시스템 설정 열기" },
  "es": { notice_off: "macOS tiene desactivadas las notificaciones de Ragdoll Mail. Activa «Permitir notificaciones» en Ajustes del Sistema.", notice_open: "Abrir Ajustes del Sistema" },
  "fr": { notice_off: "macOS a désactivé les notifications de Ragdoll Mail. Activez « Autoriser les notifications » dans Réglages Système.", notice_open: "Ouvrir Réglages Système" },
  "de": { notice_off: "macOS hat die Mitteilungen für Ragdoll Mail ausgeschaltet. Schalte „Mitteilungen erlauben“ in den Systemeinstellungen ein.", notice_open: "Systemeinstellungen öffnen" },
};
for (const [k, v] of Object.entries(MORE4)) Object.assign(LANGS[k], v);

// the heading over the owner's own folders, and the arrow that folds them
const MORE5 = {
  "en": { my_folders: "Folders", fold: "Show or hide folders" },
  "zh-Hans": { my_folders: "文件夹", fold: "展开或收起文件夹" },
  "zh-Hant": { my_folders: "檔案夾", fold: "展開或收合檔案夾" },
  "ja": { my_folders: "フォルダ", fold: "フォルダを表示または隠す" },
  "ko": { my_folders: "폴더", fold: "폴더 펼치기 또는 접기" },
  "es": { my_folders: "Carpetas", fold: "Mostrar u ocultar carpetas" },
  "fr": { my_folders: "Dossiers", fold: "Afficher ou masquer les dossiers" },
  "de": { my_folders: "Ordner", fold: "Ordner ein- oder ausblenden" },
};
for (const [k, v] of Object.entries(MORE5)) Object.assign(LANGS[k], v);

// the button and shortcut that hide and show the sidebar
const MORE6 = {
  "en": { side_hide: "Hide sidebar", side_show: "Show sidebar", side_toggle: "Show or hide sidebar" },
  "zh-Hans": { side_hide: "收起侧栏", side_show: "显示侧栏", side_toggle: "显示或收起侧栏" },
  "zh-Hant": { side_hide: "收合側欄", side_show: "顯示側欄", side_toggle: "顯示或收合側欄" },
  "ja": { side_hide: "サイドバーを隠す", side_show: "サイドバーを表示", side_toggle: "サイドバーの表示/非表示" },
  "ko": { side_hide: "사이드바 숨기기", side_show: "사이드바 보기", side_toggle: "사이드바 보기 또는 숨기기" },
  "es": { side_hide: "Ocultar barra lateral", side_show: "Mostrar barra lateral", side_toggle: "Mostrar u ocultar la barra lateral" },
  "fr": { side_hide: "Masquer la barre latérale", side_show: "Afficher la barre latérale", side_toggle: "Afficher ou masquer la barre latérale" },
  "de": { side_hide: "Seitenleiste ausblenden", side_show: "Seitenleiste einblenden", side_toggle: "Seitenleiste ein- oder ausblenden" },
};
for (const [k, v] of Object.entries(MORE6)) Object.assign(LANGS[k], v);

// the ragdoll command, hand-offs from assistants
const MORE7 = {
  "en": { cli: "Command line", cli_command: "The ragdoll command", cli_install: "Install", cli_reinstall: "Install again",
    cli_done: "Installed: %s.", cli_kept: "%s is your own; it was left as it is.", cli_new_terminal: "Open a new terminal window to use it.",
    draft_ready: "Draft ready: %s" },
  "zh-Hans": { cli: "命令行", cli_command: "ragdoll 命令", cli_install: "安装", cli_reinstall: "重新安装",
    cli_done: "已安装：%s。", cli_kept: "%s 是你自己建的，没有改动。", cli_new_terminal: "新开一个终端窗口就能用。",
    draft_ready: "草稿写好了：%s" },
  "zh-Hant": { cli: "命令列", cli_command: "ragdoll 命令", cli_install: "安裝", cli_reinstall: "重新安裝",
    cli_done: "已安裝：%s。", cli_kept: "%s 是你自己建的，沒有改動。", cli_new_terminal: "新開一個終端機視窗就能用。",
    draft_ready: "草稿寫好了：%s" },
  "ja": { cli: "コマンドライン", cli_install: "インストール", cli_reinstall: "再インストール", draft_ready: "下書きができました：%s" },
  "ko": { cli: "명령줄", cli_install: "설치", cli_reinstall: "다시 설치", draft_ready: "초안 준비됨: %s" },
  "es": { cli: "Línea de comandos", cli_install: "Instalar", cli_reinstall: "Instalar de nuevo", draft_ready: "Borrador listo: %s" },
  "fr": { cli: "Ligne de commande", cli_install: "Installer", cli_reinstall: "Réinstaller", draft_ready: "Brouillon prêt : %s" },
  "de": { cli: "Befehlszeile", cli_install: "Installieren", cli_reinstall: "Erneut installieren", draft_ready: "Entwurf fertig: %s" },
};
for (const [k, v] of Object.entries(MORE7)) Object.assign(LANGS[k], v);

// the warning banner over the list: what it means, and a button that names the fix
const MORE8 = {
  "en": { b_pw_title: "No password saved", b_pw_sub: "New mail can't come in until it is.", b_pw_btn: "Add password",
    b_acct_title: "No account yet", b_acct_btn: "Add account", b_signin_title: "Sign-in failed",
    b_signin_sub: "Check the address and password.", b_signin_btn: "Check", b_fix: "Settings" },
  "zh-Hans": { b_pw_title: "还没有保存密码", b_pw_sub: "保存后才能收到新邮件。", b_pw_btn: "添加密码",
    b_acct_title: "还没有账户", b_acct_btn: "添加账户", b_signin_title: "登录失败",
    b_signin_sub: "请检查邮箱地址和密码。", b_signin_btn: "检查", b_fix: "设置" },
  "zh-Hant": { b_pw_title: "尚未儲存密碼", b_pw_sub: "儲存後才能收到新郵件。", b_pw_btn: "新增密碼",
    b_acct_title: "尚未有帳號", b_acct_btn: "新增帳號", b_signin_title: "登入失敗",
    b_signin_sub: "請檢查郵件地址和密碼。", b_signin_btn: "檢查", b_fix: "設定" },
  "ja": { b_pw_title: "パスワードが保存されていません", b_pw_btn: "パスワードを追加", b_signin_title: "サインインできません", b_fix: "設定" },
  "ko": { b_pw_title: "저장된 비밀번호가 없습니다", b_pw_btn: "비밀번호 추가", b_signin_title: "로그인 실패", b_fix: "설정" },
  "es": { b_pw_title: "No hay contraseña guardada", b_pw_btn: "Añadir contraseña", b_signin_title: "No se pudo iniciar sesión", b_fix: "Ajustes" },
  "fr": { b_pw_title: "Aucun mot de passe enregistré", b_pw_btn: "Ajouter", b_signin_title: "Échec de la connexion", b_fix: "Réglages" },
  "de": { b_pw_title: "Kein Passwort gespeichert", b_pw_btn: "Passwort hinzufügen", b_signin_title: "Anmeldung fehlgeschlagen", b_fix: "Einstellungen" },
};
for (const [k, v] of Object.entries(MORE8)) Object.assign(LANGS[k], v);
const MORE9 = {
  "en": { unsub: "Unsubscribe", unsub_title: "Unsubscribe from %s?", unsub_one: "You'll stop getting these mails. The app tells the sender for you.",
    unsub_web: "The sender's unsubscribe page opens in your browser.", unsub_mail: "A mail asking to unsubscribe opens. Send it to finish.",
    unsub_done: "Unsubscribed from %s", all_day: "All day", invite: "Invitation", inv_cancelled: "Cancelled", inv_from: "From %s", add_cal: "Add to Calendar" },
  "zh-Hans": { unsub: "退订", unsub_title: "退订 %s？", unsub_one: "以后不会再收到这类邮件。应用会替你通知发件方。",
    unsub_web: "发件方的退订页面会在浏览器里打开。", unsub_mail: "会打开一封退订邮件，发出后即完成。",
    unsub_done: "已退订 %s", all_day: "全天", invite: "会议邀请", inv_cancelled: "已取消", inv_from: "发起人：%s", add_cal: "添加到日历" },
  "zh-Hant": { unsub: "取消訂閱", unsub_title: "取消訂閱 %s？", unsub_one: "以後不會再收到這類郵件。應用程式會替你通知寄件方。",
    unsub_web: "寄件方的取消訂閱頁面會在瀏覽器中開啟。", unsub_mail: "會開啟一封取消訂閱郵件，寄出後即完成。",
    unsub_done: "已取消訂閱 %s", all_day: "全天", invite: "會議邀請", inv_cancelled: "已取消", inv_from: "發起人：%s", add_cal: "加入行事曆" },
  "ja": { unsub: "配信停止", unsub_title: "%s の配信を停止しますか？", unsub_one: "今後このメールは届きません。送信元にはアプリが知らせます。",
    unsub_web: "送信元の配信停止ページがブラウザで開きます。", unsub_mail: "配信停止のメールが開きます。送信すると完了します。",
    unsub_done: "%s の配信を停止しました", all_day: "終日", invite: "招待", inv_cancelled: "キャンセル", inv_from: "主催：%s", add_cal: "カレンダーに追加" },
  "ko": { unsub: "구독 취소", unsub_title: "%s 구독을 취소할까요?", unsub_one: "이런 메일을 더 받지 않습니다. 앱이 보낸 쪽에 알려 줍니다.",
    unsub_web: "보낸 쪽의 구독 취소 페이지가 브라우저에서 열립니다.", unsub_mail: "구독 취소 메일이 열립니다. 보내면 끝납니다.",
    unsub_done: "%s 구독을 취소했습니다", all_day: "종일", invite: "초대", inv_cancelled: "취소됨", inv_from: "주최: %s", add_cal: "캘린더에 추가" },
  "es": { unsub: "Cancelar suscripción", unsub_title: "¿Cancelar la suscripción a %s?", unsub_one: "Dejarás de recibir estos correos. La app avisa al remitente.",
    unsub_web: "La página para darte de baja se abre en el navegador.", unsub_mail: "Se abre un correo para darte de baja. Envíalo para terminar.",
    unsub_done: "Suscripción a %s cancelada", all_day: "Todo el día", invite: "Invitación", inv_cancelled: "Cancelada", inv_from: "De %s", add_cal: "Añadir al calendario" },
  "fr": { unsub: "Se désabonner", unsub_title: "Se désabonner de %s ?", unsub_one: "Vous ne recevrez plus ces e-mails. L'app prévient l'expéditeur.",
    unsub_web: "La page de désabonnement s'ouvre dans le navigateur.", unsub_mail: "Un e-mail de désabonnement s'ouvre. Envoyez-le pour terminer.",
    unsub_done: "Désabonné de %s", all_day: "Toute la journée", invite: "Invitation", inv_cancelled: "Annulée", inv_from: "De %s", add_cal: "Ajouter au calendrier" },
  "de": { unsub: "Abbestellen", unsub_title: "%s abbestellen?", unsub_one: "Diese Mails kommen nicht mehr. Die App sagt es dem Absender.",
    unsub_web: "Die Abmeldeseite des Absenders öffnet sich im Browser.", unsub_mail: "Eine Abmelde-Mail öffnet sich. Senden Sie sie, um fertig zu werden.",
    unsub_done: "%s abbestellt", all_day: "Ganztägig", invite: "Einladung", inv_cancelled: "Abgesagt", inv_from: "Von %s", add_cal: "Zum Kalender hinzufügen" },
};
for (const [k, v] of Object.entries(MORE9)) Object.assign(LANGS[k], v);

// 0.11 group A_COMPOSE: new strings for this group only
const MORE_A_COMPOSE = {
  "en": {
  },
  "zh-Hans": {
  },
  "zh-Hant": {
  },
  "ja": {
  },
  "ko": {
  },
  "es": {
  },
  "fr": {
  },
  "de": {
  },
};
for (const [k, v] of Object.entries(MORE_A_COMPOSE)) Object.assign(LANGS[k], v);

// 0.11 group B_SEND: new strings for this group only
const MORE_B_SEND = {
  "en": {
  },
  "zh-Hans": {
  },
  "zh-Hant": {
  },
  "ja": {
  },
  "ko": {
  },
  "es": {
  },
  "fr": {
  },
  "de": {
  },
};
for (const [k, v] of Object.entries(MORE_B_SEND)) Object.assign(LANGS[k], v);

// 0.11 group C1_LIST: new strings for this group only
const MORE_C1_LIST = {
  "en": {
  },
  "zh-Hans": {
  },
  "zh-Hant": {
  },
  "ja": {
  },
  "ko": {
  },
  "es": {
  },
  "fr": {
  },
  "de": {
  },
};
for (const [k, v] of Object.entries(MORE_C1_LIST)) Object.assign(LANGS[k], v);

// 0.11 group C2_READ: new strings for this group only
const MORE_C2_READ = {
  "en": {
  },
  "zh-Hans": {
  },
  "zh-Hant": {
  },
  "ja": {
  },
  "ko": {
  },
  "es": {
  },
  "fr": {
  },
  "de": {
  },
};
for (const [k, v] of Object.entries(MORE_C2_READ)) Object.assign(LANGS[k], v);

// 0.11 group D_SYNC: new strings for this group only
const MORE_D_SYNC = {
  "en": {
  },
  "zh-Hans": {
  },
  "zh-Hant": {
  },
  "ja": {
  },
  "ko": {
  },
  "es": {
  },
  "fr": {
  },
  "de": {
  },
};
for (const [k, v] of Object.entries(MORE_D_SYNC)) Object.assign(LANGS[k], v);

// 0.11 group E_FOLDERS: new strings for this group only
const MORE_E_FOLDERS = {
  "en": {
  },
  "zh-Hans": {
  },
  "zh-Hant": {
  },
  "ja": {
  },
  "ko": {
  },
  "es": {
  },
  "fr": {
  },
  "de": {
  },
};
for (const [k, v] of Object.entries(MORE_E_FOLDERS)) Object.assign(LANGS[k], v);

// 0.11 group F_INVITES: new strings for this group only
const MORE_F_INVITES = {
  "en": {
  },
  "zh-Hans": {
  },
  "zh-Hant": {
  },
  "ja": {
  },
  "ko": {
  },
  "es": {
  },
  "fr": {
  },
  "de": {
  },
};
for (const [k, v] of Object.entries(MORE_F_INVITES)) Object.assign(LANGS[k], v);

