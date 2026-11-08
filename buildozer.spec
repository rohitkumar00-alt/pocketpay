[app]
title = PocketPay Demo
package.name = pocketpay
package.domain = org.example
source.dir = .
source.include_exts = py,kv,png,jpg,atlas,ttf
source.exclude_dirs = tests,docs,.github,.venv,.venv-build,work,bin,.buildozer,__pycache__
source.exclude_patterns = *.db,*.sqlite,*.sqlite3,*.pyc,*.log
version = 0.1.0

# sqlite3 is an explicit p4a recipe; the desktop standard library alone is insufficient.
requirements = python3==3.11.5,kivy==2.3.1,sqlite3,filetype==1.2.0
orientation = portrait
fullscreen = 0

# Demo APK for direct installation; this configuration is not a Play Store release.
android.api = 33
android.minapi = 23
android.ndk = 25b
android.ndk_api = 23
android.archs = arm64-v8a
android.allow_backup = False
android.debug_artifact = apk
android.accept_sdk_license = True
android.permissions =

p4a.branch = v2024.01.21
p4a.bootstrap = sdl2

[buildozer]
log_level = 2
warn_on_root = 1
