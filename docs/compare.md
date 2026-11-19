# How ragdoll-mail compares

[Back to the front page](../README.md)

|  | **ragdoll** | Thunderbird | Superhuman | Spark | Shortwave | himalaya | NeoMutt / aerc |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Any IMAP mailbox | ✅ | ✅ | Gmail, Outlook | ✅ | Gmail only | ✅ | ✅ |
| Desktop app | ✅ | ✅ | ✅ | ✅ | ✅ | — | terminal UI |
| Command line an agent can drive (`--json`) | ✅ | — | — | — | — | ✅ | — |
| Local full-text search (works when server search doesn't) | ✅ | ✅ | — | — | — | — | with notmuch |
| Checks a draft before it is sent | ✅ | attachment reminder | — | — | — | — | — |
| Mail stays on your computer, no vendor cloud | ✅ | ✅ | — | — | — | ✅ | ✅ |
| Free and open source | ✅ MIT | ✅ | paid | free tier, closed | free tier, closed | ✅ | ✅ |

**In short:** Thunderbird is a great desktop client with no way for an agent in. himalaya is a great CLI with no app for you. Superhuman, Spark and Shortwave are polished, but they run through their own cloud and cost a subscription for the good parts. ragdoll is the one place where you and your agent work on the same mailbox, on your own machine.

## For agents: ragdoll vs. the usual ways in

|  | **ragdoll** | Gmail API / MCP connector | Your own IMAP script |
|---|:---:|:---:|:---:|
| Works with Exmail, QQ, 163, iCloud, Fastmail, any IMAP | ✅ | Gmail only | ✅ |
| No API quota or OAuth app to register | ✅ | — | ✅ |
| Fast local search in Chinese and English | ✅ | server search | write it yourself |
| Replies keep signature, quote and inline images | ✅ | partly | write it yourself |
| Pre-send check and double-send guard | ✅ | — | write it yourself |
| A human app on the same mailbox | ✅ | Gmail web | — |

<sub>Compared from each product's public pages, November 2026. Something wrong or out of date? <a href="https://github.com/erict16/ragdoll-mail/issues">Open an issue</a> and we will fix it.</sub>
