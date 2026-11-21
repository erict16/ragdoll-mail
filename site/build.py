#!/usr/bin/env python3
"""Make the site's pages: python3 site/build.py  (the home page and the Exmail guide, English and
Chinese, and sitemap.xml).
Both languages share the layout; only the words differ, so the pages cannot drift apart."""
import html, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = "https://erict16.github.io/ragdoll-mail/"
REPO = "https://github.com/erict16/ragdoll-mail"
DL = REPO + "/releases/latest/download/"

ICONS = {
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "lock": '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    "undo": '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 5.5 5.5a5.5 5.5 0 0 1-5.5 5.5H11"/>',
    "pen": '<path d="M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.375 2.625a1 1 0 0 1 3 3l-9.013 9.014a2 2 0 0 1-.853.505l-2.873.84a.5.5 0 0 1-.62-.62l.84-2.873a2 2 0 0 1 .506-.852z"/>',
    "languages": '<path d="m5 8 6 6"/><path d="m4 14 6-6 2-3"/><path d="M2 5h12"/><path d="M7 2h1"/><path d="m22 22-5-10-5 10"/><path d="M14 18h6"/>',
    "keyboard": '<path d="M10 8h.01"/><path d="M12 12h.01"/><path d="M14 8h.01"/><path d="M16 12h.01"/><path d="M18 8h.01"/><path d="M6 8h.01"/><path d="M7 16h10"/><path d="M8 12h.01"/><rect width="20" height="16" x="2" y="4" rx="2"/>',
    "check": '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
    "terminal": '<polyline points="4 17 10 11 4 5"/><line x1="12" x2="20" y1="19" y2="19"/>',
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/>',
    "chevron": '<path d="m6 9 6 6 6-6"/>',
    "file-text": '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
    "shield-check": '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
    "send": '<path d="M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z"/><path d="m21.854 2.147-10.94 10.939"/>',
    "key": '<path d="m15.5 7.5 2.3 2.3a1 1 0 0 0 1.4 0l2.1-2.1a1 1 0 0 0 0-1.4L19 4"/><path d="m21 2-9.6 9.6"/><circle cx="7.5" cy="15.5" r="5.5"/>',
    "volume-2": '<path d="M11 4.702a.705.705 0 0 0-1.203-.498L6.413 7.587A1.4 1.4 0 0 1 5.416 8H3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.416a1.4 1.4 0 0 1 .997.413l3.383 3.384A.705.705 0 0 0 11 19.298z"/><path d="M16 9a5 5 0 0 1 0 6"/><path d="M19.364 18.364a9 9 0 0 0 0-12.728"/>',
    "volume-x": '<path d="M11 4.702a.705.705 0 0 0-1.203-.498L6.413 7.587A1.4 1.4 0 0 1 5.416 8H3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.416a1.4 1.4 0 0 1 .997.413l3.383 3.384A.705.705 0 0 0 11 19.298z"/><line x1="22" x2="16" y1="9" y2="15"/><line x1="16" x2="22" y1="9" y2="15"/>',
}


def icon(name):
    return '<svg class="i" viewBox="0 0 24 24" aria-hidden="true">%s</svg>' % ICONS[name]


EN = {
    "lang": "en", "path": "", "other": "zh/", "other_name": "简体中文", "hreflang": "zh-Hans",
    "title": "Ragdoll Mail: the free mail app your AI agent can use, for Mac and Windows",
    "desc": "A free, open-source mail app for Mac and Windows with a command line built in. Claude Code, Codex and "
            "other agents can search your mail and draft replies, and you approve every send. Local SQLite search, "
            "any IMAP mailbox.",
    "nav": ["For AI agents", "Why it's fast", "Compare", "Questions"], "download": "Download",
    "pill": ["Free", "Open source", "Mac and Windows"],
    "h1": "The mail app your AI agent <em>can actually use</em>.",
    "lead": "Ragdoll Mail is a desktop mail app with a command line built in. Claude Code, Codex or any agent that "
            "runs commands can search your mailbox and write replies for you. Every draft shows up in the app, and "
            "nothing goes out until you press Send.",
    "mac": ["Download for Mac", "Apple silicon"], "win": ["Download for Windows", "10 and 11"],
    "first": "Not signed by Apple or Microsoft yet. The first time, choose Open Anyway (Mac: System Settings → "
             "Privacy &amp; Security) or Run anyway (Windows: More info).",
    "demo": "en", "demo_name": "Ragdoll Mail in 35 seconds", "demo_len": "PT35S",
    "shot_alt": "Ragdoll Mail in use: an AI agent in a terminal writes a reply with the ragdoll command, the draft "
                "opens in the app, the send is undone and set for tomorrow morning, and search finds mail as you type",
    "sound": ["Sound on", "Sound off"],

    "y_kick": "Why I built it",
    "y_h2": "I wanted AI to help with my email. Nothing out there fit.",
    "y_p": [
        "I deal with a lot of work email, and I wanted Claude Code to help me answer it. The good AI mail apps are "
        "subscriptions, usually $25 to $30 a month, and most of them only work with Gmail or Outlook. My work "
        "mailbox is on Tencent Exmail, so they were out before I could even try them.",
        "Command-line mail tools such as Himalaya are free, but they hand every search to the mail server. Each "
        "search means a trip over the network, and it gets slower as the mailbox grows. Some servers barely search "
        "at all. Mine ignored the words completely and sent back the whole folder, all 5,044 mails, for anything I "
        "typed.",
        "So I built the tool I wanted: a normal mail app for me and a command line for my agent, both searching "
        "the same index on my own computer.",
    ],
    "y_sign": "Eric Tan, who made Ragdoll Mail",

    "a_kick": "For AI agents", "a_h2": "Your agent writes the draft, and you decide whether it goes out.",
    "a_sub": "The <code>ragdoll</code> command is installed from the app in one click (Settings → Command line). "
             "Every command has a <code>--json</code> option, and <code>ragdoll --help</code> lists them all, so "
             "an agent can learn it on its own.",
    "a_pts": [
        ("file-text", "Real drafts in your real mailbox", "ragdoll draft saves the reply in your Drafts folder, "
         "with your signature and the earlier mails quoted. You can open it in the app, on your phone or in any "
         "other mail app."),
        ("shield-check", "Checked before it can go", "ragdoll check catches an empty subject, a mail that says "
         "“attached” with nothing attached, a [Name] left in the text, and garbled characters."),
        ("send", "Nothing is sent without you", "Sending needs an explicit yes, and a draft that has already gone out "
         "cannot be sent again by mistake."),
        ("key", "No API key, no OAuth app, no quota", "It talks plain IMAP and SMTP to your own mail server. The "
         "password stays in the system keychain and is never printed."),
    ],
    "a_guide": "Read the command-line guide",
    "term": [("you", "Reply to Jane and attach the signed quote."),
             ("$", "ragdoll search jane quote --json"),
             ("$", "ragdoll draft --reply inbox:312 --body reply.html --attach Quote.pdf"),
             ("$", "ragdoll check drafts:14 --reply"),
             ("ok", "CHECK OK"),
             ("$", "ragdoll open drafts:14"),
             ("agent", "The draft is open in Ragdoll Mail. Send it when you are happy.")],

    "s_kick": "Why it's fast", "s_h2": "Search never leaves your computer.",
    "s_sub": "Ragdoll Mail keeps a full-text index of your mail in SQLite on your own disk. Tools that rely on the "
             "server have to connect, sign in and wait for the server each time you search.",
    "lanes": [
        ("Ragdoll Mail", ["Your search", "SQLite index on your disk", "Results"], "6 ms"),
        ("Server search", ["Your search", "Internet", "Sign in", "Mail server searches", "Internet", "Results"],
         "about 1 s"),
    ],
    "bars_h": "One search from the command line, on a real inbox of 5,044 mails",
    "bars": [("Ragdoll Mail, local SQLite", 0.0063, "0.006 s", "989 mails that contain the word"),
             ("Search on the mail server (IMAP)", 1.03, "1.03 s", "5,044 mails: the whole folder")],
    "bars_note": "Measured on 21 November 2026 on a MacBook, with a Tencent Exmail inbox of 5,044 mails and the word "
                 "“invoice”. The server search opened a new connection and sent IMAP SEARCH, which is what a "
                 "command-line tool does on every run: 0.9 s to sign in, 0.13 s to search. Times change with the "
                 "server and the network. A two-character Chinese word takes longer on the local side, about 0.08 s.",

    "c_kick": "Compare", "c_h2": "How it compares with AI mail apps and command-line tools.",
    "c_cols": ["", "Ragdoll Mail", "Superhuman", "Shortwave", "Himalaya", "Apple Mail, Outlook"],
    "c_rows": [
        ("Price", "Free", "From about $25 a month", "Free plan with AI limits, paid plans", "Free", "Free"),
        ("Mailboxes", "Any IMAP mailbox", "Gmail and Outlook", "Mainly Gmail", "Any IMAP mailbox", "Most mailboxes"),
        ("Desktop app", "Yes", "Yes", "Yes", "No, terminal only", "Yes"),
        ("Command line your agent can use", "Yes", "No", "No", "Yes", "No"),
        ("Where search runs", "Your computer", "Online, through Gmail or Outlook", "Online, on Shortwave's servers",
         "On the mail server", "Depends on the app"),
        ("Open source", "Yes", "No", "No", "Yes", "No"),
    ],
    "c_note": "From each product's public pages, November 2026. If something here is wrong or out of date, "
              "open an issue on GitHub and I will fix it.",
    "c_more": "More comparisons, including Foxmail, Thunderbird and Spark",

    "f_kick": "Also a complete mail app", "f_h2": "Good enough to use every day, even without AI.",
    "f": [
        ("search", "Every word, every mail, at once", "Subjects, names, file names and the full text, in English, "
         "Chinese, Japanese and Korean. It still works with no internet."),
        ("lock", "Your mail stays with you", "The app talks only to your own mail server. There is no cloud in "
         "between and no account with us."),
        ("undo", "Hard to send a mistake", "You have 30 seconds to take a mail back. It also stops you when you wrote "
         "“attached” and attached nothing."),
        ("pen", "Write the way you like", "Fonts, lists, links and your signature. Send now, tonight, or Monday at "
         "nine."),
        ("languages", "Chinese mail that reads right", "Names and file names from older Chinese mail systems show "
         "up as they should, not as broken characters."),
        ("keyboard", "A key for everything", "C writes a mail, R replies, E archives. Press ? to see them all."),
        ("check", "Nothing changes in your mailbox", "It uses the same folders as your webmail and your phone, so "
         "they keep working as before."),
    ],
    "route": ["Your computer", "Your mail server", "No other server in between"],
    "sending": "Sending…", "undo": "Undo", "warn": "You wrote “attached”, but nothing is attached.",
    "w_kick": "Works with", "w_h2": "The mailbox you already have.",
    "w": ["Gmail", "iCloud", "Fastmail", "Tencent Exmail", "QQ Mail", "163 Mail", "Any IMAP mailbox"],
    "q_kick": "Questions", "q_h2": "Good to know.",
    "q": [
        ("Which AI agents work with it?",
         "Any agent that can run shell commands, such as Claude Code, Codex, Cursor or Gemini CLI. The agent calls "
         "the ragdoll command the same way you would in a terminal."),
        ("Do I need an API key or a paid plan?",
         "No. Ragdoll Mail signs in to your mailbox over IMAP and SMTP, like any mail app. There is no API key to "
         "create, no OAuth app to register and no usage limit."),
        ("Can my agent send mail without asking me?",
         "Not by accident. The send command refuses to run without an explicit yes, and the setup we suggest tells "
         "agents to ask you first. Most people let the agent write the draft and press Send themselves."),
        ("Why not just use the mail server's search?",
         "Every server search is a round trip over the network, and it slows down as the mailbox grows. Some "
         "servers hardly search at all. A local index answers in milliseconds and works offline."),
        ("Is my mail safe?", "Your mail is stored on your computer and on your own mail server, and nowhere else. "
         "The app sends nothing to us. We do not run a server."),
        ("Is it really free?", "Yes. There are no ads, no subscription and no account. The code is open source under "
         "the MIT license, so anyone can check what it does."),
    ],
    "e_h2": "Give your agent a mailbox it can work with.", "e_sub": "Free and open source. No account, no ads.",
    "foot": ["Source code", "Command line", "Report a problem", "Tencent Exmail setup", "Compare mail apps"],
}

ZH = dict(EN, **{
    "lang": "zh-Hans", "path": "zh/", "og": "og-zh.png", "other": "../", "other_name": "English", "hreflang": "en",
    "title": "Ragdoll Mail：AI 助手也能用的免费邮件软件（Mac / Windows）",
    "desc": "免费开源的 Mac 和 Windows 邮件软件，自带命令行。Claude Code、Codex 这类 AI 助手可以帮你搜邮件、写回复，"
            "每一封都要你确认才会发出。本地 SQLite 搜索，支持任何 IMAP 邮箱。",
    "nav": ["AI 助手", "为什么快", "对比", "常见问题"], "download": "下载",
    "pill": ["免费", "开源", "Mac 和 Windows"],
    "h1": "让 AI 助手<em>真正用得上</em>的邮件软件。",
    "lead": "Ragdoll Mail 是一个桌面邮件软件，自带命令行。Claude Code、Codex，或者任何能跑命令的 AI，都可以帮你搜邮件、"
            "写回复。草稿会直接出现在软件里，你不点发送，就什么都不会发出去。",
    "mac": ["下载 Mac 版", "M 系列芯片"], "win": ["下载 Windows 版", "Windows 10 / 11"],
    "first": "还没有苹果和微软的签名。第一次打开时：Mac 在 系统设置 → 隐私与安全性 里点“仍要打开”；Windows 点“更多信息 → 仍要运行”。",
    "demo": "zh", "demo_name": "30 秒看懂 Ragdoll Mail", "demo_len": "PT33S",
    "shot_alt": "Ragdoll Mail 使用演示：AI 助手在终端里用 ragdoll 命令写好回复，草稿在软件里打开；撤销发送后改成明天上午发；"
                "最后边打字边搜到邮件",
    "sound": ["打开声音", "关闭声音"],

    "y_kick": "为什么做它",
    "y_h2": "我想让 AI 帮我回邮件，可一直没找到合适的工具。",
    "y_p": [
        "我每天要处理很多工作邮件，一直想让 Claude Code 帮我回。可做得好的 AI 邮件软件基本都是按月收费，一个月 25 到 30 "
        "美元，而且大多只支持 Gmail 和 Outlook。我的工作邮箱是腾讯企业邮箱，连试的机会都没有。",
        "命令行邮件工具倒是有免费的，比如 Himalaya，但它每次搜索都交给邮件服务器去做。每搜一次都要走一趟网络，邮件越多越慢。"
        "有的服务器甚至根本不好好搜：我的邮箱不管输入什么词，都把整个文件夹的 5,044 封邮件原样返回。",
        "所以我干脆自己做了一个：我用的是一个普通的邮件软件，AI 用的是一套命令行，两边搜的是同一份索引，就放在我自己的电脑上。",
    ],
    "y_sign": "Eric Tan，Ragdoll Mail 作者",

    "a_kick": "给 AI 助手", "a_h2": "AI 来写草稿，发不发由你决定。",
    "a_sub": "<code>ragdoll</code> 命令在软件里一键安装（设置 → 命令行）。每条命令都有 <code>--json</code> 输出，"
             "<code>ragdoll --help</code> 列出了全部用法，AI 自己看一遍就会用。",
    "a_pts": [
        ("file-text", "草稿就存在你的邮箱里", "ragdoll draft 会把回复存进你邮箱的草稿箱，签名和之前的往来邮件都带上。"
         "在软件里、手机上或者别的邮件软件里都能打开。"),
        ("shield-check", "发之前先检查一遍", "ragdoll check 会拦下这些问题：标题是空的，正文说了“附件”却没加附件，"
         "还留着 [姓名] 这样的占位符，或者有乱码。"),
        ("send", "你不点头，就不会发", "发送必须明确确认。一封草稿发出去以后，不会因为手滑再发第二次。"),
        ("key", "不用 API Key，不用 OAuth，没有调用额度", "它直接用 IMAP 和 SMTP 连你自己的邮件服务器。"
         "密码存在系统钥匙串里，任何时候都不会显示出来。"),
    ],
    "a_guide": "看命令行说明（英文）",
    "term": [("you", "回复 Jane，附上签好的报价单。"),
             ("$", "ragdoll search jane quote --json"),
             ("$", "ragdoll draft --reply inbox:312 --body reply.html --attach Quote.pdf"),
             ("$", "ragdoll check drafts:14 --reply"),
             ("ok", "CHECK OK"),
             ("$", "ragdoll open drafts:14"),
             ("agent", "草稿已经在 Ragdoll Mail 里打开了，你看好了就发。")],

    "s_kick": "为什么快", "s_h2": "搜索全在你自己的电脑上完成。",
    "s_sub": "Ragdoll Mail 用 SQLite 在你的硬盘上给邮件建了一份全文索引。靠服务器搜索的工具就不一样了，每搜一次，"
             "都要先连上服务器、登录，再等服务器慢慢找。",
    "lanes": [
        ("Ragdoll Mail", ["你的搜索", "你硬盘上的 SQLite 索引", "结果"], "6 毫秒"),
        ("服务器搜索", ["你的搜索", "互联网", "登录", "邮件服务器搜索", "互联网", "结果"], "约 1 秒"),
    ],
    "bars_h": "在命令行里搜一次，真实收件箱，共 5,044 封邮件",
    "bars": [("Ragdoll Mail，本地 SQLite", 0.0063, "0.006 秒", "989 封，都含这个词"),
             ("在邮件服务器上搜（IMAP）", 1.03, "1.03 秒", "5,044 封，也就是整个文件夹")],
    "bars_note": "2026 年 11 月 21 日在一台 MacBook 上实测，用的是一个有 5,044 封邮件的腾讯企业邮箱收件箱，搜的词是 "
                 "“invoice”。服务器那一边每次都新建连接再发 IMAP SEARCH，命令行工具每次运行也是这样：登录 0.9 秒，"
                 "搜索 0.13 秒。具体耗时会随服务器和网络变化。两个字的中文词在本地会慢一些，大约 0.08 秒。",

    "c_kick": "对比", "c_h2": "和 AI 邮件软件、命令行工具比一比。",
    "c_cols": ["", "Ragdoll Mail", "Superhuman", "Shortwave", "Himalaya", "Apple 邮件、Outlook"],
    "c_rows": [
        ("价格", "免费", "每月约 25 美元起", "免费版 AI 有限额，另有付费版", "免费", "免费"),
        ("支持的邮箱", "任何 IMAP 邮箱", "Gmail 和 Outlook", "主要是 Gmail", "任何 IMAP 邮箱", "大多数邮箱"),
        ("桌面软件", "有", "有", "有", "没有，只能在终端里用", "有"),
        ("AI 能用的命令行", "有", "没有", "没有", "有", "没有"),
        ("在哪里搜索", "你的电脑", "在线，经由 Gmail 或 Outlook", "在线，在 Shortwave 的服务器上", "邮件服务器", "看具体软件"),
        ("开源", "是", "否", "否", "是", "否"),
    ],
    "c_note": "根据各产品公开页面整理，2026 年 11 月。哪里写错了或者过时了，欢迎到 GitHub 提 issue，我会改。",
    "c_more": "更多对比，包括 Foxmail、Thunderbird 和 Spark",

    "f_kick": "也是一个完整的邮件软件", "f_h2": "就算不用 AI，日常收发也足够顺手。",
    "f": [
        ("search", "每个词、每封邮件，一下就找到", "标题、人名、附件名和正文都能搜，中文、英文、日文、韩文都行，断网也能搜。"),
        ("lock", "邮件只在你手里", "软件只和你自己的邮件服务器打交道，中间没有别家的云，也不用注册我们的账号。"),
        ("undo", "不容易发错", "点了发送，30 秒内还能撤回。写了“附件”却没加附件，也会先拦你一下。"),
        ("pen", "想怎么写就怎么写", "字体、列表、链接、签名都有。可以马上发，也可以定到今晚，或者周一早上九点。"),
        ("languages", "中文邮件不乱码", "老系统发来的中文名字和附件名，都能正常显示。"),
        ("keyboard", "每个操作都有快捷键", "C 写邮件，R 回复，E 归档。按 ? 看全部。"),
        ("check", "不会改动你的邮箱", "文件夹和网页版、手机上的一模一样，原来的用法都不受影响。"),
    ],
    "route": ["你的电脑", "你的邮件服务器", "中间没有别的服务器"],
    "sending": "正在发送…", "undo": "撤回", "warn": "你写了“附件”，但还没有加附件。",
    "w_kick": "支持的邮箱", "w_h2": "用你现在的邮箱就行。",
    "w": ["腾讯企业邮箱", "QQ 邮箱", "163 邮箱", "Gmail", "iCloud", "Fastmail", "任何 IMAP 邮箱"],
    "q_kick": "常见问题", "q_h2": "你可能想问。",
    "q": [
        ("哪些 AI 助手能用？", "能执行终端命令的都可以，比如 Claude Code、Codex、Cursor、Gemini CLI。AI 调用 ragdoll 命令的方式，"
         "跟你自己在终端里敲是一样的。"),
        ("要 API Key 或者付费套餐吗？", "不用。Ragdoll Mail 跟普通邮件软件一样，用 IMAP 和 SMTP 登录你的邮箱。"
         "不用申请 API Key，不用注册 OAuth 应用，也没有调用次数限制。"),
        ("AI 会不会不问我就把邮件发出去？", "不会误发。发送命令必须带上明确的确认才会执行，我们推荐的设置也会让 AI 先问你。"
         "大多数人的用法是：AI 写草稿，自己检查后点发送。"),
        ("为什么不直接用邮件服务器的搜索？", "服务器搜索每次都要走一趟网络，邮件越多越慢，有的服务器还几乎不怎么搜。"
         "本地索引几毫秒就有结果，断网也能用。"),
        ("我的邮件安全吗？", "邮件只存在两个地方：你的电脑，和你自己的邮件服务器。软件不会把任何东西发给我们，我们也没有服务器。"),
        ("真的免费吗？", "真的。没有广告，不用订阅，也不用注册。代码按 MIT 许可开源，谁都可以查它做了什么。"),
    ],
    "e_h2": "给你的 AI 一个真正能用的邮箱。", "e_sub": "免费开源，不用注册，没有广告。",
    "foot": ["源代码", "命令行", "反馈问题", "腾讯企业邮箱设置", "邮件软件对比"],
})


def page(L):
    e = html.escape
    up = "../" if L["path"] else ""
    url = SITE + L["path"]
    other_url = SITE + ("" if L["path"] else "zh/")
    ld = [
        {"@context": "https://schema.org", "@type": "SoftwareApplication", "name": "Ragdoll Mail",
         "operatingSystem": "macOS, Windows", "applicationCategory": "CommunicationApplication",
         "description": L["desc"], "url": url, "downloadUrl": REPO + "/releases/latest",
         "license": "https://opensource.org/licenses/MIT", "isAccessibleForFree": True, "image": SITE + "img/og.png",
         "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"}},
        {"@context": "https://schema.org", "@type": "VideoObject", "name": L["demo_name"], "description": L["shot_alt"],
         "inLanguage": L["lang"], "thumbnailUrl": SITE + "media/demo-%s.webp" % L["demo"],
         "contentUrl": SITE + "media/demo-%s.mp4" % L["demo"], "uploadDate": "2026-11-21", "duration": L["demo_len"]},
        {"@context": "https://schema.org", "@type": "FAQPage",
         "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in L["q"]]},
    ]
    f = L["f"]

    def tile(k, cls, extra=""):
        ic, h, p = f[k]
        return ('<div class="tile %s reveal"><div class="ic">%s</div><h3>%s</h3><p>%s</p>%s</div>'
                % (cls, icon(ic), e(h), e(p), extra))

    term = []
    for who, text in L["term"]:
        if who == "$":
            term.append('<span class="p">$</span> ' + e(text))
        elif who == "ok":
            term.append('  <span class="p">' + e(text) + "</span>")
        else:
            term.append('<span class="y">%s</span> <span class="c">›</span> %s' % ("you  " if who == "you" else "agent", e(text)))
    dl = lambda os_, cls: ('<a class="btn %s" data-os="%s" href="%s">%s%s <small>%s</small></a>' % (  # noqa: E731
        cls, os_, DL + ("ragdoll-mail-mac.dmg" if os_ == "mac" else "ragdoll-mail-windows.zip"),
        icon("download"), e(L[os_][0]), e(L[os_][1])))
    pts = "".join('<div class="pt"><div class="ic">%s</div><div><h3>%s</h3><p>%s</p></div></div>' % (icon(i), e(h), e(p))
                  for i, h, p in L["a_pts"])
    lanes = "".join(
        '<div class="lane%s"><div class="lane-name">%s</div><div class="flow">%s</div><div class="lane-t">%s</div></div>'
        % (" ours" if k == 0 else "", e(name),
           '<i class="arr"></i>'.join('<span class="step%s">%s</span>' % (" net" if j in (1, 4) and k else "", e(s))
                                      for j, s in enumerate(steps)), e(t))
        for k, (name, steps, t) in enumerate(L["lanes"]))
    top = max(v for _, v, _, _ in L["bars"])
    bars = "".join(
        '<div class="bar-row%s"><div class="bar-label">%s</div><div class="bar-track"><i style="--w:%.2f%%"></i></div>'
        '<div class="bar-val"><b>%s</b><span>%s</span></div></div>'
        % (" ours" if k == 0 else "", e(name), max(1.2, v / top * 100), e(val), e(note))
        for k, (name, v, val, note) in enumerate(L["bars"]))
    cmp_head = "".join("<th%s>%s</th>" % (' class="us"' if i == 1 else "", e(c)) for i, c in enumerate(L["c_cols"]))
    cmp_rows = "".join("<tr>%s</tr>" % "".join(("<th>%s</th>" if i == 0 else ('<td class="us">%s</td>' if i == 1 else "<td>%s</td>")) % e(c)
                                               for i, c in enumerate(r)) for r in L["c_rows"])
    return f"""<!doctype html>
<html lang="{L['lang']}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(L['title'])}</title>
<meta name="description" content="{e(L['desc'])}">
<link rel="canonical" href="{url}">
<link rel="alternate" hreflang="{L['lang']}" href="{url}">
<link rel="alternate" hreflang="{L['hreflang']}" href="{other_url}">
<link rel="alternate" hreflang="x-default" href="{SITE}">
<link rel="icon" href="{up}img/icon-256.png">
<link rel="apple-touch-icon" href="{up}img/icon-256.png">
<meta name="theme-color" content="#fbf9f6" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#161615" media="(prefers-color-scheme: dark)">
<meta property="og:type" content="website">
<meta property="og:title" content="{e(L['title'])}">
<meta property="og:description" content="{e(L['desc'])}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{SITE}img/{L.get('og', 'og.png')}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:locale" content="{L['lang'].replace('-Hans', '_CN').replace('en', 'en_US')}">
<meta name="twitter:card" content="summary_large_image">
<link rel="stylesheet" href="{up}style.css">
<link rel="preload" as="image" href="{up}media/demo-{L['demo']}.webp" fetchpriority="high">
<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>
</head>
<body>
<header class="top"><div class="wrap">
  <a class="brand" href="{up or './'}"><img src="{up}img/icon.webp" alt="" width="30" height="30">Ragdoll Mail</a>
  <nav>
    <a class="hide-s" href="#ai">{e(L['nav'][0])}</a>
    <a class="hide-s" href="#speed">{e(L['nav'][1])}</a>
    <a class="hide-s" href="#compare">{e(L['nav'][2])}</a>
    <a class="hide-s" href="#questions">{e(L['nav'][3])}</a>
    <a href="{L['other']}" hreflang="{L['hreflang']}">{e(L['other_name'])}</a>
    <a href="{REPO}">GitHub</a>
  </nav>
  <a class="btn primary" data-dl href="{DL}ragdoll-mail-mac.dmg">{e(L['download'])}</a>
</div></header>

<main>
<div class="hero"><div class="wrap">
  <img class="icon" src="{up}img/icon.webp" alt="Ragdoll Mail" width="96" height="96">
  <div class="pill">{'<b></b>'.join(e(x) for x in L['pill'])}</div>
  <h1>{L['h1']}</h1>
  <p class="lead">{e(L['lead'])}</p>
  <div class="cta">{dl('mac', 'primary')}{dl('win', '')}</div>
  <p class="first-open">{L['first']}</p>
</div>
  <div class="shot">
    <video class="demo" data-src="{up}media/demo-{L['demo']}.mp4" poster="{up}media/demo-{L['demo']}.webp" width="1920" height="1200"
      muted loop playsinline preload="none" aria-label="{e(L['shot_alt'])}"></video>
    <button class="sound" type="button" aria-pressed="false" data-on="{e(L['sound'][0])}" data-off="{e(L['sound'][1])}" aria-label="{e(L['sound'][0])}">{icon('volume-x')}{icon('volume-2')}</button>
  </div>
</div>

<section id="why"><div class="wrap">
  <div class="story reveal">
    <div class="kicker">{e(L['y_kick'])}</div>
    <h2>{e(L['y_h2'])}</h2>
    {''.join('<p>%s</p>' % e(p) for p in L['y_p'])}
    <p class="sign">{e(L['y_sign'])}</p>
  </div>
</div></section>

<section id="ai"><div class="wrap">
  <div class="reveal">
    <div class="kicker">{e(L['a_kick'])}</div>
    <h2>{e(L['a_h2'])}</h2>
    <p class="sub">{L['a_sub']} <a href="{REPO}/blob/main/docs/command-line.md" style="color:var(--accent-ink)">{e(L['a_guide'])} →</a></p>
  </div>
  <div class="grid" style="align-items:start">
    <div class="t-wide reveal"><div class="term-win"><div class="term-bar"><b></b><b></b><b></b></div><div class="term" role="img" aria-label="{e(L['a_kick'])}">{chr(10).join(term)}</div></div></div>
    <div class="pts t-narrow reveal">{pts}</div>
  </div>
</div></section>

<section id="speed"><div class="wrap">
  <div class="reveal">
    <div class="kicker">{e(L['s_kick'])}</div>
    <h2>{e(L['s_h2'])}</h2>
    <p class="sub">{e(L['s_sub'])}</p>
  </div>
  <div class="speed reveal">
    <div class="lanes">{lanes}</div>
    <div class="bars"><h3>{e(L['bars_h'])}</h3>{bars}</div>
    <p class="speed-note">{e(L['bars_note'])}</p>
  </div>
</div></section>

<section id="compare"><div class="wrap">
  <div class="reveal">
    <div class="kicker">{e(L['c_kick'])}</div>
    <h2>{e(L['c_h2'])}</h2>
  </div>
  <div class="table hc reveal"><table><thead><tr>{cmp_head}</tr></thead><tbody>{cmp_rows}</tbody></table></div>
  <p class="speed-note">{e(L['c_note'])} <a href="compare/" style="color:var(--accent-ink)">{e(L['c_more'])} →</a></p>
</div></section>

<section id="features"><div class="wrap">
  <div class="reveal">
    <div class="kicker">{e(L['f_kick'])}</div>
    <h2>{e(L['f_h2'])}</h2>
  </div>
  <div class="grid">
    {tile(0, 't-wide', f'<div class="peek"><img src="{up}img/search-{L["demo"]}.webp" alt="" loading="lazy" width="1800" height="1161"></div>')}
    {tile(1, 't-narrow', f'<div class="path"><span>{e(L["route"][0])}</span><i></i><span>{e(L["route"][1])}</span></div><div class="path-x">{e(L["route"][2])}</div>')}
    {tile(2, 't-narrow', f'<div class="undo">{e(L["sending"])}<span class="bar"><i></i></span><a href="#features">{e(L["undo"])}</a></div><div class="warn">{e(L["warn"])}</div>')}
    {tile(3, 't-wide', f'<div class="peek peek-r"><img src="{up}img/compose-{L["demo"]}.webp" alt="" loading="lazy" width="1800" height="1161"></div>')}
    {tile(4, 't-third')}
    {tile(5, 't-third')}
    {tile(6, 't-third')}
  </div>
</div></section>

<section id="works"><div class="wrap center reveal">
  <div class="kicker">{e(L['w_kick'])}</div>
  <h2>{e(L['w_h2'])}</h2>
  <div class="chips">{''.join('<span class="chip">%s</span>' % e(x) for x in L['w'])}</div>
</div></section>

<section id="questions"><div class="wrap">
  <div class="center reveal">
    <div class="kicker">{e(L['q_kick'])}</div>
    <h2>{e(L['q_h2'])}</h2>
  </div>
  <div class="faq">
    {''.join(f'<details><summary>{e(q)}{icon("chevron")}</summary><p>{e(a)}</p></details>' for q, a in L['q'])}
  </div>
</div></section>

<div class="end"><div class="wrap reveal">
  <img src="{up}img/icon.webp" alt="" width="72" height="72" loading="lazy">
  <h2 style="margin:0 auto">{e(L['e_h2'])}</h2>
  <p class="sub" style="margin:14px auto 0">{e(L['e_sub'])}</p>
  <div class="cta" style="animation:none">{dl('mac', 'primary')}{dl('win', '')}</div>
</div></div>
</main>

<footer><div class="wrap">
  <span class="grow">Ragdoll Mail · MIT</span>
  <a href="{REPO}">{e(L['foot'][0])}</a>
  <a href="{REPO}/blob/main/docs/command-line.md">{e(L['foot'][1])}</a>
  <a href="{REPO}/issues">{e(L['foot'][2])}</a>
  <a href="exmail/">{e(L['foot'][3])}</a>
  <a href="compare/">{e(L['foot'][4])}</a>
  <a href="{L['other']}" hreflang="{L['hreflang']}">{e(L['other_name'])}</a>
</div></footer>
<script src="{up}main.js" defer></script>
</body>
</html>
"""


# ---------------------------------------------------------------- the Tencent Exmail guide
# One page per language for what people search before they find the app: how to use Tencent
# Exmail on a Mac or a Windows PC, its server settings, and why its own search finds nothing.

GUIDE_EN = {
    "lang": "en", "path": "exmail/", "other": "../zh/exmail/", "other_name": "简体中文", "hreflang": "zh-Hans",
    "en_path": "exmail/", "zh_path": "zh/exmail/",
    "home": "../", "og": "og.png",
    "title": "Tencent Exmail on Mac and Windows: IMAP settings and a search that works",
    "desc": "Use Tencent Exmail (腾讯企业邮箱) in a mail app on Mac or Windows: IMAP imap.exmail.qq.com:993, "
            "SMTP smtp.exmail.qq.com:465, the client password, and a local search that finds the right mail.",
    "kick": "Guide",
    "h1": "Tencent Exmail on a Mac or a Windows PC",
    "lead": "Sign in with your address and password. Ragdoll Mail sees that your company's mail is on Tencent "
            "Exmail and fills in the servers itself.",
    "steps_h": "Three steps",
    "steps": [
        ("Check that IMAP is on",
         "In Exmail on the web, open the settings and make sure the IMAP/SMTP service is on. If your company "
         "turned it off for everyone, ask whoever runs your mail."),
        ("Make a client password if you need one",
         "If you sign in to Exmail with WeChat or a dynamic code, mail apps need a client password "
         "(客户端专用密码) instead of your web password. You make it in the account security part of the settings."),
        ("Sign in to Ragdoll Mail",
         "Type your address and that password. The first time, it reads your mail into a local index; "
         "after that, search answers at once, also offline."),
    ],
    "srv_h": "Server settings",
    "srv_sub": "For Ragdoll Mail these are filled in for you. They are the same in any other mail app.",
    "srv_cols": ["", "Server", "Port", "Security"],
    "srv": [("Incoming (IMAP)", "imap.exmail.qq.com", "993", "SSL/TLS"),
            ("Outgoing (SMTP)", "smtp.exmail.qq.com", "465", "SSL/TLS")],
    "srv_user": "User name: your full email address.",
    "why_h": "Why Exmail's own search finds everything, or nothing",
    "why": [
        "Exmail does not search inside mails when a mail app asks it to: it gives back the whole folder. "
        "On a real Exmail mailbox with 6,442 mails, a search returned 4,988 mails for any word, even for a "
        "word we made up.",
        "Ragdoll Mail keeps its own full-text index on your computer. It returns only the mails with your words, "
        "in under a tenth of a second, in Chinese and English, also with no network.",
    ],
    "q_h": "Questions",
    "q": [
        ("It says the password is wrong. What now?",
         "Most of the time Exmail wants the client password (客户端专用密码), not the one you use on the web. "
         "If that is not it, check that IMAP/SMTP is on in the settings."),
        ("Does it work with other company mail?",
         "Yes. It also finds the servers itself for Alibaba Mail, NetEase enterprise mail, Google Workspace, "
         "Zoho and Fastmail. For any other IMAP mailbox, type the server names once."),
        ("Does my mail go to your servers?",
         "No. The app talks only to your own mail server. The index and your password stay on your computer."),
        ("What does it cost?", "Nothing. It is free and open source (MIT)."),
    ],
    "cta_h": "Try it on your Exmail",
    "mac": ["Download for Mac", "Apple silicon"], "win": ["Download for Windows", "10 and 11"],
    "nav_home": "Ragdoll Mail", "foot": ["Source code", "Command line", "Report a problem"],
}

GUIDE_ZH = {
    "lang": "zh-Hans", "path": "zh/exmail/", "other": "../../exmail/", "other_name": "English", "hreflang": "en",
    "en_path": "exmail/", "zh_path": "zh/exmail/",
    "home": "../", "og": "og-zh.png",
    "title": "腾讯企业邮箱 Mac / Windows 客户端设置：IMAP 服务器、专用密码、搜索",
    "desc": "在 Mac 和 Windows 上用腾讯企业邮箱：收信 imap.exmail.qq.com:993，发信 smtp.exmail.qq.com:465，"
            "客户端专用密码怎么用，以及企业邮箱自带搜索为什么搜不准、怎么秒搜。",
    "kick": "使用指南",
    "h1": "腾讯企业邮箱，在 Mac 和 Windows 上用",
    "lead": "填邮箱地址和密码就能登录。Ragdoll Mail 会自己认出你公司的邮箱在腾讯企业邮箱上，服务器不用手填。",
    "steps_h": "三步",
    "steps": [
        ("确认 IMAP 已开启",
         "在企业邮箱网页版的设置里，确认 IMAP/SMTP 服务是开着的。如果公司统一关掉了，问一下邮箱管理员。"),
        ("需要的话，生成客户端专用密码",
         "如果你登录网页版用微信扫码或动态密码，邮件软件就要用“客户端专用密码”，不是网页登录的密码。"
         "在设置的账户安全里生成。"),
        ("登录 Ragdoll Mail",
         "填邮箱地址和这个密码。第一次会把邮件建成本地索引，之后搜索不用等，断网也能搜。"),
    ],
    "srv_h": "服务器设置",
    "srv_sub": "用 Ragdoll Mail 不用手填。其它邮件软件（Foxmail、Outlook、苹果邮件）也是这几项。",
    "srv_cols": ["", "服务器", "端口", "加密"],
    "srv": [("收信（IMAP）", "imap.exmail.qq.com", "993", "SSL/TLS"),
            ("发信（SMTP）", "smtp.exmail.qq.com", "465", "SSL/TLS")],
    "srv_user": "用户名：完整的邮箱地址。",
    "why_h": "为什么企业邮箱自带的搜索，要么全给你，要么搜不到",
    "why": [
        "邮件软件让腾讯企业邮箱按内容搜索时，它并不真的搜，而是把整个文件夹都返回。"
        "在一个有 6,442 封邮件的真实企业邮箱里，随便搜什么词都返回 4,988 封，连编出来的词也一样。",
        "Ragdoll Mail 在你电脑上自己建全文索引，只返回真正含这些词的邮件，0.1 秒以内，中文英文都行，断网也能搜。",
    ],
    "q_h": "常见问题",
    "q": [
        ("提示密码错误怎么办？",
         "多半是要用“客户端专用密码”，不是网页登录的密码。如果不是这个原因，看一下设置里 IMAP/SMTP 服务有没有开。"),
        ("别的企业邮箱能用吗？",
         "能。阿里企业邮箱、网易企业邮箱、Google Workspace、Zoho、Fastmail 也会自己认出服务器。"
         "其它 IMAP 邮箱手填一次服务器地址就行。"),
        ("邮件会传到你们的服务器吗？", "不会。软件只连你自己的邮件服务器，索引和密码都留在你电脑上。"),
        ("收费吗？", "免费，开源（MIT 协议）。"),
    ],
    "cta_h": "用你的企业邮箱试试",
    "mac": ["下载 Mac 版", "M 系列芯片"], "win": ["下载 Windows 版", "Windows 10 / 11"],
    "nav_home": "Ragdoll Mail", "foot": ["源代码", "命令行", "反馈问题"],
}


# ---------------------------------------------------------------- the comparison
# What people search when they look for another mail app ("Foxmail alternative", "Exmail client for Mac"):
# the same table as the README, gaps included.

YES = "Yes"
COMPARE_EN = {
    "lang": "en", "path": "compare/", "other": "../zh/compare/", "other_name": "简体中文", "hreflang": "zh-Hans",
    "en_path": "compare/", "zh_path": "zh/compare/", "home": "../", "og": "og.png",
    "title": "Ragdoll Mail vs Foxmail, Outlook, Apple Mail, Thunderbird and Spark",
    "desc": "A free, open-source mail app for Mac and Windows compared with Foxmail, Outlook, Apple Mail, Thunderbird "
            "and Spark: price, privacy, search, Tencent Exmail and QQ Mail support, and what it does not do yet.",
    "kick": "Compare",
    "h1": "How Ragdoll Mail compares",
    "lead": "Ragdoll Mail does one thing: your own mailbox, with a search that finds the mail. Here it is next to "
            "the apps you may know, the good parts and the gaps.",
    "cmp_h": "Side by side",
    "cmp_cols": ["", "Ragdoll Mail", "Apple Mail", "Outlook (new)", "Thunderbird", "Foxmail", "Spark"],
    "cmp": [
        ("Price", "Free", "Free", "Free with ads, or paid", "Free", "Free", "Free plan, paid plan"),
        ("Mac and Windows", "Both", "Mac only", "Both", "Both", "Both", "Both"),
        ("Mail goes straight between you and your mail server", YES, YES, "A copy is kept in Microsoft's cloud", YES, YES,
         "Goes through Spark's servers"),
        ("Open code that anyone can check", YES, "No", "No", YES, "No", "No"),
        ("Your own AI assistant can use the mailbox", YES, "No", "No", "No", "No", "No"),
        ("Phone app", "No", YES, YES, "Android", "No", YES),
        ("Several mailboxes in one window", "Not yet", YES, YES, YES, YES, YES),
    ],
    "cmp_note": "Compared from each product's public pages, November 2026. Something wrong or out of date? "
                "Open an issue on GitHub and we will fix it.",
    "why_blocks": [
        ("Where Ragdoll Mail is strong", [
            "Search. It keeps a full-text index on your computer, so a word, a name or an order number finds the right "
            "mails in under a tenth of a second, in Chinese and English, also offline. Mailboxes like Tencent Exmail "
            "give back the whole folder when a mail app asks them to search.",
            "Privacy. The app talks only to your own mail server. Your password is in the system's password store.",
            "Fewer mistakes. Undo send, send later, and a check for a missing attachment, an empty subject or a "
            "[Name] left in the text.",
            "Chinese mail. Names and file names from older Chinese mail systems show as they should."]),
        ("Where the others are better", [
            "Ragdoll Mail has no phone app and no calendar, and it shows one mailbox at a time. If you need those, "
            "use one of the others, or use both: they read the same mailbox."]),
    ],
    "q_h": "Questions",
    "q": [
        ("Is there a good Foxmail alternative for Mac?",
         "Ragdoll Mail is one: it runs on Mac (Apple silicon) and Windows, signs in to the same mailboxes as Foxmail "
         "(Tencent Exmail, QQ Mail, 163 and any IMAP mailbox), and its search answers at once."),
        ("Which mail app works best with Tencent Exmail?",
         "Any IMAP app can read Exmail, but Exmail's own search gives back the whole folder. Ragdoll Mail searches "
         "its own index instead, so only the mails with your words come back."),
        ("Can I keep my current mail app?",
         "Yes. Ragdoll Mail reads the same mailbox. Your phone and your other mail apps keep working as before."),
        ("What does it cost?", "Nothing. It is free and open source (MIT). No account, no ads."),
    ],
    "cta_h": "Try it on your own mailbox",
    "mac": ["Download for Mac", "Apple silicon"], "win": ["Download for Windows", "10 and 11"],
    "nav_home": "Ragdoll Mail", "foot": ["Source code", "Command line", "Report a problem"],
}

SHI = "有"
COMPARE_ZH = {
    "lang": "zh-Hans", "path": "zh/compare/", "other": "../../compare/", "other_name": "English", "hreflang": "en",
    "en_path": "compare/", "zh_path": "zh/compare/", "home": "../", "og": "og-zh.png",
    "title": "Foxmail 替代之选：腾讯企业邮箱、QQ 邮箱的 Mac / Windows 客户端对比",
    "desc": "免费开源的邮件客户端 Ragdoll Mail，和 Foxmail、Outlook、苹果邮件、Thunderbird、Spark 对比："
            "价格、隐私、搜索、腾讯企业邮箱和 QQ 邮箱支持，以及它还做不到的地方。",
    "kick": "对比",
    "h1": "Ragdoll Mail 和其他邮件软件比",
    "lead": "Ragdoll Mail 只做一件事：用你自己的邮箱收发邮件，而且一搜就到。下面把它和常见的邮件软件放在一起，"
            "优点和不足都写清楚。",
    "cmp_h": "逐项对比",
    "cmp_cols": ["", "Ragdoll Mail", "苹果“邮件”", "新版 Outlook", "Thunderbird", "Foxmail", "Spark"],
    "cmp": [
        ("价格", "免费", "免费", "免费版有广告，或付费", "免费", "免费", "有免费版和付费版"),
        ("Mac 和 Windows", "都有", "只有 Mac", "都有", "都有", "都有", "都有"),
        ("邮件只在你和邮箱服务器之间走", "是", "是", "会在微软云端存一份", "是", "是", "要经过 Spark 的服务器"),
        ("代码公开，谁都能查", "是", "否", "否", "是", "否", "否"),
        ("你自己的 AI 助手可以用这个邮箱", "是", "否", "否", "否", "否", "否"),
        ("手机版", "没有", SHI, SHI, "安卓", "没有", SHI),
        ("一个窗口里看多个邮箱", "还没有", "可以", "可以", "可以", "可以", "可以"),
    ],
    "cmp_note": "根据各产品公开的页面整理，2026 年 11 月。有写错或过时的地方？在 GitHub 上告诉我们，马上改。",
    "why_blocks": [
        ("Ragdoll Mail 强在哪", [
            "搜索。它在你电脑上建全文索引，搜一个词、一个人名或订单号，0.1 秒内就找到对的邮件，中文英文都行，断网也能搜。"
            "腾讯企业邮箱这类邮箱，邮件软件让它按内容搜时，它会把整个文件夹都返回。",
            "隐私。软件只连你自己的邮件服务器，密码存在系统自带的钥匙串里。",
            "少出错。发出后可以撤回，可以定时发送；写了“附件”却没附件、主题空着、[姓名] 没改，都会提醒。",
            "中文邮件。老系统发来的中文名字和附件名，都能正常显示，不会乱码。"]),
        ("别人强在哪", [
            "Ragdoll Mail 没有手机版，没有日历，一次只能看一个邮箱。需要这些的话，用别的软件，或者两个一起用：它们读的是同一个邮箱。"]),
    ],
    "q_h": "常见问题",
    "q": [
        ("Mac 上有好用的 Foxmail 替代吗？",
         "Ragdoll Mail 就是一个：支持 Mac（M 系列芯片）和 Windows，能登录 Foxmail 能登录的邮箱"
         "（腾讯企业邮箱、QQ 邮箱、163 和任何 IMAP 邮箱），而且搜索秒出结果。"),
        ("腾讯企业邮箱用哪个客户端好？",
         "任何支持 IMAP 的软件都能收企业邮箱，但企业邮箱自带的搜索会把整个文件夹都返回。"
         "Ragdoll Mail 搜的是自己的本地索引，只返回真正含这些词的邮件。"),
        ("能和现在用的邮件软件一起用吗？", "能。Ragdoll Mail 读的是同一个邮箱，手机和其他邮件软件照常用。"),
        ("收费吗？", "免费，开源（MIT 协议）。不用注册账号，没有广告。"),
    ],
    "cta_h": "用你自己的邮箱试试",
    "mac": ["下载 Mac 版", "M 系列芯片"], "win": ["下载 Windows 版", "Windows 10 / 11"],
    "nav_home": "Ragdoll Mail", "foot": ["源代码", "命令行", "反馈问题"],
}


def guide(G):
    e = html.escape
    up = "../" * G["path"].count("/")
    url = SITE + G["path"]
    other_url = SITE + (G["zh_path"] if G["lang"] == "en" else G["en_path"])
    ld = [
        {"@context": "https://schema.org", "@type": "HowTo", "name": G["h1"], "description": G["desc"],
         "inLanguage": G["lang"], "url": url,
         "step": [{"@type": "HowToStep", "position": i + 1, "name": h, "text": t} for i, (h, t) in enumerate(G["steps"])]}
    ] if G.get("steps") else []
    ld += [
        {"@context": "https://schema.org", "@type": "FAQPage", "inLanguage": G["lang"],
         "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in G["q"]]},
        {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Ragdoll Mail", "item": SITE + ("" if G["lang"] == "en" else "zh/")},
            {"@type": "ListItem", "position": 2, "name": G["kick"], "item": url}]},
    ]
    dl = lambda os_, cls: ('<a class="btn %s" data-os="%s" href="%s">%s%s <small>%s</small></a>' % (  # noqa: E731
        cls, os_, DL + ("ragdoll-mail-mac.dmg" if os_ == "mac" else "ragdoll-mail-windows.zip"),
        icon("download"), e(G[os_][0]), e(G[os_][1])))
    body = ""
    if G.get("cmp"):
        head = "".join("<th>%s</th>" % e(c) for c in G["cmp_cols"])
        trs = "".join("<tr><th>%s</th>%s</tr>" % (e(r[0]), "".join("<td>%s</td>" % e(c) for c in r[1:])) for r in G["cmp"])
        body += f"""
  <h2>{e(G['cmp_h'])}</h2>
  <div class="table cmp"><table><thead><tr>{head}</tr></thead><tbody>{trs}</tbody></table></div>
  <p class="note">{e(G['cmp_note'])}</p>
"""
    if G.get("steps"):
        steps = "".join('<li><h3>%s</h3><p>%s</p></li>' % (e(h), e(t)) for h, t in G["steps"])
        body += f"""
  <h2>{e(G['steps_h'])}</h2>
  <ol class="steps">{steps}</ol>
"""
    if G.get("srv"):
        rows = "".join("<tr><th>%s</th><td><code>%s</code></td><td>%s</td><td>%s</td></tr>" % tuple(map(e, r)) for r in G["srv"])
        body += f"""
  <h2>{e(G['srv_h'])}</h2>
  <p class="sub">{e(G['srv_sub'])}</p>
  <div class="table"><table>
    <thead><tr>{''.join('<th>%s</th>' % e(c) for c in G['srv_cols'])}</tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
  <p class="note">{e(G['srv_user'])}</p>
"""
    for h, paras in G.get("why_blocks") or [(G["why_h"], G["why"])]:
        body += f"""
  <h2>{e(h)}</h2>
  {''.join('<p class="sub">%s</p>' % e(x) for x in paras)}
"""
    return f"""<!doctype html>
<html lang="{G['lang']}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(G['title'])}</title>
<meta name="description" content="{e(G['desc'])}">
<link rel="canonical" href="{url}">
<link rel="alternate" hreflang="{G['lang']}" href="{url}">
<link rel="alternate" hreflang="{G['hreflang']}" href="{other_url}">
<link rel="alternate" hreflang="x-default" href="{SITE}{G['en_path']}">
<link rel="icon" href="{up}img/icon-256.png">
<link rel="apple-touch-icon" href="{up}img/icon-256.png">
<meta name="theme-color" content="#fbf9f6" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#161615" media="(prefers-color-scheme: dark)">
<meta property="og:type" content="article">
<meta property="og:title" content="{e(G['title'])}">
<meta property="og:description" content="{e(G['desc'])}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{SITE}img/{G['og']}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<link rel="stylesheet" href="{up}style.css">
<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>
</head>
<body>
<header class="top"><div class="wrap">
  <a class="brand" href="{G['home']}"><img src="{up}img/icon.webp" alt="" width="30" height="30">Ragdoll Mail</a>
  <nav>
    <a href="{G['other']}" hreflang="{G['hreflang']}">{e(G['other_name'])}</a>
    <a href="{REPO}">GitHub</a>
  </nav>
  <a class="btn primary" data-dl href="{DL}ragdoll-mail-mac.dmg">{e(G['mac'][0].split()[0])}</a>
</div></header>

<main class="doc">
<div class="wrap narrow">
  <div class="kicker">{e(G['kick'])}</div>
  <h1>{e(G['h1'])}</h1>
  <p class="lead">{e(G['lead'])}</p>
  <div class="cta">{dl('mac', 'primary')}{dl('win', '')}</div>
{body}
  <h2>{e(G['q_h'])}</h2>
  <div class="faq">
    {''.join(f'<details><summary>{e(q)}{icon("chevron")}</summary><p>{e(a)}</p></details>' for q, a in G['q'])}
  </div>
</div>

<div class="end"><div class="wrap">
  <img src="{up}img/icon.webp" alt="" width="72" height="72" loading="lazy">
  <h2 style="margin:0 auto">{e(G['cta_h'])}</h2>
  <div class="cta" style="animation:none">{dl('mac', 'primary')}{dl('win', '')}</div>
</div></div>
</main>

<footer><div class="wrap">
  <span class="grow"><a href="{G['home']}">Ragdoll Mail</a> · MIT</span>
  <a href="{REPO}">{e(G['foot'][0])}</a>
  <a href="{REPO}/blob/main/docs/command-line.md">{e(G['foot'][1])}</a>
  <a href="{REPO}/issues">{e(G['foot'][2])}</a>
</div></footer>
<script src="{up}main.js" defer></script>
</body>
</html>
"""


PAGES = [("", "zh/"), ("exmail/", "zh/exmail/"), ("compare/", "zh/compare/")]


def sitemap():
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">']
    for en, zh in PAGES:
        for loc in (en, zh):
            out += ["  <url>", "    <loc>%s%s</loc>" % (SITE, loc),
                    '    <xhtml:link rel="alternate" hreflang="en" href="%s%s"/>' % (SITE, en),
                    '    <xhtml:link rel="alternate" hreflang="zh-Hans" href="%s%s"/>' % (SITE, zh),
                    "  </url>"]
    return "\n".join(out + ["</urlset>", ""])


if __name__ == "__main__":
    jobs = [(L["path"], page(L)) for L in (EN, ZH)] + [(G["path"], guide(G)) for G in (GUIDE_EN, GUIDE_ZH, COMPARE_EN, COMPARE_ZH)]
    for path, text in jobs:
        out = os.path.join(HERE, path, "index.html")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
        print("wrote", os.path.relpath(out, HERE))
    with open(os.path.join(HERE, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write(sitemap())
    print("wrote sitemap.xml")
