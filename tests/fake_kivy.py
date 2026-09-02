# -*- coding: utf-8 -*-
"""Kivy 测试桩：在无窗口环境下验证"我自己写的逻辑"。

为什么不用真 Kivy：CI/容器里没有 X server，SDL 的 dummy 驱动又不提供
OpenGL，Kivy 起不来。但我要验证的是**业务数据流**（编辑→收集→保存→重开），
不是 Kivy 的渲染——所以用桩替代渲染层，保持其余代码原样运行。

忠实还原的语义（这些是逻辑正确性的前提，不能糊弄）：
  * TextInput.text 是普通字符串，赋值会触发 bind(text=...) 回调
  * bind(minimum_height=...) 在文本变化后触发（控件的高度自适应靠它）
  * Clock 可调：测试能手动推进定时任务，验证"定时兜底回写"
  * 容器支持 add_widget / clear_widgets / 子控件遍历

不还原的部分（与业务逻辑无关）：真实布局计算、触摸事件派发、OpenGL 绘制。
"""
from __future__ import annotations

import sys
import types
from typing import Any, Callable, List, Optional


# ===========================================================================
# 事件调度
# ===========================================================================
class _Clock:
    def __init__(self):
        self._once: List[tuple] = []
        self._interval: List[tuple] = []

    def schedule_once(self, cb, timeout=0):
        self._once.append((cb, timeout))
        return _Event(cb)

    def schedule_interval(self, cb, timeout):
        self._interval.append((cb, timeout))
        return _Event(cb)

    def unschedule(self, ev):
        for lst in (self._once, self._interval):
            lst[:] = [item for item in lst if item[0] is not getattr(ev, "cb", None)]

    def run_pending(self, rounds: int = 3):
        """手动推进：先跑一次性任务，再跑周期任务。"""
        for _ in range(rounds):
            once, self._once = self._once, []
            for cb, _t in once:
                cb(0)
            for cb, _t in list(self._interval):
                cb(0)


class _Event:
    def __init__(self, cb):
        self.cb = cb

    def cancel(self):
        Clock.unschedule(self)


Clock = _Clock()


# ===========================================================================
# 属性系统
# ===========================================================================
class _Property:
    """Kivy 属性：真正实现描述符，值与事件都挂在实例上。

    必须是真描述符——像 app_ref 这种属性被大量读写，
    若退化成类属性，读到的是描述符对象本身，业务代码立刻崩。
    """

    def __init__(self, default=None):
        self.default = default
        self.name = ""

    def __set_name__(self, owner, name):
        self.name = name

    def _initial(self):
        d = self.default
        if isinstance(d, list):
            return list(d)         # 列表默认值必须按实例拷贝，否则串数据
        if isinstance(d, dict):
            return dict(d)
        return d

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        store = obj.__dict__.setdefault("_prop_values", {})
        if self.name not in store:
            store[self.name] = self._initial()
        return store[self.name]

    def __set__(self, obj, value):
        store = obj.__dict__.setdefault("_prop_values", {})
        store[self.name] = value
        fire = getattr(obj, "_fire", None)
        if callable(fire):
            fire(self.name, value)


def StringProperty(default=""):
    return _Property(default)


def BooleanProperty(default=False):
    return _Property(default)


def ObjectProperty(default=None):
    return _Property(default)


def ListProperty(default=None):
    return _Property(default if default is not None else [])


def NumericProperty(default=0):
    return _Property(default)


def dp(value):
    """密度无关像素：测试环境下按 1:1 处理（比例关系不受影响）。"""
    return float(value)


def sp(value):
    return float(value)


# ===========================================================================
# 控件基类
# ===========================================================================
class Widget:
    def __init__(self, **kw):
        self.children: List[Widget] = []
        self.parent = None
        self.size = (100, 100)
        self.pos = (0, 0)
        self.size_hint_x = kw.get("size_hint_x", 1)
        self.size_hint_y = kw.get("size_hint_y", 1)
        self.height = kw.get("height", 100)
        self.width = kw.get("width", 100)
        self.opacity = 1
        self.disabled = kw.get("disabled", False)
        self._bindings: dict[str, List[Callable]] = {}
        self._props: dict[str, Any] = {}
        self.ids: dict[str, Any] = {}
        self.canvas = _Canvas()
        for k, v in kw.items():
            if k not in ("size_hint_x", "size_hint_y", "height", "width",
                         "disabled", "size_hint"):
                setattr(self, k, v)
        if "size_hint" in kw and kw["size_hint"] is not None:
            sh = kw["size_hint"]
            self.size_hint_x = sh[0]
            self.size_hint_y = sh[1]

    # -- 属性绑定 -------------------------------------------------------
    def bind(self, **kw):
        for name, cb in kw.items():
            self._bindings.setdefault(name, []).append(cb)

    def unbind(self, **kw):
        for name in kw:
            self._bindings.pop(name, None)

    def _fire(self, name, *args):
        for cb in list(self._bindings.get(name, [])):
            cb(self, *args)

    def setter(self, name):
        return lambda _inst, value: setattr(self, name, value)

    # -- 树操作 ---------------------------------------------------------
    def add_widget(self, widget, index=0):
        widget.parent = self
        if index == 0:
            self.children.insert(0, widget)
        else:
            self.children.append(widget)
        self._fire("children")

    def remove_widget(self, widget):
        if widget in self.children:
            self.children.remove(widget)
            widget.parent = None

    def clear_widgets(self, **kw):
        for c in list(self.children):
            c.parent = None
        self.children = []
        self._fire("children")

    def walk(self):
        yield self
        for c in list(self.children):
            for w in c.walk():
                yield w

    def __repr__(self):
        return "<%s>" % type(self).__name__


class _Canvas:
    def __init__(self):
        self.before = _InstructionGroup()
        self.after = _InstructionGroup()

    def clear(self):
        self.before.clear()


class _InstructionGroup:
    def __init__(self):
        self.children = []

    def clear(self):
        self.children = []

    def add(self, item):
        self.children.append(item)


# ===========================================================================
# 具体控件
# ===========================================================================
class Label(Widget):
    def __init__(self, **kw):
        self._text = kw.pop("text", "")
        self.text_size = kw.pop("text_size", None)
        self.halign = kw.pop("halign", "left")
        self.valign = kw.pop("valign", "bottom")
        self.color = kw.pop("color", (1, 1, 1, 1))
        self.font_size = kw.pop("font_size", 14)
        self.bold = kw.pop("bold", False)
        self.markup = kw.pop("markup", False)
        self.shorten = kw.pop("shorten", False)
        super().__init__(**kw)

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, value):
        self._text = "" if value is None else str(value)
        self._fire("text", self._text)          # _fire 会补 instance 参数


class Button(Label):
    def __init__(self, **kw):
        self.background_normal = kw.pop("background_normal", "")
        self.background_color = kw.pop("background_color", (1, 1, 1, 1))
        self.background_down = kw.pop("background_down", "")
        super().__init__(**kw)

    def on_release(self, *_a):
        self._fire("on_release")

    def trigger_action(self, duration=0):
        self._fire("on_release")


class TextInput(Widget):
    """文本输入框：核心是 .text 与 bind(text=...) 的联动。"""

    def __init__(self, **kw):
        self._text = "" if kw.pop("text", "") is None else str(kw.pop("text", ""))
        self.hint_text = kw.pop("hint_text", "")
        self.multiline = kw.pop("multiline", True)
        self.readonly = kw.pop("readonly", False)
        self.password = kw.pop("password", False)
        self.background_color = kw.pop("background_color", (1, 1, 1, 1))
        self.foreground_color = kw.pop("foreground_color", (1, 1, 1, 1))
        self.cursor_color = kw.pop("cursor_color", (1, 1, 1, 1))
        self.hint_text_color = kw.pop("hint_text_color", (0.5,) * 4)
        self.font_size = kw.pop("font_size", 14)
        self.padding = kw.pop("padding", [0, 0, 0, 0])
        self.focus = kw.pop("focus", False)
        self.cursor = (0, 0)
        super().__init__(**kw)
        # Kivy 里 minimum_height 由文本行数决定，变化时通知外部调整高度
        self.minimum_height = 0
        self._sync_minimum()

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, value):
        new = "" if value is None else str(value)
        if new == self._text:
            return
        self._text = new
        self._sync_minimum()
        self._fire("text", new)                 # 回调签名：(instance, value)

    def _sync_minimum(self):
        lines = max(1, self._text.count("\n") + 1)
        self.minimum_height = lines * 20
        self._fire("minimum_height", self.minimum_height)

    def insert_text(self, substring, from_undo=False):
        self.text = self._text + substring

    def select_all(self):
        pass


class BoxLayout(Widget):
    def __init__(self, **kw):
        self.orientation = kw.pop("orientation", "horizontal")
        self.spacing = kw.pop("spacing", 0)
        self.padding = kw.pop("padding", [0, 0, 0, 0])
        super().__init__(**kw)


class ScrollView(Widget):
    def __init__(self, **kw):
        self.do_scroll_x = kw.pop("do_scroll_x", True)
        self.do_scroll_y = kw.pop("do_scroll_y", True)
        self.scroll_type = kw.pop("scroll_type", ["content"])
        self.effect_cls = kw.pop("effect_cls", None)
        self.bar_width = kw.pop("bar_width", 4)
        super().__init__(**kw)

    def scroll_to(self, widget, **kw):
        pass


class Popup(Widget):
    """弹窗：open/dismiss 记录到 LOG，供测试断言。"""

    opened = []
    LOG = {"popups": []}

    def __init__(self, **kw):
        self.title = kw.pop("title", "")
        self.content = kw.pop("content", None)
        self.size_hint = kw.pop("size_hint", (1, 1))
        self.background = kw.pop("background", "")
        self.separator_color = kw.pop("separator_color", (1, 1, 1, 1))
        self.separator_height = kw.pop("separator_height", 1)
        self.title_color = kw.pop("title_color", (1, 1, 1, 1))
        self.title_size = kw.pop("title_size", 14)
        self.auto_dismiss = kw.pop("auto_dismiss", True)
        super().__init__(**kw)
        self._open = False

    def open(self, *_a, **kw):
        self._open = True
        Popup.opened.append(self)
        Popup.LOG["popups"].append(self.title)

    def dismiss(self, *_a, **kw):
        self._open = False
        if self in Popup.opened:
            Popup.opened.remove(self)


class Screen(Widget):
    name = ""
    manager = None

    def __init__(self, **kw):
        self.name = kw.pop("name", "")
        super().__init__(**kw)

    def on_pre_enter(self, *_a):
        pass

    def on_enter(self, *_a):
        pass

    def on_pre_leave(self, *_a):
        pass

    def on_leave(self, *_a):
        pass


class ScreenManager(Widget):
    def __init__(self, **kw):
        self.transition = kw.pop("transition", None)
        self._screens: dict[str, Screen] = {}
        self.current = ""
        super().__init__(**kw)

    def add_widget(self, widget, index=0):
        super().add_widget(widget, index)
        if isinstance(widget, Screen):
            widget.manager = self
            self._screens[widget.name] = widget
            if not self.current:
                self.current = widget.name

    def get_screen(self, name) -> Optional[Screen]:
        return self._screens.get(name)

    @property
    def screens(self) -> List[Screen]:
        return list(self._screens.values())

    @property
    def current_screen(self) -> Optional[Screen]:
        return self._screens.get(self.current)

    def __setattr__(self, name, value):
        if name == "current" and hasattr(self, "_screens"):
            prev = getattr(self, "current", None)
            object.__setattr__(self, "current", value)
            if prev and prev in self._screens and prev != value:
                self._screens[prev].on_pre_leave()
                self._screens[prev].on_leave()
            scr = self._screens.get(value)
            if scr is not None:
                scr.on_pre_enter()
                scr.on_enter()
            return
        object.__setattr__(self, name, value)


class SlideTransition:
    def __init__(self, **kw):
        self.direction = kw.pop("direction", "left")
        self.duration = kw.pop("duration", 0.3)


class CheckBox(Widget):
    """复选框：界面用 .active 读写，必须支持 bind(active=...)。"""

    def __init__(self, **kw):
        self._active = bool(kw.pop("active", False))
        super().__init__(**kw)

    @property
    def active(self):
        return self._active

    @active.setter
    def active(self, value):
        new = bool(value)
        if new != self._active:
            self._active = new
            self._fire("active", new)

    def on_active(self, *_a):
        pass


class Spinner(Button):
    """下拉选择：用 text 读写，values 仅记录。"""

    def __init__(self, **kw):
        self.values = kw.pop("values", ())
        super().__init__(**kw)


class ButtonBehavior:
    """混入类：给任意控件加按钮行为。

    真 Kivy 里它是 EventDispatcher 的子类，需要和布局类多重继承。
    桩里只需提供 state 与 on_release 事件即可。
    """

    def __init__(self, *args, **kw):
        self.state = kw.pop("state", "normal")
        super().__init__(*args, **kw)

    def on_release(self, *_a):
        self._fire("on_release")

    def trigger_action(self, duration=0):
        self._fire("on_release")


class ToggleButton(Button):
    def __init__(self, **kw):
        self.group = kw.pop("group", None)
        self.state = kw.pop("state", "normal")
        super().__init__(**kw)


# ===========================================================================
# App
# ===========================================================================
class App:
    def __init__(self, **kw):
        self.title = kw.pop("title", "")
        self.root = None

    def build(self):
        return None

    def run(self):
        self.root = self.build()

    def stop(self):
        pass

    def on_pause(self):
        return True

    def on_stop(self):
        pass

    def get_running_app():
        return None


# ===========================================================================
# 组装成模块，塞进 sys.modules
# ===========================================================================
def _mod(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


def install():
    """把桩装进 sys.modules，必须在 import main 之前调用。"""
    _mod("kivy", __version__="2.3.1-stub")
    _mod("kivy.clock", Clock=Clock, mainthread=lambda f: f)
    _mod("kivy.metrics", dp=dp, sp=sp, Metrics=object)
    _mod("kivy.properties",
         StringProperty=StringProperty, BooleanProperty=BooleanProperty,
         ObjectProperty=ObjectProperty, ListProperty=ListProperty,
         NumericProperty=NumericProperty, AliasProperty=_Property)
    _mod("kivy.graphics",
         Color=lambda *a, **k: None, Rectangle=lambda **k: None,
         RoundedRectangle=lambda **k: None, Line=lambda **k: None,
         Ellipse=lambda **k: None, InstructionGroup=_InstructionGroup)
    _mod("kivy.core", __path__=[])
    _mod("kivy.core.window",
         Window=types.SimpleNamespace(size=(400, 800), softinput_mode=""),
         WindowBase=types.SimpleNamespace(softinput_mode=""))

    _mod("kivy.uix", __path__=[])   # 必须是包，才能有子模块
    _mod("kivy.uix.widget", Widget=Widget)
    _mod("kivy.uix.label", Label=Label)
    _mod("kivy.uix.button", Button=Button)
    _mod("kivy.uix.textinput", TextInput=TextInput)
    _mod("kivy.uix.boxlayout", BoxLayout=BoxLayout)
    _mod("kivy.uix.scrollview", ScrollView=ScrollView)
    _mod("kivy.uix.popup", Popup=Popup)
    _mod("kivy.uix.screenmanager",
         Screen=Screen, ScreenManager=ScreenManager,
         SlideTransition=SlideTransition, NoTransition=SlideTransition)
    _mod("kivy.uix.behaviors", ButtonBehavior=ButtonBehavior,
         ToggleButtonBehavior=ButtonBehavior)
    _mod("kivy.uix.togglebutton", ToggleButton=ToggleButton)
    _mod("kivy.uix.image", Image=Label, AsyncImage=Label)
    _mod("kivy.uix.spinner", Spinner=Spinner)
    _mod("kivy.uix.slider", Slider=Widget)
    _mod("kivy.uix.progressbar", ProgressBar=Widget)
    _mod("kivy.uix.checkbox", CheckBox=CheckBox)
    _mod("kivy.uix.filechooser", FileChooserListView=Widget)
    _mod("kivy.uix.floatlayout", FloatLayout=Widget)
    _mod("kivy.uix.gridlayout", GridLayout=BoxLayout)
    _mod("kivy.uix.stacklayout", StackLayout=BoxLayout)
    _mod("kivy.uix.anchorlayout", AnchorLayout=Widget)
    _mod("kivy.uix.relativelayout", RelativeLayout=Widget)
    _mod("kivy.uix.modalview", ModalView=Popup)

    _mod("kivy.app", App=App, MDApp=App)
    _mod("kivy.lang", Builder=types.SimpleNamespace(
        load_file=lambda *a, **k: None,
        load_string=lambda *a, **k: None))
    _mod("kivy.event", EventDispatcher=Widget)
    _mod("kivy.factory", Factory=types.SimpleNamespace())
    _mod("kivy.utils", platform=lambda: "android",
         get_color_from_hex=lambda s: (1, 1, 1, 1))
    _mod("kivy.resources", resource_add_path=lambda p: None,
         resource_find=lambda p: None)
    _mod("kivy.logger", Logger=types.SimpleNamespace(
        info=lambda *a: None, warning=lambda *a: None,
        error=lambda *a: None, debug=lambda *a: None))
    _mod("kivy.animation", Animation=object)

    # android 包：桌面测试时不存在，提供空壳让 import 不报错
    _mod("android")
    _mod("android.storage",
         app_storage_path=lambda: "/tmp/_fake_android_app",
         primary_external_storage_path=lambda: "/tmp/_fake_android_sd")

    return Clock
