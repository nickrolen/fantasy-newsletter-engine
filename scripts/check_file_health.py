#!/usr/bin/env python3
"""
check_file_health.py -- Detect encoding corruption and non-ASCII in project files.

HOW TO USE:
    python check_file_health.py                  # scan all .py/.md in current dir
    python check_file_health.py path/to/dir       # scan a specific directory
    python check_file_health.py path/to/file.py   # scan a single file

POLICY:
    All .py and .md source files must be ASCII-only (ord <= 127 for every char).
    Unicode characters needed at runtime should use \\u escape sequences in Python
    string literals, and ASCII equivalents (like ->) in comments, docstrings, and
    markdown files.

    This prevents mojibake corruption when files pass through download/upload
    pipelines that don't preserve UTF-8 encoding.

WHAT TO LOOK FOR:
    [FAIL]  = file contains non-ASCII characters (fix before committing)
    [OK]    = file is pure ASCII
"""

import os
import sys
from pathlib import Path


# File extensions to check for ASCII-only compliance
CHECKED_EXTENSIONS = {'.py', '.md'}

# Files to skip
SKIP_FILES = set()

# Common mojibake patterns -- indicates file was corrupted during transfer
MOJIBAKE_SIGNATURES = [
    '\u00c3\u00a2',       # most common double-encoded marker
    '\u00c3\u0192',       # triple-encoded marker
    '\u00c3\u201a',       # another double-encoded marker
    '\u00e2\u2020\u2019', # -> arrow read as CP1252
    '\u00e2\u20ac\u201c', # em dash read as CP1252
    '\u00e2\u20ac\u2122', # right quote read as CP1252
]


def check_file(filepath):
    """Check a single file for non-ASCII characters and mojibake."""
    result = {
        'filepath': filepath,
        'status': 'ok',
        'non_ascii_lines': [],
        'mojibake_found': [],
        'file_size': 0,
    }

    try:
        result['file_size'] = os.path.getsize(filepath)
    except OSError:
        result['status'] = 'error'
        return result

    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
    except Exception:
        result['status'] = 'error'
        return result

    # Check for mojibake signatures
    for sig in MOJIBAKE_SIGNATURES:
        count = content.count(sig)
        if count > 0:
            result['mojibake_found'].append((sig, count))
            result['status'] = 'fail'

    # Check for any non-ASCII characters
    for i, line in enumerate(content.split('\n'), 1):
        for j, ch in enumerate(line):
            if ord(ch) > 127:
                result['non_ascii_lines'].append({
                    'line': i,
                    'col': j + 1,
                    'char': ch,
                    'codepoint': f'U+{ord(ch):04X}',
                    'preview': line.rstrip()[:100],
                })
                result['status'] = 'fail'

    return result


def scan_directory(dirpath):
    """Scan all relevant text files in a directory."""
    results = []
    for root, dirs, files in os.walk(dirpath):
        dirs[:] = [d for d in dirs if not d.startswith('.')
                   and d not in {'node_modules', '__pycache__', 'venv', '.git'}]
        for fname in sorted(files):
            ext = Path(fname).suffix.lower()
            if ext in CHECKED_EXTENSIONS and fname not in SKIP_FILES:
                filepath = os.path.join(root, fname)
                results.append(check_file(filepath))
    return results


def print_report(results):
    """Print a human-readable health report."""
    fail_count = sum(1 for r in results if r['status'] == 'fail')
    ok_count = sum(1 for r in results if r['status'] == 'ok')

    print('=' * 70)
    print('ASCII HEALTH CHECK')
    print('=' * 70)
    print(f'  Scanned: {len(results)} files')
    print(f'  [OK]: {ok_count}   [FAIL]: {fail_count}')
    print('=' * 70)

    failures = [r for r in results if r['status'] == 'fail']
    if failures:
        print('\nFAILING FILES:\n')
        for r in failures:
            fname = os.path.basename(r['filepath'])
            n = len(r['non_ascii_lines'])
            print(f'  [FAIL] {fname} -- {n} non-ASCII characters')

            for sig, count in r['mojibake_found']:
                print(f'         !! MOJIBAKE: {repr(sig)} found {count}x')

            seen_lines = set()
            shown = 0
            for info in r['non_ascii_lines']:
                if info['line'] not in seen_lines and shown < 10:
                    seen_lines.add(info['line'])
                    shown += 1
                    print(f"         L{info['line']}: {info['char']} "
                          f"({info['codepoint']}) -- {info['preview'][:80]}")

            total_lines = len(set(x['line'] for x in r['non_ascii_lines']))
            if total_lines > len(seen_lines):
                print(f'         ... and {total_lines - len(seen_lines)} more lines')
            print()
    else:
        print('\n  All files are pure ASCII!\n')

    print('ALL FILES:')
    for r in results:
        tag = '[OK]  ' if r['status'] == 'ok' else '[FAIL]'
        fname = os.path.basename(r['filepath'])
        size_kb = r['file_size'] / 1024
        extra = ''
        if r['status'] == 'fail':
            extra = f'  ({len(r["non_ascii_lines"])} non-ASCII chars)'
        print(f'  {tag} {fname:<40} {size_kb:>8.1f} KB{extra}')

    return fail_count == 0


if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else '.'

    if os.path.isfile(target):
        results = [check_file(target)]
    elif os.path.isdir(target):
        results = scan_directory(target)
    else:
        print(f"Error: '{target}' not found")
        sys.exit(1)

    all_clean = print_report(results)
    sys.exit(0 if all_clean else 1)
