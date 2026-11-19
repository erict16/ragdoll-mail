# The command line, for you and your AI agent

`ragdoll` is the same mailbox from the terminal. One Python file, standard library only, Windows and macOS. Every command has `--json` output, so an agent (Claude Code, Codex, or any script) can use the same fast search as the app.

[Back to the front page](../README.md)

## Agents draft. You send.

```console
you    › Reply to Lucas, attach the certificate of origin, cc Bao.

agent  $ ragdoll search Lucas "certificate of origin" --since 2026-11-01 --json
agent  $ ragdoll thread inbox:312 --json
agent  $ ragdoll draft --reply inbox:312 --cc bao.tran@saigon-grid.example \
              --body reply.html --attach CO-4471.pdf
agent  $ ragdoll check drafts:14 --reply
         To:      Lucas Martin <lucas.martin@blueharbor.example>
         Cc:      bao.tran@saigon-grid.example
         Subject: Re: Order 4471 - shipping documents
         Attach:  CO-4471.pdf (212 KB)
         CHECK OK

agent  › The draft is in your Drafts folder. Shall I send it?
you    › Yes.
agent  $ ragdoll send drafts:14 --yes
```

Every step is a plain command, so any agent can learn it from `ragdoll --help`. Nothing leaves your computer until a person says so:

- **Drafts go where you can see them.** `draft` saves to your server's real Drafts folder, with your signature, the quoted history and its inline images. Open it in ragdoll, your phone or any mail app before anything is sent.
- **A check before every send.** `check` fails on an empty To or subject, a missing signature, lost images, garbled characters (�), the sender as a recipient, a missing required Cc, placeholders such as `[Name]`, `XXX` or `TBD` left in the text, and text that says "attached" when nothing is.
- **No double sends.** Every sent Message-ID is logged. Sending the same draft twice is refused. If tidying up fails after a mail has gone, ragdoll says so instead of inviting a second send.
- **Nothing is destroyed by accident.** `send`, `trash` and `delete-draft` need `--yes`. Trash moves mail to the Trash folder, where you can get it back.
- **No API quota, no OAuth app, no vendor.** ragdoll talks plain IMAP and SMTP to your own mail server. The password stays in the system keychain and is never printed.

### Teach your agent in one paragraph

Put this in your `CLAUDE.md`, `AGENTS.md` or system prompt:

```markdown
Mail: use the `ragdoll` command (`ragdoll --help` lists everything; add --json).
Find with `search` / `thread`, read with `read --new`, write with `draft --reply <id>`,
then run `check <draft id> --reply` and fix every problem. Never run `send` until I
have said yes to that draft.
```

## Search that works

A real mailbox on Tencent Exmail, 6,442 mails, searched both ways:

| Search for | The server's IMAP search | ragdoll |
|---|---|---|
| `invoice` | 4,988 results (the whole inbox) | the matching mails, 15 ms |
| `certificate origin` | 4,988 results (the whole inbox) | the matching mails, 8 ms |
| `报价` (Chinese: "quotation") | 4,988 results (the whole inbox) | the matching mails, 23 ms |
| `nonexistentzzq` (a made-up word) | 4,988 results (the whole inbox) | none, 0.4 ms |

<sub>Measured 18 Nov 2026 on Windows 11. ragdoll times are the search itself, best of 5, on a 382 MB index.</sub>

- **One index, every part of a mail.** Subject, sender, recipients, attachment file names and the full body text, in a SQLite FTS5 trigram index.
- **Chinese, Japanese and Korean too.** Trigrams need no word splitting, so `分接开关` or `見積` are found inside running text. Two-letter words such as `PO` or `报价` still work.
- **All words must match,** with filters: `--from`, `--to`, `--since`, `--until`, `--folder`, `--unread`, `--att`. In the app: `from:jane in:sent is:unread has:attachment`.
- **Offline.** On a plane, on a bad hotel network, or when the server is down, search still answers from the index.
- **Your agent gets the same search.** `ragdoll search ... --json` gives an agent exact hits instead of a whole mailbox to read, so it spends fewer tokens and makes fewer mistakes.

## Setup

1. Python 3.10+ (SQLite 3.34+ for the trigram index; the python.org builds have it).
2. Copy `config.example.json` to `~/.config/ragdoll-mail/config.json` and fill it in. Dates use the computer's time zone; add `"utc_offset_hours": 8` (for example) to use a fixed one.
3. Put the IMAP app password in the environment variable named by `password_env` (or sign in once in the desktop app, which saves it in the system keychain). Windows (stays set for new programs):
   ```powershell
   [Environment]::SetEnvironmentVariable('RAGDOLL_PASSWORD', '<password>', 'User')
   ```
   macOS: `export RAGDOLL_PASSWORD=...` in your shell profile. ragdoll never prints it.
4. Make the `ragdoll` command. macOS / Linux (with `~/.local/bin` on your PATH):
   ```sh
   printf '#!/bin/sh\nexec python3 -I "%s/ragdoll.py" "$@"\n' "$PWD" > ~/.local/bin/ragdoll && chmod +x ~/.local/bin/ragdoll
   ```
   Windows: a `ragdoll.cmd` with `@python -I "%USERPROFILE%\Github\ragdoll-mail\ragdoll.py" %*` in a folder on your PATH. `python ragdoll.py ...` always works too.
5. First index: `ragdoll sync --bodies` (headers first, then bodies on 4 connections). Later commands only fetch what is new.

## Commands

```
ragdoll status
ragdoll search PO-1234 报价 --since 2026-11-01 --att
ragdoll thread inbox:9255
ragdoll read inbox:9255 --new
ragdoll attach inbox:9255 --out ./files
ragdoll draft --reply inbox:9255 --all --cc a@b.com --body body.html --attach file.pdf
ragdoll check drafts:12 --reply
ragdoll send drafts:12 --yes
ragdoll app            (the desktop app; add --demo for a made-up mailbox)
```

`ragdoll --help` lists every option. Ids are `<folder>:<uid>`. Add `--json` for machine output.

## How drafts work, in detail

`draft` writes only the new text you give it, then adds the signature file, a quote header and the original mail (with its inline images), and saves the result in the server's Drafts folder, so it shows up in the normal mail apps. To change a draft, build it again with `--replace drafts:<old>`.

`check` fails on a missing signature or quote, a lost image, an empty To or subject, the sender as a recipient, a missing required Cc, garbled characters (�) in names, subject, text or file names, placeholders left in the text (`[Name]`, `XXX`, `TBD`, `待定`; `--blanks-ok` to allow), text that mentions an attachment when none is attached (`--attach-ok` to allow), and email tables that will render badly.

`send` sends a draft over SMTP with the current date, makes sure one copy is in Sent (Exmail files its own and rewrites the Message-ID as `<XXXX+id>`), deletes the draft and marks the original answered. Every sent Message-ID goes to `sent.log` in the data dir; sending the same draft again is refused, and if tidying up fails after the mail went out, the output says so instead of inviting a second send. `--replace`, `send` and `delete-draft` only touch the Drafts folder.

An attached mail (message/rfc822) is kept as one .eml attachment.

## Updates

ragdoll updates itself the careful way (the model is S2Arm's updater):

- **It looks, it does not touch.** At most every 6 hours a command starts a quiet background check (`git fetch` of `main`, never asks for a password, never slows the command). When a newer version is waiting, commands print one line on stderr: `ragdoll 0.4.1 is out (2 change(s); this is 0.4.0). Run: ragdoll update`. No network, no line. `status` shows `version` and `update_available`.
- **It replaces only when asked:** `ragdoll update` (`--check` only says what is new). It refuses while another ragdoll command runs (a sync, a send), when the clone has changed files, is not on `main`, or has commits that are not on GitHub.
- **It tests before it keeps.** After the fast-forward it runs `ragdoll.py --version` and the offline tests of the new version. If they fail, it puts the old version back by itself and says why.
- **It says what changed** (the commit titles) and logs every step to `<data dir>/logs/update.log`.
- **One step back:** `ragdoll update --rollback` returns to the version before the last update and stops offering the one you left.

Off: `"update_check": false` in the config, or `RAGDOLL_NO_UPDATE_CHECK=1`. `RAGDOLL_UPDATE_REMOTE` points the check at another remote (for testing). Updating needs a git clone; a copied `ragdoll.py` only says so.

## Renamed from hmail

Before 0.4.0 the program was `hmail` (`hmail.py`, `~/.config/hmail`, `~/.local/share/hmail`, `HMAIL_*` variables). The first run of 0.4.0 moves both folders to their new names and fixes the paths in the config; the `HMAIL_*` variables still work. `hmail.py` stays as a thin alias so older copies can update and `import hmail` keeps working. `update --rollback` will not go back past the rename.

## How the code is laid out

| Where | What |
|---|---|
| `ragdoll.py` | The command line and the search index. One file, standard library only. |
| `ragdoll_app/` | The desktop app's local server. `backend.py` is the object behind the page; each feature (reading, compose, send later, snooze, invites, templates, settings, updates) is one file. `desktop.py` holds everything that touches the operating system. |
| `app/` | The page: `index.html`, `style.css`, `i18n.js` (the 8 languages), `icons.js`, and one file per part of the page in `app/js/`. |
| `tests/` | Offline tests (`python -m unittest discover -s tests`) and a click-through of the real window (`python tests/ui_smoke.py`). |
