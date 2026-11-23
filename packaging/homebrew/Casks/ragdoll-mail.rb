# Homebrew cask for Ragdoll Mail. It lives in the tap erict16/homebrew-tap:
#   brew install --cask erict16/tap/ragdoll-mail
# packaging/bump.py fills in version and sha256 from a release.
cask "ragdoll-mail" do
  version "0.11.0"
  sha256 "32ba596d6a139049748ce669d2b4b418e189a234475fee55f7e8226533d67be9"

  url "https://github.com/erict16/ragdoll-mail/releases/download/v#{version}/ragdoll-mail-mac.dmg"
  name "Ragdoll Mail"
  desc "Mail app with instant local search for IMAP mailboxes and a command-line tool"
  homepage "https://erict16.github.io/ragdoll-mail/"

  livecheck do
    url :url
    strategy :github_latest
  end

  depends_on :macos

  app "Ragdoll Mail.app"
  # the app's own program is also the command line: ragdoll-mail cli ...
  binary "#{staged_path}/ragdoll.sh", target: "ragdoll"

  preflight_steps do
    write_file "ragdoll.sh", <<~EOS, base: :staged_path
      #!/bin/sh
      for dir in /Applications "$HOME/Applications"; do
        app="$dir/Ragdoll Mail.app/Contents/MacOS/ragdoll-mail"
        [ -x "$app" ] && exec "$app" cli "$@"
      done
      echo "ragdoll: Ragdoll Mail.app is not in /Applications" >&2
      exit 1
    EOS
    set_permissions "ragdoll.sh", "0755", base: :staged_path
  end

  zap trash: [
    "~/.config/ragdoll-mail",
    "~/.local/share/ragdoll-mail",
  ]

  caveats <<~EOS
    Ragdoll Mail is not signed by Apple yet. The first time macOS says it
    could not check the app, open System Settings > Privacy & Security and
    press Open Anyway.
  EOS
end
