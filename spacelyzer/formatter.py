import re
import sys

def has_unicode_support() -> bool:
    """Check if stdout supports printing unicode characters without throwing EncodeError."""
    try:
        # Check standard unicode characters we use
        "┌─┬┐└┘├┤┴┼│✓█⠋·".encode(sys.stdout.encoding or 'ascii')
        return True
    except Exception:
        return False

def format_bytes(num_bytes: int, raw_bytes: bool = False) -> str:
    """Format bytes into human-readable format or keep raw bytes if specified."""
    if raw_bytes:
        return f"{num_bytes} B"
    
    if num_bytes < 0:
        return "0 B"
        
    for unit in ['B', 'KB', 'MB', 'GB', 'TB', 'PB']:
        if num_bytes < 1024.0:
            # For bytes, show integer. For others, show one decimal place.
            if unit == 'B':
                return f"{int(num_bytes)} B"
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} PB"

def parse_size(size_str: str) -> int:
    """Parse size string like '100MB', '1.5GB' to raw bytes. Raises ValueError if invalid."""
    if not size_str:
        return 0
    
    match = re.match(r'^\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]*)\s*$', size_str)
    if not match:
        raise ValueError(f"Invalid size format: '{size_str}'")
        
    number = float(match.group(1))
    unit = match.group(2).upper()
    
    unit_multipliers = {
        '': 1,
        'B': 1,
        'K': 1024,
        'KB': 1024,
        'M': 1024 * 1024,
        'MB': 1024 * 1024,
        'G': 1024 * 1024 * 1024,
        'GB': 1024 * 1024 * 1024,
        'T': 1024 * 1024 * 1024 * 1024,
        'TB': 1024 * 1024 * 1024 * 1024,
    }
    
    if unit not in unit_multipliers:
        raise ValueError(f"Unknown unit: '{unit}' in '{size_str}'")
        
    return int(number * unit_multipliers[unit])

def format_percent(part: float, total: float) -> str:
    """Format share percentage."""
    if total <= 0:
        return "0.0%"
    percent = (part / total) * 100
    return f"{percent:.1f}%"

def get_color_codes() -> dict:
    """Return ANSI color escape sequences if stdout is a TTY."""
    import sys
    if sys.stdout.isatty():
        return {
            'blue': '\033[94m',
            'cyan': '\033[96m',
            'green': '\033[92m',
            'yellow': '\033[93m',
            'red': '\033[91m',
            'magenta': '\033[95m',
            'bold': '\033[1m',
            'reset': '\033[0m'
        }
    else:
        return {
            'blue': '',
            'cyan': '',
            'green': '',
            'yellow': '',
            'red': '',
            'magenta': '',
            'bold': '',
            'reset': ''
        }
