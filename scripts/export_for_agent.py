#!/usr/bin/env python3
"""
Solo-Quant Codebase Packager for AI Agent Review
Generates:
1. codebase_for_agent.md: Complete LLM-ready single markdown dump with file tree & code blocks.
2. solo_quant_core.zip: Clean source zip archive excluding cache, node_modules, .venv, etc.
3. latest_changes.diff: Git diff of all recent modifications against HEAD.
"""
import os
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Files and directories to include
CORE_EXTENSIONS = {'.py', '.ts', '.tsx', '.js', '.mjs', '.sql', '.json', '.yml', '.yaml', '.sh', '.md', '.env.example'}

# Exclude patterns
EXCLUDE_DIRS = {
    'node_modules', '.next', '.git', '.venv', 'venv', '__pycache__',
    '.pytest_cache', '.turbo', 'build', 'dist', 'coverage', '.gemini'
}

EXCLUDE_FILES = {
    'package-lock.json', 'tsconfig.tsbuildinfo', '.DS_Store', 'codebase_for_agent.md',
    'solo_quant_core.zip', 'latest_changes.diff'
}

def is_valid_file(path: Path) -> bool:
    if path.name in EXCLUDE_FILES:
        return False
    for part in path.parts:
        if part in EXCLUDE_DIRS:
            return False
    if path.suffix.lower() not in CORE_EXTENSIONS and path.name not in {'Dockerfile', 'LICENSE'}:
        return False
    return True

def generate_markdown_bundle(output_file: Path):
    files_to_bundle = []
    for root, dirs, files in os.walk(ROOT):
        # Prune excluded directories in-place
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith('.')]
        for f in files:
            p = Path(root) / f
            if is_valid_file(p):
                files_to_bundle.append(p)

    files_to_bundle.sort(key=lambda p: str(p.relative_to(ROOT)))

    with open(output_file, 'w', encoding='utf-8') as out:
        out.write("# Solo-Quant Core Codebase Bundle for AI Agent Review\n\n")
        out.write(f"Generated at: {subprocess.getoutput('date -u')}\n")
        out.write(f"Total bundled files: {len(files_to_bundle)}\n\n")

        out.write("## 1. Project Directory Structure\n\n```text\n")
        for p in files_to_bundle:
            out.write(f"{p.relative_to(ROOT)}\n")
        out.write("```\n\n")

        out.write("## 2. File Contents\n\n")
        for p in files_to_bundle:
            rel_path = p.relative_to(ROOT)
            ext = p.suffix.lower().lstrip('.')
            lang = 'python' if ext == 'py' else ('typescript' if ext in ('ts', 'tsx') else ('json' if ext == 'json' else ext))
            if p.name == 'Dockerfile':
                lang = 'dockerfile'
            out.write(f"### File: `{rel_path}`\n\n")
            out.write(f"```{lang}\n")
            try:
                content = p.read_text(encoding='utf-8', errors='replace')
                out.write(content)
                if not content.endswith('\n'):
                    out.write('\n')
            except Exception as e:
                out.write(f"// Error reading file: {e}\n")
            out.write("```\n\n")

    print(f"✅ Generated single-file AI bundle: {output_file} ({output_file.stat().st_size / 1024:.1f} KB)")

def generate_zip_archive(output_file: Path):
    with zipfile.ZipFile(output_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith('.')]
            for f in files:
                p = Path(root) / f
                if is_valid_file(p):
                    zipf.write(p, arcname=str(p.relative_to(ROOT)))
    print(f"✅ Generated clean zip archive: {output_file} ({output_file.stat().st_size / 1024:.1f} KB)")

def generate_diff(output_file: Path):
    # Generates git show HEAD (latest commit diff) or git diff HEAD (working tree)
    res = subprocess.run(['git', 'diff', 'HEAD'], cwd=ROOT, capture_output=True, text=True)
    if res.stdout.strip():
        output_file.write_text(res.stdout, encoding='utf-8')
        print(f"✅ Generated working tree diff: {output_file} ({output_file.stat().st_size / 1024:.1f} KB)")
    else:
        res_head = subprocess.run(['git', 'show', 'HEAD'], cwd=ROOT, capture_output=True, text=True)
        output_file.write_text(res_head.stdout, encoding='utf-8')
        print(f"✅ Generated latest commit diff: {output_file} ({output_file.stat().st_size / 1024:.1f} KB)")

if __name__ == '__main__':
    md_out = ROOT / 'codebase_for_agent.md'
    zip_out = ROOT / 'solo_quant_core.zip'
    diff_out = ROOT / 'latest_changes.diff'

    print("🚀 Packaging Solo-Quant codebase for AI Agent review...")
    generate_markdown_bundle(md_out)
    generate_zip_archive(zip_out)
    generate_diff(diff_out)
    print("\n🎉 Packaging complete! All 3 files are ready in project root.")
