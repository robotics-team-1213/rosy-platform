"""Read-only robot list from the Fleet owner; being listed is not a connection or control check."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import ssl
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

ROBOTS = '/api/v1/fleet/robots'
PROFILES = '/api/fleet/device-profiles'
LIMIT = 4 * 1024 * 1024
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}')
REASONS = {
    'unconfigured': '이 호스트에 Fleet 읽기 연결이 설정되지 않았습니다. 운영 담당자에게 연결을 요청하거나 목록에 없는 로봇으로 직접 입력하세요.',
    'unauthorized': 'Fleet가 이 호스트의 읽기 권한을 거절했습니다. 운영 담당자에게 Fleet Viewer 토큰 갱신을 요청하세요.',
    'unreachable': 'Fleet에 연결하지 못했습니다. Fleet 실행 상태와 네트워크를 확인한 뒤 다시 확인하세요.',
    'invalid': 'Fleet 응답 형식이 예상과 다릅니다. 운영 담당자에게 Fleet 버전 확인을 요청하세요.',
}


class OwnerUnavailable(Exception):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):   # the Viewer token must not follow a redirect elsewhere
        return None


def _name(value, fallback):
    text = ''.join(c for c in value if not unicodedata.category(c).startswith('C')).strip() if isinstance(value, str) else ''
    return text[:1024] or fallback


def _model(profile):
    model = re.sub(r'[^A-Za-z0-9_.:-]+', '-', profile.get('model') or '').strip('-_.:')[:128] if profile else ''
    return model if _ID.fullmatch(model) else 'unrecorded'


def _kind(profile, rostered):
    words = f"{profile.get('model', '')} {profile.get('display_name', '')}".lower() if profile else ''
    if profile and profile.get('device_kind') == 'manipulator' and re.search(r'omx|openmanipulator', words):
        return 'omx'
    if rostered and (not profile or profile.get('device_kind') == 'mobile'):
        return 'pinky'
    return profile['device_kind'] if profile else 'robot'


def merge(robots, profiles):
    """Fleet roster rows and descriptive profiles joined by device ID; unusable IDs are counted, not guessed."""
    roster = {row['robot_id']: row for row in (robots or {'robots': []})['robots']}
    described = {row['device_id']: row for row in (profiles or {'profiles': []})['profiles']}
    rows, skipped = [], 0
    for device_id in sorted(set(roster) | set(described)):
        if not isinstance(device_id, str) or not _ID.fullmatch(device_id):
            skipped += 1
            continue
        profile, robot = described.get(device_id), roster.get(device_id)
        rows.append(dict(device_id=device_id, name=_name(profile and profile.get('display_name'), device_id),
                         kind=_kind(profile, robot is not None), model_revision=_model(profile),
                         online=bool(robot and robot.get('online')),
                         sources=[name for name, row in (('roster', robot), ('profile', profile)) if row]))
    return rows, skipped


class FleetOwners:
    def __init__(self, config):
        if not isinstance(config, dict) or not re.fullmatch(r'https?://[^\s/]+(/[^\s]*)?', str(config.get('url', ''))):
            raise ValueError('Fleet owner config needs an http(s) url')
        self.url = config['url'].rstrip('/')
        self.token = Path(config['token_file']).read_text(encoding='utf-8').strip()
        if not self.token or any(c.isspace() for c in self.token):
            raise ValueError('Fleet owner token file must hold one bearer token')
        context = ssl.create_default_context(cafile=config.get('ca_file'))
        self.opener = build_opener(ProxyHandler({}), _NoRedirect(), HTTPSHandler(context=context))

    def _get(self, path):
        request = Request(self.url + path, headers={'Authorization': 'Bearer ' + self.token, 'Accept': 'application/json'})
        try:
            with self.opener.open(request, timeout=5) as response:
                return json.loads(response.read(LIMIT + 1)[:LIMIT])
        except HTTPError as exc:
            if exc.code == 404:   # Fleet without that store configured lists nothing there
                return None
            raise OwnerUnavailable('unauthorized' if exc.code in (401, 403) else 'unreachable') from None
        except ValueError:
            raise OwnerUnavailable('invalid') from None
        except (URLError, OSError):
            raise OwnerUnavailable('unreachable') from None

    def candidates(self):
        try:
            rows, skipped = merge(self._get(ROBOTS), self._get(PROFILES))
        except OwnerUnavailable as exc:
            return dict(status=exc.args[0], reason=REASONS[exc.args[0]], robots=[], skipped=0)
        except (TypeError, KeyError, AttributeError):
            return dict(status='invalid', reason=REASONS['invalid'], robots=[], skipped=0)
        return dict(status='ok', reason='', robots=rows, skipped=skipped,
                    checked_at=datetime.now(timezone.utc).isoformat())

    def confirm(self, device_id):
        listed = self.candidates()
        if listed['status'] != 'ok':
            raise ValueError(listed['reason'])
        row = next((row for row in listed['robots'] if row['device_id'] == device_id), None)
        if row is None:
            raise ValueError('Fleet 목록에서 이 device ID를 찾지 못했습니다. Fleet 장치 정보에 먼저 등록하거나 다시 확인하세요.')
        return row, listed['checked_at']


def candidates(owners, registered=()):
    listed = owners.candidates() if owners else dict(status='unconfigured', reason=REASONS['unconfigured'], robots=[], skipped=0)
    taken = set(registered)
    return dict(listed, robots=[dict(row, registered=row['device_id'] in taken) for row in listed['robots']])
