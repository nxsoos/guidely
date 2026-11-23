"""Inspect Git's index and available history without displaying secret values.

This heuristic is intentionally conservative; it is not a guarantee of absence.
Run: python scripts/check_secrets.py
"""
import re
import subprocess
import sys
from pathlib import Path


def git(*args):
    return subprocess.run(['git', *args], capture_output=True, check=True).stdout


def inspect(path, content, origin):
    findings = set()
    name = path.rsplit('/', 1)[-1]
    if (name == '.env' or name.startswith('.env.')) and not name.endswith('.example'):
        findings.add('environment file tracked')
    if re.search(r'(?i)(credentials|service.account).*\.json$|\.(pem|key|p12|pfx)$', name):
        findings.add('credential file tracked')
    text = content.decode('utf-8', errors='replace')
    for match in re.finditer(r'(?m)^[ \t]*([A-Z][A-Z0-9_]*(?:KEY|SECRET|TOKEN|PASSWORD|DATABASE_URL)[A-Z0-9_]*)[ \t]*[:=][ \t]*[\x22\x27]?([^\s\x22\x27#]+)', text):
        variable, value = match.groups()
        if value.lower() not in ('', 'false', 'true', 'none', 'null') and not any(p in value.lower() for p in ('placeholder', 'replace', 'example', 'your-', 'your_', '${', 'os.getenv', 'field(', 'test-', 'dummy', '<')):
            findings.add(variable)
    patterns = {'GEMINI_API_KEY': r'AIza[0-9A-Za-z_-]{35}', 'PRIVATE_KEY': r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
                'SUPABASE_SECRET_KEY': r'sb_secret_[A-Za-z0-9_-]{20,}', 'DATABASE_URL': r'postgres(?:ql)?://[^\s:/]+:[^\s@]+@'}
    for variable, pattern in patterns.items():
        if re.search(pattern, text) and not path.endswith('.example'):
            findings.add(variable)
    return [(origin, path, finding) for finding in sorted(findings)]


def main():
    results = []
    tracked = git('ls-files', '-z').decode().split('\0')
    for path in filter(None, tracked):
        results.extend(inspect(path, git('show', ':' + path), 'index'))
        if Path(path).is_file():
            results.extend(inspect(path, Path(path).read_bytes(), 'working tree'))
    untracked = git('ls-files', '--others', '--exclude-standard', '-z').decode().split('\0')
    for path in filter(None, untracked):
        if Path(path).is_file():
            results.extend(inspect(path, Path(path).read_bytes(), 'untracked candidate'))
    commits = git('rev-list', '--all').decode().splitlines()
    seen = set()
    for commit in commits:
        entries = git('ls-tree', '-r', '-z', commit).decode().split('\0')
        for entry in filter(None, entries):
            meta, path = entry.split('\t', 1)
            _, kind, oid = meta.split()
            if kind != 'blob' or (path, oid) in seen:
                continue
            seen.add((path, oid))
            results.extend(inspect(path, git('cat-file', 'blob', oid), 'history'))
    for origin, path, finding in sorted(set(results)):
        print(f'{origin}: {path}: {finding}')
    print(f'Checked {len(list(filter(None, tracked)))} indexed paths and {len(commits)} available commits; {len(set(results))} potential findings. Secret values were not displayed.')
    return bool(results)


if __name__ == '__main__':
    sys.exit(main())
