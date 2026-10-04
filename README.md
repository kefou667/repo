# kefou源

个人自用 iOS 越狱源，使用 GitHub Pages + GitHub Actions。

源地址：

`https://kefou.github.io/Sileo/`

## 添加插件

把 rootless `.deb` 放进 `debs/`，然后提交到 `main`。

GitHub Actions 会自动：

1. 解析 `.deb` 的 control 信息
2. 生成 `Packages`
3. 生成 `Packages.gz`
4. 生成 `Packages.bz2`
5. 生成基础 Sileo Depiction
6. 自动提交索引文件

## Rootless

本源面向 rootless 越狱环境。请只上传已经制作成 rootless 的 `.deb`。

常见架构：
- `iphoneos-arm64`
- `iphoneos-arm64e`

脚本不会仅凭 Architecture 判断一个包是否真正 rootless；是否 rootless 仍取决于 `.deb` 内部安装路径和打包方式。

## GitHub Pages

仓库 Settings → Pages：

- Source: Deploy from a branch
- Branch: `main`
- Folder: `/ (root)`

然后在 Sileo / Zebra 中添加：

`https://kefou.github.io/Sileo/`
