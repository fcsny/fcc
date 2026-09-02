[app]
title = AI 写作工作台
package.name = aiwriter
package.domain = org.aiwriter.mobile
source.dir = .
source.include_exts = py,png,jpg,jpeg,atlas,json,kv,md,txt,ttf,ttc,otf
source.exclude_patterns = tests/*,__pycache__/*,*.pyc
# 注意：assets/ 不能整个排除——fonts/ 里的兜底中文字体必须打进 APK
source.exclude_dirs = tests,__pycache__,build,.buildozer
# version 由 version.regex 从 main.py 读取，不能再写死
version.regex = __version__ = ['"](.*)['"]
version.filename = %(source.dir)s/main.py
requirements = python3,kivy
orientation = portrait
fullscreen = 0
android.permissions = INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,READ_MEDIA_IMAGES
android.api = 33
# 不锁 NDK：buildozer 会按 android.api 挑匹配版本，锁定反而易崩
android.minapi = 23
android.archs = arm64-v8a
android.allow_backup = True
android.accept_sdk_license = True
# 不锁定分支：p4a 主分支已从 master 迁到 develop，锁死容易拉不到代码
icon.filename = assets/icon.png
presplash.filename = assets/presplash.png
presplash.color = #1c1c1f
log_level = 2
warn_on_root = 1

[buildozer]
log_level = 2
warn_on_root = 1
build_dir = ./.buildozer
bin_dir = ./bin
