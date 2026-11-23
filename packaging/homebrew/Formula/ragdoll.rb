# Homebrew formula for the ragdoll command alone (no app, so no Apple signature is needed).
# It lives in the tap erict16/homebrew-tap:  brew install erict16/tap/ragdoll
# packaging/bump.py fills in url and sha256 from a release.
class Ragdoll < Formula
  desc "Search, read and draft IMAP mail from the terminal, for you and AI agents"
  homepage "https://erict16.github.io/ragdoll-mail/"
  url "https://github.com/erict16/ragdoll-mail/archive/refs/tags/v0.11.1.tar.gz"
  sha256 "169744c3d7c46bf087d3a069640e292599e14c570af09a0fa08bcb75f7452972"
  license "MIT"

  livecheck do
    url :stable
    strategy :github_latest
  end

  depends_on "python@3.13"

  def install
    # one file and the standard library: nothing to build
    libexec.install "ragdoll.py", "hmail.py"
    (bin/"ragdoll").write <<~SH
      #!/bin/sh
      exec "#{formula_opt_bin("python@3.13")}/python3.13" -I "#{libexec}/ragdoll.py" "$@"
    SH
  end

  def caveats
    <<~EOS
      Sign in once: copy the example config from
        https://github.com/erict16/ragdoll-mail/blob/main/config.example.json
      to ~/.config/ragdoll-mail/config.json, or sign in with the Ragdoll Mail app
      (brew install --cask ragdoll-mail), which shares its config and index.
      If the app is installed with the cask, it already gives you `ragdoll`.
      Guide: https://github.com/erict16/ragdoll-mail/blob/main/docs/command-line.md
    EOS
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/ragdoll --version")
  end
end
