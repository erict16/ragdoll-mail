# ragdoll: your mailbox from the terminal, for you and your AI agent

`ragdoll` is the command line of [Ragdoll Mail](https://erict16.github.io/ragdoll-mail/), a free, open-source mail app for Mac and Windows. It works with any IMAP mailbox. You can search, read whole threads, write reply drafts, check them and send them. Claude Code, Codex or any other agent that runs commands can do the same, so the agent and you work on the same mailbox.

```console
you    › Reply to Lucas and tell him the first batch ships on the 4th.

agent  $ ragdoll search Lucas "PO-1234" --json
agent  $ ragdoll draft --reply inbox:312 --body reply.html
agent  $ ragdoll check drafts:14 --reply
         CHECK OK
agent  › The draft is in your Drafts folder. Shall I send it?
```

Search runs on a local SQLite index, not on the mail server. On a real inbox of 5,044 mails, a search took 6 ms locally. The same search through the server took about a second, because the CLI had to sign in again first.

Drafts are saved in your mailbox's real Drafts folder, with your signature and the quoted thread. `check` catches an empty subject, "attached" with nothing attached, or a `[Name]` left in the text. `send` needs `--yes`, and the same draft is never sent twice. There is no API key, no OAuth app and no quota: ragdoll talks plain IMAP and SMTP to your own server.

## Install

```sh
pipx install ragdoll-mail
```

Python 3.10 or newer; it uses only the standard library. Update with `pipx upgrade ragdoll-mail`.

On a Mac you can also use Homebrew (`brew tap erict16/tap`, `brew trust erict16/tap`, `brew install ragdoll`), or get the desktop app, which comes with the command.

## Set up

1. Copy [config.example.json](https://github.com/erict16/ragdoll-mail/blob/main/config.example.json) to `~/.config/ragdoll-mail/config.json` and fill in your mailbox.
2. Put the IMAP app password in the environment variable that `password_env` names, or sign in once in the desktop app, which keeps it in the system keychain. ragdoll never prints it.
3. Build the index once: `ragdoll sync --bodies`. Later commands fetch only what is new.

Every command, and a paragraph to put in your `CLAUDE.md` or `AGENTS.md`, is in [the command-line guide](https://github.com/erict16/ragdoll-mail/blob/main/docs/command-line.md).

MIT licence. Source: [github.com/erict16/ragdoll-mail](https://github.com/erict16/ragdoll-mail).
