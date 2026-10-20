"""D-831 interpretation copies and conservative rejection; never execution authority."""
from dataclasses import dataclass
import hashlib
import json
import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

VERSION = 'd831-v1'
DISCORD_REVISION = 'd728-semantic-v3-d831'
QUOTES = re.compile(r'''"(?:\\.|[^"\\])*"|(?<!\w)'(?:\\.|[^'\\])*'|‘[^’]*’|“[^”]*”|`[^`]*`''')
ACTION = re.compile(r'\b(?:move|send|navigate|cancel|stop|dock|undock|follow|return)\b|'
                    r'보내|움직|이동|취소|정지|도킹|추종|복귀', re.I)
NEGATIVE = re.compile(r"\b(?:not|never|don't|doesn't|cannot|can't|without)\b|"
                      r'지\s*(?:마|말|않)|말고|안\s+(?:보내|움직|이동|실행)', re.I)
CONDITIONAL = re.compile(r'\b(?:if|unless|suppose|hypothetical)\b|만약|'
                         r'(?:보내|움직이|이동하|실행하).{0,8}(?:면|다면)', re.I)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def hashed(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def normalize(text):
    def plain(value):
        return re.sub(r'[ \t]+', ' ', unicodedata.normalize('NFC', value))
    parts, at = [], 0
    for match in QUOTES.finditer(text):
        parts.extend((plain(text[at:match.start()]), match.group()))
        at = match.end()
    parts.append(plain(text[at:]))
    return ''.join(parts).strip(' \t')


@dataclass(frozen=True)
class Prepared:
    original: str
    normalized: str
    input_hash: str
    catalog_hash: str
    ambiguous: tuple[str, ...]
    context_json: str

    @property
    def context(self):
        return json.loads(self.context_json)

    @property
    def digest(self):
        return hashlib.sha256(self.context_json.encode()).hexdigest()


def prepare(question, *, environment=None):
    raw = question.model_dump()
    original = raw['question']
    normalized = normalize(original)
    environment = question.environment if environment is None else environment
    aliases = {}
    catalog = []
    for kind, rows, id_key in (
        ('robot', environment.get('robots', []), 'robot_id'),
        ('place', (environment.get('map') or {}).get('places', []), 'id'),
    ):
        for row in rows:
            identity = row[id_key]
            names = {identity, row.get('name', identity)}
            catalog.append((kind, identity, sorted(names)))
            for name in names:
                aliases.setdefault(unicodedata.normalize('NFC', name), set()).add(kind+':'+identity)
    hints, ambiguous = [], []
    for alias, identities in sorted(aliases.items()):
        pattern = r'(?<![A-Za-z0-9_.:-])'+re.escape(alias)+r'(?![A-Za-z0-9_.:-])'
        if re.search(pattern, normalized):
            hints.append({'name':alias, 'refs':sorted(identities)})
            if len(identities) != 1:
                ambiguous.append(alias)
    catalog_hash = hashed({'entries':sorted(catalog), 'map':environment.get('map')})
    # Authentication IDs are verified by Fleet/the broker and are not model reasoning context.
    context = {key:value for key, value in raw.items() if key not in {
        'scope', 'request_id', 'principal_id', 'author_id', 'guild_id', 'channel_id', 'content_hash'}}
    if 'history' in context:
        context['history'] = [{key:value for key, value in turn.items() if key not in {
            'request_id', 'principal_id', 'author_id', 'guild_id', 'channel_id', 'content_hash'}}
            for turn in context['history']]
    accepted = context.get('accepted_execution_context')
    if accepted is not None:
        context['accepted_execution_context'] = {key:value for key, value in accepted.items() if key not in {
            'principal_id', 'author_id', 'guild_id', 'channel_id', 'request_id'}}
    context['preparation'] = {'version':VERSION, 'input_hash':question.digest,
                             'catalog_hash':catalog_hash, 'name_hints':hints}
    return Prepared(original, normalized, question.digest, catalog_hash, tuple(ambiguous), canonical(context))


def control_issue(prepared, *, steps=1):
    if steps != 1:
        return 'CONFLICT'
    if prepared.ambiguous:
        return 'AMBIGUOUS_REFERENCE'
    text = prepared.normalized
    # These cues can only block a proposal; they never authorize or choose an action.
    if NEGATIVE.search(text):
        return 'AMBIGUOUS_REFERENCE'
    if CONDITIONAL.search(text) or any(ACTION.search(m.group()) for m in QUOTES.finditer(text)):
        return 'CONFLICT'
    if re.search(r'그리고|그\s*다음|\b(?:and|then)\b', text, re.I) and len(ACTION.findall(text)) > 1:
        return 'CONFLICT'
    return None


class InferenceUsage(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    preprocessing_version: Literal['d831-v1'] = VERSION
    input_tokens: int = Field(gt=0, le=7168)
    output_tokens: int = Field(gt=0, le=1024)
    elapsed_ms: FiniteFloat = Field(ge=0)
    preparation_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
