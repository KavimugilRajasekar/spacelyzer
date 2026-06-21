import json
import csv
import io
import sys
import math
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional
from spacelyzer.scanner import ScanResults, EntryInfo
from spacelyzer.formatter import format_bytes, format_percent, has_unicode_support
from spacelyzer.analyzer import analyze_entry
from spacelyzer.suggestions import SuggestionItem
from spacelyzer.fingerprint import FingerprintCategory

class DiskUsageRenderer:
    def __init__(self, results: ScanResults, raw_bytes: bool = False):
        self.results = results
        self.raw_bytes = raw_bytes

    def get_sorted_entries(self, sort_key: str = 'size', reverse: bool = False) -> List[EntryInfo]:
        """Get scan entries sorted by size, name, or modified date."""
        entries_list = list(self.results.entries.values())
        
        # Filter out the root directory from main table to avoid redundancy
        entries_list = [e for e in entries_list if str(e.path) != str(self.results.root_path)]

        if sort_key == 'size':
            entries_list.sort(key=lambda x: x.size, reverse=not reverse)
        elif sort_key == 'name':
            entries_list.sort(key=lambda x: x.name.lower(), reverse=reverse)
        elif sort_key == 'modified':
            entries_list.sort(key=lambda x: x.modified, reverse=not reverse)
            
        return entries_list

    def render_terminal_table(self, top_n: Optional[int] = None, sort_key: str = 'size', reverse: bool = False):
        """Render standard Unicode-based table output."""
        entries = self.get_sorted_entries(sort_key, reverse)
        if top_n:
            entries = entries[:top_n]

        import sys
        from spacelyzer.formatter import get_color_codes
        colors = get_color_codes()
        use_color = sys.stdout.isatty()
        c_blue = colors['blue']
        c_cyan = colors['cyan']
        c_green = colors['green']
        c_yellow = colors['yellow']
        c_red = colors['red']
        c_bold = colors['bold']
        c_reset = colors['reset']

        # Print overall stats header
        print(f" {c_cyan}Path{c_reset}      : {self.results.root_path}")
        print(f" {c_cyan}Depth{c_reset}     : {self.results.folders_scanned if not hasattr(self, 'depth') else 'Custom'}")
        print(f" {c_cyan}Folders{c_reset}   : {self.results.folders_scanned:,}")
        print(f" {c_cyan}Files{c_reset}     : {self.results.files_scanned:,}")
        print(f" {c_cyan}Total{c_reset}     : {format_bytes(self.results.total_size, self.raw_bytes)}")
        print(f" {c_cyan}Elapsed{c_reset}   : {self.results.elapsed_time:.2f} s\n")

        if not entries:
            print("No entries matched the criteria.")
            return

        has_unicode = has_unicode_support()

        # Prepare records - both raw (uncolored) and styled (colored)
        table_rows_raw = []
        table_rows_styled = []
        for idx, entry in enumerate(entries, 1):
            reason, category, icon, safety = analyze_entry(entry.path, entry.is_dir)
            type_str = "DIR" if entry.is_dir else "FILE"
            size_str = format_bytes(entry.size, self.raw_bytes)
            share_str = format_percent(entry.size, self.results.total_size)
            
            # Use icon prefix for Path
            icon_prefix = f"{icon} " if (icon and has_unicode) else ""
            path_display = f"{icon_prefix}{entry.path}"
            
            table_rows_raw.append((
                str(idx),
                type_str,
                size_str,
                share_str,
                category,
                path_display
            ))
            
            type_styled = f"{c_blue}{type_str}{c_reset}" if entry.is_dir else f"{c_yellow}{type_str}{c_reset}"
            size_styled = f"{c_green}{size_str}{c_reset}"
            share_styled = f"{c_green}{share_str}{c_reset}"
            
            if category == 'SYSTEM':
                category_styled = f"{c_red}{category}{c_reset}"
                path_styled = f"{c_red}{path_display}{c_reset}"
            elif category in ('Dependency', 'Cache', 'Virtual Environment'):
                category_styled = f"{c_yellow}{category}{c_reset}"
                path_styled = f"{c_bold}{path_display}{c_reset}"
            else:
                category_styled = f"{c_blue}{category}{c_reset}" if entry.is_dir else category
                path_styled = path_display
                
            table_rows_styled.append((
                f"{c_bold}{idx}{c_reset}",
                type_styled,
                size_styled,
                share_styled,
                category_styled,
                path_styled
            ))

        # Calculate column widths using the raw (uncolored) content
        col_widths = [1, 4, 4, 5, 8, 4] # Min widths
        for row in table_rows_raw:
            for i, val in enumerate(row):
                col_widths[i] = max(col_widths[i], len(val))

        def pad_cell(styled: str, raw: str, width: int, align: str = 'left') -> str:
            extra_spaces = max(0, width - len(raw))
            if align == 'right':
                return " " * extra_spaces + styled
            elif align == 'center':
                left_space = extra_spaces // 2
                right_space = extra_spaces - left_space
                return " " * left_space + styled + " " * right_space
            else: # left
                return styled + " " * extra_spaces

        # Print Table Headers
        hdr_idx = pad_cell(f"{c_bold}{c_cyan}#{c_reset}", "#", col_widths[0], 'left')
        hdr_type = pad_cell(f"{c_bold}{c_cyan}Type{c_reset}", "Type", col_widths[1], 'center')
        hdr_size = pad_cell(f"{c_bold}{c_cyan}Size{c_reset}", "Size", col_widths[2], 'right')
        hdr_share = pad_cell(f"{c_bold}{c_cyan}Share{c_reset}", "Share", col_widths[3], 'right')
        hdr_cat = pad_cell(f"{c_bold}{c_cyan}Category{c_reset}", "Category", col_widths[4], 'left')
        hdr_path = pad_cell(f"{c_bold}{c_cyan}Path{c_reset}", "Path", col_widths[5], 'left')
        
        # Border Characters
        if has_unicode:
            b_top = f"┌─{'─'*col_widths[0]}─┬─{'─'*col_widths[1]}─┬─{'─'*col_widths[2]}─┬─{'─'*col_widths[3]}─┬─{'─'*col_widths[4]}─┬─{'─'*col_widths[5]}─┐"
            b_mid = f"├─{'─'*col_widths[0]}─┼─{'─'*col_widths[1]}─┼─{'─'*col_widths[2]}─┼─{'─'*col_widths[3]}─┼─{'─'*col_widths[4]}─┼─{'─'*col_widths[5]}─┤"
            b_bot = f"└─{'─'*col_widths[0]}─┴─{'─'*col_widths[1]}─┴─{'─'*col_widths[2]}─┴─{'─'*col_widths[3]}─┴─{'─'*col_widths[4]}─┴─{'─'*col_widths[5]}─┘"
            b_side = "│"
        else:
            b_top = f"+-{'-'*col_widths[0]}-+-{'-'*col_widths[1]}-+-{'-'*col_widths[2]}-+-{'-'*col_widths[3]}-+-{'-'*col_widths[4]}-+-{'-'*col_widths[5]}-+"
            b_mid = f"+-{'-'*col_widths[0]}-+-{'-'*col_widths[1]}-+-{'-'*col_widths[2]}-+-{'-'*col_widths[3]}-+-{'-'*col_widths[4]}-+-{'-'*col_widths[5]}-+"
            b_bot = f"+-{'-'*col_widths[0]}-+-{'-'*col_widths[1]}-+-{'-'*col_widths[2]}-+-{'-'*col_widths[3]}-+-{'-'*col_widths[4]}-+-{'-'*col_widths[5]}-+"
            b_side = "|"

        b_top_styled = f"{c_blue}{b_top}{c_reset}"
        b_mid_styled = f"{c_blue}{b_mid}{c_reset}"
        b_bot_styled = f"{c_blue}{b_bot}{c_reset}"
        b_side_styled = f"{c_blue}{b_side}{c_reset}"

        print(b_top_styled)
        print(f"{b_side_styled} {hdr_idx} {b_side_styled} {hdr_type} {b_side_styled} {hdr_size} {b_side_styled} {hdr_share} {b_side_styled} {hdr_cat} {b_side_styled} {hdr_path} {b_side_styled}")
        print(b_mid_styled)
        
        for raw_row, styled_row in zip(table_rows_raw, table_rows_styled):
            ridx = pad_cell(styled_row[0], raw_row[0], col_widths[0], 'left')
            rtype = pad_cell(styled_row[1], raw_row[1], col_widths[1], 'center')
            rsize = pad_cell(styled_row[2], raw_row[2], col_widths[2], 'right')
            rshare = pad_cell(styled_row[3], raw_row[3], col_widths[3], 'right')
            rcat = pad_cell(styled_row[4], raw_row[4], col_widths[4], 'left')
            rpath = pad_cell(styled_row[5], raw_row[5], col_widths[5], 'left')
            print(f"{b_side_styled} {ridx} {b_side_styled} {rtype} {b_side_styled} {rsize} {b_side_styled} {rshare} {b_side_styled} {rcat} {b_side_styled} {rpath} {b_side_styled}")
            
        print(b_bot_styled)

    def render_json(self) -> str:
        """Produce JSON representation of the results."""
        entries_json = []
        entries = self.get_sorted_entries()
        for idx, entry in enumerate(entries, 1):
            reason, category, icon, safety = analyze_entry(entry.path, entry.is_dir)
            type_str = "DIR" if entry.is_dir else "FILE"
            
            entries_json.append({
                "rank": idx,
                "type": type_str,
                "name": entry.name,
                "path": str(entry.path),
                "size_bytes": entry.size,
                "size_human": format_bytes(entry.size, self.raw_bytes),
                "share_percent": round((entry.size / self.results.total_size * 100), 1) if self.results.total_size else 0.0,
                "category": category,
                "reason": reason,
                "icon": icon,
                "safety": safety
            })
            
        root_name = self.results.root_path.name or str(self.results.root_path)
        
        # Calculate true potentially reclaimable size
        from spacelyzer.similarity import SimilarityDetector
        from spacelyzer.suggestions import SuggestionsAnalyzer
        detector = SimilarityDetector(self.results.files, [e for e in self.results.entries.values() if e.is_dir])
        duplicates = detector.find_exact_duplicates()
        s_analyzer = SuggestionsAnalyzer(self.results.entries, duplicates)
        suggestions = s_analyzer.generate_suggestions()
        total_reclaimable = sum(s.total_size for s in suggestions)

        output = {
            "path": str(self.results.root_path),
            "total_size_bytes": self.results.total_size,
            "elapsed_seconds": round(self.results.elapsed_time, 2),
            "entries": entries_json,
            "summary": {
                "folders_scanned": self.results.folders_scanned,
                "files_scanned": self.results.files_scanned,
                "largest_folder": root_name, # Simplified fallback
                "largest_file": self.results.files[0].name if self.results.files else None,
                "potentially_reclaimable_bytes": total_reclaimable
            }
        }
        return json.dumps(output, indent=2)

    def render_csv(self) -> str:
        """Produce CSV representation of results."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["rank", "type", "name", "size_bytes", "size_human", "share_percent", "category", "reason", "safety", "path"])
        
        entries = self.get_sorted_entries()
        for idx, entry in enumerate(entries, 1):
            reason, category, icon, safety = analyze_entry(entry.path, entry.is_dir)
            type_str = "DIR" if entry.is_dir else "FILE"
            share = round((entry.size / self.results.total_size * 100), 1) if self.results.total_size else 0.0
            
            writer.writerow([
                idx,
                type_str,
                entry.name,
                entry.size,
                format_bytes(entry.size, self.raw_bytes),
                share,
                category,
                reason,
                safety or "",
                str(entry.path)
            ])
        return output.getvalue()

    def render_markdown(self) -> str:
        """Produce Markdown table of results."""
        lines = []
        lines.append("| # | Type | Size | Share | Category | Path |")
        lines.append("|---|------|------|-------|----------|------|")
        
        entries = self.get_sorted_entries()
        for idx, entry in enumerate(entries, 1):
            reason, category, icon, safety = analyze_entry(entry.path, entry.is_dir)
            type_str = "DIR" if entry.is_dir else "FILE"
            share = format_percent(entry.size, self.results.total_size)
            lines.append(f"| {idx} | {type_str} | {format_bytes(entry.size, self.raw_bytes)} | {share} | {category} | {entry.path} |")
            
        return "\n".join(lines)

    # Hierarchical Tree View
    def render_tree(self, max_depth: Optional[int] = None):
        """Render hierarchical tree view with cumulative sizes."""
        has_unicode = has_unicode_support()
        marker_last = "└── " if has_unicode else "`-- "
        marker_mid = "├── " if has_unicode else "|-- "
        prefix_vertical = "│   " if has_unicode else "|   "
        
        from spacelyzer.formatter import get_color_codes
        colors = get_color_codes()
        c_blue = colors['blue']
        c_green = colors['green']
        c_reset = colors['reset']

        def print_tree_node(path_str: str, prefix: str, is_last: bool, current_depth: int):
            if max_depth is not None and current_depth > max_depth:
                return
                
            entry = self.results.entries.get(path_str)
            if not entry:
                return
                
            # Node printing
            marker = marker_last if is_last else marker_mid
            name_display = f"{c_blue}{entry.name}{c_reset}" if entry.is_dir else entry.name
            size_display = f"{c_green}{format_bytes(entry.size, self.raw_bytes)}{c_reset}"
            extra_spaces = max(0, 25 - len(entry.name))
            print(f"{prefix}{marker}{name_display}{' ' * extra_spaces} {size_display}")
            
            # Subdirectories
            children = self.results.hierarchy.get(path_str, [])
            children = [c for c in children if c in self.results.entries]
            children.sort(key=lambda x: self.results.entries[x].size, reverse=True)
            
            new_prefix = prefix + ("    " if is_last else prefix_vertical)
            for i, child_path in enumerate(children):
                is_child_last = (i == len(children) - 1)
                print_tree_node(child_path, new_prefix, is_child_last, current_depth + 1)

        root_path_str = str(self.results.root_path)
        root_entry = self.results.entries.get(root_path_str)
        if root_entry:
            name_display = f"{c_blue}{root_entry.name}{c_reset}" if root_entry.is_dir else root_entry.name
            size_display = f"{c_green}{format_bytes(root_entry.size, self.raw_bytes)}{c_reset}"
            extra_spaces = max(0, 25 - len(root_entry.name))
            print(f"{name_display}{' ' * extra_spaces} {size_display}")
            
            children = self.results.hierarchy.get(root_path_str, [])
            children = [c for c in children if c in self.results.entries]
            children.sort(key=lambda x: self.results.entries[x].size, reverse=True)
            for i, child_path in enumerate(children):
                is_child_last = (i == len(children) - 1)
                print_tree_node(child_path, "", is_child_last, 1)

    # --- Visualizations ---
    def get_top_visualization_data(self, limit: int = 5) -> Tuple[List[Tuple[str, int, float]], int]:
        """Group entries into top categories/folders and an 'Others' block."""
        entries = self.get_sorted_entries(sort_key='size')
        total = self.results.total_size
        
        top_items = []
        sum_top_size = 0
        for entry in entries[:limit]:
            share = (entry.size / total) if total > 0 else 0.0
            top_items.append((entry.name, entry.size, share))
            sum_top_size += entry.size
            
        others_size = total - sum_top_size
        if others_size > 0 and len(entries) > limit:
            share = (others_size / total) if total > 0 else 0.0
            top_items.append(('Others', others_size, share))
            
        return top_items, total

    def render_bar_chart(self):
        """Render terminal bar chart."""
        data, total = self.get_top_visualization_data()
        max_bar_width = 30
        has_unicode = has_unicode_support()
        bar_char = "█" if has_unicode else "#"
        
        from spacelyzer.formatter import get_color_codes
        colors = get_color_codes()
        c_green = colors['green']
        c_blue = colors['blue']
        c_reset = colors['reset']
        
        for name, size, share in data:
            bar_len = int(share * max_bar_width)
            bar = bar_char * bar_len
            name_padded = name + " " * max(0, 15 - len(name))
            bar_padded = bar + " " * max(0, 30 - len(bar))
            print(f"{c_blue}{name_padded}{c_reset} {c_green}{bar_padded}{c_reset} {share*100:.0f}%")

    def render_pie_chart(self):
        """Render Unicode-based approximation of a pie chart alongside data."""
        data, total = self.get_top_visualization_data(4)
        
        from spacelyzer.formatter import get_color_codes
        colors = get_color_codes()
        c_green = colors['green']
        c_blue = colors['blue']
        c_magenta = colors['magenta']
        c_reset = colors['reset']
        c_bold = colors['bold']
        
        print(f"{c_bold}{c_blue}Storage Distribution{c_reset}\n")
        
        # Semi-hardcoded circles/pie arcs to represent slices
        has_unicode = has_unicode_support()
        if has_unicode:
            pies = [
                "◜██████████◝",
                "◜█████◞     ",
                "◜███◝       ",
                "            "
            ]
        else:
            pies = [
                " /##########\\",
                " /#####/     ",
                " /###\\       ",
                "             "
            ]
        
        for idx, (name, size, share) in enumerate(data):
            pie_symbol = pies[idx] if idx < len(pies) else ("            " if has_unicode else "             ")
            name_padded = name + " " * max(0, 12 - len(name))
            print(f"{c_magenta}{pie_symbol}{c_reset}  {c_blue}{name_padded}{c_reset} {c_green}{share*100:.1f}%{c_reset}")

    def render_sunburst(self):
        """Render ASCII Sunburst tree representation down to depth level 2."""
        total = self.results.total_size
        has_unicode = has_unicode_support()
        
        from spacelyzer.formatter import get_color_codes
        colors = get_color_codes()
        c_green = colors['green']
        c_blue = colors['blue']
        c_reset = colors['reset']
        c_bold = colors['bold']
        
        print(f"{c_bold}Disk  100%{c_reset}")
        print("│" if has_unicode else "|")
        
        root_path_str = str(self.results.root_path)
        children = self.results.hierarchy.get(root_path_str, [])
        children = [c for c in children if c in self.results.entries]
        children.sort(key=lambda x: self.results.entries[x].size, reverse=True)
        
        # Show top level
        for i, child_path in enumerate(children[:5]):
            child = self.results.entries[child_path]
            share = (child.size / total * 100) if total > 0 else 0
            is_last = (i == len(children[:5]) - 1)
            
            if has_unicode:
                prefix = "└────────" if is_last else "├────────"
            else:
                prefix = "`--------" if is_last else "|--------"
                
            name_padded = child.name + " " * max(0, 20 - len(child.name))
            print(f"{prefix} {c_blue}{name_padded}{c_reset} {c_green}{share:.0f}%{c_reset}")
            
            # Show sub-children if size is significant (>5% share)
            sub_children = self.results.hierarchy.get(child_path, [])
            sub_children = [sc for sc in sub_children if sc in self.results.entries]
            sub_children.sort(key=lambda x: self.results.entries[x].size, reverse=True)
            
            if has_unicode:
                sub_prefix = "       " if is_last else "│      "
            else:
                sub_prefix = "       " if is_last else "|      "
                
            sub_count = 0
            for j, sc_path in enumerate(sub_children):
                sc = self.results.entries[sc_path]
                sc_share = (sc.size / total * 100) if total > 0 else 0
                if sc_share >= 5.0 and sub_count < 3:
                    is_sc_last = (j == len(sub_children) - 1 or sub_count == 2)
                    if has_unicode:
                        sc_marker = "└────" if is_sc_last else "├────"
                    else:
                        sc_marker = "`----" if is_sc_last else "|----"
                    name_padded = sc.name + " " * max(0, 15 - len(sc.name))
                    print(f"{sub_prefix} {sc_marker} {c_blue}{name_padded}{c_reset} {c_green}{sc_share:.0f}%{c_reset}")
                    sub_count += 1
            if not is_last:
                print("│" if has_unicode else "|")

    def render_treemap(self):
        """Render character grid representing folder/file sizes proportionally."""
        data, total = self.get_top_visualization_data(4)
        
        width = 48
        grid = [" " * width for _ in range(4)]
        has_unicode = has_unicode_support()
        segment_char = "█" if has_unicode else "#"
        border_char = "█" if has_unicode else "#"
        
        from spacelyzer.formatter import get_color_codes
        colors = get_color_codes()
        c_green = colors['green']
        c_blue = colors['blue']
        c_reset = colors['reset']
        
        # Let's allocate columns proportionally to each item
        curr_col = 0
        for name, size, share in data:
            col_width = int(share * width)
            if col_width < 2:
                continue
            
            # Print title in the middle row of the segment
            label = f"{name} {share*100:.0f}%"
            # Ensure label fits
            if len(label) > col_width:
                label = label[:col_width]
                
            for row in range(4):
                if row in (1, 2) and col_width > 4:
                    # Put labels inside
                    start_idx = (col_width - len(label)) // 2
                    if row == 1 and start_idx >= 0:
                        row_content = segment_char * start_idx + label + segment_char * (col_width - start_idx - len(label))
                    else:
                        row_content = segment_char * col_width
                else:
                    row_content = segment_char * col_width
                
                # Update grid
                grid[row] = grid[row][:curr_col] + row_content + grid[row][curr_col + col_width:]
            curr_col += col_width

        # Print Treemap block
        print(f"{c_blue}{border_char * (width + 2)}{c_reset}")
        for r in grid:
            # Pad or trim to fit boundary
            line = r.ljust(width)[:width]
            print(f"{c_blue}{border_char}{c_reset}{c_green}{line}{c_reset}{c_blue}{border_char}{c_reset}")
        print(f"{c_blue}{border_char * (width + 2)}{c_reset}")

    # --- Mode-specific outputs ---
    def render_largest_files(self, limit: int = 10):
        """List the largest individual files."""
        sorted_files = sorted(self.results.files, key=lambda x: x.size, reverse=True)
        
        from spacelyzer.formatter import get_color_codes
        colors = get_color_codes()
        c_green = colors['green']
        c_bold = colors['bold']
        c_reset = colors['reset']
        c_blue = colors['blue']
        
        for idx, f in enumerate(sorted_files[:limit], 1):
            idx_str = f"{idx}"
            idx_padded = idx_str + " " * max(0, 3 - len(idx_str))
            name_str = f.name
            name_padded = name_str + " " * max(0, 20 - len(name_str))
            size_str = format_bytes(f.size, self.raw_bytes)
            size_padded = size_str + " " * max(0, 10 - len(size_str))
            
            print(f"  {c_bold}{idx_padded}{c_reset} {c_blue}{name_padded}{c_reset} {c_green}{size_padded}{c_reset} {f.path}")

    def render_extensions(self, limit: int = 10):
        """Group and rank by file extension size."""
        ext_sizes = defaultdict(int)
        ext_counts = defaultdict(int)
        for f in self.results.files:
            ext = f.path.suffix.lower() or "no extension"
            ext_sizes[ext] += f.size
            ext_counts[ext] += 1
            
        sorted_exts = sorted(ext_sizes.items(), key=lambda x: x[1], reverse=True)
        
        from spacelyzer.formatter import get_color_codes
        colors = get_color_codes()
        c_green = colors['green']
        c_blue = colors['blue']
        c_yellow = colors['yellow']
        c_reset = colors['reset']
        c_bold = colors['bold']
        
        print(f"{c_bold}{c_blue}{'Extension':<15} {'Total Size':<15} {'Files':<10}{c_reset}")
        print(("_" if not has_unicode_support() else "─") * 43)
        for ext, size in sorted_exts[:limit]:
            count = str(ext_counts[ext])
            ext_padded = ext + " " * max(0, 15 - len(ext))
            size_str = format_bytes(size, self.raw_bytes)
            size_padded = size_str + " " * max(0, 15 - len(size_str))
            count_padded = count + " " * max(0, 10 - len(count))
            print(f"{c_blue}{ext_padded}{c_reset} {c_green}{size_padded}{c_reset} {c_yellow}{count_padded}{c_reset}")

    def render_breakdown(self, path_str: str):
        """Show percentage breakdown of a specific folder's contents."""
        path = Path(path_str).resolve()
        path_str_resolved = str(path)
        
        if path_str_resolved not in self.results.entries:
            print(f"Path not scanned or not found: {path_str}")
            return
            
        entry = self.results.entries[path_str_resolved]
        print(f"{entry.name}")
        
        children = self.results.hierarchy.get(path_str_resolved, [])
        children_infos = [self.results.entries[c] for c in children if c in self.results.entries]
        
        # Add files in this folder
        # Find files whose parent is exactly this folder
        direct_files = [f for f in self.results.files if str(f.path.parent) == path_str_resolved]
        
        all_children = children_infos + direct_files
        all_children.sort(key=lambda x: x.size, reverse=True)
        
        total_size = entry.size
        has_unicode = has_unicode_support()
        bar_char = "█" if has_unicode else "#"
        marker_last = "└── " if has_unicode else "`-- "
        marker_mid = "├── " if has_unicode else "|-- "
        
        from spacelyzer.formatter import get_color_codes
        colors = get_color_codes()
        c_green = colors['green']
        c_blue = colors['blue']
        c_yellow = colors['yellow']
        c_reset = colors['reset']
        
        for idx, child in enumerate(all_children[:5]):
            share = (child.size / total_size) if total_size > 0 else 0
            bar_len = int(share * 24)
            bar = bar_char * bar_len
            marker = marker_last if idx == len(all_children[:5]) - 1 else marker_mid
            
            name_padded = child.name + " " * max(0, 15 - len(child.name))
            share_str = f"{share*100:>3.0f}%"
            print(f"{marker}{c_blue}{name_padded}{c_reset} {c_green}{share_str}{c_reset}  {c_yellow}{bar}{c_reset}")

# Import defaultdict helper inside to prevent import errors
from collections import defaultdict
