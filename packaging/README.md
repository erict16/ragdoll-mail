# Packaging

Files for installing Ragdoll Mail with a package manager. Nothing here is published by itself.

After each release (the build workflow adds `SHA256SUMS.txt` to it):

```bash
python3 packaging/bump.py
```

This points the cask and the winget files at the version in `pyproject.toml`.

## Homebrew (Mac)

One time: make the public repo `erict16/homebrew-tap` and copy `homebrew/Casks/ragdoll-mail.rb`
into its `Casks/` folder. After that, people install with:

```bash
brew install --cask erict16/tap/ragdoll-mail
```

This also gives them the `ragdoll` command. The main Homebrew list (homebrew/cask) needs an app
that Apple has notarized and a better-known repo, so the tap comes first.

## winget (Windows)

Copy the three files in `winget/` to `manifests/e/erict16/RagdollMail/<version>/` in a fork of
`microsoft/winget-pkgs`, check them with `winget validate`, and open a pull request.
People then install with `winget install erict16.RagdollMail`.
Both `Ragdoll Mail.exe` and the `ragdoll` command come from the same zip.

## PyPI (the command line only)

The name `ragdoll-mail` is free on PyPI. One time:

1. On pypi.org, add a trusted publisher: repo `erict16/ragdoll-mail`, workflow `build.yml`,
   environment `pypi`.
2. In the GitHub repo settings, add the variable `PYPI` with the value `on`.

From the next tag on, the build workflow also publishes to PyPI. People then install with
`pipx install ragdoll-mail`. A pip install updates with pipx or pip, not `ragdoll update`.
