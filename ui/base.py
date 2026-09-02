# -*- coding: utf-8 -*-
"""移动端页面基类与通用容器。

所有功能页都继承 BaseScreen，统一处理两件事：
  * 进入时 refresh()（模型 → 界面）
  * 离开前 flush()（界面 → 模型）——切页面丢内容是最容易踩的坑
"""
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.screenmanager import Screen

from ui import theme as th


class BaseScreen(Screen):
    """所有功能页的基类。

    app 用**注入**而不是每次 App.get_running_app()：后者在页面构造阶段
    （App 还没 run 起来）会返回 None，任何 mark_dirty() 都会直接崩。
    显式注入让页面在任何时刻都能可靠访问应用实例，测试里也更好构造。
    """

    title = "未命名"

    def __init__(self, **kw):
        self.app_ref = None
        super().__init__(**kw)

    @property
    def app(self):
        if self.app_ref is not None:
            return self.app_ref
        from kivy.app import App
        return App.get_running_app()

    # -- 生命周期 ---------------------------------------------------------
    def on_pre_enter(self, *args):
        """进入页面前把模型内容填进界面。"""
        try:
            self.refresh()
        except Exception:  # noqa: BLE001
            from core import trace
            trace.log_exception("refresh 失败：%s" % type(self).__name__)

    def on_pre_leave(self, *args):
        """离开前把未提交的编辑收进模型。"""
        try:
            self.flush()
        except Exception:  # noqa: BLE001
            from core import trace
            trace.log_exception("flush 失败：%s" % type(self).__name__)

    # -- 子类实现 ---------------------------------------------------------
    def refresh(self):
        """数据模型 → 界面。"""

    def flush(self):
        """界面 → 数据模型。"""

    def mark_dirty(self):
        self.app.mark_dirty()


class PaddedBody(BoxLayout):
    """带留白的纵向容器，页面内容都塞这里（配合 ScrollView 使用）。"""

    def __init__(self, **kw):
        kw.setdefault("orientation", "vertical")
        kw.setdefault("spacing", dp(10))
        kw.setdefault("padding", [th.PAD, th.PAD, th.PAD, th.PAD])
        kw.setdefault("size_hint_y", None)
        super().__init__(**kw)
        self.bind(minimum_height=self.setter("height"))
