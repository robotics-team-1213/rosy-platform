"""Static T1 label sheet for the closed-question bench (docs/plans/2026-10-23-vlm-fast-judge-experiment.md).

Reads a bench ``rows.jsonl``, copies its frames next to one ``index.html`` and writes a page where a person picks
one option per question; "Download" saves ``labels.jsonl`` (frame sha256, question set, answers, labeller).
Model answers are not shown, so they cannot steer the label. Open the page from the output folder in a browser.
"""

import argparse
import hashlib
import html
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vlm_question_bench import QUESTION_SET, QUESTIONS  # noqa: E402

PAGE = """<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>VLM 질문 정답</title><style>
body{{font:15px system-ui,sans-serif;margin:16px;max-width:760px}}figure{{margin:0 0 24px;border-bottom:1px solid #ccc;padding-bottom:16px}}
img{{width:100%;height:auto}}fieldset{{border:0;padding:4px 0}}legend{{font-weight:600}}label{{margin-right:12px;white-space:nowrap}}
#bar{{position:sticky;top:0;background:#fff;padding:8px 0}}</style>
<div id="bar">질문 세트 {qs} · {n}장 · <input id="who" placeholder="이름" required> <button id="dl">Download labels.jsonl</button> <span id="left"></span></div>
{items}
<script>
const rows={rows};
function left(){{const total=document.querySelectorAll('fieldset').length, done=document.querySelectorAll('input[type=radio]:checked').length;document.getElementById('left').textContent=`${{done}}/${{total}}`;}}
document.addEventListener('change',left);left();
document.getElementById('dl').onclick=()=>{{const who=document.getElementById('who').value.trim();if(!who){{alert('이름을 적어 주세요');return;}}
const out=rows.map((r,i)=>{{const a={{}};for(const q of r.questions){{const c=document.querySelector(`input[name="f${{i}}-${{q}}"]:checked`);a[q]=c?c.value:null;}}
return JSON.stringify({{frame:r.frame,sha256:r.sha256,view:r.view,question_set:"{qs}",answers:a,labeller:who,labelled_at:new Date().toISOString()}});}});
const blob=new Blob([out.join('\\n')+'\\n'],{{type:'application/jsonl'}});const u=URL.createObjectURL(blob);const e=document.createElement('a');e.href=u;e.download='labels.jsonl';e.click();}};
</script></html>"""


def build(rows_path: Path, out: Path) -> int:
    rows = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    seen, items, meta = set(), [], []
    (out / "frames").mkdir(parents=True, exist_ok=True)
    for row in rows:
        frame = Path(row["frame"])
        if (row["view"], frame) in seen:
            continue                                   # a bench row repeats per --long-side
        seen.add((row["view"], frame))
        digest = hashlib.sha256(frame.read_bytes()).hexdigest()
        name = f"{digest[:16]}{frame.suffix}"
        shutil.copyfile(frame, out / "frames" / name)
        index = len(meta)
        questions = QUESTIONS[row["view"]]
        sets = "".join(
            f'<fieldset><legend>{html.escape(text)}</legend>'
            + "".join(f'<label><input type="radio" name="f{index}-{qid}" value="{o}"> {o}</label>' for o in options)
            + "</fieldset>" for qid, (text, options) in questions.items())
        items.append(f'<figure><img src="frames/{name}" alt="{row["view"]} {html.escape(frame.name)}" loading="lazy">'
                     f'<figcaption>{index + 1}. {row["view"]} · {html.escape(frame.name)}</figcaption>{sets}</figure>')
        meta.append({"frame": str(frame), "sha256": digest, "view": row["view"], "questions": list(questions)})
    page = PAGE.format(qs=QUESTION_SET, n=len(meta), items="\n".join(items), rows=json.dumps(meta))
    (out / "index.html").write_text(page, encoding="utf-8")
    return len(meta)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("rows", type=Path, nargs="+", help="bench rows.jsonl files")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists() and any(args.out.iterdir()):
        raise SystemExit(f"{args.out} is not empty")
    total = 0
    for rows in args.rows:
        total += build(rows, args.out / rows.parent.name)
    print(f"{total} frames under {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
