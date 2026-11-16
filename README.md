# ragdoll-mail

`hmail`: a mail command line for one IMAP/SMTP mailbox, made to be driven by an AI agent (Claude Code) and checked by a person. One Python file, standard library only, Windows and macOS.

Why it exists: Tencent Exmail ignores IMAP text search (every `SEARCH SUBJECT/FROM/BODY` returns the whole mailbox), and API-based clients ran out of quota. hmail keeps its own SQLite index with trigram full-text search, so Chinese and English both work, and does drafts the way a person would: signature, quoted history with its images, attachments, then a check before anything is sent.

## Setup

1. Python 3.10+ (SQLite 3.34+ for the trigram index; the python.org builds have it).
2. Copy `config.example.json` to `~/.config/hmail/config.json` and fill it in.
3. Put the IMAP app password in the environment variable named by `password_env`. Windows (stays set for new programs):
   ```powershell
   [Environment]::SetEnvironmentVariable('HMAIL_PASSWORD', '<password>', 'User')
   ```
   macOS: `export HMAIL_PASSWORD=...` in your shell profile. hmail never prints it.
4. First index: `python hmail.py sync --bodies` (headers first, then bodies on 4 connections). Later commands only fetch what is new.

## Commands

```
python hmail.py status
python hmail.py search E-W260084 越南 --since 2026-11-01 --att
python hmail.py thread inbox:9255
python hmail.py read inbox:9255 --new
python hmail.py attach inbox:9255 --out ./files
python hmail.py draft --reply inbox:9255 --all --cc a@b.com --body body.html --attach file.pdf
python hmail.py check drafts:12 --reply
python hmail.py send drafts:12 --yes
```

`python hmail.py --help` lists every option. Ids are `<folder>:<uid>`. Add `--json` for machine output.

### How drafts work

`draft` writes only the new text you give it, then adds the signature file, a quote header and the original mail (with its inline images), and saves the result in the server's Drafts folder, so it shows up in the normal mail apps. To change a draft, build it again with `--replace drafts:<old>`. `check` fails on a missing signature or quote, a lost image, an empty To or subject, the sender as a recipient, a missing required Cc, garbled characters (�) in names, subject, text or file names, placeholders left in the text (`[Name]`, `XXX`, `TBD`, `待定`; `--blanks-ok` to allow), text that mentions an attachment when none is attached (`--attach-ok` to allow), and email tables that will render badly. `send` sends a draft over SMTP with the current date, makes sure one copy is in Sent (Exmail files its own and rewrites the Message-ID as `<XXXX+id>`), deletes the draft and marks the original answered. Every sent Message-ID goes to `sent.log` in the data dir; sending the same draft again is refused, and if tidying up fails after the mail went out, the output says so instead of inviting a second send. `--replace`, `send` and `delete-draft` only touch the Drafts folder.

Text in GB2312, GBK, GB18030 and Big5 is read with the superset codecs (GB18030, cp950), so names such as 赵珺 labelled GB2312 stay intact; raw 8-bit GBK headers and file names are repaired, unknown charsets never stop a sync, and an attached mail (message/rfc822) is kept as one .eml attachment.

## Updates

hmail updates itself the careful way (the model is S2Arm's updater):

- **It looks, it does not touch.** At most every 6 hours a command starts a quiet background check (`git fetch` of `main`, never asks for a password, never slows the command). When a newer version is waiting, commands print one line on stderr: `hmail 0.3.1 is out (2 change(s); this is 0.3.0). Run: hmail update`. No network, no line. `status` shows `version` and `update_available`.
- **It replaces only when asked:** `hmail update` (`--check` only says what is new). It refuses while another hmail command runs (a sync, a send), when the clone has changed files, is not on `main`, or has commits that are not on GitHub.
- **It tests before it keeps.** After the fast-forward it runs `hmail.py --version` and the offline tests of the new version. If they fail, it puts the old version back by itself and says why.
- **It says what changed** (the commit titles) and logs every step to `<data dir>/logs/update.log`.
- **One step back:** `hmail update --rollback` returns to the version before the last update and stops offering the one you left.

Off: `"update_check": false` in the config, or `HMAIL_NO_UPDATE_CHECK=1`. `HMAIL_UPDATE_REMOTE` points the check at another remote (for testing). Updating needs a git clone; a copied `hmail.py` only says so.

## Tests

```
python -m unittest discover -s tests
```

The tests are offline; they build and check messages without a server.
