"""
Disk-usage renderer — turns ``ScanResults`` into human or machine output.

The renderer is split into small, single-purpose methods so the CLI can
pick the right combination. New outputs are easy to add: just write a
``render_<thing>`` method and surface a flag for it in the CLI.

Public methods
--------------
- render_terminal_table
- render_compact_table       (small terminal friendly)
- render_json
- render_csv
- render_markdown
- render_html                (self-contained, no JS required)
- render_ndjson              (one entry per line)
- render_yaml                (best-effort, no PyYAML dependency)
- render_tree
- render_largest_files
- render_extensions
- render_breakdown
- render_bar_chart
- render_pie_chart
- render_sunburst
- render_treemap
- render_age_breakdown
- render_storage_fingerprint
- render_suggestions
- render_category_bars       (storage category summary)
- render_smart_skip_notice   (size-only entries)
- render_summary
- render_diff
"""

from __future__ import annotations

import csv
import io
import json
import re
import time
import html
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from spacelyzer.analyzer import analyze_entry
from spacelyzer.formatter import (
    format_age, format_bytes, format_percent,
    get_color_codes, has_unicode_support, pad_visible,
    truncate_middle, terminal_width,
)
from spacelyzer.scanner import EntryInfo, ScanResults
from spacelyzer.snapshots import Diff
from spacelyzer.suggestions import SuggestionItem


# --------------------------------------------------------------------------- #
#  Box-drawing helpers
# --------------------------------------------------------------------------- #
class _Box:
    """Unicode / ASCII box-drawing characters for tables and trees."""

    def __init__(self, unicode_ok: bool):
        if unicode_ok:
            self.h = "─"
            self.v = "│"
            self.x = "┼"
            self.tl = "┌"; self.tr = "┐"; self.bl = "└"; self.br = "┘"
            self.t_up = "┴"; self.t_down = "┬"
            self.t_left = "┤"; self.t_right = "├"
            self.tree_mid = "├── "
            self.tree_last = "└── "
            self.tree_v = "│   "
            self.tree_empty = "    "
            self.bullet = "·"
            self.dash = "—"
            self.arrow = "→"
            self.chk = "✓"
            self.cross = "✗"
            self.bar_char = "█"
        else:
            self.h = "-"
            self.v = "|"
            self.x = "+"
            self.tl = "+"; self.tr = "+"; self.bl = "+"; self.br = "+"
            self.t_up = "+"; self.t_down = "+"
            self.t_left = "+"; self.t_right = "+"
            self.tree_mid = "|-- "
            self.tree_last = "`-- "
            self.tree_v = "|   "
            self.tree_empty = "    "
            self.bullet = "-"
            self.dash = "-"
            self.arrow = "->"
            self.chk = "[OK]"
            self.cross = "[X]"
            self.bar_char = "#"


def _build_table(headers: Sequence[str], rows: Sequence[Sequence[str]],
                 aligns: Sequence[str], width: int, box: _Box) -> str:
    """Build a unicode/ASCII table that fits *width* columns.

    `headers`, `rows`, and `aligns` are parallel sequences; each row is
    a sequence of plain strings (no ANSI codes — wrap externally).
    """
    ncols = len(headers)
    # Initial widths: header length or 1 (so an empty col is still visible)
    col_w = [max(1, len(headers[i])) for i in range(ncols)]
    for row in rows:
        for i, cell in enumerate(row):
            col_w[i] = max(col_w[i], len(cell))

    # Total width = sum(col) + 3*ncols + 1  (3 for " | " separators)
    fixed = sum(col_w) + 3 * ncols + 1
    if fixed > width:
        # Trim the last (path) column first
        excess = fixed - width
        for col_idx in range(ncols - 1, -1, -1):
            if col_idx == 0:
                # Don't crush the rank column below 1
                col_w[col_idx] = max(1, col_w[col_idx] - excess)
                break
            can = max(3, col_w[col_idx] - excess)
            if can >= 3:
                col_w[col_idx] = can
                excess -= (col_w[col_idx] - can) if can > 0 else 0
                if excess <= 0:
                    break
    else:
        # If we have spare room, give the last col the rest
        spare = width - fixed
        col_w[-1] += max(0, spare)

    def _cell(s: str, w: int, align: str) -> str:
        if align == "right":
            return s.rjust(w)
        if align == "center":
            return s.center(w)
        return s.ljust(w)

    def _border(left: str, mid: str, right: str) -> str:
        segs = [box.h * (col_w[i] + 2) for i in range(ncols)]
        return left + mid.join(segs) + right

    top = _border(box.tl, box.t_down, box.tr)
    mid = _border(box.t_right, box.x, box.t_left)
    bot = _border(box.bl, box.t_up, box.br)

    out: List[str] = []
    out.append(top)
    header_cells = [
        " " + _cell(headers[i], col_w[i], "center") + " "
        for i in range(ncols)
    ]
    out.append(box.v + box.v.join(header_cells) + box.v)
    out.append(mid)
    for row in rows:
        cells = []
        for i in range(ncols):
            v = row[i]
            if len(v) > col_w[i]:
                v = v[:max(0, col_w[i] - 1)] + "…"
            cells.append(" " + _cell(v, col_w[i], aligns[i]) + " ")
        out.append(box.v + box.v.join(cells) + box.v)
    out.append(bot)
    return "\n".join(out)


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #
def _section(title: str, color: str = "cyan") -> str:
    colors = get_color_codes()
    return (
        f"{colors.get('bold','')}{colors.get(color,'')}{title}"
        f"{colors.get('reset','')}"
    )


# --------------------------------------------------------------------------- #
class DiskUsageRenderer:
    def __init__(
        self,
        results: ScanResults,
        raw_bytes: bool = False,
        depth_limit: Optional[int] = None,
        terminal_width: Optional[int] = None,
    ):
        self.results = results
        self.raw_bytes = raw_bytes
        self.depth_limit = depth_limit
        self.terminal_width = terminal_width or _detect_width()
        self.box = _Box(has_unicode_support() and self.terminal_width >= 60)

    # ------------------------------------------------------------------ #
    #  Sorting
    # ------------------------------------------------------------------ #
    def get_sorted_entries(
        self, sort_key: str = "size", reverse: bool = False
    ) -> List[EntryInfo]:
        entries_list = [
            e for e in self.results.entries.values()
            if str(e.path) != str(self.results.root_path)
        ]
        # Sort alphabetically by path name first to act as a stable secondary key
        entries_list.sort(key=lambda x: str(x.path).lower())
        if sort_key == "size":
            entries_list.sort(key=lambda x: x.size, reverse=not reverse)
        elif sort_key == "name":
            entries_list.sort(key=lambda x: x.name.lower(), reverse=reverse)
        elif sort_key == "modified":
            entries_list.sort(key=lambda x: x.modified, reverse=not reverse)
        else:
            entries_list.sort(key=lambda x: x.size, reverse=not reverse)
        return entries_list

    # ------------------------------------------------------------------ #
    #  Header / overview
    # ------------------------------------------------------------------ #
    def render_header(self) -> str:
        colors = get_color_codes()
        c_cyan = colors["cyan"]
        c_yellow = colors["yellow"]
        c_dim = colors["dim"]
        c_reset = colors["reset"]
        r = self.results
        depth_str = (
            f"limit {self.depth_limit}  (reached {r.max_depth_reached})"
            if self.depth_limit is not None
            else f"{r.max_depth_reached}  (unlimited)"
        )
        max_label_w = max(len(s) for s in [
            "Path", "Depth", "Folders", "Files", "Total", "Elapsed",
            "Avg File", "Median File", "Skipped",
        ])
        pad = " " + " " * (max_label_w - 1) + ": "
        lines = [
            f" {c_cyan}{'Path'.ljust(max_label_w)}{c_reset}     : {r.root_path}",
            f" {c_cyan}{'Depth'.ljust(max_label_w)}{c_reset}     : {depth_str}",
            f" {c_cyan}{'Folders'.ljust(max_label_w)}{c_reset}   : {r.folders_scanned:,}",
            f" {c_cyan}{'Files'.ljust(max_label_w)}{c_reset}     : {r.files_scanned:,}",
            f" {c_cyan}{'Total'.ljust(max_label_w)}{c_reset}     : {format_bytes(r.total_size, self.raw_bytes)}",
            f" {c_cyan}{'Elapsed'.ljust(max_label_w)}{c_reset}   : {r.elapsed_time:.2f} s",
        ]
        if r.files:
            lines.append(
                f" {c_cyan}{'Avg File'.ljust(max_label_w)}{c_reset}  : "
                f"{format_bytes(int(r.avg_file_size), self.raw_bytes)}"
            )
            lines.append(
                f" {c_cyan}{'Median File'.ljust(max_label_w)}{c_reset}: "
                f"{format_bytes(int(r.median_file_size), self.raw_bytes)}"
            )
        if r.smart_skipped:
            skipped_size = sum(e.size for e in r.smart_skipped)
            lines.append(
                f" {c_yellow}{'Skipped'.ljust(max_label_w)}{c_reset}   : "
                f"{len(r.smart_skipped):,} smart-summarized folders "
                f"({format_bytes(skipped_size, self.raw_bytes)}) "
                f"{c_dim}(use --no-smart-skip to recurse){c_reset}"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    #  Main table
    # ------------------------------------------------------------------ #
    def render_terminal_table(
        self,
        top_n: Optional[int] = None,
        sort_key: str = "size",
        reverse: bool = False,
        include_age: bool = False,
        compact: bool = False,
    ) -> str:
        out_lines: List[str] = []
        out_lines.append(self.render_header())
        out_lines.append("")

        entries = self.get_sorted_entries(sort_key, reverse)
        if top_n:
            entries = entries[:top_n]

        if not entries:
            out_lines.append("No entries matched the criteria.")
            return "\n".join(out_lines)

        colors = get_color_codes()
        c_blue = colors["blue"]
        c_cyan = colors["cyan"]
        c_green = colors["green"]
        c_yellow = colors["yellow"]
        c_red = colors["red"]
        c_bold = colors["bold"]
        c_reset = colors["reset"]
        c_dim = colors["dim"]
        c_magenta = colors["magenta"]
        has_uni = has_unicode_support()
        now = time.time()

        # Build rows first as plain strings, then a parallel "styled" version
        raw_rows: List[Tuple] = []
        styled_rows: List[Tuple] = []
        for idx, entry in enumerate(entries, 1):
            reason, category, icon, safety = analyze_entry(entry.path, entry.is_dir)
            type_str = "DIR" if entry.is_dir else "FILE"
            size_str = format_bytes(entry.size, self.raw_bytes)
            share_str = format_percent(entry.size, self.results.total_size)
            icon_prefix = f"{icon} " if (icon and has_uni) else ""
            path_display = f"{icon_prefix}{entry.path}"
            # Mark smart-summarized folders with an asterisk in the type cell
            if entry._smart_summary:
                type_str = "DIR*"

            age_str = format_age(entry.modified, now) if include_age else ""

            if include_age:
                raw_rows.append((str(idx), type_str, size_str, share_str, category, age_str, path_display))
            else:
                raw_rows.append((str(idx), type_str, size_str, share_str, category, path_display))

            type_styled = (
                f"{c_blue}{type_str}{c_reset}" if entry.is_dir and not entry._smart_summary
                else f"{c_yellow}{type_str}{c_reset}" if not entry.is_dir
                else f"{c_magenta}{type_str}{c_reset}"
            )
            size_styled = f"{c_green}{size_str}{c_reset}"
            share_styled = f"{c_green}{share_str}{c_reset}"
            if category == "SYSTEM":
                cat_styled = f"{c_red}{category}{c_reset}"
                path_styled = f"{c_red}{path_display}{c_reset}"
            elif category in ("Dependency", "Cache", "Virtual Environment", "Build"):
                cat_styled = f"{c_yellow}{category}{c_reset}"
                path_styled = f"{c_bold}{path_display}{c_reset}"
            else:
                cat_styled = (
                    f"{c_blue}{category}{c_reset}" if entry.is_dir
                    else category
                )
                path_styled = path_display
            age_styled = f"{c_dim}{age_str}{c_reset}" if age_str else ""
            if include_age:
                styled_rows.append((
                    f"{c_bold}{idx}{c_reset}",
                    type_styled, size_styled, share_styled,
                    cat_styled, age_styled, path_styled,
                ))
            else:
                styled_rows.append((
                    f"{c_bold}{idx}{c_reset}",
                    type_styled, size_styled, share_styled,
                    cat_styled, path_styled,
                ))

        # Build the table
        ncols = 7 if include_age else 6
        if include_age:
            headers = ["#", "Type", "Size", "Share", "Category", "Age", "Path"]
            aligns = ["right", "left", "right", "right", "left", "left", "left"]
        else:
            headers = ["#", "Type", "Size", "Share", "Category", "Path"]
            aligns = ["right", "left", "right", "right", "left", "left"]

        # We need to format the cells with their visible widths, but the
        # raw table builder is plain-text. Build a "raw" string-per-cell
        # representation that preserves visible width but drops ANSI,
        # while keeping the styled version for the final output.
        plain_rows: List[List[str]] = []
        for raw_row in raw_rows:
            plain_rows.append([_visible(s) for s in raw_row])

        # Width budget: terminal width minus a small margin
        width_budget = max(60, self.terminal_width - 2)
        table = _build_table(headers, plain_rows, aligns, width_budget, self.box)
        # Re-apply styling by re-coloring each cell with its measured width.
        # We rebuild the table from styled_rows, padding to col_w.
        # Easier: print the table as-is (no ANSI) and rely on the bold
        # header color coming from a separate header line. Many terminals
        # lose alignment if we mix ANSI in cells, so keep the table plain
        # and put a colored header above.
        out_lines.append(f"{c_cyan}{c_bold}Top {len(plain_rows)} entries{c_reset}")
        out_lines.append(table)
        # Legend
        legend = (
            f" {c_dim}DIR* = smart-summarized (size-only){c_reset}"
        )
        out_lines.append(legend)
        return "\n".join(out_lines)

    # ------------------------------------------------------------------ #
    #  JSON
    # ------------------------------------------------------------------ #
    def render_json(self) -> str:
        entries_json = []
        for idx, entry in enumerate(self.get_sorted_entries(), 1):
            reason, category, icon, safety = analyze_entry(entry.path, entry.is_dir)
            type_str = "DIR" if entry.is_dir else "FILE"
            entries_json.append({
                "rank": idx,
                "type": type_str,
                "name": entry.name,
                "path": str(entry.path),
                "size_bytes": entry.size,
                "size_human": format_bytes(entry.size, self.raw_bytes),
                "share_percent": round(entry.size / self.results.total_size * 100, 2)
                                  if self.results.total_size else 0.0,
                "category": category,
                "reason": reason,
                "icon": icon,
                "safety": safety,
                "modified": entry.modified,
                "modified_iso": time.strftime("%Y-%m-%dT%H:%M:%S",
                                              time.localtime(entry.modified)) if entry.modified else None,
                "smart_summary": bool(getattr(entry, "_smart_summary", False)),
            })

        output = {
            "meta": {
                "tool": "spacelyzer",
                "version": "2.0.0",
                "scanned_at": time.time(),
            },
            "path": str(self.results.root_path),
            "total_size_bytes": self.results.total_size,
            "total_size_human": format_bytes(self.results.total_size, self.raw_bytes),
            "elapsed_seconds": round(self.results.elapsed_time, 2),
            "folders_scanned": self.results.folders_scanned,
            "files_scanned": self.results.files_scanned,
            "max_depth_reached": self.results.max_depth_reached,
            "smart_skipped_count": len(self.results.smart_skipped),
            "category_sizes": {
                k: {"bytes": v, "human": format_bytes(v, self.raw_bytes)}
                for k, v in self.results.category_sizes.items()
            },
            "extension_stats": {
                k: {"bytes": v[0], "count": v[1]}
                for k, v in self.results.extension_stats.items()
            },
            "age_buckets": {
                k: {"bytes": v[0], "count": v[1]}
                for k, v in self.results.age_buckets.items()
            },
            "entries": entries_json,
        }
        largest_folder = ""
        largest_file = self.results.files[0].name if self.results.files else None
        sub = [e for e in self.results.entries.values()
               if e.is_dir and str(e.path) != str(self.results.root_path)]
        if sub:
            largest_folder = max(sub, key=lambda x: x.size).name
        output["summary"] = {
            "folders_scanned": self.results.folders_scanned,
            "files_scanned": self.results.files_scanned,
            "largest_folder": largest_folder,
            "largest_file": largest_file,
            "potentially_reclaimable_bytes": sum(
                e["size_bytes"] for e in entries_json
                if e["category"] in ("Dependency", "Cache", "Build",
                                     "Virtual Environment", "Temporary")
            ),
        }
        return json.dumps(output, indent=2)

    # ------------------------------------------------------------------ #
    def render_csv(self) -> str:
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow([
            "rank", "type", "name", "size_bytes", "size_human",
            "share_percent", "category", "reason", "safety", "modified",
            "path", "smart_summary",
        ])
        for idx, entry in enumerate(self.get_sorted_entries(), 1):
            reason, category, icon, safety = analyze_entry(entry.path, entry.is_dir)
            type_str = "DIR" if entry.is_dir else "FILE"
            share = round(
                (entry.size / self.results.total_size * 100), 2
            ) if self.results.total_size else 0.0
            writer.writerow([
                idx, type_str, entry.name, entry.size,
                format_bytes(entry.size, self.raw_bytes),
                share, category, reason, safety or "",
                time.strftime("%Y-%m-%d %H:%M:%S",
                              time.localtime(entry.modified)) if entry.modified else "",
                str(entry.path),
                "1" if getattr(entry, "_smart_summary", False) else "0",
            ])
        return out.getvalue()

    # ------------------------------------------------------------------ #
    def render_markdown(self) -> str:
        lines = [
            "# Spacelyzer Report",
            "",
            f"**Path:** `{self.results.root_path}`  ",
            f"**Total:** {format_bytes(self.results.total_size, self.raw_bytes)}  ",
            f"**Folders:** {self.results.folders_scanned:,}  ",
            f"**Files:** {self.results.files_scanned:,}  ",
            f"**Smart-skipped:** {len(self.results.smart_skipped)} folders  ",
            f"**Elapsed:** {self.results.elapsed_time:.2f}s",
            "",
            "| # | Type | Size | Share | Category | Path |",
            "|---|------|------|-------|----------|------|",
        ]
        for idx, entry in enumerate(self.get_sorted_entries(), 1):
            reason, category, icon, safety = analyze_entry(entry.path, entry.is_dir)
            type_str = "DIR*" if getattr(entry, "_smart_summary", False) else ("DIR" if entry.is_dir else "FILE")
            share = format_percent(entry.size, self.results.total_size)
            lines.append(
                f"| {idx} | {type_str} | {format_bytes(entry.size, self.raw_bytes)} "
                f"| {share} | {category} | `{entry.path}` |"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    def render_ndjson(self) -> str:
        lines = []
        meta = {
            "type": "_meta",
            "tool": "spacelyzer",
            "scanned_at": time.time(),
            "path": str(self.results.root_path),
            "total_size_bytes": self.results.total_size,
            "folders_scanned": self.results.folders_scanned,
            "files_scanned": self.results.files_scanned,
            "smart_skipped_count": len(self.results.smart_skipped),
        }
        lines.append(json.dumps(meta))
        for idx, entry in enumerate(self.get_sorted_entries(), 1):
            reason, category, icon, safety = analyze_entry(entry.path, entry.is_dir)
            lines.append(json.dumps({
                "rank": idx,
                "type": "DIR" if entry.is_dir else "FILE",
                "name": entry.name,
                "path": str(entry.path),
                "size_bytes": entry.size,
                "share_percent": round(entry.size / self.results.total_size * 100, 2)
                                  if self.results.total_size else 0.0,
                "category": category,
                "reason": reason,
                "safety": safety,
                "modified": entry.modified,
                "smart_summary": bool(getattr(entry, "_smart_summary", False)),
            }))
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    def render_yaml(self) -> str:
        """Minimal YAML emitter (no PyYAML dependency)."""
        def _emit(value, indent=0) -> List[str]:
            pad = "  " * indent
            out: List[str] = []
            if isinstance(value, dict):
                for k, v in value.items():
                    if isinstance(v, (dict, list)) and v:
                        out.append(f"{pad}{_yaml_str(k)}:")
                        out.extend(_emit(v, indent + 1))
                    else:
                        out.append(f"{pad}{_yaml_str(k)}: {_yaml_val(v)}")
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, (dict, list)):
                        out.append(f"{pad}-")
                        out.extend(_emit(item, indent + 1))
                    else:
                        out.append(f"{pad}- {_yaml_val(item)}")
            return out

        payload = json.loads(self.render_json())
        return "\n".join(_emit(payload))

    # ------------------------------------------------------------------ #
    def render_html(self, title: str = "Spacelyzer Report") -> str:
        entries = self.get_sorted_entries()
        total = self.results.total_size
        rows_html: List[str] = []
        for idx, entry in enumerate(entries, 1):
            reason, category, icon, safety = analyze_entry(entry.path, entry.is_dir)
            share = entry.size / total * 100 if total else 0
            bar = max(1, int(share * 2))
            rows_html.append(
                "<tr>"
                f"<td class='num'>{idx}</td>"
                f"<td>{'DIR' if entry.is_dir else 'FILE'}</td>"
                f"<td class='size'>{format_bytes(entry.size, self.raw_bytes)}</td>"
                f"<td class='size'>{share:.1f}%</td>"
                f"<td>{html.escape(category)}</td>"
                f"<td class='path'>"
                f"<div class='bar' style='width:{bar}px'></div>"
                f"{html.escape(str(entry.path))}</td>"
                "</tr>"
            )
        rows = "\n".join(rows_html)

        cats = sorted(self.results.category_sizes.items(),
                      key=lambda x: x[1], reverse=True)
        cat_bars: List[str] = []
        for cat, sz in cats:
            share = sz / total * 100 if total else 0
            w = int(share * 4)
            cat_bars.append(
                f"<tr><td>{html.escape(cat)}</td>"
                f"<td class='size'>{format_bytes(sz, self.raw_bytes)}</td>"
                f"<td><div class='hbar' style='width:{w}px'></div> {share:.1f}%</td></tr>"
            )
        cat_rows = "\n".join(cat_bars)

        return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
  body{{font:14px/1.45 -apple-system,Segoe UI,Helvetica,sans-serif;
       color:#222;max-width:1200px;margin:24px auto;padding:0 16px}}
  h1,h2{{margin:.4em 0}}
  .meta{{background:#f5f7fa;padding:14px 18px;border-radius:10px;margin:12px 0}}
  table{{border-collapse:collapse;width:100%;margin:14px 0;font-size:13px}}
  th,td{{border-bottom:1px solid #eee;padding:6px 8px;text-align:left;vertical-align:top}}
  th{{background:#fafbfc;position:sticky;top:0}}
  td.num{{color:#888;width:40px}}
  td.size{{white-space:nowrap;font-variant-numeric:tabular-nums;width:120px}}
  td.path{{font-family:ui-monospace,Consolas,monospace;font-size:12px;
           word-break:break-all;position:relative}}
  .bar{{position:absolute;left:0;top:0;height:100%;
        background:linear-gradient(90deg,#cce5ff,#99c2ff);opacity:.5;z-index:-1}}
  .hbar{{display:inline-block;height:10px;background:#5cb85c;vertical-align:middle}}
  .cat{{background:#fafbfc;padding:12px;border-radius:8px}}
  .pill{{display:inline-block;padding:2px 8px;border-radius:99px;
         background:#eef;color:#335;font-size:12px;margin-right:6px}}
</style>
</head><body>
<h1>📊 Spacelyzer Report</h1>
<p class="meta">
  <span class="pill">Path: {html.escape(str(self.results.root_path))}</span>
  <span class="pill">Total: {format_bytes(total, self.raw_bytes)}</span>
  <span class="pill">Folders: {self.results.folders_scanned:,}</span>
  <span class="pill">Files: {self.results.files_scanned:,}</span>
  <span class="pill">Elapsed: {self.results.elapsed_time:.2f}s</span>
</p>
<h2>Categories</h2>
<div class="cat">
  <table>
    <tr><th>Category</th><th>Size</th><th>Share</th></tr>
    {cat_rows}
  </table>
</div>
<h2>Top entries</h2>
<table>
  <tr><th>#</th><th>Type</th><th>Size</th><th>Share</th><th>Category</th><th>Path</th></tr>
  {rows}
</table>
</body></html>"""

    # ------------------------------------------------------------------ #
    #  Tree
    # ------------------------------------------------------------------ #
    def render_tree(self, max_depth: Optional[int] = None,
                    top_children: Optional[int] = None) -> str:
        out: List[str] = []
        colors = get_color_codes()
        c_blue = colors["blue"]
        c_green = colors["green"]
        c_yellow = colors["yellow"]
        c_red = colors["red"]
        c_magenta = colors["magenta"]
        c_dim = colors["dim"]
        c_reset = colors["reset"]
        c_bold = colors["bold"]

        def _print_node(path_str: str, prefix: str, is_last: bool, depth: int) -> None:
            if max_depth is not None and depth > max_depth:
                return
            entry = self.results.entries.get(path_str)
            if not entry:
                return
            marker = self.box.tree_last if is_last else self.box.tree_mid
            _, category, icon, safety = analyze_entry(entry.path, entry.is_dir)
            icon_str = f"{icon} " if (icon and has_unicode_support()) else ""
            if entry._smart_summary:
                name_disp = f"{c_magenta}{icon_str}{entry.name}*{c_reset}"
            elif category == "SYSTEM":
                name_disp = f"{c_red}{icon_str}{entry.name}{c_reset}"
            elif entry.is_dir:
                name_disp = f"{c_blue}{icon_str}{entry.name}{c_reset}"
            else:
                name_disp = f"{c_yellow}{entry.name}{c_reset}"
            size_disp = f"{c_green}{format_bytes(entry.size, self.raw_bytes)}{c_reset}"
            note = ""
            if entry._smart_summary:
                note = f"  {c_dim}(size only){c_reset}"
            out.append(f"{prefix}{marker}{name_disp}  {size_disp}{note}")

            children = [c for c in self.results.hierarchy.get(path_str, [])
                        if c in self.results.entries]
            children.sort(key=lambda x: self.results.entries[x].size, reverse=True)
            if top_children is not None:
                children = children[:top_children]
            new_prefix = prefix + (self.box.tree_empty if is_last else self.box.tree_v)
            for i, child_path in enumerate(children):
                _print_node(child_path, new_prefix, i == len(children) - 1, depth + 1)

        root = str(self.results.root_path)
        root_entry = self.results.entries.get(root)
        if root_entry:
            size_disp = f"{c_green}{format_bytes(root_entry.size, self.raw_bytes)}{c_reset}"
            out.append(f"{c_bold}{root_entry.path}{c_reset}  {size_disp}")
            children = [c for c in self.results.hierarchy.get(root, [])
                        if c in self.results.entries]
            children.sort(key=lambda x: self.results.entries[x].size, reverse=True)
            if top_children is not None:
                children = children[:top_children]
            for i, child_path in enumerate(children):
                _print_node(child_path, "", i == len(children) - 1, 1)
        return "\n".join(out)

    # ------------------------------------------------------------------ #
    #  Standalone mode renderers
    # ------------------------------------------------------------------ #
    def render_largest_files(self, limit: int = 10) -> str:
        sorted_files = sorted(self.results.files, key=lambda x: x.size, reverse=True)
        colors = get_color_codes()
        c_green, c_bold, c_blue, c_dim, c_reset = (
            colors["green"], colors["bold"], colors["blue"],
            colors["dim"], colors["reset"]
        )
        out = [f"{c_bold}Largest files{c_reset}", ""]
        if not sorted_files:
            out.append("(no files found)")
            return "\n".join(out)
        for idx, f in enumerate(sorted_files[:limit], 1):
            age = f"  {c_dim}{format_age(f.modified)}{c_reset}" if f.modified else ""
            out.append(
                f"  {c_bold}{idx:>3}{c_reset}  "
                f"{c_blue}{f.name}{c_reset}  "
                f"{c_green}{format_bytes(f.size, self.raw_bytes):>10}{c_reset}  "
                f"{f.path}{age}"
            )
        return "\n".join(out)

    def render_extensions(self, limit: int = 15) -> str:
        ext_data = sorted(
            self.results.extension_stats.items(),
            key=lambda x: x[1][0], reverse=True
        )
        colors = get_color_codes()
        c_blue, c_green, c_yellow, c_bold, c_reset = (
            colors["blue"], colors["green"], colors["yellow"],
            colors["bold"], colors["reset"]
        )
        out = [f"{c_bold}Extensions{c_reset}  (top {limit})", ""]
        if not ext_data:
            out.append("(no files found)")
            return "\n".join(out)
        plain = []
        for ext, (size, count) in ext_data[:limit]:
            share = format_percent(size, self.results.total_size)
            plain.append((ext, format_bytes(size, self.raw_bytes),
                          f"{count:,}", share))
        table = _build_table(
            ["Extension", "Size", "Files", "Share"],
            plain,
            ["left", "right", "right", "right"],
            max(60, self.terminal_width - 2),
            self.box,
        )
        out.append(table)
        return "\n".join(out)

    def render_breakdown(self, path_str: str) -> str:
        path = Path(path_str).resolve()
        path_resolved = str(path)
        if path_resolved not in self.results.entries:
            return f"Path not scanned or not found: {path_str}"
        entry = self.results.entries[path_resolved]
        colors = get_color_codes()
        c_green, c_blue, c_yellow, c_bold, c_magenta, c_dim, c_reset = (
            colors["green"], colors["blue"], colors["yellow"],
            colors["bold"], colors["magenta"], colors["dim"], colors["reset"]
        )
        out = [
            f"{c_bold}{entry.name}{c_reset}  "
            f"{c_green}{format_bytes(entry.size, self.raw_bytes)}{c_reset}  "
            f"{c_dim}{path_resolved}{c_reset}",
            "",
        ]
        children = [self.results.entries[c] for c in
                    self.results.hierarchy.get(path_resolved, [])
                    if c in self.results.entries]
        direct = [f for f in self.results.files
                  if str(f.path.parent) == path_resolved]
        all_children = children + direct
        all_children.sort(key=lambda x: x.size, reverse=True)
        if not all_children:
            out.append(f"{c_dim}(empty){c_reset}")
            return "\n".join(out)
        total_size = entry.size or 1
        has_uni = has_unicode_support()
        bar_char = self.box.bar_char
        for idx, child in enumerate(all_children[:10]):
            share = child.size / total_size
            bar_len = max(0, int(share * 24))
            is_last = idx == min(9, len(all_children) - 1)
            marker = self.box.tree_last if is_last else self.box.tree_mid
            label = "DIR*" if getattr(child, "_smart_summary", False) else child.name
            name_styled = (
                f"{c_magenta}{label}{c_reset}" if getattr(child, "_smart_summary", False)
                else f"{c_blue}{label}{c_reset}" if child.is_dir
                else f"{c_yellow}{label}{c_reset}"
            )
            out.append(
                f"{marker}{name_styled}  "
                f"{c_green}{share*100:>3.0f}%{c_reset}  "
                f"{c_green}{format_bytes(child.size, self.raw_bytes):>10}{c_reset}  "
                f"{c_yellow}{bar_char*bar_len}{c_reset}"
            )
        return "\n".join(out)

    # ------------------------------------------------------------------ #
    #  Visualizations
    # ------------------------------------------------------------------ #
    def get_top_visualization_data(
        self, limit: int = 5
    ) -> Tuple[List[Tuple[str, int, float]], int]:
        entries = self.get_sorted_entries(sort_key="size")
        total = self.results.total_size
        top = []
        s = 0
        for e in entries[:limit]:
            top.append((e.name, e.size, e.size / total if total else 0))
            s += e.size
        if total - s > 0 and len(entries) > limit:
            top.append(("Others", total - s, (total - s) / total))
        return top, total

    def render_bar_chart(self, limit: int = 8) -> str:
        data, _ = self.get_top_visualization_data(limit)
        colors = get_color_codes()
        c_green, c_blue, c_yellow, c_reset, c_bold = (
            colors["green"], colors["blue"], colors["yellow"],
            colors["reset"], colors["bold"]
        )
        out = [f"{c_bold}Bar chart{c_reset}", ""]
        if not data:
            out.append("(nothing to chart)")
            return "\n".join(out)
        max_w = 32
        for name, size, share in data:
            bar_len = max(0, int(share * max_w))
            out.append(
                f"{c_blue}{name[:14]:<14}{c_reset} "
                f"{c_green}{self.box.bar_char*bar_len:<32}{c_reset} "
                f"{c_yellow}{share*100:5.1f}%{c_reset}"
            )
        return "\n".join(out)

    def render_pie_chart(self) -> str:
        data, _ = self.get_top_visualization_data(4)
        colors = get_color_codes()
        c_blue, c_magenta, c_green, c_yellow, c_reset, c_bold = (
            colors["blue"], colors["magenta"], colors["green"],
            colors["yellow"], colors["reset"], colors["bold"]
        )
        out = [f"{c_bold}Storage Distribution{c_reset}", ""]
        has_uni = has_unicode_support()
        if has_uni:
            arcs = ["◜██████████◝", "◜█████◞     ", "◜███◝       ", "            "]
        else:
            arcs = [" /##########\\", " /#####/     ", " /###\\       ", "             "]
        if not data:
            out.append("(nothing to chart)")
            return "\n".join(out)
        for idx, (name, size, share) in enumerate(data):
            sym = arcs[idx] if idx < len(arcs) else ("            " if has_uni else "             ")
            out.append(
                f"{c_magenta}{sym}{c_reset}  "
                f"{c_blue}{name[:14]:<14}{c_reset} "
                f"{c_green}{share*100:5.1f}%{c_reset}"
            )
        return "\n".join(out)

    def render_sunburst(self) -> str:
        colors = get_color_codes()
        c_green, c_blue, c_reset, c_bold = (
            colors["green"], colors["blue"], colors["reset"], colors["bold"]
        )
        total = self.results.total_size
        out = [f"{c_bold}Disk  100%{c_reset}", self.box.v]
        root = str(self.results.root_path)
        children = [c for c in self.results.hierarchy.get(root, [])
                    if c in self.results.entries]
        children.sort(key=lambda x: self.results.entries[x].size, reverse=True)
        if not children:
            out.append("(no children)")
            return "\n".join(out)
        for i, cp in enumerate(children[:5]):
            child = self.results.entries[cp]
            share = child.size / total * 100 if total else 0
            last = i == min(4, len(children[:5]) - 1)
            prefix = self.box.tree_last if last else self.box.tree_mid
            prefix = prefix.rstrip()  # remove trailing space from tree marker
            out.append(
                f"{prefix} {c_blue}{child.name[:18]:<18}{c_reset} "
                f"{c_green}{share:5.1f}%{c_reset}"
            )
        return "\n".join(out)

    def render_treemap(self) -> str:
        data, _ = self.get_top_visualization_data(4)
        colors = get_color_codes()
        c_green, c_blue, c_yellow, c_bold, c_reset = (
            colors["green"], colors["blue"], colors["yellow"],
            colors["bold"], colors["reset"]
        )
        if not data:
            return "(nothing to chart)"
        has_uni = has_unicode_support()
        seg = self.box.bar_char
        width = 56
        grid = [" " * width for _ in range(4)]
        curr = 0
        for name, size, share in data:
            cw = int(share * width)
            if cw < 2:
                continue
            label = f"{name} {share*100:.0f}%"
            if len(label) > cw:
                label = label[:cw]
            for row in range(4):
                if row in (1, 2) and cw > 4:
                    start = (cw - len(label)) // 2
                    if row == 1 and start >= 0:
                        content = seg * start + label + seg * (cw - start - len(label))
                    else:
                        content = seg * cw
                else:
                    content = seg * cw
                grid[row] = grid[row][:curr] + content + grid[row][curr + cw:]
            curr += cw
        out = [f"{c_blue}{seg*(width+2)}{c_reset}"]
        for r in grid:
            line = r.ljust(width)[:width]
            out.append(f"{c_blue}{seg}{c_reset}{c_green}{line}{c_reset}{c_blue}{seg}{c_reset}")
        out.append(f"{c_blue}{seg*(width+2)}{c_reset}")
        return "\n".join(out)

    # ------------------------------------------------------------------ #
    #  Age / fingerprint / suggestions / category / summary
    # ------------------------------------------------------------------ #
    def render_age_breakdown(self) -> str:
        colors = get_color_codes()
        c_blue, c_green, c_yellow, c_bold, c_reset = (
            colors["blue"], colors["green"], colors["yellow"],
            colors["bold"], colors["reset"]
        )
        total = self.results.total_size
        order = ["< 1 day", "1-7 days", "1-4 weeks", "1-3 months",
                 "3-12 months", "1-2 years", "> 2 years", "unknown"]
        out = [f"{c_bold}Age Distribution{c_reset}", ""]
        any_buckets = False
        for bucket in order:
            if bucket not in self.results.age_buckets:
                continue
            any_buckets = True
            size, count = self.results.age_buckets[bucket]
            share = size / total * 100 if total else 0
            bar_len = int(share * 0.5)
            out.append(
                f"{c_blue}{bucket:<14}{c_reset} "
                f"{c_green}{format_bytes(size, self.raw_bytes):>10}{c_reset} "
                f"{c_yellow}{count:>8,}{c_reset}  "
                f"{self.box.bar_char*bar_len} {share:.1f}%"
            )
        if not any_buckets:
            out.append("(no data)")
        return "\n".join(out)

    def render_storage_fingerprint(self) -> str:
        from spacelyzer.fingerprint import StorageFingerprinter
        colors = get_color_codes()
        c_blue, c_green, c_magenta, c_bold, c_reset, c_dim = (
            colors["blue"], colors["green"], colors["magenta"],
            colors["bold"], colors["reset"], colors["dim"]
        )
        fp = StorageFingerprinter(self.results.entries, self.results.files)
        fps = fp.get_fingerprints()
        total = sum(f.size for f in fps) or 1
        max_w = 24
        out = [f"{c_bold}{c_magenta}Storage Fingerprint{c_reset}", ""]
        if not fps:
            out.append(f"{c_dim}(no fingerprint detected){c_reset}")
            return "\n".join(out)
        for fp in fps:
            share = fp.size / total
            bar_len = max(0, int(share * max_w))
            bar = self.box.bar_char * bar_len
            max_w_str = str(max_w)
            size_str = format_bytes(fp.size, self.raw_bytes)
            out.append(
                f"  {c_blue}{fp.name:<28}{c_reset} "
                f"{c_magenta}{bar:<{max_w_str}}{c_reset}   "
                f"{c_green}{size_str:>10}{c_reset}"
            )
        total_str = self.box.bar_char * max_w
        total_size_str = format_bytes(total, self.raw_bytes)
        out.append(
            f"  {c_dim}{'Total':<28}{c_reset} "
            f"{c_dim}{total_str:<{max_w_str}}   {c_reset}"
            f"{c_bold}{total_size_str:>10}{c_reset}"
        )
        return "\n".join(out)

    def render_category_bars(self, raw_bytes: bool = False) -> str:
        """Bar graph of storage categories, sorted by size descending."""
        colors = get_color_codes()
        c_blue, c_green, c_yellow, c_bold, c_magenta, c_dim, c_reset = (
            colors["blue"], colors["green"], colors["yellow"],
            colors["bold"], colors["magenta"], colors["dim"], colors["reset"]
        )
        cats = sorted(self.results.category_sizes.items(),
                      key=lambda x: x[1], reverse=True)
        if not cats:
            return f"{c_bold}Storage Categories{c_reset}\n{c_dim}(no data){c_reset}"
        out = [f"{c_bold}Storage Categories{c_reset}", ""]
        total = self.results.total_size or 1
        max_label = max(len(c) for c, _ in cats)
        max_label = max(max_label, 10)
        max_w = 30
        for cat, size in cats:
            share = size / total * 100
            bar_len = max(0, int(share / 100 * max_w))
            color = c_yellow if cat in ("Dependency", "Cache", "Build",
                                         "Virtual Environment", "Temporary") else c_blue
            out.append(
                f"  {color}{cat:<{max_label}}{c_reset} "
                f"{c_green}{format_bytes(size, raw_bytes):>10}{c_reset}  "
                f"{color}{self.box.bar_char*bar_len:<{max_w}}{c_reset} "
                f"{c_dim}{share:5.1f}%{c_reset}"
            )
        return "\n".join(out)

    def render_smart_skip_notice(self) -> str:
        """Notice about which folders were size-only summarized."""
        colors = get_color_codes()
        c_yellow, c_green, c_bold, c_dim, c_reset = (
            colors["yellow"], colors["green"], colors["bold"],
            colors["dim"], colors["reset"]
        )
        skipped = self.results.smart_skipped
        if not skipped:
            return ""
        # Stably sort skipped folders (alphabetically by path name first to break ties)
        skipped.sort(key=lambda e: str(e.path).lower())
        skipped.sort(key=lambda e: e.size, reverse=True)
        total = sum(e.size for e in skipped)
        dash = "—" if has_unicode_support() else "-"
        out = [
            f"{c_bold}{c_yellow}Smart-Summarized Folders{c_reset}  "
            f"{c_dim}(size only {dash} use --no-smart-skip to recurse){c_reset}",
            "",
        ]
        for e in skipped[:15]:
            reason, category, icon, _ = analyze_entry(e.path, e.is_dir)
            label = f"{icon} {reason}" if (icon and has_unicode_support()) else reason
            out.append(
                f"  {c_yellow}{label:<28}{c_reset} "
                f"{c_green}{format_bytes(e.size, self.raw_bytes):>10}{c_reset}  "
                f"{c_dim}{e.path}{c_reset}"
            )
        if len(skipped) > 15:
            out.append(f"  {c_dim}… and {len(skipped) - 15} more{c_reset}")
        out.append(
            f"\n  {c_bold}Total summarized:{c_reset} "
            f"{c_green}{format_bytes(total, self.raw_bytes)}{c_reset} "
            f"across {len(skipped)} folders"
        )
        return "\n".join(out)

    def render_suggestions(
        self, suggestions: List[SuggestionItem], show_paths: bool = True,
    ) -> str:
        colors = get_color_codes()
        c_green, c_yellow, c_bold, c_dim, c_reset = (
            colors["green"], colors["yellow"], colors["bold"],
            colors["dim"], colors["reset"]
        )
        has_uni = has_unicode_support()
        chk = self.box.chk
        arr = self.box.arrow
        bullet = self.box.bullet
        div = "─" * 64 if has_uni else "-" * 64
        out = [f"{c_bold}Suggestions{c_reset}", div]
        total = 0
        for s in suggestions:
            out.append(
                f"{c_green}{chk}{c_reset}  Found {s.count:>3} {s.label:<40} "
                f"{arr}  {c_green}{format_bytes(s.total_size, self.raw_bytes)} "
                f"potentially reclaimable{c_reset}"
            )
            if show_paths and s.top_paths:
                for p, sz in s.top_paths[:3]:
                    out.append(
                        f"      {c_dim}{bullet} "
                        f"{truncate_middle(p, max(40, self.terminal_width - 30))} "
                        f"({format_bytes(sz, self.raw_bytes)}){c_reset}"
                    )
            total += s.total_size
        if not suggestions:
            out.append(f"{c_green}{chk}{c_reset}  No obvious storage-wasting patterns found.")
        out += [
            "",
            "No action was performed.",
            div,
            f"{c_bold}Total potentially reclaimable: "
            f"{c_green}{format_bytes(total, self.raw_bytes)}{c_reset}",
        ]
        return "\n".join(out)

    def render_summary(
        self,
        reclaimable_size: int,
        duplicate_groups: Sequence[Tuple[str, List[EntryInfo]]],
    ) -> str:
        colors = get_color_codes()
        c_cyan, c_green, c_bold, c_dim, c_yellow, c_reset = (
            colors["cyan"], colors["green"], colors["bold"],
            colors["dim"], colors["yellow"], colors["reset"]
        )
        r = self.results
        has_uni = has_unicode_support()
        div = "─" * 64 if has_uni else "-" * 64
        dash = "—" if has_uni else "-"
        sub_folders = [e for e in r.entries.values()
                       if e.is_dir and str(e.path) != str(r.root_path)]
        largest_folder = (
            max(sub_folders, key=lambda x: x.size).name if sub_folders else dash
        )
        largest_file = r.files[0].name if r.files else dash
        largest_dup = max((len(g) for _, g in duplicate_groups), default=0)
        total_dup_size = 0
        for _, g in duplicate_groups:
            g_sorted = sorted(g, key=lambda x: x.size, reverse=True)
            total_dup_size += sum(f.size for f in g_sorted[1:])
        out = [
            div,
            f"{c_bold}{c_cyan}Scan Summary{c_reset}",
            f"  {c_cyan}{'Path':<22}{c_reset} : {r.root_path}",
            f"  {c_cyan}{'Total size':<22}{c_reset} : "
            f"{c_green}{format_bytes(r.total_size, self.raw_bytes)}{c_reset}",
            f"  {c_cyan}{'Folders scanned':<22}{c_reset} : {r.folders_scanned:,}",
            f"  {c_cyan}{'Files scanned':<22}{c_reset} : {r.files_scanned:,}",
            f"  {c_cyan}{'Smart-summarized':<22}{c_reset} : "
            f"{c_yellow}{len(r.smart_skipped):,}{c_reset} folders",
            f"  {c_cyan}{'Unique extensions':<22}{c_reset} : {len(r.extensions):,}",
            f"  {c_cyan}{'Largest folder':<22}{c_reset} : {largest_folder}",
            f"  {c_cyan}{'Largest file':<22}{c_reset} : {largest_file}",
            f"  {c_cyan}{'Largest duplicate group':<22}{c_reset} : "
            f"{largest_dup if largest_dup else dash}",
            f"  {c_cyan}{'Total duplicate size':<22}{c_reset} : "
            f"{format_bytes(total_dup_size, self.raw_bytes)}",
            f"  {c_cyan}{'Potentially reclaimable':<22}{c_reset} : "
            f"{c_green}{format_bytes(reclaimable_size, self.raw_bytes)}{c_reset}",
            f"  {c_cyan}{'Avg file size':<22}{c_reset} : "
            f"{format_bytes(int(r.avg_file_size), self.raw_bytes) if r.files else dash}",
            f"  {c_cyan}{'Median file size':<22}{c_reset} : "
            f"{format_bytes(int(r.median_file_size), self.raw_bytes) if r.files else dash}",
            f"  {c_cyan}{'Elapsed time':<22}{c_reset} : {r.elapsed_time:.2f} sec",
            div,
        ]
        return "\n".join(out)

    # ------------------------------------------------------------------ #
    def render_diff(self, diff: Diff, top: int = 20) -> str:
        colors = get_color_codes()
        c_green, c_red, c_yellow, c_bold, c_dim, c_reset = (
            colors["green"], colors["red"], colors["yellow"],
            colors["bold"], colors["dim"], colors["reset"]
        )
        out = [
            f"{c_bold}Snapshot Diff{c_reset}",
            f"  {c_dim}old: {time.strftime('%Y-%m-%d %H:%M', time.localtime(diff.old.scanned_at))}"
            f"  ({format_bytes(diff.old_total, self.raw_bytes)}){c_reset}",
            f"  {c_dim}new: {time.strftime('%Y-%m-%d %H:%M', time.localtime(diff.new.scanned_at))}"
            f"  ({format_bytes(diff.new_total, self.raw_bytes)}){c_reset}",
            f"  {c_yellow}Δ total: {format_bytes(diff.total_delta, self.raw_bytes)}{c_reset}",
            f"  {c_dim}files: {diff.old.files_scanned:,} → {diff.new.files_scanned:,} "
            f"(Δ {diff.file_count_delta:+,}){c_reset}",
            "",
            f"  {c_bold}Top {top} movers{c_reset}",
        ]
        movers = sorted(diff.entries, key=lambda e: abs(e.delta), reverse=True)[:top]
        for e in movers:
            if e.status == "added":
                line = f"  {c_green}+{format_bytes(e.new_size or 0, self.raw_bytes):>10}{c_reset}  {e.path}"
            elif e.status == "removed":
                line = f"  {c_red}-{format_bytes(e.old_size or 0, self.raw_bytes):>10}{c_reset}  {e.path}"
            elif e.delta > 0:
                line = (f"  {c_yellow}↑{format_bytes(e.delta, self.raw_bytes):>+10}  "
                        f"({format_bytes(e.old_size or 0, self.raw_bytes)} → "
                        f"{format_bytes(e.new_size or 0, self.raw_bytes)}){c_reset}  {e.path}")
            elif e.delta < 0:
                line = (f"  {c_green}↓{format_bytes(e.delta, self.raw_bytes):>+10}  "
                        f"({format_bytes(e.old_size or 0, self.raw_bytes)} → "
                        f"{format_bytes(e.new_size or 0, self.raw_bytes)}){c_reset}  {e.path}")
            else:
                continue
            out.append(line)
        return "\n".join(out)


# --------------------------------------------------------------------------- #
def _yaml_str(s: str) -> str:
    if not isinstance(s, str):
        s = str(s)
    if re.match(r"^[A-Za-z0-9_\-.]+$", s):
        return s
    return json.dumps(s)


def _yaml_val(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return _yaml_str(v)
    return json.dumps(v)


# --------------------------------------------------------------------------- #
def _visible(s: str) -> str:
    """Return *s* with ANSI SGR sequences removed (so widths are honest)."""
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", s)


def _detect_width() -> int:
    return terminal_width(120)


# Backwards-compat: keep `_pad` around for any external importer.
def _pad(s: str, width: int, align: str = "left") -> str:
    return pad_visible(s, width, align)
