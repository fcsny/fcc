# -*- coding: utf-8 -*-
"""安卓版逻辑测试：用 Kivy 桩在无窗口环境跑通整套界面与数据流。

不需要真机、不需要 Android SDK——跑的是**业务逻辑**（编辑→收集→保存→重开），
渲染层由 tests/fake_kivy.py 替代（与桌面版 fake_tk 同一套路）。

重点覆盖手机上特有的风险：
  * 切后台被系统杀进程 → on_pause 必须落盘
  * 切页面 → flush 不能丢内容
  * 切换人物卡 → 不能串号（桌面版踩过的坑）
  * 导入导出 → 与桌面版格式互通

运行： python -m tests.test_mobile
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import tests.fake_kivy as fake  # noqa: E402

fake.install()

TMP = tempfile.mkdtemp(prefix="aiwriter-mobile-")
os.environ["AIWRITER_HOME"] = TMP

from core import paths  # noqa: E402
from core.storage import PROJECT_EXT, Project, default_project  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print("  ✓ %s" % name)
    else:
        FAIL.append((name, detail))
        print("  ✗ %s  %s" % (name, detail))


def clean():
    """清空数据目录，保证每个用例从干净状态开始。"""
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP, exist_ok=True)
    # 目录被删过，可写性探测缓存已失效，必须清掉再重建
    cache = getattr(paths, "_probe_cache", None)
    if isinstance(cache, dict):
        cache.clear()
    os.makedirs(paths.data_dir(), exist_ok=True)
    os.makedirs(paths.export_dir(), exist_ok=True)


def boot():
    """启动一个干净的应用实例。"""
    import main
    app = main.AIWriterApp()
    app.build()
    return app


# ---------------------------------------------------------------------------
def test_imports():
    print("\n[模块导入]")
    try:
        import main  # noqa: F401
        check("main.py 可导入", True)
    except Exception as e:  # noqa: BLE001
        check("main.py 可导入", False, repr(e))
        return
    for name in ("storage", "api_client", "context", "retriever", "paths"):
        try:
            __import__("core." + name)
            check("core.%s 可导入" % name, True)
        except Exception as e:  # noqa: BLE001
            check("core.%s 可导入" % name, False, repr(e))


def test_paths():
    print("\n[路径模块]")
    check("数据目录非空", bool(paths.data_dir()), paths.data_dir())
    ok, reason = paths.is_writable(paths.data_dir())
    check("数据目录可写", ok, reason)
    ok2, reason2 = paths.is_writable(paths.export_dir())
    check("交换区可写", ok2, reason2)


def test_project_compat():
    """与桌面版共用同一份数据格式，这是互导互通的前提。"""
    print("\n[与桌面版格式一致]")
    clean()
    p = Project(path=os.path.join(paths.data_dir(), "兼容测试" + PROJECT_EXT),
                data=default_project("兼容测试"))
    ch = p.add_character("林昭")
    ch["personality"] = "外冷内热"
    ch["images"] = [{"path": "images/a.png", "caption": "立绘"}]
    l = p.add_lore("回声之力")
    l["content"] = "以记忆为燃料"
    l["pinned"] = True
    p.data["world"]["worldview"] = "架空都市"
    p.save()

    with open(p.path, "r", encoding="utf-8") as f:
        disk = json.load(f)
    for key in ("meta", "articles", "characters", "lore", "world", "gen", "api"):
        check("顶层字段 %s 存在" % key, key in disk, str(list(disk.keys())))

    reloaded = Project.load(p.path)
    check("重新打开人物卡完整",
          any(c["name"] == "林昭" and c["personality"] == "外冷内热"
              for c in reloaded.data["characters"]))
    check("图片信息保留",
          reloaded.data["characters"][0]["images"][0]["caption"] == "立绘")
    check("资料常驻标记保留", reloaded.data["lore"][0]["pinned"] is True)
    check("世界观保留", reloaded.data["world"]["worldview"] == "架空都市")


def test_app_structure():
    print("\n[应用结构]")
    clean()
    app = boot()
    check("项目已加载", app.project is not None)
    check("6 个页面齐全", len(app.sm.screens) == 6,
          str([s.name for s in app.sm.screens]))
    for name in ("article", "character", "lore", "world", "api", "project"):
        scr = app.get_screen(name)
        check("页面 %s 存在" % name, scr is not None)
    scr = app.get_screen("character")
    check("页面能访问 app", scr.app is app)


def test_edit_and_save():
    """编辑 → 收集 → 保存 → 重开，内容必须还在。"""
    print("\n[编辑与保存闭环]")
    clean()
    app = boot()

    app.switch_to("article")
    art_scr = app.get_screen("article")
    art_scr.title_input.field.text = "第一章 雨夜"
    art_scr.editor.text = "雨下了一整夜。"
    app.save_now()

    app.switch_to("character")
    cp = app.get_screen("character")
    cp.name_input.field.text = "林昭"
    cp.texts["personality"].field.text = "外冷内热，嘴硬心软"
    app.save_now()

    app.switch_to("lore")
    lp = app.get_screen("lore")
    lp.title_input.field.text = "回声之力"
    lp.content_input.field.text = "以记忆为燃料"
    app.save_now()

    app.switch_to("world")
    wp = app.get_screen("world")
    wp.texts["worldview"].field.text = "架空都市"
    app.save_now()

    path = app.project.path
    with open(path, "r", encoding="utf-8") as f:
        disk = json.load(f)
    check("正文已落盘", "雨下了一整夜" in disk["articles"][0]["content"],
          disk["articles"][0]["content"][:30])
    check("章节标题已落盘", disk["articles"][0]["title"] == "第一章 雨夜",
          disk["articles"][0]["title"])
    check("人物卡已落盘", any(c["name"] == "林昭" for c in disk["characters"]),
          str([c["name"] for c in disk["characters"]]))
    check("人物性格已落盘",
          any(c["personality"] == "外冷内热，嘴硬心软"
              for c in disk["characters"]))
    check("资料已落盘",
          any(l["content"] == "以记忆为燃料" for l in disk["lore"]))
    check("世界观已落盘", disk["world"]["worldview"] == "架空都市",
          disk["world"]["worldview"])

    # 模拟重启
    reloaded = Project.load(path)
    check("重开后人物卡还在",
          any(c["name"] == "林昭" for c in reloaded.data["characters"]),
          str([c["name"] for c in reloaded.data["characters"]]))


def test_switch_page_no_loss():
    """切页面时，当前页未提交的编辑必须被收集（flush）。"""
    print("\n[切页面不丢内容]")
    clean()
    app = boot()
    app.switch_to("world")
    wp = app.get_screen("world")
    wp.texts["style"].field.text = "第一人称，短句为主"

    app.switch_to("lore")          # 切走，应触发 flush
    check("切走后世界观仍在模型里",
          app.project.data["world"]["style"] == "第一人称，短句为主",
          repr(app.project.data["world"].get("style")))

    app.switch_to("character")
    cp = app.get_screen("character")
    cp.name_input.field.text = "周野"
    app.switch_to("article")
    check("切走后人物卡仍在模型里",
          any(c["name"] == "周野" for c in app.project.data["characters"]),
          str([c["name"] for c in app.project.data["characters"]]))


def test_switch_character_no_contamination():
    """切换人物卡不能串号——桌面版踩过的坑，手机版必须守住。"""
    print("\n[切换人物卡不串号]")
    clean()
    app = boot()
    app.switch_to("character")
    cp = app.get_screen("character")

    a = app.project.add_character("甲")
    a["personality"] = "甲的性格"
    b = app.project.add_character("乙")
    b["personality"] = "乙的性格"
    cp.refresh()

    cp._switch(a)
    check("切到甲", cp.name_input.field.text == "甲",
          cp.name_input.field.text)
    cp.texts["notes"].field.text = "只给甲的备注"
    cp.flush()

    cp._switch(b)
    check("切到乙", cp.name_input.field.text == "乙", cp.name_input.field.text)
    check("乙的性格正确", cp.texts["personality"].field.text == "乙的性格",
          cp.texts["personality"].field.text)
    check("备注没串到乙", (b.get("notes") or "") == "", repr(b.get("notes")))
    check("甲的备注还留着", a.get("notes") == "只给甲的备注",
          repr(a.get("notes")))

    cp._switch(a)
    check("切回甲内容完整",
          cp.texts["notes"].field.text == "只给甲的备注",
          cp.texts["notes"].field.text)


def test_context_build():
    """上下文组装：手机上也要能正确喂给 AI。"""
    print("\n[上下文组装]")
    clean()
    from core.context import build_context, context_summary
    app = boot()
    ch = app.project.add_character("林昭")
    ch["personality"] = "外冷内热"
    l = app.project.add_lore("回声之力")
    l["content"] = "以记忆为燃料"
    app.project.data["world"]["worldview"] = "架空都市"
    art = app.current_article()
    art["content"] = "雨下了一整夜。"

    result = build_context(app.project, art, "写一场对峙", "continue",
                           char_ids=[ch["id"]])
    body = result.prompt_text
    check("上下文含世界观", "架空都市" in body)
    check("上下文含人物", "林昭" in body)
    check("上下文含正文", "雨下了一整夜" in body)
    check("上下文含额外要求", "写一场对峙" in body)
    check("摘要可读", bool(context_summary(result)))


def test_generation_presets():
    """文章页能用的生成模式必须都是真实存在的预设。"""
    print("\n[生成预设有效]")
    from core.storage import PROMPT_PRESETS
    check("continue 预设存在", "continue" in PROMPT_PRESETS,
          str(list(PROMPT_PRESETS.keys())))
    for key in PROMPT_PRESETS:
        preset = PROMPT_PRESETS[key]
        check("预设 %s 有任务描述" % key, bool(preset.get("task")))


def test_export_import():
    """导出 → 导入 闭环（手机与电脑互通的基础）。"""
    print("\n[导出与导入]")
    clean()
    app = boot()
    ch = app.project.add_character("导出测试角色")
    ch["personality"] = "要能活着回来"
    app.save_now()

    path = app.export_project()
    check("导出文件已生成", os.path.exists(path), path)

    app._do_import(path)
    check("导入后人物卡还在",
          any(c["name"] == "导出测试角色"
              for c in app.project.data["characters"]),
          str([c["name"] for c in app.project.data["characters"]]))
    check("导入后性格还在",
          any(c["personality"] == "要能活着回来"
              for c in app.project.data["characters"]))


def test_zip_export_import():
    """挂了图片时导出为 zip，导入后图片与文字都要还原。"""
    print("\n[zip 导出导入]")
    clean()
    import zipfile
    app = boot()
    app.project.data["characters"] = []
    ch = app.project.add_character("带图角色")
    ch["personality"] = "有立绘"

    img_dir = app.project.image_dir
    os.makedirs(img_dir, exist_ok=True)
    img_path = os.path.join(img_dir, "test.png")
    with open(img_path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    ch["images"] = [{"path": os.path.relpath(
        img_path, os.path.dirname(app.project.path)), "caption": "立绘"}]
    app.save_now()

    path = app.export_project()
    check("带图导出为 zip", path.endswith(".zip"), path)
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
    check("zip 内含项目文件", any(n.endswith(PROJECT_EXT) for n in names),
          str(names))
    check("zip 内含图片", any("images/" in n for n in names), str(names))

    app._do_import(path)
    check("zip 导入后角色还在",
          any(c["name"] == "带图角色" for c in app.project.data["characters"]),
          str([c["name"] for c in app.project.data["characters"]]))
    imported = next((c for c in app.project.data["characters"]
                     if c["name"] == "带图角色"), {})
    check("zip 导入后图片信息还在", bool(imported.get("images")),
          str(imported.get("images")))


def test_export_path_not_nested():
    """导出路径不能出现两层同名目录。

    踩过的坑：export_dir() 本身已指向 .../Documents/AI写作工作台，
    调用处又拼了一次目录名，结果文件落在
    .../AI写作工作台/AI写作工作台/ 里——用户按文档给的路径去找
    根本找不到，会以为导出失败了。
    """
    print("\n[导出路径不重复拼接]")
    clean()
    app = boot()
    app.project.add_character("路径测试")
    app.save_now()

    path = app.export_project()
    check("导出文件存在", os.path.exists(path), path)
    count = path.count(paths.EXPORT_DIRNAME)
    check("目录名只出现一次（无嵌套）", count == 1,
          "出现 %d 次：%s" % (count, path))
    check("导出文件就在 export_dir 下",
          os.path.dirname(os.path.abspath(path))
          == os.path.abspath(paths.export_dir()),
          "%s vs %s" % (os.path.dirname(path), paths.export_dir()))


def test_save_failure_visible():
    """保存失败必须让用户看到，不能假装成功。"""
    print("\n[保存失败可见]")
    clean()
    app = boot()
    real = Project.save

    def boom(self, *a, **kw):
        raise OSError("模拟：磁盘写保护")

    Project.save = boom
    try:
        ok = app.save_now()
    finally:
        Project.save = real
    check("保存失败返回 False", ok is False)
    check("界面显示保存失败", "失败" in app.save_lbl.text, app.save_lbl.text)

    check("恢复后能保存", app.save_now() is True)
    check("界面显示已保存", app.save_lbl.text == "已保存", app.save_lbl.text)


def test_on_pause_saves():
    """安卓切后台会被系统杀掉，on_pause 必须落盘。"""
    print("\n[切后台自动保存]")
    clean()
    app = boot()
    app.switch_to("article")
    w = app.get_screen("article")
    w.editor.text = "切后台前写的一句话"
    app.mark_dirty()
    app.on_pause()

    with open(app.project.path, "r", encoding="utf-8") as f:
        disk = json.load(f)
    check("on_pause 已落盘",
          "切后台前写的一句话" in disk["articles"][0]["content"],
          disk["articles"][0]["content"][:40])


def main():
    print("=" * 60)
    test_imports()
    test_paths()
    test_project_compat()
    test_app_structure()
    test_edit_and_save()
    test_switch_page_no_loss()
    test_switch_character_no_contamination()
    test_context_build()
    test_generation_presets()
    test_export_import()
    test_zip_export_import()
    test_export_path_not_nested()
    test_save_failure_visible()
    test_on_pause_saves()
    print("\n" + "=" * 60)
    print("通过 %d 项，失败 %d 项" % (len(PASS), len(FAIL)))
    for name, detail in FAIL:
        print("  失败：%s  %s" % (name, detail))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
