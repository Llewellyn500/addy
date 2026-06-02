[app]
title = Addy
package.name = addy
package.domain = com.llewellyn500

source.dir = .
source.include_exts = py,png
source.exclude_dirs = bin,.buildozer,__pycache__

version = 1.0.0
requirements = python3==3.10.11,hostpython3==3.10.11,kivy,pyjnius

orientation = portrait
fullscreen = 0

icon.filename = %(source.dir)s/assets/icon.png
presplash.filename = %(source.dir)s/assets/logo.png

android.permissions = INTERNET,ACCESS_NETWORK_STATE,ACCESS_WIFI_STATE,WRITE_EXTERNAL_STORAGE
android.api = 35
android.minapi = 23
android.accept_sdk_license = True
android.archs = arm64-v8a

[buildozer]
log_level = 1
warn_on_root = 1
