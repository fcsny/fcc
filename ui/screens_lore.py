# -*- coding: utf-8 -*-
"""资料库页：条目列表 + 编辑。

手机上把"召回测试"做成一键按钮，方便确认资料能不能被 AI 找到。
"""
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView

from ui import theme as th
from ui.base import BaseScreen, PaddedBody
from ui.widgets import (Divider, EmptyHint, FormInput, GhostButton,
                        PrimaryButton, SectionTitle)


class LoreChip(Label):
    def __init__(self, name="", active=False, on_tap=None, **kw):
        super().__init__(**kw)
        self.text = name or "未命名"
        self.font_size = th.FONT_SMALL
        self.color = th.FG if active else th.FG_DIM
        self.size_hint = (None, None)
        self.size = (dp(104), dp(36))
        self.halign = "center"
        self.valign = "middle"
        self.text_size = (dp(96), None)
        self.on_tap = on_tap

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos) and self.on_tap:
            self.on_tap()
            return True
        return super().on_touch_down(touch)


class LoreScreen(BaseScreen):
    title = "资料库"

    def __init__(self, **kw):
        super().__init__(**kw)
        self._building = True
        self._form_id = None
        self._save_ev = None

        self._root = BoxLayout(orientation="vertical", spacing=0)

        self.chip_scroll = ScrollView(do_scroll_y=False, size_hint=(1, None),
                                      height=dp(46))
        self.chip_inner = BoxLayout(size_hint=(None, 1), spacing=dp(6),
                                    padding=[dp(8), dp(5)])
        self.chip_inner.bind(minimum_width=self.chip_inner.setter("width"))
        self.chip_scroll.add_widget(self.chip_inner)
        self._root.add_widget(self.chip_scroll)

        ops = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6),
                        padding=[th.PAD, 0])
        for text, fn in (("＋ 新建", self._new), ("删除", self._del),
                         ("召回测试", self._test_recall)):
            b = GhostButton(text=text)
            b.bind(on_release=lambda *_w, f=fn: f())
            ops.add_widget(b)
        self._root.add_widget(ops)

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
        self._build_form()
        self._building = False

    def _build_form(self):
        self.title_input = FormInput(label="标题", multiline=False)
        self.title_input.on_change = lambda v: self._touch()
        self.body.add_widget(self.title_input)

        self.tags_input = FormInput(label="标签（空格分隔，用于召回）",
                                    multiline=False)
        self.tags_input.on_change = lambda v: self._touch()
        self.body.add_widget(self.tags_input)

        self.body.add_widget(Divider())
        self.content_input = FormInput(label="正文内容", multiline=True,
                                       field_height=dp(260))
        self.content_input.on_change = lambda v: self._touch()
        self.body.add_widget(self.content_input)

        self.body.add_widget(SectionTitle(text="参与生成的开关"))
        for key, label in (("enabled", "允许 AI 自动参考"),
                           ("pinned", "★ 常驻（无条件携带）")):
            row = BoxLayout(size_hint_y=None, height=dp(44))
            from kivy.uix.checkbox import CheckBox
            cb = CheckBox(size_hint_x=None, width=dp(48), active=True)
            cb.bind(active=lambda *_a: self._touch())
            setattr(self, "cb_" + key, cb)
            row.add_widget(cb)
            lab = Label(text=label, color=th.FG_DIM, font_size=th.FONT_SMALL,
                        halign="left")
            lab.bind(width=lambda *a, l=lab: setattr(l, "text_size",
                                                     (l.width, None)))
            row.add_widget(lab)
            self.body.add_widget(row)

        self.recall_label = Label(text="", color=th.FG_DIM,
                                  font_size=th.FONT_SMALL, size_hint_y=None,
                                  height=dp(50), halign="left", valign="top")
        self.recall_label.bind(width=lambda *a: setattr(
            self.recall_label, "text_size", (self.recall_label.width, None)))
        self.body.add_widget(self.recall_label)

    # ------------------------------------------------------------------
    def refresh(self):
        was = self._building
        self._building = True
        try:
            lores = self.app.project.data["lore"]
            if not lores:
                self.app.project.add_lore("新资料")
                lores = self.app.project.data["lore"]
            if self._form_id not in [l["id"] for l in lores]:
                self._form_id = lores[0]["id"]
            self._render_chips()
            self._load_form()
        finally:
            self._building = was

    def _render_chips(self):
        self.chip_inner.clear_widgets()
        for l in self.app.project.data["lore"]:
            star = "★" if l.get("pinned") else ""
            name = (star + (l.get("title") or "未命名"))[:9]
            chip = LoreChip(name=name, active=l["id"] == self._form_id,
                            on_tap=lambda x=l: self._switch(x))
            self.chip_inner.add_widget(chip)

    def _switch(self, item):
        if item["id"] == self._form_id:
            return
        self.flush()
        self._form_id = item["id"]
        self._render_chips()
        self._load_form()

    def _cur(self):
        for l in self.app.project.data["lore"]:
            if l["id"] == self._form_id:
                return l
        return None

    def _load_form(self):
        l = self._cur()
        if not l:
            return
        was = self._building
        self._building = True
        try:
            self.title_input.set_text(l.get("title", "") or "")
            self.tags_input.set_text(l.get("tags", "") or "")
            self.content_input.set_text(l.get("content", "") or "")
            self.cb_enabled.active = bool(l.get("enabled", True))
            self.cb_pinned.active = bool(l.get("pinned", False))
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
        l = self._cur()
        self.save_state.color = th.OK
        self.save_state.text = "✔ 已保存　%s" % ((l or {}).get("title", "") or "")

    def flush(self):
        if self._building or not self._form_id:
            return
        l = self._cur()
        if not l:
            return
        l["title"] = self.title_input.field.text
        l["tags"] = self.tags_input.field.text
        l["content"] = self.content_input.field.text
        l["enabled"] = self.cb_enabled.active
        l["pinned"] = self.cb_pinned.active

    def _save(self):
        self.flush()
        if self.app.save_project():
            l = self._cur()
            self.save_state.color = th.OK
            self.save_state.text = "✔ 已保存　%s" % ((l or {}).get("title", "") or "")

    # ------------------------------------------------------------------
    def _new(self):
        self.flush()
        l = self.app.project.add_lore("新资料")
        self._form_id = l["id"]
        self.refresh()
        self.mark_dirty()

    def _del(self):
        l = self._cur()
        if not l:
            return
        self._form_id = None
        self.app.project.remove_lore(l["id"])
        self.refresh()
        self.mark_dirty()

    def _test_recall(self):
        """用当前正文前 30 字当查询，看能不能召回这条资料。"""
        self.flush()
        l = self._cur()
        if not l:
            return
        import copy
        probe = copy.deepcopy(l)
        query = (self.content_input.field.text or "")[:30]
        if not query.strip():
            self.recall_label.color = th.WARN
            self.recall_label.text = "先写点正文，才能测试召回"
            return
        from core.retriever import retrieve
        hits = retrieve(query, self.app.project.data["lore"], topk=6)
        names = [h[1].get("title", "") for h in hits]
        if probe.get("title") in names:
            rank = names.index(probe.get("title")) + 1
            self.recall_label.color = th.OK
            self.recall_label.text = "✔ 能被召回（第 %d 位）\n共命中 %d 条：%s" % (
                rank, len(names), "、".join(names) or "无")
        else:
            self.recall_label.color = th.WARN
            self.recall_label.text = "✘ 没被召回。\n建议补充关键词/标签。\n实际命中：%s" % (
                "、".join(names) or "无")
