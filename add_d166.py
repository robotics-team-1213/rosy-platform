import sys
from pathlib import Path

f = Path('docs/progress.md')
text = f.read_text(encoding='utf-8')
if 'D-165]' in text:
    text = text.replace('D-165]', 'D-165, D-166]')
    f.write_text(text, encoding='utf-8')
    print("Added D-166 to progress.md adrs")
