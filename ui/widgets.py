# -*- coding: utf-8 -*-
"""移动端通用组件。

手机上的硬约束：
  * 所有可点元素高度 >= 48dp（手指点得准，安卓 Material 规范下限）
  * 输入框自带标签，省掉左右对齐的视觉噪音
  * 深色为主，夜间写作不刺眼
"""
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import (BooleanProperty, ListProperty, NumericProperty,
                             ObjectProperty, StringProperty)
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

from ui import theme as th

Builder.load_string("""
#: import th ui.theme

<PrimaryButton>:
    canvas.before:
        Color:
            rgba: root.bg_color
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [root.radius]
    Label:
        text: root.text
        color: root.fg_color
        font_size: root.font_size
        bold: root.bold
        halign: "center"
        valign: "center"
        text_size: self.size
        pos: root.pos
        size: root.size

<CardItem>:
    canvas.before:
        Color:
            rgba: root.bg_color
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [root.radius]

<Divider>:
    canvas:
        Color:
            rgba: root.color
        Rectangle:
            pos: self.pos
            size: self.size

<SectionTitle>:
    text_size: self.width, None
    size_hint_y: None
    height: dp(34)
    color: th.FG
    font_size: th.FONT_H2
    bold: True
    halign: "left"
    valign: "middle"

<EmptyHint>:
    text_size: self.width, None
    size_hint_y: None
    height: dp(60)
    color: th.FG_FAINT
    font_size: th.FONT_SMALL
    halign: "center"
    valign: "middle"
""")


class PrimaryButton(ButtonBehavior, BoxLayout):
    """主按钮：实心圆角，带按下态反馈。"""
    text = StringProperty("")
    bg_color = ListProperty(list(th.ACCENT))
    fg_color = ListProperty([1, 1, 1, 1])
    font_size = NumericProperty(th.FONT_UI)
    radius = NumericProperty(th.RADIUS)
    bold = BooleanProperty(False)

    def __init__(self, **kw):
        super().__init__(**kw)
        self.size_hint_y = None
        self.height = th.TOUCH_MIN
        self._orig_bg = list(self.bg_color)
        self.bind(state=self._on_state)

    def _on_state(self, *_):
        if self.state == "down":
            self.bg_color = list(th.ACCENT_SOFT)
        else:
            self.bg_color = self._orig_bg


class GhostButton(PrimaryButton):
    """次要按钮：浅底而非实心，用在"保存/取消"这类非主操作上。"""

    def __init__(self, **kw):
        kw.setdefault("bg_color", list(th.BG_CARD))
        kw.setdefault("fg_color", list(th.FG_DIM))
        super().__init__(**kw)


class CardItem(ButtonBehavior, BoxLayout):
    """可点击的卡片（列表项用）。"""
    bg_color = ListProperty(list(th.BG_CARD))
    radius = NumericProperty(th.RADIUS)

    def __init__(self, **kw):
        super().__init__(**kw)
        self.size_hint_y = None
        self.height = th.TOUCH_MIN
        self.padding = [th.PAD, dp(6)]
        self.spacing = dp(6)
        self._orig_bg = list(self.bg_color)
        self.bind(state=self._on_state)

    def _on_state(self, *_):
        self.bg_color = list(th.BG_HOVER) if self.state == "down" else self._orig_bg


class Divider(Widget):
    """分隔线。"""
    color = ListProperty(list(th.BORDER))

    def __init__(self, **kw):
        super().__init__(**kw)
        self.size_hint_y = None
        self.height = 1


class FormInput(BoxLayout):
    """带标签的输入框，单行/多行通用。

    用纯 Python 构建子控件，不走 .kv。原因：kv 生成的 ids 在无窗口的
    测试环境里是空的，业务代码会拿不到输入框；而"编辑→收集→保存"这条
    数据流恰恰是最需要被测试覆盖的。让真机和测试走同一条代码路径，
    测出来的结论才有意义。
    """
    label = StringProperty("")
    hint = StringProperty("")
    multiline = BooleanProperty(False)
    field_height = NumericProperty(th.INPUT_H)
    on_change = ObjectProperty(None)

    def __init__(self, **kw):
        super().__init__(**kw)
        self.orientation = "vertical"
        self.size_hint_y = None
        self.spacing = dp(4)
        self.padding = [0, dp(6), 0, dp(6)]

        self._label = Label(text=self.label, color=th.FG_DIM,
                            font_size=th.FONT_SMALL, size_hint_y=None,
                            height=dp(20), halign="left")
        self._label.bind(width=lambda *a: setattr(
            self._label, "text_size", (self._label.width, None)))

        self.field = TextInput(
            text="", hint_text=self.hint, multiline=self.multiline,
            font_size=th.FONT_BODY, font_name=th.FONT_NAME,
            foreground_color=th.FG, hint_text_color=th.FG_FAINT,
            background_color=th.BG_INPUT, cursor_color=th.ACCENT,
            padding=[dp(12), dp(12), dp(12), dp(12)],
            size_hint_y=None, height=self.field_height)
        self.field.bind(text=lambda *_: self._fire_change())
        self.field.bind(minimum_height=lambda *_: self._sync_height())

        self.add_widget(self._label)
        self.add_widget(self.field)

        self.bind(label=self._sync_label, hint=self._sync_hint,
                  field_height=self._sync_height,
                  minimum_height=self._sync_height)
        self._sync_height()

    # Kivy 的 kv 用 ids.field 引用；这里保留同名访问方式，
    # 让两种写法都能取到输入框。
    @property
    def ids(self):
        return {"field": self.field}

    @ids.setter
    def ids(self, _value):
        """忽略外部赋值（Widget.__init__ 会初始化这个属性）。

        ids 的实际内容由上面的 getter 决定，永远是 {"field": 输入框}。
        """
        pass

    def _sync_label(self, *_):
        self._label.text = self.label

    def _sync_hint(self, *_):
        self.field.hint_text = self.hint

    def _sync_height(self, *_):
        self.field.height = self.field_height
        self.height = self._label.height + self.field_height + dp(16)

    def _fire_change(self):
        if self.on_change:
            self.on_change(self.field.text)

    def set_text(self, value):
        """程序化赋值（载入数据用）：值相同就不写，避免误触发"已修改"。"""
        field = self.field
        new = value or ""
        if field.text != new:
            field.text = new


class SectionTitle(Label):
    """分区标题。"""
    pass


class EmptyHint(Label):
    """空状态提示。"""
    pass


class ScrollBox(ScrollView):
    """常用纵向滚动容器。"""

    def __init__(self, **kw):
        kw.setdefault("bar_width", dp(5))
        kw.setdefault("scroll_type", ["content", "bars"])
        super().__init__(**kw)
        self.do_scroll_x = False
