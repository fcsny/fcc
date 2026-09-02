# -*- coding: utf-8 -*-
"""API 接入页：填服务商、地址、Key、模型，测连通。

手机上要点：
  * 「测试连接」和「拉取模型列表」做成两个大按钮，点一下就能确认能不能用
  * 结果直接显示在同一页，不弹窗（弹窗在手机上容易误触关闭）
"""
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner

from ui import theme as th
from ui.base import BaseScreen, PaddedBody
from ui.widgets import Divider, FormInput, GhostButton, PrimaryButton, SectionTitle


class ApiScreen(BaseScreen):
    title = "API 接入"

    def __init__(self, **kw):
        super().__init__(**kw)
        self._building = True
        self.fields: dict[str, FormInput] = {}

        self._root = BoxLayout(orientation="vertical")
        self.body = PaddedBody()
        sv = ScrollView()
        sv.add_widget(self.body)
        self._root.add_widget(sv)
        self.add_widget(self._root)
        self._build()
        self._building = False

    def _build(self):
        body = self.body
        body.add_widget(SectionTitle(text="模型接入"))

        # 服务商
        box = BoxLayout(orientation="vertical", size_hint_y=None,
                        height=th.INPUT_H + dp(22), spacing=dp(2))
        box.add_widget(Label(text="服务商", color=th.FG_DIM,
                             font_size=th.FONT_SMALL, size_hint_y=None,
                             height=dp(20), halign="left"))
        self.provider = Spinner(
            text="openai", values=("openai", "anthropic", "custom"),
            size_hint_y=None, height=th.INPUT_H,
            background_color=th.BG_INPUT, color=th.FG, font_size=th.FONT_UI)
        self.provider.bind(text=lambda *_: self._on_change())
        box.add_widget(self.provider)
        body.add_widget(box)

        for key, label, hint in (
            ("base_url", "Base URL", "https://api.deepseek.com/v1"),
            ("api_key", "API Key", "sk-..."),
            ("model", "模型名称", "deepseek-chat"),
        ):
            f = FormInput(label=label, hint=hint, multiline=False)
            f.on_change = lambda _v: self._on_change()
            self.fields[key] = f
            body.add_widget(f)

        row = BoxLayout(size_hint_y=None, height=th.TOUCH_MIN, spacing=dp(8))
        b1 = GhostButton(text="拉取模型")
        b1.bind(on_release=lambda *_: self._fetch_models())
        b2 = PrimaryButton(text="测试连接")
        b2.bind(on_release=lambda *_: self._test())
        row.add_widget(b1)
        row.add_widget(b2)
        body.add_widget(row)

        self.result = Label(text="", color=th.FG_DIM, font_size=th.FONT_SMALL,
                            size_hint_y=None, height=dp(56), halign="left",
                            valign="top")
        self.result.bind(width=lambda *a: setattr(self.result, "text_size",
                                                  (self.result.width, None)))
        body.add_widget(self.result)

        body.add_widget(Divider())
        body.add_widget(SectionTitle(text="生成参数"))
        for key, label, hint in (("temperature", "温度 Temperature", "0.9"),
                                 ("max_tokens", "最大输出 Tokens", "2000")):
            f = FormInput(label=label, hint=hint, multiline=False)
            f.on_change = lambda _v: self._on_change()
            self.fields[key] = f
            body.add_widget(f)

        tip = Label(
            text="Base URL 末尾一般带 /v1。\n"
                 "国内可用：DeepSeek、智谱、Moonshot、硅基流动，\n"
                 "都能用 OpenAI 兼容协议（服务商选 openai）。",
            color=th.FG_FAINT, font_size=th.FONT_SMALL, size_hint_y=None,
            height=dp(70), halign="left", valign="top")
        tip.bind(width=lambda *a: setattr(tip, "text_size", (tip.width, None)))
        body.add_widget(tip)
        body.add_widget(Label(text="", size_hint_y=None, height=dp(20)))

    # ------------------------------------------------------------------
    def _on_change(self, *_):
        if self._building:
            return
        self.flush()
        self.mark_dirty()

    def refresh(self):
        was = self._building
        self._building = True
        try:
            api = self.app.project.data["api"]
            self.provider.text = str(api.get("provider") or "openai")
            self.fields["base_url"].set_text(api.get("base_url", "") or "")
            self.fields["api_key"].set_text(api.get("api_key", "") or "")
            self.fields["model"].set_text(api.get("model", "") or "")
            self.fields["temperature"].set_text(str(api.get("temperature", 0.9)))
            self.fields["max_tokens"].set_text(str(api.get("max_tokens", 2000)))
        finally:
            self._building = was

    def flush(self):
        if self._building:
            return
        api = self.app.project.data["api"]
        api["provider"] = self.provider.text
        api["base_url"] = self.fields["base_url"].field.text.strip()
        api["api_key"] = self.fields["api_key"].field.text.strip()
        api["model"] = self.fields["model"].field.text.strip()
        for key, cast in (("temperature", float), ("max_tokens", int)):
            raw = self.fields[key].field.text.strip()
            try:
                api[key] = cast(raw)
            except (TypeError, ValueError):
                pass

    # ------------------------------------------------------------------
    def _fetch_models(self):
        self.flush()
        self.app.save_project()
        self.result.color = th.FG_DIM
        self.result.text = "正在拉取…"
        self.app.run_async(self._do_fetch, self._on_fetch_done)

    def _do_fetch(self):
        from core.api_client import AIClient
        return AIClient(self.app.project.data["api"]).list_models()

    def _on_fetch_done(self, result):
        ok, value = result
        if ok:
            models = value or []
            if models:
                self.fields["model"].set_text(models[0])
                self.flush()
                self.result.color = th.OK
                self.result.text = "拉到 %d 个模型，已填入：%s" % (
                    len(models), models[0])
            else:
                self.result.color = th.WARN
                self.result.text = "接口没返回模型列表，请手动填写模型名"
        else:
            self.result.color = th.ERR
            self.result.text = "失败：%s" % value

    def _test(self):
        self.flush()
        self.app.save_project()
        self.result.color = th.FG_DIM
        self.result.text = "正在测试…"
        self.app.run_async(self._do_test, self._on_test_done)

    def _do_test(self):
        from core.api_client import AIClient
        return AIClient(self.app.project.data["api"]).test()

    def _on_test_done(self, result):
        ok, value = result
        if ok:
            self.result.color = th.OK
            self.result.text = "连接成功，模型回复：%s" % (value or "").strip()[:60]
        else:
            self.result.color = th.ERR
            self.result.text = "连接失败：%s" % value
