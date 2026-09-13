class Slidebridge < Formula
  include Language::Python::Virtualenv

  desc "Repair PowerPoint metafile previews while preserving embedded OLE data"
  homepage "https://github.com/Earth10514TW/SlideBridge"
  url "https://github.com/Earth10514TW/SlideBridge/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "REPLACE_WITH_SOURCE_TARBALL_SHA256"
  license "GPL-2.0-only"
  head "https://github.com/Earth10514TW/SlideBridge.git", branch: "main"

  depends_on "python@3.12"
  depends_on "resvg"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "slidebridge", shell_output("#{bin}/slidebridge --help")
  end
end
