# Security policy

## Supported versions

Only the newest release gets security fixes. Update with **Check for updates** in the app, `brew upgrade --cask ragdoll-mail`, or the [latest release](https://github.com/erict16/ragdoll-mail/releases/latest).

## Report a vulnerability

Please do not open a public issue for a security problem.

Report it privately: open the repository's **Security** tab and press **Report a vulnerability** ([direct link](https://github.com/erict16/ragdoll-mail/security/advisories/new)). Only the maintainer can see the report.

Please include:

- what an attacker can do, and what they need first (a mail they send you, access to your computer, and so on)
- the steps to make it happen, and the version and system you used
- a proof of concept, if you have one

You get an answer within 7 days. When the fix is released, the advisory is published, with credit to you if you want it.

## What is in scope

- The Ragdoll Mail app and the `ragdoll` command in this repository
- How they handle mail from strangers: HTML, attachments, calendar invitations, headers
- Where the app keeps your password and your mail on disk
- The website in `site/`

Problems in your mail server or in Tencent Exmail, Gmail and other providers belong with those providers.
