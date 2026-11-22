#!/usr/bin/env python3
"""Point the Homebrew cask, the Homebrew formula and the winget manifests at a release.

    python3 packaging/bump.py            # the version in pyproject.toml
    python3 packaging/bump.py 0.10.0

It takes each file's SHA-256 from the release on GitHub (the API gives every asset a digest).
When the API has none, it downloads the file and hashes it itself.
"""
import hashlib, json, os, re, sys, urllib.request

REPO = "erict16/ragdoll-mail"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FILES = {"mac": "ragdoll-mail-mac.dmg", "win": "ragdoll-mail-windows.zip"}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "ragdoll-mail-bump"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def sums(version):
    base = "https://github.com/%s/releases/download/v%s/" % (REPO, version)
    found = {}
    try:
        rel = json.loads(get("https://api.github.com/repos/%s/releases/tags/v%s" % (REPO, version)))
        for asset in rel.get("assets", []):
            algo, _, digest = (asset.get("digest") or "").partition(":")
            if algo == "sha256" and re.fullmatch(r"[0-9a-f]{64}", digest):
                found[asset["name"]] = digest
    except Exception as e:
        print("no digests from the GitHub API (%s)" % e, file=sys.stderr)
    for name in FILES.values():
        if name not in found:
            print("hashing", name, "...", file=sys.stderr)
            found[name] = hashlib.sha256(get(base + name)).hexdigest()
    return found


def rewrite(path, pairs):
    s = open(path, encoding="utf-8").read()
    for pat, new in pairs:
        s, n = re.subn(pat, new, s, flags=re.M)
        if not n:
            sys.exit("%s: nothing matched %s" % (path, pat))
    open(path, "w", encoding="utf-8").write(s)


def main():
    if len(sys.argv) > 1:
        version = sys.argv[1].lstrip("v")
    else:
        version = re.search(r'^version = "(.+)"', open(os.path.join(ROOT, "pyproject.toml")).read(), re.M).group(1)
    h = sums(version)
    rewrite(os.path.join(HERE, "homebrew", "Casks", "ragdoll-mail.rb"), [
        (r'^  version ".*"', '  version "%s"' % version),
        (r'^  sha256 ".*"', '  sha256 "%s"' % h[FILES["mac"]]),
    ])
    # the formula builds from the tag's source archive (GitHub makes it; its hash is stable)
    src = get("https://github.com/%s/archive/refs/tags/v%s.tar.gz" % (REPO, version))
    rewrite(os.path.join(HERE, "homebrew", "Formula", "ragdoll.rb"), [
        (r'/tags/v[^/]+\.tar\.gz"', '/tags/v%s.tar.gz"' % version),
        (r'^  sha256 ".*"', '  sha256 "%s"' % hashlib.sha256(src).hexdigest()),
    ])
    wg = os.path.join(HERE, "winget")
    for f in sorted(os.listdir(wg)):
        if f.endswith(".yaml"):
            pairs = [(r"^PackageVersion: .*", "PackageVersion: " + version)]
            if f.endswith(".installer.yaml"):
                pairs += [(r"/download/v[^/]+/", "/download/v%s/" % version),
                          (r"^    InstallerSha256: .*", "    InstallerSha256: " + h[FILES["win"]].upper())]
            rewrite(os.path.join(wg, f), pairs)
    print("cask, formula and winget now point at v%s" % version)


if __name__ == "__main__":
    main()
