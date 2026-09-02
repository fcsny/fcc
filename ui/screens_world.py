# -*- coding: utf-8 -*-
"""世界观与指令页：五块设定 + 参与开关。

手机上用一个纵向滚动表单，五块依次排列，不追求一屏看完。
"""
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView

from ui import theme as th
from ui.base import BaseScreen, PaddedBody
from ui.widgets import Divider, FormInput, PrimaryButton, SectionTitle

WORLD_FIELDS = [
    ("worldview", "世界观设定", "地理环境、力量体系、社会结构…", 5),
    ("outline", "故事大纲 / 剧情线", "主线与关键节点，越具体 AI 越不跑偏", 5),
    ("style", "文风要求", "人称、句式、节奏、禁忌…", 3),
    ("banned", "禁用词 / 禁写内容", "一行一个，会进 System 强制约束", 3),
    ("instructions", "全局指令", "每次生成都会带上的要求", 3),
]

SWITCHES = [
    ("use_world", "世界观设定"),
    ("use_outline", "故事大纲"),
    ("use_style", "文风要求"),
    ("use_banned", "禁用词"),
    ("use_instructions", "全局指令"),
    ("use_characters", "人物卡"),
    ("use_lore", "资料库"),
]


class WorldScreen(BaseScreen):
    title = "世界观"

    def __init__(self, **kw):
        super().__init__(**kw)
        self._building = True
        self.texts: dict = {}
        self.cbs: dict = {}
        self._save_ev = None

        self._root = BoxLayout(orientation="vertical")
        self.body = PaddedBody()
        sv = ScrollView()
        sv.add_widget(self.body)
        self._root.add_widget(sv)

        bar = BoxLayout(size_hint_y=None, height=th.TOUCH_MIN, spacing=dp(8),
                        padding=[th.PAD, dp(4), th.PAD, dp(8)])
        self.save_state = Label(text="", color=th.FG_DIM,
                                font_size=th.FONT_SMALL, halign="left")
        self.save_state.bind(width=lambda *a: setattr(
            self.save_state, "text_size", (self.save_state.width, None)))
        bar.add_widget(self.save_state)
        btn = PrimaryButton(text="保存", size_hint_x=None, width=dp(110))
        btn.bind(on_release=lambda *_: self._save())
        bar.add_widget(btn)
        self._root.add_widget(bar)

        self.add_widget(self._root)
        self._build()
        self._building = False

    def _build(self):
        self.body.add_widget(SectionTitle(text="设定内容"))
        for key, label, hint, lines in WORLD_FIELDS:
            f = FormInput(label=label, hint=hint, multiline=True,
                          field_height=max(dp(90), dp(26) * lines))
            f.on_change = lambda v: self._touch()
            self.texts[key] = f
            self.body.add_widget(f)

        self.body.add_widget(Divider())
        self.body.add_widget(SectionTitle(text="参与生成的开关"))
        from kivy.uix.checkbox import CheckBox
        for key, label in SWITCHES:
            row = BoxLayout(size_hint_y=None, height=dp(42))
            cb = CheckBox(size_hint_x=None, width=dp(48), active=True)
            cb.bind(active=lambda *_a: self._touch())
            self.cbs[key] = cb
            row.add_widget(cb)
            lab = Label(text=label, color=th.FG_DIM, font_size=th.FONT_SMALL,
                        halign="left")
            lab.bind(width=lambda *a, l=lab: setattr(l, "text_size",
                                                     (l.width, None)))
            row.add_widget(lab)
            self.body.add_widget(row)

        self.body.add_widget(Label(text="", size_hint_y=None, height=dp(20)))

    # ------------------------------------------------------------------
    def refresh(self):
        was = self._building
        self._building = True
        try:
            world = self.app.project.data["world"]
            gen = self.app.project.data["gen"]
            for key, f in self.texts.items():
                f.set_text(world.get(key, "") or "")
            for key, cb in self.cbs.items():
                cb.active = bool(gen.get(key, True))
        finally:
            self._building = was

    def _touch(self, *_):
        if self._building:
            return
        self.save_state.color = th.WARN
        self.save_state.text = "● 有未保存的修改"
        self.mark_dirty()
        if self._save_ev:
            self._save_ev.cancel()
        self._save_ev = Clock.schedule_once(lambda *_: self._autosave(), 1.5)

    def _autosave(self):
        self.flush()
        self.app.save_project()
        self.save_state.color = th.OK
        self.save_state.text = "✔ 已保存"

    def flush(self):
        if self._building:
            return
        world = self.app.project.data["world"]
        gen = self.app.project.data["gen"]
        for key, f in self.texts.items():
            world[key] = f.field.text
        for key, cb in self.cbs.items():
            gen[key] = cb.active

    def _save(self):
        self.flush()
        if self.app.save_project():
            self.save_state.color = th.OK
            self.save_state.text = "✔ 已保存"
