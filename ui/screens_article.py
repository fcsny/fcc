# -*- coding: utf-8 -*-
"""文章编辑页：章节列表 + 正文编辑 + 底部 AI 生成。

手机上的关键取舍：
  * 章节列表做成横向可滑的标签条，不占竖向空间（写作区尽量大）
  * 编辑即自动保存（1.5 秒防抖），不设保存按钮占用屏幕
  * 生成结果直接插入光标处，不弹新窗口
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


class ChapterChip(Label):
    """横向章节标签。"""

    def __init__(self, title="", active=False, on_tap=None, **kw):
        super().__init__(**kw)
        self.text = title or "未命名"
        self.font_size = th.FONT_SMALL
        self.color = th.FG if active else th.FG_DIM
        self.size_hint = (None, None)
        self.size = (dp(96), dp(38))
        self.halign = "center"
        self.valign = "middle"
        self.text_size = (dp(88), None)
        self.on_tap = on_tap

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos) and self.on_tap:
            self.on_tap()
            return True
        return super().on_touch_down(touch)


class ArticleScreen(BaseScreen):
    title = "文章"

    def __init__(self, **kw):
        super().__init__(**kw)
        self._building = True
        self.current_id = None
        self._save_ev = None
        self._root = BoxLayout(orientation="vertical", spacing=0)

        # 章节标签条
        self.chip_bar = BoxLayout(
            size_hint_y=None, height=dp(48), padding=[dp(8), dp(6)],
            spacing=dp(6))
        from kivy.uix.scrollview import ScrollView as SV
        self.chip_scroll = SV(do_scroll_y=False, size_hint=(1, 1))
        self.chip_inner = BoxLayout(size_hint=(None, 1), spacing=dp(6),
                                    padding=[0, 0, dp(8), 0])
        self.chip_inner.bind(minimum_width=self.chip_inner.setter("width"))
        self.chip_scroll.add_widget(self.chip_inner)
        self.chip_bar.add_widget(self.chip_scroll)
        self._root.add_widget(self.chip_bar)

        # 标题
        self.title_input = FormInput(label="章节标题", multiline=False)
        self.title_input.on_change = lambda v: self._on_edit()
        self._root.add_widget(self.title_input)

        # 正文（尽量占满剩余空间）
        body_wrap = BoxLayout(orientation="vertical", padding=[th.PAD, dp(4),
                                                               th.PAD, dp(4)])
        body_wrap.add_widget(Label(text="正文", color=th.FG_DIM,
                                   font_size=th.FONT_SMALL, size_hint_y=None,
                                   height=dp(20), halign="left"))
        self.editor = TextInput(
            font_size=th.FONT_BODY, foreground_color=th.FG,
            background_color=th.BG_INPUT, cursor_color=th.ACCENT,
            padding=[dp(12)] * 4, multiline=True, scroll_type=["content",
                                                               "bars"],
            bar_width=dp(5), font_name=th.FONT_NAME)
        self.editor.bind(text=lambda *_: self._on_edit())
        body_wrap.add_widget(self.editor)
        self._root.add_widget(body_wrap)

        self._root.add_widget(Divider())
        self._root.add_widget(self._build_generate_bar())
        self.add_widget(self._root)
        self._building = False

    def _build_generate_bar(self):
        bar = BoxLayout(orientation="vertical", size_hint_y=None,
                        height=dp(150), padding=[th.PAD, dp(6)], spacing=dp(6))

        row1 = BoxLayout(size_hint_y=None, height=dp(34), spacing=dp(6))
        row1.add_widget(Label(text="AI 生成", color=th.FG, font_size=th.FONT_H2,
                              bold=True, size_hint_x=None, width=dp(90),
                              halign="left"))
        self.status_label = Label(text="", color=th.FG_DIM,
                                  font_size=th.FONT_SMALL, halign="right")
        self.status_label.bind(width=lambda *a: setattr(
            self.status_label, "text_size", (self.status_label.width, None)))
        row1.add_widget(self.status_label)
        bar.add_widget(row1)

        self.instruction = TextInput(
            hint_text="给 AI 的指令（留空则按当前模式续写）",
            font_size=th.FONT_SMALL, foreground_color=th.FG,
            background_color=th.BG_INPUT, cursor_color=th.ACCENT,
            padding=[dp(10), dp(10)], size_hint_y=None, height=dp(44),
            multiline=False, font_name=th.FONT_NAME)
        bar.add_widget(self.instruction)

        row2 = BoxLayout(size_hint_y=None, height=th.TOUCH_MIN, spacing=dp(6))
        self.btn_gen = PrimaryButton(text="生成")
        self.btn_gen.bind(on_release=lambda *_: self._generate())
        self.btn_stop = GhostButton(text="停止")
        self.btn_stop.bind(on_release=lambda *_: self._stop())
        row2.add_widget(self.btn_gen)
        row2.add_widget(self.btn_stop)
        bar.add_widget(row2)
        return bar

    # ------------------------------------------------------------------
    def refresh(self):
        self._building = True
        try:
            arts = self.app.project.data["articles"]
            if not arts:
                self.app.project.data["articles"].append(
                    _default_article("第一章"))
                arts = self.app.project.data["articles"]
            if self.current_id not in [a["id"] for a in arts]:
                self.current_id = arts[0]["id"]
            self._render_chips()
            self._load_current()
        finally:
            self._building = False

    def _render_chips(self):
        self.chip_inner.clear_widgets()
        for art in self.app.project.data["articles"]:
            active = art["id"] == self.current_id
            chip = ChapterChip(title=art.get("title", "未命名"), active=active,
                               on_tap=lambda a=art: self._switch(a))
            self.chip_inner.add_widget(chip)

    def _switch(self, art):
        self.flush()
        self.current_id = art["id"]
        self._render_chips()
        self._load_current()

    def _load_current(self):
        art = self._cur()
        if not art:
            return
        self._building = True
        try:
            self.title_input.set_text(art.get("title", ""))
            self.editor.text = art.get("content", "") or ""
        finally:
            self._building = False

    def _cur(self):
        for a in self.app.project.data["articles"]:
            if a["id"] == self.current_id:
                return a
        return None

    def _on_edit(self):
        if self._building:
            return
        self.mark_dirty()
        if self._save_ev:
            self._save_ev.cancel()
        self._save_ev = Clock.schedule_once(lambda *_: self.flush_or_save(), 1.5)

    def flush_or_save(self):
        self.flush()
        self.app.save_project()

    def flush(self):
        if self._building:
            return
        art = self._cur()
        if not art:
            return
        art["title"] = self.title_input.field.text
        art["content"] = self.editor.text

    # ------------------------------------------------------------------
    def _generate(self):
        self.flush()
        self.app.save_project()
        self.status_label.color = th.FG_DIM
        self.status_label.text = "生成中…"
        self.btn_gen.disabled = True
        self.app.run_async(
            lambda: self._do_generate(),
            self._on_generated)

    def _do_generate(self):
        from core.api_client import AIClient, AIError
        from core.context import build_context
        result = build_context(
            self.app.project, self._cur(),
            self.instruction.text.strip(),
            self.app.project.data["gen"].get("preset", "continue"))
        client = AIClient(self.app.project.data["api"])
        return client.chat(result.messages, system=result.system, stream=False)

    def _on_generated(self, result):
        self.btn_gen.disabled = False
        ok, value = result
        if ok:
            text = (value or "").strip()
            if text:
                self.editor.insert_text(text + "\n")
                self.flush()
                self.app.save_project()
            self.status_label.color = th.OK
            self.status_label.text = "已插入 %d 字" % len(text)
        else:
            self.status_label.color = th.ERR
            self.status_label.text = "失败：%s" % value

    def _stop(self):
        self.status_label.text = "已停止"


def _default_article(title="新章节"):
    import uuid
    return {"id": "art_" + uuid.uuid4().hex[:12], "title": title,
            "content": "", "summary": "", "updated": ""}
