# SlideBridge Homebrew Tap 配置指南

本目錄包含供 Homebrew 使用的 Formula 與 Cask 模板，讓 Mac 使用者能透過標準的 `brew` 指令安裝 SlideBridge。

---

## 快速發布方式（建立自託管 Tap 倉庫）

1. **在 GitHub 上建立 Tap 倉庫**：
   - 倉庫名稱必須為：`homebrew-slidebridge`（例如 `https://github.com/<your-username>/homebrew-slidebridge`）。
2. **複製定義檔案至該倉庫**：
   - 將本目錄下的結構直接提交至該倉庫：
     ```text
     homebrew-slidebridge/
     ├── Formula/
     │   └── slidebridge.rb
     └── Casks/
         └── slidebridge.rb
     ```
3. **發布 Release 並更新 SHA256**：
   - 當 SlideBridge 發布 Release Tag（如 `v0.1.0`）並上傳原始碼壓縮檔與 `SlideBridge-v0.1.0.zip` 後：
   - 計算 SHA256：
     ```sh
     curl -sL https://github.com/<your-username>/SlideBridge/archive/refs/tags/v0.1.0.tar.gz | shasum -a 256
     curl -sL https://github.com/<your-username>/SlideBridge/releases/download/v0.1.0/SlideBridge-v0.1.0.zip | shasum -a 256
     ```
   - 分別填入 `Formula/slidebridge.rb` 與 `Casks/slidebridge.rb` 中的 `sha256` 欄位並提交。

---

## 使用者端安裝體驗

一旦 Tap 倉庫建立完成，使用者只需執行：

```sh
# 訂閱您的 Tap 倉庫
brew tap <your-username>/slidebridge

# 方案 A：安裝 CLI 指令工具
brew install slidebridge

# 方案 B：安裝 macOS 原生桌面應用（SlideBridge.app）
brew install --cask slidebridge
```
