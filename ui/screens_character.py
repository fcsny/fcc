# -*- coding: utf-8 -*-
"""人物卡页：左侧列表 + 右侧表单。

手机上不做左右分栏（屏幕太窄），改成：
顶部一排卡片切换条（点一下换人）+ 下方表单滚动区。
"""
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

from ui import theme as th
from ui.base import BaseScreen, PaddedBody
from ui.widgets import (Divider, EmptyHint, FormInput, GhostButton,
                        PrimaryButton, SectionTitle)

# 单行字段
SHORT_FIELDS = [("aliases", "别名 / 称呼"), ("gender", "性别"), ("age", "年龄")]

# 多行字段（label, 行数权重）
TEXT_FIELDS = [
    ("appearance", "外貌特征", 3),
    ("personality", "性格", 4),
    ("speech", "语言风格 / 口癖", 3),
    ("background", "背景经历", 4),
    ("relations", "人际关系", 3),
    ("notes", "作者备注（AI 也会读到）", 3),
    ("sample", "示例对话 / 范例片段", 4),
]


class CharChip(Label):
    def __init__(self, name="", active=False, on_tap=None, **kw):
        super().__init__(**kw)
        self.text = name or "未命名"
        self.font_size = th.FONT_SMALL
        self.color = th.FG if active else th.FG_DIM
        self.size_hint = (None, None)
        self.size = (dp(92), dp(36))
        self.halign = "center"
        self.valign = "middle"
        self.text_size = (dp(84), None)
        self.on_tap = on_tap

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos) and self.on_tap:
            self.on_tap()
            return True
        return super().on_touch_down(touch)


class CharacterScreen(BaseScreen):
    title = "人物卡"

    def __init__(self, **kw):
        super().__init__(**kw)
        self._building = True
        self.current_id = None
        self._form_id = None        # 表单里显示的是哪张卡
        self.short: dict = {}
        self.texts: dict = {}
        self._save_ev = None

        self._root = BoxLayout(orientation="vertical", spacing=0)

        # 顶部：人物切换条
        self.chip_scroll = ScrollView(do_scroll_y=False, size_hint=(1, None),
                                      height=dp(46))
        self.chip_inner = BoxLayout(size_hint=(None, 1), spacing=dp(6),
                                    padding=[dp(8), dp(5), dp(8), dp(5)])
        self.chip_inner.bind(minimum_width=self.chip_inner.setter("width"))
        self.chip_scroll.add_widget(self.chip_inner)
        self._root.add_widget(self.chip_scroll)

        # 操作行
        ops = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6),
                        padding=[th.PAD, 0, th.PAD, 0])
        for text, fn in (("＋ 新建", self._new), ("复制", self._dup),
                         ("删除", self._del)):
            b = GhostButton(text=text)
            b.bind(on_release=lambda *_w, f=fn: f())
            ops.add_widget(b)
        self._root.add_widget(ops)

        # 表单
        self.body = PaddedBody()
        sv = ScrollView()
        sv.add_widget(self.body)
        self._root.add_widget(sv)

        # 底部保存条
        bar = BoxLayout(size_hint_y=None, height=th.TOUCH_MIN, spacing=dp(8),
                        padding=[th.PAD, dp(4), th.PAD, dp(8)])
        self.save_state = Label(text="", color=th.FG_DIM,
                                font_size=th.FONT_SMALL, halign="left")
        self.save_state.bind(width=lambda *a: setattr(
            self.save_state, "text_size", (self.save_state.width, None)))
        bar.add_widget(self.save_state)
        btn_save = PrimaryButton(text="保存", size_hint_x=None, width=dp(110))
        btn_save.bind(on_release=lambda *_: self._save())
        bar.add_widget(btn_save)
        self._root.add_widget(bar)

        self.add_widget(self._root)
        self._build_form()
        self._building = False

    def _build_form(self):
        self.body.add_widget(SectionTitle(text="人物信息"))
        self.name_input = FormInput(label="姓名", multiline=False)
        self.name_input.on_change = lambda v: self._on_edit()
        self.body.add_widget(self.name_input)

        for key, label in SHORT_FIELDS:
            f = FormInput(label=label, multiline=False)
            f.on_change = lambda v, k=key: self._on_field(k, v)
            self.short[key] = f
            self.body.add_widget(f)

        self.body.add_widget(Divider())
        self.body.add_widget(SectionTitle(text="详细设定"))
        for key, label, lines in TEXT_FIELDS:
            f = FormInput(label=label, multiline=True,
                          field_height=max(dp(80), dp(26) * lines))
            f.on_change = lambda v, k=key: self._on_field(k, v)
            self.texts[key] = f
            self.body.add_widget(f)

        self.body.add_widget(Label(text="", size_hint_y=None, height=dp(20)))

    # ------------------------------------------------------------------
    def refresh(self):
        was = self._building
        self._building = True
        try:
            chars = self.app.project.data["characters"]
            if not chars:
                self.app.project.add_character("新角色")
                chars = self.app.project.data["characters"]
            if self._form_id not in [c["id"] for c in chars]:
                self._form_id = chars[0]["id"]
            self.current_id = self._form_id
            self._render_chips()
            self._load_form()
        finally:
            self._building = was

    def _render_chips(self):
        self.chip_inner.clear_widgets()
        for c in self.app.project.data["characters"]:
            active = c["id"] == self._form_id
            name = c.get("name") or "未命名"
            chip = CharChip(name=name, active=active,
                            on_tap=lambda x=c: self._switch(x))
            self.chip_inner.add_widget(chip)

    def _switch(self, ch):
        if ch["id"] == self._form_id:
            return
        self.flush()
        self._form_id = ch["id"]
        self.current_id = ch["id"]
        self._render_chips()
        self._load_form()

    def _cur(self):
        for c in self.app.project.data["characters"]:
            if c["id"] == self._form_id:
                return c
        return None

    def _load_form(self):
        ch = self._cur()
        if not ch:
            return
        was = self._building
        self._building = True
        try:
            self.name_input.set_text(ch.get("name", "") or "")
            for key, f in self.short.items():
                f.set_text(ch.get(key, "") or "")
            for key, f in self.texts.items():
                f.set_text(ch.get(key, "") or "")
        finally:
            self._building = was

    def _on_edit(self, *_):
        if self._building:
            return
        self._touch()

    def _on_field(self, key, value):
        if self._building:
            return
        self._touch()

    def _touch(self):
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
        ch = self._cur()
        self.save_state.text = "✔ 已保存　%s" % ((ch or {}).get("name", "") or "")

    def flush(self):
        if self._building or not self._form_id:
            return
        ch = self._cur()
        if not ch:
            return
        ch["name"] = self.name_input.field.text
        for key, f in self.short.items():
            ch[key] = f.field.text
        for key, f in self.texts.items():
            ch[key] = f.field.text

    def _save(self):
        self.flush()
        if self.app.save_project():
            ch = self._cur()
            self.save_state.color = th.OK
            self.save_state.text = "✔ 已保存　%s" % ((ch or {}).get("name", "") or "")

    # ------------------------------------------------------------------
    def _new(self):
        self.flush()
        ch = self.app.project.add_character("新角色")
        self._form_id = ch["id"]
        self.current_id = ch["id"]
        self.refresh()
        self.mark_dirty()

    def _dup(self):
        import copy
        import uuid
        ch = self._cur()
        if not ch:
            return
        self.flush()
        new = copy.deepcopy(ch)
        new["id"] = "char_" + uuid.uuid4().hex[:12]
        new["name"] = (ch.get("name", "") or "新角色") + "（副本）"
        self.app.project.data["characters"].append(new)
        self._form_id = new["id"]
        self.current_id = new["id"]
        self.refresh()
        self.mark_dirty()

    def _del(self):
        ch = self._cur()
        if not ch:
            return
        self._form_id = None
        self.current_id = None
        self.app.project.remove_character(ch["id"])
        self.refresh()
        self.mark_dirty()
