#!/usr/bin/env python3
"""控制台横向溢出判据：两视口 × 全部域内页，断言页面不被撑宽。

为什么需要它：2026-11-20/21 修表格溢出改了四轮——每轮都是「看真实页面哪里宽
就改哪里」，没有一次把撑宽路径枚举全。没有判据，下次改表格样式还会重犯。

为什么三态退出码：本仓已有先例（check_status_wording.py / fd-bench-web 的
check_facts.py）。「没跑成」与「跑过且通过」输出必须不同，否则又是一道假绿门。

跑法（需要真实登录凭据，从环境变量读，不落盘）：
    CONSOLE_EMAIL=... CONSOLE_PASSWORD=... \\
        python3 scripts/check_console_overflow.py --base https://lawbench.finddatatech.cloud

    # 判据自身是否有效（不碰网络）：
    python3 scripts/check_console_overflow.py --self-check

退出码：0 全部零溢出 / 1 检出溢出 / 2 未判定。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

VIEWPORTS = ((1440, 900), (390, 844))
DOMAIN_PAGES = ("", "/ontology", "/inbox", "/publish", "/team", "/promotion")


def _exit(code: int, msg: str) -> int:
    print(msg, file=sys.stderr if code else sys.stdout)
    return code


def _measure_js() -> str:
    return "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"


def check_overflow(overflow_px_by_page: dict[str, dict[str, int]]) -> tuple[int, list[str]]:
    """Pure: given {page: {viewport: px}}, decide pass/fail. Returns (code, problems)."""
    problems = [
        f"{page} @{vp}: {px}px 溢出"
        for page, per_vp in overflow_px_by_page.items()
        for vp, px in per_vp.items()
        if px > 0
    ]
    return (1 if problems else 0), problems


def self_check() -> int:
    """判据本身必须双向有效：干净页绿、溢出页红。"""
    cases = [
        ("干净", {"/d": {"1440": 0, "390": 0}}, 0),
        ("桌面溢出", {"/d": {"1440": 1200, "390": 0}}, 1),
        ("移动溢出", {"/d/legal": {"1440": 0, "390": 174}}, 1),
    ]
    bad = 0
    for name, data, want in cases:
        got, _ = check_overflow(data)
        ok = got == want
        print(f"{'✓' if ok else '✗'} 夹具[{name}] 期望 {want} 实得 {got}")
        bad += 0 if ok else 1
    return 1 if bad else 0


def run(base: str) -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return _exit(2, "⚠ 未判定：缺 playwright（这不是通过）")

    email = os.environ.get("CONSOLE_EMAIL")
    password = os.environ.get("CONSOLE_PASSWORD")
    if not email or not password:
        return _exit(2, "⚠ 未判定：缺 CONSOLE_EMAIL / CONSOLE_PASSWORD（这不是通过）")

    results: dict[str, dict[str, int]] = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width, height in VIEWPORTS:
            ctx = browser.new_context(viewport={"width": width, "height": height})
            page = ctx.new_page()
            try:
                page.goto(base + "/", wait_until="domcontentloaded", timeout=60000)
                page.wait_for_selector('input[name="identifier"]', timeout=30000)
                page.fill('input[name="identifier"]', email)
                page.click('button[type="submit"]')
                page.wait_for_selector('input[type="password"]', timeout=30000)
                page.fill('input[type="password"]', password)
                page.click('button[type="submit"]')
                page.wait_for_url(
                    lambda u: base.split("//")[-1] in u and "/auth/" not in u, timeout=60000
                )
            except Exception as exc:  # noqa: BLE001
                browser.close()
                return _exit(2, f"⚠ 未判定：登录失败 {type(exc).__name__}: {str(exc)[:120]}")

            # 从 /d 读域列表，再逐域展开。
            page.goto(base + "/d", wait_until="networkidle", timeout=45000)
            # 注意：域链接可能是绝对 URL（生产实测是 https://host/d/xxx），
            # 所以按路径片段取而不是按 `href^="/d/"` 前缀匹配——后者会静默取到 0 个域，
            # 判据看起来「通过」但只测了 1 页（2026-11-21 实撞）。
            domains = page.evaluate(
                """() => [...document.querySelectorAll('a')]
                  .map(a => a.getAttribute('href') || '')
                  .filter(h => h.indexOf('/d/') !== -1)
                  .map(h => h.split('/d/')[1].split('/')[0].split('?')[0].split('#')[0])
                  .filter((v,i,arr) => v && arr.indexOf(v) === i)"""
            )
            if not domains:
                browser.close()
                return _exit(2, "⚠ 未判定：/d 页没解析出任何域（选择器失配），这不是通过")
            paths = ["/d"] + [f"/d/{d}" for d in domains]
            paths += [f"/d/{d}{suffix}" for d in domains for suffix in DOMAIN_PAGES if suffix]

            for path in paths:
                resp = page.goto(base + path, wait_until="networkidle", timeout=45000)
                if resp is None or resp.status >= 400:
                    browser.close()
                    return _exit(2, f"⚠ 未判定：{path} 返回 {resp.status if resp else 'no response'}")
                px = page.evaluate(_measure_js())
                results.setdefault(path, {})[str(width)] = int(px)
            ctx.close()
        browser.close()

    code, problems = check_overflow(results)
    if problems:
        for p in problems:
            print(f"✗ {p}", file=sys.stderr)
        return 1
    print(f"✓ {len(results)} 页 × {len(VIEWPORTS)} 视口全部零溢出")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://lawbench.finddatatech.cloud")
    ap.add_argument("--self-check", action="store_true")
    ap.add_argument("--json", action="store_true", help="输出机器可读结果")
    args = ap.parse_args()
    if args.self_check:
        return self_check()
    return run(args.base)


if __name__ == "__main__":
    sys.exit(main())
