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
}


def icon(name):
    return '<svg class="i" viewBox="0 0 24 24" aria-hidden="true">%s</svg>' % ICONS[name]


EN = {
    "lang": "en", "path": "", "other": "zh/", "other_name": "简体中文", "hreflang": "zh-Hans",
    "title": "Ragdoll Mail: a free mail app for Mac and Windows with search that works",
    "desc": "Free, open-source mail app for Mac and Windows. Fast local search for Tencent Exmail, QQ Mail, 163, "
            "Gmail, iCloud and any IMAP mailbox. Private, works offline.",
    "nav": ["Features", "For your AI", "Questions"], "download": "Download",
    "pill": ["Free", "Open source", "Mac and Windows"],
    "h1": "Search that <em>finds</em> your&nbsp;mail.",
    "lead": "A mail app for the mailbox you already have. Works with Tencent Exmail, QQ Mail, 163, Gmail, "
            "iCloud and any other IMAP mailbox.",
    "mac": ["Download for Mac", "Apple silicon"], "win": ["Download for Windows", "10 and 11"],
    "first": "Not signed by Apple or Microsoft yet. The first time, choose Open Anyway (Mac: System Settings → "
             "Privacy &amp; Security) or Run anyway (Windows: More info).",
    "demo": "en", "demo_name": "Ragdoll Mail in 30 seconds", "demo_len": "PT32S",
    "shot_alt": "Ragdoll Mail in use: search finds a mail as you type, a mail with two attachments opens, a reply is "
                "written, the send is undone, and the reply is set to go tomorrow morning",
    "s_kick": "Search", "s_h2": "Your mailbox's search gives back everything. Ours gives back the&nbsp;mail.",
    "s_sub": "We typed the same words into both. On a real Tencent Exmail mailbox with 6,442 mails, its own "
             "search returned 4,988 mails every time, even for a word we made up.",
    "theirs": "Mailbox website search", "ours": "Ragdoll Mail",
    "race_foot": "Left: Tencent Exmail's own search, tested on a real mailbox of 6,442 mails. Right: the demo "
                 "mailbox in Ragdoll Mail.",
    "race": {"theirs": 4988, "theirsNote": "results, for any word you type", "searching": "Searching…",
             "fast": "in under 0.1 s, only the mails with that word", "none": "No mail has this word. As it should be.",
             "words": [{"word": "PO-1234", "rows": [["Jane Doe", "Quote for PO-1234"], ["To: Jane Doe", "Re: Quote for PO-1234"],
                                                    ["Tom Becker", "Packing list for PO-1234"]]},
                       {"word": "图纸", "rows": [["Li Ming", "北京ABC项目 — 图纸确认"]]},
                       {"word": "zqxv", "rows": []}],
             "noise": [["GitHub", "Release v0.5.0 published"], ["Northwind Billing", "Your invoice INV-0006 is ready"],
                       ["Sara Kim", "Lunch on Thursday?"]]},
    "f_kick": "Made for real mail", "f_h2": "Quiet, quick, and hard to get wrong.",
    "f": [
        ("search", "Every word, every mail, in a blink", "Subject, people, file names and the full text. Chinese, "
         "Japanese and Korean too. It works with no internet."),
        ("lock", "Your mail stays with you", "The app talks only to your own mail server. No cloud in between, no "
         "account with us. The password stays in Keychain or Credential Manager."),
        ("undo", "Hard to send a mistake", "Up to 30 seconds to take a mail back. It stops you when you wrote "
         "“attached” and attached nothing, or left [Name] in the text."),
        ("pen", "Write the way you like", "Fonts, lists, links and your signature. A reply keeps the earlier mails and "
         "their pictures. Send now, tonight, or Monday at nine."),
        ("languages", "Chinese mail that reads right", "Names and file names from older Chinese mail systems show as "
         "they should, not as broken characters."),
        ("keyboard", "A key for everything", "C writes a mail, R replies, E archives. Press ? to see them all."),
        ("check", "Nothing changes in your mailbox", "The same folders and mail as the website. Your phone keeps "
         "working as before."),
    ],
    "route": ["Your computer", "Your mail server", "No other server in between"],
    "sending": "Sending…", "undo": "Undo", "warn": "You wrote “attached”, but nothing is attached.",
    "a_kick": "For your AI", "a_h2": "Your assistant drafts. You&nbsp;send.",
    "a_sub": "Claude Code, Codex or any assistant that runs commands can search your mail and write replies with "
             "the <code>ragdoll</code> command. Each draft opens in the app, and nothing goes out until you press Send.",
    "a_how": "Get the command in the app: Settings → Command line → Install.",
    "a_guide": "Read the command-line guide",
    "term": [("you", "Reply to Jane and attach the signed quote."),
             ("$", "ragdoll search jane quote --json"),
             ("$", "ragdoll draft --reply inbox:312 --body reply.html --attach Quote.pdf"),
             ("$", "ragdoll check drafts:14 --reply"),
             ("ok", "CHECK OK"),
             ("$", "ragdoll open drafts:14"),
             ("agent", "The draft is open in Ragdoll Mail. Send it when you are happy.")],
    "w_kick": "Works with", "w_h2": "The mailbox you already have.",
    "w": ["Tencent Exmail", "QQ Mail", "163 Mail", "Gmail", "iCloud", "Fastmail", "Any IMAP mailbox"],
    "q_kick": "Questions", "q_h2": "Good to know.",
    "q": [
        ("Is there a Mac or Windows app for Tencent Exmail (腾讯企业邮箱) with search that works?",
         "Yes, this one. On a real Exmail mailbox with 6,442 mails, the mailbox's own search gave back 4,988 mails for "
         "every word we typed, even for a made-up word. Ragdoll Mail gave back only the mails with that word, in less "
         "than a tenth of a second."),
        ("Is my mail safe?", "Your mail is stored on your computer and on your own mail server, nowhere else. The app "
         "sends nothing to us. We have no server."),
        ("Where is my password kept?", "In the password store of your system: Keychain on Mac, Credential Manager on "
         "Windows. It is never written into a file."),
        ("Which password do I use?", "Many mailboxes want a special password for mail apps. Tencent Exmail calls it "
         "客户端专用密码, QQ Mail and 163 call it 授权码, and Gmail, iCloud and Fastmail call it an app password. "
         "You make it in your mailbox's settings on the website."),
        ("Does it work with no internet?", "Reading and searching the mail you already have: yes. Sending and getting "
         "new mail need the internet."),
        ("Is it really free?", "Yes. No ads, no subscription, no account. The code is open source under the MIT "
         "license, so anyone can check what it does."),
    ],
    "e_h2": "Try it on your own mailbox.", "e_sub": "Free. No account. No ads.",
    "foot": ["Source code", "Command line", "Report a problem", "Tencent Exmail setup"],
}

ZH = dict(EN, **{
    "lang": "zh-Hans", "path": "zh/", "og": "og-zh.png", "other": "../", "other_name": "English", "hreflang": "en",
    "title": "Ragdoll Mail：免费的 Mac / Windows 邮件客户端，腾讯企业邮箱也能秒搜",
    "desc": "免费开源的 Mac 和 Windows 邮件软件。本地索引，搜索秒出结果。支持腾讯企业邮箱、QQ 邮箱、163、Gmail、iCloud "
            "和任何 IMAP 邮箱。邮件只在你电脑上，断网也能搜。",
    "nav": ["功能", "AI 助手", "常见问题"], "download": "下载",
    "pill": ["免费", "开源", "Mac 和 Windows"],
    "h1": "邮件，<em>一搜就到</em>。",
    "lead": "用你现在的邮箱登录就行。腾讯企业邮箱、QQ 邮箱、163、Gmail、iCloud，还有任何 IMAP 邮箱都能用。",
    "mac": ["下载 Mac 版", "M 系列芯片"], "win": ["下载 Windows 版", "Windows 10 / 11"],
    "first": "还没有苹果和微软的签名。第一次打开时：Mac 在 系统设置 → 隐私与安全性 里点“仍要打开”；Windows 点“更多信息 → 仍要运行”。",
    "demo": "zh", "demo_name": "30 秒看 Ragdoll Mail", "demo_len": "PT30S",
    "shot_alt": "Ragdoll Mail 使用演示：边打字边搜到邮件，打开一封带两个附件的邮件，写回复，撤销发送，再定到明天上午发送",
    "s_kick": "搜索", "s_h2": "邮箱自带的搜索什么都给你。我们只给你要找的那封。",
    "s_sub": "同样的词，两边一起搜。在一个有 6,442 封邮件的真实腾讯企业邮箱里，它自带的搜索每次都返回 4,988 封，"
             "连随手编的词也一样。",
    "theirs": "邮箱网页版搜索", "ours": "Ragdoll Mail",
    "race_foot": "左边：腾讯企业邮箱自带的搜索，在一个有 6,442 封邮件的真实邮箱里测的。右边：Ragdoll Mail 的示例邮箱。",
    "race": dict(EN["race"], theirsNote="封，不管搜什么词", searching="正在搜索…",
                 fast="不到 0.1 秒，只有含这个词的邮件", none="没有邮件含这个词，本来就该是 0。"),
    "f_kick": "为真实的邮件而做", "f_h2": "安静、快，而且不容易出错。",
    "f": [
        ("search", "每个词、每封邮件，一下就找到", "标题、人名、附件名和全文都能搜。中文、日文、韩文都行，断网也能搜。"),
        ("lock", "邮件只在你手里", "软件只和你自己的邮件服务器说话，中间没有别家的云，也不用注册我们的账号。密码存在系统的钥匙串或凭据管理器里。"),
        ("undo", "不容易发错", "点了发送，30 秒内还能撤回。写了“附件”却没加附件、正文里还留着 [姓名]，都会先拦一下。"),
        ("pen", "想怎么写就怎么写", "字体、列表、链接、签名都有。回复会带上之前的邮件和图片。可以马上发，也可以定到今晚或周一早上九点。"),
        ("languages", "中文邮件不乱码", "老系统发来的中文名字和附件名，都能正常显示。"),
        ("keyboard", "每个操作都有快捷键", "C 写邮件，R 回复，E 归档。按 ? 看全部。"),
        ("check", "不会改动你的邮箱", "文件夹和邮件跟网页版一模一样。手机照常用。"),
    ],
    "route": ["你的电脑", "你的邮件服务器", "中间没有别的服务器"],
    "sending": "正在发送…", "undo": "撤回", "warn": "你写了“附件”，但还没有加附件。",
    "a_kick": "AI 助手", "a_h2": "AI 写草稿，你来点发送。",
    "a_sub": "Claude Code、Codex 这些能跑命令的 AI，可以用 <code>ragdoll</code> 命令帮你搜邮件、写回复。草稿会在 App 里打开，"
             "你不点发送，什么都不会发出去。",
    "a_how": "在 App 里装命令：设置 → 命令行 → 安装。",
    "a_guide": "看命令行说明（英文）",
    "term": [("you", "回复 Jane，附上签好的报价单。"),
             ("$", "ragdoll search jane quote --json"),
             ("$", "ragdoll draft --reply inbox:312 --body reply.html --attach Quote.pdf"),
             ("$", "ragdoll check drafts:14 --reply"),
             ("ok", "CHECK OK"),
             ("$", "ragdoll open drafts:14"),
             ("agent", "草稿已经在 Ragdoll Mail 里打开了，你看好了就发。")],
    "w_kick": "支持的邮箱", "w_h2": "用你现在的邮箱就行。",
    "w": ["腾讯企业邮箱", "QQ 邮箱", "163 邮箱", "Gmail", "iCloud", "Fastmail", "任何 IMAP 邮箱"],
    "q_kick": "常见问题", "q_h2": "你可能想问。",
    "q": [
        ("腾讯企业邮箱有没有搜索好用的 Mac / Windows 客户端？",
         "有，就是这个。我们拿一个真实的企业邮箱试过，里面有 6,442 封邮件。邮箱自带的搜索不管输入什么词，都返回 4,988 封，"
         "连随手编的词也一样。Ragdoll Mail 只返回真正含这个词的邮件，用时不到 0.1 秒。"),
        ("我的邮件安全吗？", "邮件只存在两个地方：你的电脑，和你自己的邮箱服务器。软件不会把任何东西发给我们，我们根本没有服务器。"),
        ("密码存在哪里？", "存在系统自带的密码库里：Mac 的“钥匙串”，Windows 的“凭据管理器”。不会写进任何文件。"),
        ("登录要用哪个密码？", "很多邮箱要给邮件软件单独设一个密码：腾讯企业邮箱叫“客户端专用密码”，QQ 邮箱和 163 叫“授权码”，"
         "Gmail、iCloud 和 Fastmail 叫 app password。在邮箱网页版的设置里生成。"),
        ("没有网能用吗？", "看已经收下来的邮件、搜索邮件：可以。发邮件和收新邮件要联网。"),
        ("真的免费吗？", "真的。没有广告，不用订阅，也不用注册。代码按 MIT 许可开源，谁都可以查它做了什么。"),
    ],
    "e_h2": "用你自己的邮箱试试。", "e_sub": "免费，不用注册，没有广告。",
    "foot": ["源代码", "命令行", "反馈问题", "腾讯企业邮箱设置"],
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
    <a class="hide-s" href="#features">{e(L['nav'][0])}</a>
    <a class="hide-s" href="#ai">{e(L['nav'][1])}</a>
    <a class="hide-s" href="#questions">{e(L['nav'][2])}</a>
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
  </div>
</div>

<section id="search"><div class="wrap">
  <div class="center reveal">
    <div class="kicker">{e(L['s_kick'])}</div>
    <h2>{L['s_h2']}</h2>
    <p class="sub">{e(L['s_sub'])}</p>
  </div>
  <div class="race reveal" aria-label="{e(L['s_kick'])}">
    <div class="race-q">{icon('search')}<span class="typed"></span><span class="caret"></span></div>
    <div class="race-cols">
      <div class="race-col theirs"><h3><span class="dot"></span>{e(L['theirs'])}</h3>
        <div class="count">0</div><div class="count-note"></div><div class="rows blur"></div></div>
      <div class="race-col ours"><h3><span class="dot"></span>{e(L['ours'])}</h3>
        <div class="count">0</div><div class="count-note"></div><div class="rows"></div></div>
    </div>
    <div class="race-foot">{e(L['race_foot'])}</div>
  </div>
  <script type="application/json" id="race-data">{json.dumps(L['race'], ensure_ascii=False)}</script>
</div></section>

<section id="features"><div class="wrap">
  <div class="reveal">
    <div class="kicker">{e(L['f_kick'])}</div>
    <h2>{e(L['f_h2'])}</h2>
  </div>
  <div class="grid">
    {tile(0, 't-wide', f'<div class="peek"><img src="{up}img/search-light.webp" alt="" loading="lazy" width="1800" height="1161"></div>')}
    {tile(1, 't-narrow', f'<div class="path"><span>{e(L["route"][0])}</span><i></i><span>{e(L["route"][1])}</span></div><div class="path-x">{e(L["route"][2])}</div>')}
    {tile(2, 't-narrow', f'<div class="undo">{e(L["sending"])}<span class="bar"><i></i></span><a href="#features">{e(L["undo"])}</a></div><div class="warn">{e(L["warn"])}</div>')}
    {tile(3, 't-wide', f'<div class="peek peek-r"><img src="{up}img/compose-light.webp" alt="" loading="lazy" width="1800" height="1161"></div>')}
    {tile(4, 't-third')}
    {tile(5, 't-third')}
    {tile(6, 't-third')}
  </div>
</div></section>

<section id="ai"><div class="wrap">
  <div class="grid" style="margin-top:0;align-items:center">
    <div class="reveal" style="grid-column:span 5">
      <div class="kicker">{e(L['a_kick'])}</div>
      <h2>{L['a_h2']}</h2>
      <p class="sub">{L['a_sub']}</p>
      <p class="sub" style="font-size:15.5px">{e(L['a_how'])} <a href="{REPO}/blob/main/docs/command-line.md" style="color:var(--accent-ink)">{e(L['a_guide'])} →</a></p>
    </div>
    <div class="reveal" style="grid-column:span 7"><div class="term-win"><div class="term-bar"><b></b><b></b><b></b></div><div class="term" role="img" aria-label="{e(L['a_kick'])}">{chr(10).join(term)}</div></div></div>
  </div>
</div></section>

<section id="works"><div class="wrap center reveal">
  <div class="kicker">{e(L['w_kick'])}</div>
  <h2>{e(L['w_h2'])}</h2>
  <div class="chips">{''.join('<span class="chip%s">%s</span>' % (' hl' if i == 0 else '', e(x)) for i, x in enumerate(L['w']))}</div>
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


def guide(G):
    e = html.escape
    up = "../" * G["path"].count("/")
    url = SITE + G["path"]
    other_url = SITE + ("zh/exmail/" if G["lang"] == "en" else "exmail/")
    ld = [
        {"@context": "https://schema.org", "@type": "HowTo", "name": G["h1"], "description": G["desc"],
         "inLanguage": G["lang"], "url": url,
         "step": [{"@type": "HowToStep", "position": i + 1, "name": h, "text": t} for i, (h, t) in enumerate(G["steps"])]},
        {"@context": "https://schema.org", "@type": "FAQPage", "inLanguage": G["lang"],
         "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in G["q"]]},
        {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Ragdoll Mail", "item": SITE + ("" if G["lang"] == "en" else "zh/")},
            {"@type": "ListItem", "position": 2, "name": G["kick"], "item": url}]},
    ]
    dl = lambda os_, cls: ('<a class="btn %s" data-os="%s" href="%s">%s%s <small>%s</small></a>' % (  # noqa: E731
        cls, os_, DL + ("ragdoll-mail-mac.dmg" if os_ == "mac" else "ragdoll-mail-windows.zip"),
        icon("download"), e(G[os_][0]), e(G[os_][1])))
    steps = "".join('<li><h3>%s</h3><p>%s</p></li>' % (e(h), e(t)) for h, t in G["steps"])
    rows = "".join("<tr><th>%s</th><td><code>%s</code></td><td>%s</td><td>%s</td></tr>" % tuple(map(e, r)) for r in G["srv"])
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
<link rel="alternate" hreflang="x-default" href="{SITE}exmail/">
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

  <h2>{e(G['steps_h'])}</h2>
  <ol class="steps">{steps}</ol>

  <h2>{e(G['srv_h'])}</h2>
  <p class="sub">{e(G['srv_sub'])}</p>
  <div class="table"><table>
    <thead><tr>{''.join('<th>%s</th>' % e(c) for c in G['srv_cols'])}</tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
  <p class="note">{e(G['srv_user'])}</p>

  <h2>{e(G['why_h'])}</h2>
  {''.join('<p class="sub">%s</p>' % e(x) for x in G['why'])}

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


PAGES = [("", "zh/"), ("exmail/", "zh/exmail/")]


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
    jobs = [(L["path"], page(L)) for L in (EN, ZH)] + [(G["path"], guide(G)) for G in (GUIDE_EN, GUIDE_ZH)]
    for path, text in jobs:
        out = os.path.join(HERE, path, "index.html")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
        print("wrote", os.path.relpath(out, HERE))
    with open(os.path.join(HERE, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write(sitemap())
    print("wrote sitemap.xml")
