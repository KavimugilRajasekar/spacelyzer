import sys
import argparse
from collections import defaultdict
from pathlib import Path
from typing import List, Optional

from spacelyzer import __version__
from spacelyzer.exceptions import SpacelyzerException, PathNotFoundException, PermissionDeniedException, UserCancelledException
from spacelyzer.formatter import parse_size, format_bytes, has_unicode_support, get_color_codes
from spacelyzer.scanner import DiskScanner
from spacelyzer.similarity import SimilarityDetector
from spacelyzer.suggestions import SuggestionsAnalyzer
from spacelyzer.fingerprint import StorageFingerprinter
from spacelyzer.renderer import DiskUsageRenderer

def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Spacelyzer — Read-only disk analyzer CLI tool.",
        add_help=False
    )
    
    # Arguments
    parser.add_argument('path', nargs='?', default='.', help='Directory to analyze. Defaults to current directory.')
    
    # Core Options
    parser.add_argument('-d', '--depth', type=int, default=None, help='Limit recursion to n levels deep.')
    parser.add_argument('-n', '--top', type=int, default=None, help='Show only the largest n entries.')
    parser.add_argument('-f', '--files', action='store_true', help='Include files in results (default: folders only).')
    parser.add_argument('--folders', action='store_true', help='Show folders only, ignore files entirely.')
    parser.add_argument('--hidden', action='store_true', help='Include hidden files and folders (default: excluded).')
    parser.add_argument('--follow-links', action='store_true', help='Follow symbolic links (default: no).')
    parser.add_argument('--sort', choices=['size', 'name', 'modified'], default='size', help='Sort key (default: size).')
    parser.add_argument('-r', '--reverse', action='store_true', help='Reverse sort order.')
    parser.add_argument('--min', type=str, default=None, help='Ignore entries smaller than threshold, e.g. 100MB, 1GB.')
    parser.add_argument('--bytes', action='store_true', help='Show raw byte counts.')
    parser.add_argument('--ignore', action='append', default=[], help='Exclude paths matching pattern (e.g. node_modules, "*.cache"). Repeatable.')
    
    # Analysis Modes
    parser.add_argument('--tree', action='store_true', help='Render hierarchical tree view with sizes.')
    parser.add_argument('--largest-files', action='store_true', help='List the largest individual files.')
    parser.add_argument('--extensions', action='store_true', help='Group and rank by file extension.')
    parser.add_argument('--breakdown', action='store_true', help="Show percentage breakdown of a folder's contents.")
    parser.add_argument('--similar', action='store_true', help='Detect similar and duplicate files/folders.')
    parser.add_argument('--summary', action='store_true', help='Show storage category summary.')
    parser.add_argument('--fingerprint', action='store_true', help='Show Storage Fingerprint.')
    
    # Visualization Flags
    parser.add_argument('--bar', action='store_true', help='Terminal bar chart (default visual).')
    parser.add_argument('--pie', action='store_true', help='Unicode pie chart.')
    parser.add_argument('--sunburst', action='store_true', help='ASCII sunburst tree.')
    parser.add_argument('--treemap', action='store_true', help='Terminal treemap grid.')
    
    # Output Format Flags
    parser.add_argument('--json', action='store_true', help='Output as JSON.')
    parser.add_argument('--csv', action='store_true', help='Output as CSV.')
    parser.add_argument('--markdown', action='store_true', help='Output as Markdown table.')
    
    # Other
    parser.add_argument('--help', action='help', help='Show help and exit.')
    parser.add_argument('--version', action='version', version=f"Spacelyzer v{__version__}", help='Show version and exit.')
    
    return parser

def print_suggestions_section(renderer: DiskUsageRenderer, duplicates: list):
    """Calculates and prints the intelligent suggestions section (Pillar 7)."""
    s_analyzer = SuggestionsAnalyzer(renderer.results.entries, duplicates)
    suggestions = s_analyzer.generate_suggestions()
    
    colors = get_color_codes()
    c_green = colors['green']
    c_bold = colors['bold']
    c_reset = colors['reset']
    
    has_unicode = has_unicode_support()
    div_char = "─" if has_unicode else "-"
    chk_char = "✓" if has_unicode else "[INFO]"
    arr_char = "→" if has_unicode else "->"
    
    print(f"\n{c_bold}Suggestions{c_reset}")
    print(div_char * 60)
    
    total_reclaimable = 0
    for sug in suggestions:
        print(f"{c_green}{chk_char}{c_reset}  Found {sug.count} {sug.label:<32} {arr_char}  {c_green}{format_bytes(sug.total_size, renderer.raw_bytes)} potentially reclaimable{c_reset}")
        total_reclaimable += sug.total_size
        
    if not suggestions:
        print(f"{c_green}{chk_char}{c_reset}  No obvious storage-wasting patterns found.")
        
    print("\nNo action was performed.")
    print(div_char * 60)
    print(f"{c_bold}Total potentially reclaimable:  {c_green}{format_bytes(total_reclaimable, renderer.raw_bytes)}{c_reset}")

def print_summary_section(renderer: DiskUsageRenderer, duplicates: list, reclaimable_size: int):
    """Calculates and prints the scan summary section (Pillar 9)."""
    results = renderer.results
    colors = get_color_codes()
    c_cyan = colors['cyan']
    c_bold = colors['bold']
    c_green = colors['green']
    c_reset = colors['reset']
    
    has_unicode = has_unicode_support()
    div_char = "─" if has_unicode else "-"
    dash_char = "—" if has_unicode else "-"
    
    # Unique extensions count
    ext_count = len(results.extensions)
    
    # Find largest folder (excluding root)
    sub_folders = [e for e in results.entries.values() if e.is_dir and str(e.path) != str(results.root_path)]
    largest_folder_name = dash_char
    if sub_folders:
        largest_folder = max(sub_folders, key=lambda x: x.size)
        largest_folder_name = largest_folder.name
        
    # Find largest file
    largest_file_name = dash_char
    if results.files:
        largest_file = max(results.files, key=lambda x: x.size)
        largest_file_name = largest_file.name
        
    # Largest duplicate group
    largest_dup_group_count = 0
    total_duplicate_size = 0
    for name, files in duplicates:
        if len(files) > largest_dup_group_count:
            largest_dup_group_count = len(files)
        total_duplicate_size += sum(f.size for f in files[1:]) # Reclaimable copies
        
    print("\n" + div_char * 60)
    print(f"{c_bold}{c_cyan}Scan Completed{c_reset}")
    print(f"  {c_cyan}Folders scanned{c_reset}          {results.folders_scanned:,}")
    print(f"  {c_cyan}Files scanned{c_reset}           {results.files_scanned:,}")
    print(f"  {c_cyan}Unique extensions{c_reset}            {ext_count}")
    print(f"  {c_cyan}Largest folder{c_reset}           {largest_folder_name}")
    print(f"  {c_cyan}Largest file{c_reset}          {largest_file_name}")
    print(f"  {c_cyan}Largest duplicate group{c_reset}   {largest_dup_group_count} files" if largest_dup_group_count else f"  {c_cyan}Largest duplicate group{c_reset}   {dash_char}")
    print(f"  {c_cyan}Total duplicate size{c_reset}        {format_bytes(total_duplicate_size, renderer.raw_bytes)}")
    print(f"  {c_cyan}Potentially reclaimable{c_reset}     {c_green}{format_bytes(reclaimable_size, renderer.raw_bytes)}{c_reset}")
    print(f"  {c_cyan}Elapsed time{c_reset}             {results.elapsed_time:.1f} sec")
    print(div_char * 60)

def main(args_list: Optional[List[str]] = None) -> int:
    parser = create_parser()
    args = parser.parse_args(args_list)
    has_unicode = has_unicode_support()
    
    min_size_bytes = 0
    if args.min:
        try:
            min_size_bytes = parse_size(args.min)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 3

    # Resolve scan path
    try:
        scan_path = Path(args.path).resolve()
        if not scan_path.exists():
            print(f"Path not found: {args.path}", file=sys.stderr)
            return 3
    except PermissionError:
        print("Permission denied to scan directory.", file=sys.stderr)
        return 2

    # Instantiate scanner
    scanner = DiskScanner(
        root_path=str(scan_path),
        depth=args.depth,
        include_files=args.files,
        folders_only=args.folders,
        include_hidden=args.hidden,
        follow_links=args.follow_links,
        ignore_patterns=args.ignore,
        min_size=min_size_bytes
    )
    
    try:
        results = scanner.scan()
    except PermissionError:
        print("Permission denied to scan directory.", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nScan cancelled by user.", file=sys.stderr)
        return 4
    except Exception as e:
        print(f"Unknown error during scan: {e}", file=sys.stderr)
        return 1

    renderer = DiskUsageRenderer(results, args.bytes)
    
    # Run similarity detector for reports/summaries
    detector = SimilarityDetector(results.files, [e for e in results.entries.values() if e.is_dir])
    duplicates = detector.find_exact_duplicates()
    
    # Calculate reclaimable space
    s_analyzer = SuggestionsAnalyzer(results.entries, duplicates)
    suggestions = s_analyzer.generate_suggestions()
    total_reclaimable = sum(s.total_size for s in suggestions)

    # 1. Output Format rendering
    if args.json:
        print(renderer.render_json())
        return 0
    elif args.csv:
        print(renderer.render_csv())
        return 0
    elif args.markdown:
        print(renderer.render_markdown())
        return 0

    # 2. Specific Analysis Modes
    if args.tree:
        renderer.render_tree(max_depth=args.depth)
        return 0
        
    if args.largest_files:
        renderer.render_largest_files(args.top or 10)
        return 0
        
    if args.extensions:
        renderer.render_extensions(args.top or 10)
        return 0
        
    if args.breakdown:
        renderer.render_breakdown(str(scan_path))
        return 0
        
    colors = get_color_codes()
    c_blue = colors['blue']
    c_cyan = colors['cyan']
    c_green = colors['green']
    c_yellow = colors['yellow']
    c_magenta = colors['magenta']
    c_bold = colors['bold']
    c_reset = colors['reset']

    if args.similar:
        print(f"{c_bold}{c_cyan}Similarity Detection Results{c_reset}\n")
        
        # Similar Files
        similar_files = detector.find_similar_files()
        bullet = "·" if has_unicode else "-"
        div_40 = "─" * 40 if has_unicode else "-" * 40
        dash_char = "—" if has_unicode else "-"
        
        if similar_files:
            print(f"{c_bold}Similar Files:{c_reset}")
            for name, group in similar_files[:5]:
                total_sz = sum(f.size for f in group)
                print(f"\n  {c_yellow}{name}{c_reset}  {bullet}  {len(group)} Files  {bullet}  {c_green}{format_bytes(total_sz, args.bytes)} total{c_reset}")
                for f in group:
                    print(f"    {c_blue}{f.name:<25}{c_reset} {c_green}{format_bytes(f.size, args.bytes):<10}{c_reset} {f.path}")
        else:
            print("No similar files found.")
            
        # Similar Folders
        print("\n" + div_40)
        similar_folders = detector.find_similar_folders()
        if similar_folders:
            print(f"{c_bold}Similar Folders:{c_reset}")
            for name, group in similar_folders[:5]:
                total_sz = sum(f.size for f in group)
                print(f"\n  Found {len(group)} similar folders {dash_char} \"{c_yellow}{name}{c_reset}\"  {bullet}  {c_green}{format_bytes(total_sz, args.bytes)} combined{c_reset}")
                for folder in group:
                    print(f"    {c_blue}{str(folder.path):<45}{c_reset} {c_green}{format_bytes(folder.size, args.bytes)}{c_reset}")
        else:
            print("No similar folders found.")
        return 0

    if args.summary:
        # Storage category summary (Pillar 4)
        cat_sizes = defaultdict(int)
        for entry in results.entries.values():
            # Classify every entry to find overall categories
            from spacelyzer.analyzer import analyze_entry
            _, category, _, _ = analyze_entry(entry.path, entry.is_dir)
            if category != 'Unknown':
                cat_sizes[category] += entry.size
                
        sorted_cats = sorted(cat_sizes.items(), key=lambda x: x[1], reverse=True)
        max_bar_width = 30
        bar_char = "█" if has_unicode else "#"
        for cat, size in sorted_cats:
            share = (size / results.total_size) if results.total_size > 0 else 0
            bar_len = int(share * max_bar_width)
            bar = bar_char * bar_len
            print(f"{c_blue}{cat:<20}{c_reset} {c_green}{format_bytes(size, args.bytes):<10}{c_reset} {c_yellow}{bar}{c_reset}")
        return 0

    if args.fingerprint:
        # Storage fingerprinting mode (Pillar 6 / Fingerprint section)
        div_56 = "─" * 56 if has_unicode else "-" * 56
        print(f"{c_bold}{c_magenta}Storage Fingerprint{c_reset}")
        print(div_56 + "\n")
        fingerprinter = StorageFingerprinter(results.entries, results.files)
        fingerprints = fingerprinter.get_fingerprints()
        
        max_bar_width = 15
        bar_char = "█" if has_unicode else "#"
        total_fps_size = sum(fp.size for fp in fingerprints)
        for fp in fingerprints:
            share = (fp.size / total_fps_size) if total_fps_size > 0 else 0
            bar_len = int(share * max_bar_width)
            bar = bar_char * bar_len
            print(f"  {c_blue}{fp.name:<24}{c_reset} {c_magenta}{bar:<15}{c_reset}   {c_green}{format_bytes(fp.size, args.bytes)}{c_reset}")
        return 0

    # 3. Visualization Mode rendering (instead of table)
    if args.bar:
        renderer.render_bar_chart()
        return 0
    elif args.pie:
        renderer.render_pie_chart()
        return 0
    elif args.sunburst:
        renderer.render_sunburst()
        return 0
    elif args.treemap:
        renderer.render_treemap()
        return 0

    # Default view: Standard main table + suggestions + summary
    renderer.render_terminal_table(args.top, args.sort, args.reverse)
    print_suggestions_section(renderer, duplicates)
    print_summary_section(renderer, duplicates, total_reclaimable)
    return 0

if __name__ == '__main__':
    sys.exit(main())
