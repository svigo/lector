"""
Reescribe archivos .txt uniendo líneas que no terminan en puntuación de fin de oración.
Uso:
    python reflow_stories.py /ruta/a/historias/        # reescribe en el origen
    python reflow_stories.py /ruta/a/historias/ --dry-run  # solo muestra cuántos cambian
"""
import re
import sys
from pathlib import Path


def reflow(text: str) -> str:
    text = re.sub(r'\n[ \t]*\n', '\x00', text)        # preservar párrafos
    text = re.sub(r'([^.?!\n]) *\n *', r'\1 ', text)  # unir líneas mid-sentence
    return text.replace('\x00', '\n\n')


def main():
    if len(sys.argv) < 2:
        print("Uso: python reflow_stories.py <directorio> [--dry-run]")
        sys.exit(1)

    directory = Path(sys.argv[1])
    dry_run = '--dry-run' in sys.argv

    if not directory.is_dir():
        print(f"Error: {directory} no es un directorio")
        sys.exit(1)

    files = sorted(directory.glob('*.txt'))
    total = len(files)
    changed = 0
    errors = 0

    for i, path in enumerate(files, 1):
        try:
            text = path.read_text(encoding='utf-8', errors='replace')
            reflowed = reflow(text)
            if reflowed != text:
                changed += 1
                if not dry_run:
                    path.write_text(reflowed, encoding='utf-8')
        except Exception as e:
            errors += 1
            print(f"  ERROR {path.name}: {e}")

        if i % 500 == 0 or i == total:
            status = "modificados" if not dry_run else "cambiarían"
            print(f"  {i}/{total} procesados — {changed} {status}{' (dry-run)' if dry_run else ''}")

    print(f"\nListo: {total} archivos, {changed} {'modificados' if not dry_run else 'cambiarían'}, {errors} errores.")


if __name__ == '__main__':
    main()
