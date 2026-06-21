# Spacelyzer

> **A powerful, read-only terminal-based disk space analyzer and similarity detector.**

Spacelyzer is a read-only disk analyzer that answers four key questions:
*   **Where** is my storage going?
*   **Why** is it there?
*   **Is there another copy** somewhere?
*   **How do I reach it** to act on it?

It is strictly a **read-only** tool. By printing full absolute paths, users can `Ctrl+Click` (or `Cmd+Click` on macOS) in modern terminals to open the location and manage files themselves.

---

## 🚀 Key Features

*   **Pillar 1: Disk Usage Analysis** - Detailed results sorted by size, share percentage, semantic category, and system-critical safety flags.
*   **Pillar 2: Similar Files & Folders** - Finds exact duplicate files (SHA-256) and similar folders (structural matching).
*   **Pillar 3: Common Storage Consumers** - Tracks and aggregates well-known space hogs (like `node_modules`, `__pycache__`, `venv`, `dist`, etc.).
*   **Pillar 4: Storage Categories** - Classifies scanned items into categories like Dependency, Cache, Build, IDE Metadata, Media, Archive, Documents, or Source Code.
*   **Pillar 5: Hierarchical Tree View** - Cumulative size calculation represented in tree layouts.
*   **Pillar 6: Terminal Visualizations** - Responsive bar charts, Sunburst ASCII trees, character-grid Treemaps, and Unicode Pie charts.
*   **Pillar 7: Intelligent Suggestions** - Highlights potentially reclaimable storage safely without deleting anything automatically.
*   **Pillar 8: Path Accessibility** - Guarantees full absolute paths for quick navigation.

---

## 📦 Installation

### macOS / Linux
```bash
curl -fsSL "https://raw.githubusercontent.com/KavimugilRajasekar/spacelyzer/main/scripts/install.sh" | sh
```

### Windows (PowerShell)
```powershell
irm "https://raw.githubusercontent.com/KavimugilRajasekar/spacelyzer/main/scripts/install.ps1" | iex
```

The installers will:
* Check for required dependencies and install them if missing
* Download and install the latest spacelyzer binary to your system path
* Verify the installation with `spacelyzer --version`

*Re-run either command at any time to update to the latest version.*

> [!NOTE]
> Review the installers before running: [scripts/install.sh](https://github.com/KavimugilRajasekar/spacelyzer/blob/main/scripts/install.sh) · [scripts/install.ps1](https://github.com/KavimugilRajasekar/spacelyzer/blob/main/scripts/install.ps1)

---

## 💻 Usage

```bash
spacelyzer [PATH] [OPTIONS]
```
*If no path is specified, it defaults to the current working directory (`.`).*

### Quick Examples

```bash
# Analyze the current folder
spacelyzer

# Analyze the Downloads folder
spacelyzer ~/Downloads

# Analyze with a max depth of 2 and show only top 10 items
spacelyzer ~/Projects -d 2 --top 10

# Include files in the scan and render a tree view
spacelyzer ~/Projects --files --tree

# Group and rank by file extension
spacelyzer ~/Projects --extensions

# Show duplicate or similar files and folders
spacelyzer ~/Projects --similar

# Output results as JSON
spacelyzer ~/Projects --json
```

### Core CLI Options

| Flag | Alias | Description |
|---|---|---|
| `-d, --depth <n>` | `-d` | Limit recursion to `n` levels deep |
| `-n, --top <n>` | `-n` | Show only the largest `n` entries |
| `-f, --files` | `-f` | Include files in results (default: folders only) |
| `--folders` | | Show folders only, ignore files entirely |
| `--hidden` | | Include hidden files and folders (default: excluded) |
| `--follow-links` | | Follow symbolic links (default: no) |
| `--sort <key>` | | Sort by `size` (default), `name`, or `modified` |
| `-r, --reverse` | `-r` | Reverse sort order (ascending) |
| `--min <size>` | | Ignore entries smaller than threshold, e.g., `100MB`, `1GB` |
| `--bytes` | | Show raw byte counts instead of human-readable sizes |
| `--ignore <pattern>` | | Exclude paths matching pattern (repeatable) |

### Analysis & Visualization Modes

*   `--tree`: Renders a hierarchical tree view with sizes.
*   `--largest-files`: Lists the largest individual files.
*   `--extensions`: Groups and ranks storage by file extensions.
*   `--similar`: Detects similar/duplicate files and folders.
*   `--summary`: Shows a storage category summary bar graph.
*   `--fingerprint`: Shows the Developer Storage Fingerprint.
*   `--bar` | `--pie` | `--sunburst` | `--treemap`: Terminal visualizations.

---

## 🗑️ Uninstallation

### macOS / Linux
```bash
curl -fsSL "https://raw.githubusercontent.com/KavimugilRajasekar/spacelyzer/main/scripts/uninstall.sh" | sh
```

### Windows (PowerShell)
```powershell
irm "https://raw.githubusercontent.com/KavimugilRajasekar/spacelyzer/main/scripts/uninstall.ps1" | iex
```

This removes the `spacelyzer` binary and cleans up any config files under `~/.spacelyzer/`. It does not remove any other tools installed on your system.

> [!NOTE]
> Review the uninstallers: [scripts/uninstall.sh](https://github.com/KavimugilRajasekar/spacelyzer/blob/main/scripts/uninstall.sh) · [scripts/uninstall.ps1](https://github.com/KavimugilRajasekar/spacelyzer/blob/main/scripts/uninstall.ps1)
