#!/usr/bin/env python3
"""Wrap the plain-text weekly report in monospace HTML so column alignment survives in
iPhone Mail (which otherwise renders proportional). Usage: to_html.py in.txt out.html"""
import html, sys

txt = open(sys.argv[1], encoding="utf-8").read()
open(sys.argv[2], "w", encoding="utf-8").write(
    "<!doctype html><meta name='viewport' content='width=device-width,initial-scale=1'>"
    "<body style='margin:0;background:#0d1117;color:#c9d1d9'>"
    "<pre style='font-family:Menlo,Consolas,monospace;font-size:11px;line-height:1.35;"
    "white-space:pre;overflow-x:auto;padding:10px'>" + html.escape(txt) + "</pre></body>")
