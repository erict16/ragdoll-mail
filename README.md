# hmail

A mail command line for one IMAP/SMTP mailbox, made to be driven by an AI agent (Claude Code) and checked by a person. One Python file, standard library only, Windows and macOS.

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

`draft` writes only the new text you give it, then adds the signature file, a quote header and the original mail (with its inline images), and saves the result in the server's Drafts folder, so it shows up in the normal mail apps. To change a draft, build it again with `--replace drafts:<old>`. `check` fails on a missing signature or quote, a lost image, an empty To, the sender as a recipient, a missing required Cc, and email tables that will render badly. `send` sends a draft over SMTP, makes sure one copy is in Sent, deletes the draft and marks the original answered.

## Tests

```
python -m unittest discover -s tests
```

The tests are offline; they build and check messages without a server.
