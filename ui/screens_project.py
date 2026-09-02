# -*- coding: utf-8 -*-
"""项目页：数据统计、存储自检、导入导出。

导出/导入设计与桌面版完全一致（同一个 zip 结构），
两边用微信/QQ 传文件就能互导。
"""
import json
import os

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView

from core import paths
from core.paths import (PROJECT_EXT, data_dir, export_dir,
                          is_writable)
from core.storage import Project
from ui import theme as th
from ui.base import BaseScreen, PaddedBody
from ui.widgets import Divider, GhostButton, PrimaryButton, SectionTitle


class ProjectScreen(BaseScreen):
    title = "项目"

    def __init__(self, **kw):
        super().__init__(**kw)
        self._root = BoxLayout(orientation="vertical")
        self.body = PaddedBody()
        sv = ScrollView()
        sv.add_widget(self.body)
        self._root.add_widget(sv)
        self.add_widget(self._root)
        self._build()

    def _build(self):
        self.body.add_widget(SectionTitle(text="当前项目"))
        self.info = Label(text="", color=th.FG_DIM, font_size=th.FONT_SMALL,
                          size_hint_y=None, height=dp(120), halign="left",
                          valign="top")
        self.info.bind(width=lambda *a: setattr(self.info, "text_size",
                                                (self.info.width, None)))
        self.body.add_widget(self.info)

        row = BoxLayout(size_hint_y=None, height=th.TOUCH_MIN, spacing=dp(8))
        b1 = PrimaryButton(text="立即保存")
        b1.bind(on_release=lambda *_: self._save_now())
        row.add_widget(b1)
        self.body.add_widget(row)

        self.body.add_widget(Divider())
        self.body.add_widget(SectionTitle(text="存储自检"))
        self.storage = Label(text="", color=th.FG_DIM, font_size=th.FONT_SMALL,
                             size_hint_y=None, height=dp(80), halign="left",
                             valign="top")
        self.storage.bind(width=lambda *a: setattr(self.storage, "text_size",
                                                   (self.storage.width, None)))
        self.body.add_widget(self.storage)

        self.body.add_widget(Divider())
        self.body.add_widget(SectionTitle(text="备份与迁移"))
        tip = Label(
            text="导出会把整个项目（含图片）打包成一个 zip。\n"
                 "传到电脑后，用桌面版「项目 → 从 zip 导入」即可打开，\n"
                 "两边用同一个格式，可来回迁移。",
            color=th.FG_FAINT, font_size=th.FONT_SMALL, size_hint_y=None,
            height=dp(70), halign="left", valign="top")
        tip.bind(width=lambda *a: setattr(tip, "text_size", (tip.width, None)))
        self.body.add_widget(tip)

        row2 = BoxLayout(size_hint_y=None, height=th.TOUCH_MIN, spacing=dp(8))
        for text, fn in (("导出 zip", self._export), ("导入 zip", self._import)):
            b = GhostButton(text=text)
            b.bind(on_release=lambda *_w, f=fn: f())
            row2.add_widget(b)
        self.body.add_widget(row2)

        self.op_label = Label(text="", color=th.FG_DIM, font_size=th.FONT_SMALL,
                              size_hint_y=None, height=dp(60), halign="left",
                              valign="top")
        self.op_label.bind(width=lambda *a: setattr(self.op_label, "text_size",
                                                    (self.op_label.width, None)))
        self.body.add_widget(self.op_label)

    # ------------------------------------------------------------------
    def refresh(self):
        p = self.app.project
        d = p.data
        self.info.text = (
            "项目名：%s\n"
            "章节：%d 章 ｜ 人物卡：%d 张 ｜ 资料：%d 条\n"
            "最后保存：%s\n"
            "文件：%s"
            % (p.name, len(d.get("articles", [])), len(d.get("characters", [])),
               len(d.get("lore", [])), d.get("meta", {}).get("updated", "—"),
               os.path.basename(p.path or "未保存")))

        ok, reason = is_writable(data_dir())
        if ok:
            self.storage.color = th.OK
            self.storage.text = "✔ 数据目录可正常写入\n%s" % data_dir()
        else:
            self.storage.color = th.ERR
            self.storage.text = "✘ 无法写入：%s\n%s" % (data_dir(), reason)

    def _save_now(self):
        self.flush_all()
        if self.app.save_project(force=True):
            self.op_label.color = th.OK
            self.op_label.text = "已保存并校验通过"
            self.refresh()

    def flush_all(self):
        for name in ("article", "character", "lore", "world", "api"):
            screen = (self.app.sm.get_screen(name)
                      if self.app.sm and self.app.sm.get_screen(name) else None)
            if screen and hasattr(screen, "flush"):
                try:
                    screen.flush()
                except Exception:  # noqa: BLE001
                    pass

    # -- 导入导出 --------------------------------------------------------
    def _export(self):
        """导出到对外交换区（用户能在文件管理器里找到）。"""
        try:
            path = self.app.export_project()
            self._note(th.OK,
                       "已导出到：\n%s\n\n"
                       "传到电脑后，用桌面版「项目 → 从 zip 导入」打开" % path)
        except Exception as e:  # noqa: BLE001
            self._note(th.ERR, "导出失败：%s" % e)

    def _import(self):
        """从交换区导入：列出可导入文件供选择。"""
        from core.paths import list_importable
        cands = list_importable()
        if not cands:
            self._note(th.WARN,
                       "交换区里没有可导入的文件。\n"
                       "把 .aiwriter.json 或 .zip 放进：\n%s"
                       % export_dir())
            return
        self._show_picker(cands)

    def _show_picker(self, cands):
        from kivy.uix.popup import Popup
        from kivy.uix.scrollview import ScrollView
        from ui.base import PaddedBody
        from ui.widgets import GhostButton, PrimaryButton

        body = PaddedBody()
        from kivy.uix.label import Label
        for path in cands[:20]:
            row = BoxLayout(size_hint_y=None, height=th.TOUCH_MIN, spacing=dp(8))
            lab = Label(text=os.path.basename(path), color=th.FG,
                        font_size=th.FONT_SMALL, halign="left", shorten=True,
                        size_hint_x=1)
            lab.bind(width=lambda *a, l=lab: setattr(l, "text_size",
                                                     (l.width, None)))
            btn = PrimaryButton(text="导入", size_hint_x=None, width=dp(72))
            btn.bind(on_release=lambda *_w, p=path, pop=None: self._pick(p, pop))
            row.add_widget(lab)
            row.add_widget(btn)
            body.add_widget(row)

        sv = ScrollView()
        sv.add_widget(body)
        btns = GhostButton(text="取消", size_hint_y=None, height=th.TOUCH_MIN)
        box = BoxLayout(orientation="vertical")
        box.add_widget(sv)
        box.add_widget(btns)

        self._popup = Popup(title="选择要导入的项目", content=box,
                            size_hint=(0.95, 0.85))
        btns.bind(on_release=lambda *_: self._popup.dismiss())
        self._popup.open()

    def _pick(self, path, popup=None):
        try:
            if popup is not None:
                popup.dismiss()
            if getattr(self, "_popup", None) is not None:
                self._popup.dismiss()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.app._do_import(path)
            self._note(th.OK, "已导入：%s" % self.app.project.name)
            self.refresh()
        except Exception as e:  # noqa: BLE001
            self._note(th.ERR, "导入失败：%s" % e)

    def _note(self, color, text):
        self.op_label.color = color
        self.op_label.text = text
