"""An immutable receipt from the transport actually used by the shared REST reader."""
from dataclasses import dataclass
import json


@dataclass(frozen=True)
class StateSourceRead:
    client: object
    generation: int
    number: int
    started_mono: float
    body_json: str

    @property
    def state(self):
        return json.loads(self.body_json)

    @classmethod
    async def capture(cls, client, *, generation, number, started_mono):
        # The reader owns the sole shared request. The captured client sends it;
        # an unrelated gather callback cannot attest which transport it used.
        state = await client.state()
        body = json.dumps(state, allow_nan=False, separators=(',', ':'))
        return state, cls(client, generation, number, started_mono, body)
