#!/usr/bin/env bash
# 本地编译 APK（Linux / WSL / macOS 必须走 Docker，原生不支持）
# 新手建议直接用 GitHub Actions，不要碰这个脚本。
set -e
echo "=============================================="
echo " AI 写作工作台 · APK 编译"
echo "=============================================="
echo
echo "本机编译需要："
echo "  1. Ubuntu / WSL（Windows 子系统）"
echo "  2. 至少 10GB 可用空间"
echo "  3. 网络通畅（要下载 Android SDK + NDK，约 3GB）"
echo
read -p "确认继续？[y/N] " yn
[[ "$yn" == "y" || "$yn" == "Y" ]] || exit 1

echo ">>> 安装系统依赖..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
  git zip unzip openjdk-11-jdk autoconf libtool pkg-config \
  zlib1g-dev libncurses5-dev libncursesw5-dev libtinfo5 \
  cmake libffi-dev libssl-dev build-essential ccache

echo ">>> 安装 buildozer..."
python3 -m pip install --upgrade pip
pip3 install --upgrade buildozer cython

echo ">>> 开始编译（首次约 30~60 分钟，去喝杯茶）..."
yes | buildozer -v android debug

echo
echo ">>> 完成！APK 在 bin/ 目录："
ls -lh bin/*.apk 2>/dev/null || echo "未找到 APK，请检查上面的错误信息"
