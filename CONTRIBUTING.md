# Contributing to ragdoll-mail

Thank you for helping. Bug reports, mail servers that behave oddly, translations and pull requests are all welcome.

## Report a problem

Open an [issue](https://github.com/erict16/ragdoll-mail/issues/new/choose). Give the version (`ragdoll --version`), your system and your mail server. Remove addresses and mail text you do not want to share.

## Change the code

1. Fork and clone the repository.
2. Run the tests. They are offline and need no mail account:
   ```
   python -m unittest discover -s tests
   ```
3. Try the app without an account: `python ragdoll.py app --demo`. `python tests/ui_smoke.py` opens that demo in the real window and clicks through it.
4. Keep `ragdoll.py` on the Python standard library. The desktop app may use `pywebview`. The app's server is in `ragdoll_app/` (one file per feature) and the page in `app/` (one file per part in `app/js/`).
5. Add or change a test for what you fixed, then open a pull request that says what changed and why.

## Translate the app

The app strings are in `app/i18n.js`. Add a `LANGS["xx"]` block like the others and its name to `LANG_NAMES`, then open a pull request. A missing key falls back to English, so a partial translation is fine.

## Rules that do not change

- Nothing is sent without a person saying yes. `send`, `trash` and `delete-draft` keep `--yes`.
- The password never goes into a file or the output.
- Mail stays on the user's computer and their own mail server.
