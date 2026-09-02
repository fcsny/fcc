# -*- coding: utf-8 -*-
"""AI 写作工作台（安卓版）——入口。

与桌面版共用 core/（存储、API、上下文、检索），数据格式完全一致，
两边可以互导项目文件。
"""

from __future__ import annotations

# buildozer.spec 里配了 version.regex 从本文件抓版本号，
# 没有这一行的话正则匹配不到，云编译会失败。
# 必须在 __future__ 导入之后，否则触发 SyntaxError。
__version__ = "1.0.0"

import os
import sys
import threading
import time

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.label import Label
from kivy.uix.screenmanager import ScreenManager, SlideTransition

from core import paths, trace
from core.storage import Project

# 安卓上软键盘弹出会遮挡输入框，Kivy 需要显式开启这个模式
try:
    from kivy.core.window import WindowBase
    Window.softinput_mode = "below_target"
except Exception:  # noqa: BLE001
    pass

from ui import theme as th
from ui.screens_api import ApiScreen
from ui.screens_article import ArticleScreen
from ui.screens_character import CharacterScreen
from ui.screens_lore import LoreScreen
from ui.screens_project import ProjectScreen
from ui.screens_world import WorldScreen

Window.clearcolor = th.BG[:3] + (1,)

# 底部导航：图标用 emoji（不依赖字体文件，红米上必定能显示）
NAV = [
    ("article", "文章", "✎"),
    ("character", "人物", "👤"),
    ("lore", "资料", "📚"),
    ("world", "世界观", "🌐"),
    ("api", "API", "⚙"),
    ("project", "项目", "📁"),
]


class NavButton(ButtonBehavior, BoxLayout):
    """导航项：图标在上、文字在下。

    必须显式定义成类——ButtonBehavior 是混入类，
    写成 ButtonBehavior(BoxLayout)(...) 在真机上同样会崩。
    """

    def __init__(self, **kw):
        kw.setdefault("orientation", "vertical")
        super().__init__(**kw)


class NavBar(BoxLayout):
    """底部导航条。"""

    def __init__(self, on_switch, **kw):
        super().__init__(**kw)
        self.orientation = "horizontal"
        self.size_hint_y = None
        self.height = dp(56)
        self.spacing = 0
        self.buttons = {}

        for key, label, icon in NAV:
            btn = NavButton(size_hint_x=1)
            lb_icon = Label(text=icon, font_size=dp(18), color=th.FG_DIM,
                            size_hint_y=None, height=dp(26))
            lb_text = Label(text=label, font_size=th.FONT_SMALL,
                            color=th.FG_DIM, size_hint_y=None, height=dp(20))
            btn.add_widget(lb_icon)
            btn.add_widget(lb_text)
            btn.bind(on_release=lambda *_w, k=key: on_switch(k))
            self.add_widget(btn)
            self.buttons[key] = (btn, lb_icon, lb_text)

    def highlight(self, key):
        for k, (btn, icon, text) in self.buttons.items():
            c = th.ACCENT if k == key else th.FG_DIM
            icon.color = c
            text.color = c


class AIWriterApp(App):

    def __init__(self, **kw):
        super().__init__(**kw)
        self.project: Project | None = None
        self.sm: ScreenManager | None = None
        self.nav: NavBar | None = None
        self._save_ev = None
        self._closing = False
        self.save_lbl = Label(text="", color=th.FG_DIM, font_size=th.FONT_SMALL,
                              size_hint_y=None, height=dp(0))


    # ------------------------------------------------------------------
    def build(self):
        trace.install()
        # 注入真实存储路径：私有目录存数据，公共目录做导入导出交换区
        try:
            private = self.user_data_dir
        except Exception:  # noqa: BLE001
            private = ""
        paths.configure(private_dir=private, public_dir="")

        # 字体必须在构建任何控件之前定下来：控件创建时会立刻解析字体，
        # 此时才发现字体不存在就已经晚了（会抛 IOError 直接崩）。
        try:
            th.FONT_NAME = th.resolve_font_name(app_dir=private or "")
        except Exception:  # noqa: BLE001
            th.FONT_NAME = ""

        self.project = self._load_project()

        root = BoxLayout(orientation="vertical")
        self.sm = ScreenManager(transition=SlideTransition(duration=0.15))
        for cls in (ArticleScreen, CharacterScreen, LoreScreen,
                    WorldScreen, ApiScreen, ProjectScreen):
            scr = cls(name=_key_of(cls))
            scr.app_ref = self          # 显式注入，别让页面去全局找
            self.sm.add_widget(scr)
        self.nav = NavBar(on_switch=self.switch_to)
        root.add_widget(self.sm)
        root.add_widget(self.nav)
        self.switch_to("article")
        Clock.schedule_interval(self._tick, 2.0)
        return root

    # ------------------------------------------------------------------
    def _load_project(self) -> Project:
        last = paths.load_settings().get("last_project", "")
        if last and os.path.exists(last):
            try:
                return Project.load(last)
            except Exception as e:  # noqa: BLE001
                trace.write("项目打开失败：%s" % e)
        path = os.path.join(paths.data_dir(), "我的小说" + paths.PROJECT_EXT)
        if os.path.exists(path):
            try:
                return Project.load(path)
            except Exception:  # noqa: BLE001
                pass
        p = Project(path=path)
        try:
            p.save()
        except Exception:  # noqa: BLE001
            pass
        return p

    def switch_to(self, key: str):
        """切换页面。

        刻意**不**做 `if current == key: return` 的短路：ScreenManager
        添加第一个页面时会自动把 current 设成它，于是"首次进入"会被判成
        "没切换"，refresh() 被跳过，页面停留在空表单上——表现为
        "填了内容却存不进去"（和桌面版踩过的坑同源）。
        """
        cur = self.sm.current_screen
        if cur is not None and cur.name != key and hasattr(cur, "flush"):
            try:
                cur.flush()
            except Exception:  # noqa: BLE001
                pass
        self.sm.current = key
        self.nav.highlight(key)
        scr = self.sm.get_screen(key)
        if scr is not None and hasattr(scr, "refresh"):
            scr.refresh()

    # ------------------------------------------------------------------
    # -- 页面访问 --------------------------------------------------------
    def get_screen(self, name: str):
        return self.sm.get_screen(name) if self.sm else None

    def has_screen(self, name: str) -> bool:
        return bool(self.sm and self.sm.get_screen(name))

    def refresh_all(self):
        """把所有页面的界面刷新成模型内容（导入/打开新项目后调用）。"""
        if not self.sm:
            return
        for scr in self.sm.screens:
            try:
                scr.refresh()
            except Exception:  # noqa: BLE001
                trace.log_exception("refresh_all: %s" % scr.name)

    def current_article(self):
        """当前章节（供上下文组装用）。"""
        scr = self.get_screen("article")
        if scr and hasattr(scr, "_cur"):
            art = scr._cur()
            if art is not None:
                return art
        arts = self.project.data.get("articles") or []
        return arts[0] if arts else None

    # -- 保存 ------------------------------------------------------------
    def mark_dirty(self):
        self.project.dirty = True
        if self._save_ev:
            self._save_ev.cancel()
        self._save_ev = Clock.schedule_once(lambda *_: self.save_project(), 2.0)

    def save_project(self, force: bool = False) -> bool:
        if self._closing:
            return False
        try:
            self.project.save()
            s = paths.load_settings()
            s["last_project"] = self.project.path
            paths.save_settings(s)
            return True
        except Exception as e:  # noqa: BLE001
            trace.write("保存失败：%s" % e)
            return False

    def save_now(self) -> bool:
        """立刻保存（先收集所有页面的编辑），返回结果。"""
        for scr in (self.sm.screens if self.sm else []):
            try:
                scr.flush()
            except Exception:  # noqa: BLE001
                pass
        ok = self.save_project(force=True)
        self.save_lbl.text = "已保存" if ok else "保存失败"
        return ok

    # -- 导出 / 导入 ------------------------------------------------------
    def export_project(self) -> str:
        """导出到对外交换区。无图片→单文件；有图片→zip。

        返回导出路径，失败抛异常（由调用方提示）。
        """
        self.save_now()
        # export_dir() 本身已指向 .../Documents/AI写作工作台，
        # 不能再拼一次目录名，否则会变成两层同名目录，
        # 用户按文档里的路径去找就找不到文件。
        from core.paths import export_dir
        d = export_dir()
        os.makedirs(d, exist_ok=True)
        name = _safe_filename(self.project.name) or "项目"
        has_images = any(c.get("images")
                         for c in self.project.data.get("characters", []))
        if has_images:
            path = os.path.join(d, name + ".zip")
            self.project.export_bundle(path)
        else:
            path = os.path.join(d, name + paths.PROJECT_EXT)
            self.project.save(path)
        return path

    def _do_import(self, source: str) -> None:
        """从交换区导入项目文件（.aiwriter.json 或 .zip）。"""
        from core.paths import data_dir
        target = os.path.join(data_dir(), "imported")
        if source.lower().endswith(".zip"):
            self.project = Project.import_bundle(source, target)
        else:
            self.project = Project.load(source)
        st = paths.load_settings()
        st["last_project"] = self.project.path
        paths.save_settings(st)
        self.refresh_all()
        self.save_lbl.text = "已导入"

    # -- 兜底 ------------------------------------------------------------
    def _tick(self, *_):
        """兜底：定时保存，防止切后台被杀导致内容丢失。"""
        if self.project and self.project.dirty:
            self.save_project()

    def run_async(self, fn, on_done):
        """在后台线程跑网络请求，回主线程更新 UI。"""

        def worker():
            try:
                result = (True, fn())
            except Exception as e:  # noqa: BLE001
                result = (False, str(e))
            Clock.schedule_once(lambda *_: on_done(result), 0)

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------
    def on_pause(self):
        """安卓切后台：必须保存，否则进程被杀就丢了。"""
        cur = self.sm.current_screen if self.sm else None
        if cur and hasattr(cur, "flush"):
            try:
                cur.flush()
            except Exception:  # noqa: BLE001
                pass
        self.save_project(force=True)
        return True

    def on_stop(self):
        self._closing = True
        self.on_pause()


def _safe_filename(name: str) -> str:
    return "".join(c for c in (name or "")
                   if c not in '\\/:*?"<>|').strip()


def _key_of(cls) -> str:
    return {"ArticleScreen": "article", "CharacterScreen": "character",
            "LoreScreen": "lore", "WorldScreen": "world",
            "ApiScreen": "api", "ProjectScreen": "project"}.get(
        cls.__name__, cls.__name__.lower())


def main():
    AIWriterApp().run()


if __name__ == "__main__":
    main()
