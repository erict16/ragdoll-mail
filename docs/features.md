# Everything the app does

[Back to the front page](../README.md)

**Read**
- Whole conversations on one page, newest mail on top. Long quoted history folds away.
- Search everything with ⌘K / Ctrl+K: `from:jane`, `in:sent`, `is:unread`, `has:attachment`, or any words.
- Star mail with **S** and find it again in **Starred**. Select many rows with ⌘/Ctrl or Shift and act on them at once.
- Your own folders and **Junk** in the sidebar. Move mail into a folder from the toolbar, or drag it there.
- **Snooze** a mail with **B**: it leaves the Inbox and comes back on top, unread, at the time you pick.
- **Meeting invites** show what, when and where. Answer with Accept, Maybe or Decline, or hand the invite to your calendar app.
- A desktop notification when new mail comes in while the app is in the background. Click it to open that mail. If you like, the unread count shows on the Dock or taskbar icon too. Both are in Settings → Notifications.
- New mail and changes show at once: the app waits for them instead of checking every few seconds.
- Long lists stay quick: scroll through thousands of mails or search results, and new mail does not move your place.
- Pictures from the internet stay hidden until you ask for them.
- Text size from ⌘− to ⌘+, for the list and the reader together.

**Write**
- A real editor: font and size, bold, italic, underline, lists, quotes and links. Paste from Word or a web page and only the formatting that mail clients show is kept.
- Your signature, made in Settings with the same editor, goes under every new mail, reply and forward.
- A default font and size for every mail you write.
- **Templates** for the answers you write often: make them in Settings, put one into a mail with two clicks.
- Reply, reply all and forward keep the quoted history and its inline images.
- A check before sending: empty To or subject, a missing attachment the text talks about, placeholders such as `[Name]` or `TBD`, broken characters.

**Send on your terms**
- **Undo send:** the mail waits 5, 10, 20 or 30 seconds (your choice) before it leaves. Press Undo and it goes back to the editor.
- **Send later:** this evening, tomorrow morning, Monday, or any date and time. Scheduled mail waits in **Scheduled**, where you can change it, send it now, or cancel it.
- **No connection?** Press Send anyway. The mail waits in **Scheduled** and goes out by itself when you are back online.
- **Plain truth about recall:** once a mail has left your computer, no app can take it back from the other person's inbox. ragdoll gives you the undo window and scheduled send instead, so you can stop a mail before it goes.

**Make it yours**
- Light, dark, or follow the system. One clean window on Mac and Windows, with no separate title bar. Drag the edges of the sidebar and the list to the widths you like.
- English, 简体中文, 繁體中文, 日本語, 한국어, Español, Français, Deutsch.
- Show times in any time zone.
- Keyboard first: **J/K** move, **R** reply, **A** reply all, **F** forward, **E** archive, **#** delete, **U** unread, **B** snooze, **C** new mail. Press **?** to see them all.
- A new version shows what changed. From a git clone, one click updates and restarts the app; the packaged app downloads the new file. You can skip a version.
- Small windows get a slim icon sidebar; very small ones show the list and the mail one at a time.

**Private by design**
- Mail is indexed on your computer. The app talks to your own mail server, and to GitHub only to ask whether a new version is out.
- The password is kept in the macOS Keychain or the Windows Credential Manager, never in a file.
- The app only listens on 127.0.0.1, and every call needs a random token made at start.

**Made for mail in Chinese, too**
- Text in GB2312, GBK, GB18030 and Big5 is read with the superset codecs, so names such as 陈喆 labelled GB2312 stay intact.
- Raw 8-bit GBK headers and file names are repaired, and an unknown charset never stops a sync.
- Presets for Tencent Exmail, QQ Mail and NetEase 163, next to Gmail, iCloud and Fastmail.

**Good to know**
- Snoozed mail and templates are kept on this computer only; your phone's mail app does not see them.
- Scheduled mail leaves from this computer, so the app must be open at that time.
- Everything else (read, starred, moved, sent, drafts) is on your mail server, so other mail apps show the same.
