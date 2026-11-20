#!/usr/bin/env python3
"""Make the site's pages from one template: python3 site/build.py  (writes index.html and zh/index.html).
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
    "shot_alt": "Ragdoll Mail showing the inbox and an open mail with two attachments",
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
    "foot": ["Source code", "Command line", "Report a problem"],
}

ZH = dict(EN, **{
    "lang": "zh-Hans", "path": "zh/", "other": "../", "other_name": "English", "hreflang": "en",
    "title": "Ragdoll Mail：免费的 Mac / Windows 邮件客户端，腾讯企业邮箱也能秒搜",
    "desc": "免费开源的 Mac 和 Windows 邮件软件。本地索引，搜索秒出结果。支持腾讯企业邮箱、QQ 邮箱、163、Gmail、iCloud "
            "和任何 IMAP 邮箱。邮件只在你电脑上，断网也能搜。",
    "nav": ["功能", "AI 助手", "常见问题"], "download": "下载",
    "pill": ["免费", "开源", "Mac 和 Windows"],
    "h1": "邮件，<em>一搜就到</em>。",
    "lead": "用你现在的邮箱登录就行。腾讯企业邮箱、QQ 邮箱、163、Gmail、iCloud，还有任何 IMAP 邮箱都能用。",
    "mac": ["下载 Mac 版", "M 系列芯片"], "win": ["下载 Windows 版", "Windows 10 / 11"],
    "first": "还没有苹果和微软的签名。第一次打开时：Mac 在 系统设置 → 隐私与安全性 里点“仍要打开”；Windows 点“更多信息 → 仍要运行”。",
    "shot_alt": "Ragdoll Mail 的收件箱，打开了一封带两个附件的邮件",
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
    "foot": ["源代码", "命令行", "反馈问题"],
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
<meta property="og:image" content="{SITE}img/og.png">
<meta name="twitter:card" content="summary_large_image">
<link rel="stylesheet" href="{up}style.css">
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
    <picture>
      <source srcset="{up}img/hero-dark.webp" media="(prefers-color-scheme: dark)">
      <img src="{up}img/hero-light.webp" alt="{e(L['shot_alt'])}" width="1800" height="1161" fetchpriority="high">
    </picture>
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
  <a href="{L['other']}" hreflang="{L['hreflang']}">{e(L['other_name'])}</a>
</div></footer>
<script src="{up}main.js" defer></script>
</body>
</html>
"""


if __name__ == "__main__":
    for L in (EN, ZH):
        out = os.path.join(HERE, L["path"], "index.html")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(page(L))
        print("wrote", os.path.relpath(out, HERE))
