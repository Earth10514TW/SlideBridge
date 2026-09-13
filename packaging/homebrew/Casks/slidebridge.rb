cask "slidebridge" do
  version "0.1.0"
  sha256 "REPLACE_WITH_RELEASE_ZIP_SHA256"

  url "https://github.com/earth/SlideBridge/releases/download/v#{version}/SlideBridge-v#{version}.zip"
  name "SlideBridge"
  desc "Repair PowerPoint EMF previews and bridge Origin OLE editing"
  homepage "https://github.com/earth/SlideBridge"

  depends_on macos: ">= :monterey"

  app "SlideBridge.app"

  zap trash: [
    "~/.slidebridge",
    "~/Library/Application Support/SlideBridge",
    "~/Library/Caches/SlideBridge",
  ]
end
