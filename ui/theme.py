# -*- coding: utf-8 -*-
"""手机版配色与尺寸。

两个必须注意的点：

1. **颜色用 0~1 元组**（Kivy 原生格式）。桌面版那套十六进制字符串
   在这里每次都要转换，容易漏，直接用元组最省事。

2. **中文字体**。Kivy 默认字体 Roboto **不含中文字形**，在红米上会显示成
   豆腐块。安卓系统自带 DroidSansFallback（MIUI 也有），用它兜底最稳。
"""
import os

from kivy.metrics import dp, sp

# ---- 背景层次（深→浅）----
BG          = (0.10, 0.11, 0.13, 1)
BG_PANEL    = (0.13, 0.14, 0.17, 1)
BG_CARD     = (0.16, 0.17, 0.21, 1)
BG_INPUT    = (0.08, 0.09, 0.11, 1)
BG_HOVER    = (0.20, 0.22, 0.26, 1)
BORDER      = (0.22, 0.24, 0.29, 1)
ACCENT_SOFT = (0.20, 0.32, 0.52, 1)

# ---- 文字 ----
FG       = (0.92, 0.93, 0.95, 1)
FG_DIM   = (0.66, 0.69, 0.75, 1)
FG_FAINT = (0.45, 0.48, 0.55, 1)

# ---- 语义色（与桌面版一致，跨设备视觉连贯）----
ACCENT = (0.29, 0.55, 0.98, 1)
OK     = (0.35, 0.75, 0.45, 1)
WARN   = (0.95, 0.72, 0.25, 1)
ERR    = (0.94, 0.35, 0.35, 1)

# ---- 字号（手机比桌面大一号）----
FONT_TITLE = sp(20)
FONT_H2    = sp(17)
FONT_UI    = sp(15)
FONT_BODY  = sp(16)    # 正文编辑要够大才好写
FONT_SMALL = sp(13)

# ---- 尺寸 ----
TOUCH_MIN = dp(48)     # 安卓 Material 规范：可点击区域下限
INPUT_H   = dp(46)
PAD       = dp(14)
PAD_SMALL = dp(8)
RADIUS    = dp(10)

# 中文字体：**绝不能硬编码**。
#
# Kivy 默认字体 Roboto 不含中文字形，直接写死 font_name 又很危险——
# 一旦设备上找不到那个字体，Kivy 的 resolve_font_name 会抛 IOError，
# 于是第一个输入框都建不起来，App 一启动就崩。
# 所以这里只给候选顺序，真正用哪个由 resolve_font_name() 运行时探测决定。
FONT_NAME = ""          # 由 App.build() 探测后填入

FONT_CANDIDATES = (
    "DroidSansFallback",        # 安卓系统自带，覆盖面最广
    "NotoSansCJK-Regular",
    "NotoSansSC-Regular",
    "MiSans",                   # 小米 / 红米自带
    "SourceHanSansCN-Regular",
    "WenQuanYi Micro Hei",
)

# 打包时自带的兜底字体（相对 app 根目录）
BUNDLED_FONT = "assets/fonts/wqy-microhei.ttc"

WHITE = (1, 1, 1, 1)


def resolve_font_name(app_dir: str = "") -> str:
    """挑一个真能显示中文的字体。

    优先级：打包自带的兜底字体 → 系统字体逐个试。
    全都失败就返回空串（用 Kivy 默认）——中文可能显示成方块，
    但 App 不会崩，用户还能把内容导出到桌面版继续用。
    """
    candidates = []
    if app_dir:
        bundled = os.path.join(app_dir, BUNDLED_FONT)
        if os.path.exists(bundled):
            candidates.append(bundled)
    candidates.extend(FONT_CANDIDATES)

    try:
        from kivy.core.text import Label as CoreLabel
    except Exception:  # noqa: BLE001
        return ""

    for name in candidates:
        try:
            CoreLabel(text="中文测试", font_name=name)
            return name
        except Exception:  # noqa: BLE001
            continue
    return ""


def rgba(color, alpha: float = 1.0):
    """给颜色加透明度（按下态、禁用态用）。"""
    return (color[0], color[1], color[2], alpha)
