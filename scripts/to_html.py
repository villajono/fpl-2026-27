#!/usr/bin/env python3
"""Wrap the plain-text weekly report in HTML for iPhone Mail.

Two zones, because the report serves two purposes. The DO THIS block that weekly.py::tldr()
puts at the top is what Jon acts on before the deadline, so it renders as a card — larger,
higher contrast, above the fold. Everything after it is the reasoning, and stays monospace
because its columns only line up in a fixed-width font (iPhone Mail otherwise renders
proportional and the tables collapse).

If the marker is missing — an older report, or tldr() returning nothing — the whole file falls
back to the previous monospace-everything behaviour rather than failing.

Usage: to_html.py in.txt out.html
"""
import html
import sys

MARK = "DO THIS  --  "
END = "If you are in a hurry, you are done."

txt = open(sys.argv[1], encoding="utf-8").read()
lines = txt.split("\n")

head, body = None, txt
starts = [i for i, l in enumerate(lines) if l.startswith(MARK)]
ends = [i for i, l in enumerate(lines) if l.strip() == END]
if starts and ends and ends[0] > starts[0]:
    a = starts[0]
    while a > 0 and set(lines[a - 1].strip()) <= {"="} and lines[a - 1].strip():
        a -= 1                                    # swallow the rule above the heading
    head = "\n".join(lines[a:ends[0] + 1])
    body = "\n".join(lines[:a] + lines[ends[0] + 1:])

CSS_PRE = ("font-family:Menlo,Consolas,monospace;font-size:11px;line-height:1.35;"
           "white-space:pre;overflow-x:auto;padding:10px;margin:0")

out = ["<!doctype html><meta name='viewport' content='width=device-width,initial-scale=1'>",
       "<body style='margin:0;background:#0d1117;color:#c9d1d9'>"]
if head:
    out.append(
        "<div style='background:#161b22;border-left:4px solid #2f81f7;padding:14px 12px 12px;"
        "margin:0 0 4px'>"
        "<pre style='font-family:Menlo,Consolas,monospace;font-size:13px;line-height:1.5;"
        "white-space:pre-wrap;word-break:break-word;margin:0;color:#e6edf3'>"
        + html.escape(head) + "</pre></div>")
out.append("<pre style='" + CSS_PRE + "'>" + html.escape(body) + "</pre></body>")
open(sys.argv[2], "w", encoding="utf-8").write("".join(out))
