"""Private configuration for the audited Kimi Code 2.1.1 ACP runtime.

This is a tool policy for a trusted local CLI, not an OS sandbox. No provider
money cap is available: the caller must separately obtain local consent to
timeout/tool-count limits. Never copy the user's hooks, MCP, skills or config.
"""

import hashlib
import json
import os
import stat
from pathlib import Path

try:
    import tomllib
except ImportError:  # Python 3.10
    import tomli as tomllib

from .execution import KNOWN_TOOLS, RunFailure, RunProtocolError, _load

CLI_VERSION = '2.1.1'
MODEL = 'kimi-for-coding'
MODEL_ALIAS = 'mindmap-kimi'
PROVIDER_ALIAS = 'mindmap-provider'
BASE_URL = 'https://api.kimi.com/coding/v1'
REGIONS = {BASE_URL: 'https://auth.kimi.com', 'https://api.kimi.ai/coding/v1': 'https://auth.kimi.ai'}
MAX_AUTH_BYTES = 2 * 1024 * 1024
NO_TOOLS = 'mcp__mindmap__disabled_no_tools'


def validate_offer(offer):
    allowed = KNOWN_TOOLS - {'complete_artifact' if offer.execution_mode == 'direct' else 'add_comment'}
    if offer.intent == 'discuss':
        allowed = frozenset()
    names = [tool.get('name') for tool in offer.tools]
    if (offer.agent_key != 'kimi' or offer.model_ref != MODEL or len(set(names)) != len(names)
            or any(name not in allowed for name in names)):
        raise RunFailure('AI_CAPABILITY_UNSUPPORTED')


def isolated_environment(root, *, node_directory=None):
    paths = {key: Path(root) / name for key, name in {
        'HOME': 'home', 'KIMI_CODE_HOME': 'kimi', 'TMPDIR': 'tmp', 'XDG_CONFIG_HOME': 'config',
        'XDG_CACHE_HOME': 'cache', 'XDG_DATA_HOME': 'data', 'XDG_STATE_HOME': 'state',
    }.items()}
    for path in paths.values():
        path.mkdir(mode=0o700)
    # A locally resolved Node directory can support a trusted npm CLI shebang;
    # never inherit NODE_OPTIONS, proxy credentials, KIMI_* or the user's PATH.
    path = os.defpath if node_directory is None else str(node_directory) + os.pathsep + os.defpath
    return {**{key: str(value) for key, value in paths.items()}, 'PATH': path,
            'LANG': 'C.UTF-8', 'NO_COLOR': '1', 'TMP': str(paths['TMPDIR']), 'TEMP': str(paths['TMPDIR'])}


def _read_regular(source):
    descriptor = os.open(source, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_AUTH_BYTES:
            raise ValueError
        raw = handle.read(MAX_AUTH_BYTES + 1)
    if len(raw) > MAX_AUTH_BYTES:
        raise ValueError
    return raw


def _write_private(target, raw):
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    with os.fdopen(descriptor, 'wb') as handle:
        handle.write(raw)


def _key(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 16_384 or any(c in value for c in '\0\r\n'):
        raise ValueError
    return value


def stage_local_auth(environment):
    """Read credentials only inside an explicitly enabled run, never discovery.

    Support KIMI_API_KEY (mainland coding endpoint), or the current model's
    Kimi provider in config.toml, with official mainland/global endpoints only.
    OAuth is copied, not linked or written back. Keychain/custom endpoints and
    model-provider environment overlays require a separate audited integration.
    """
    try:
        if 'KIMI_API_KEY' in os.environ:
            return {'type': 'kimi', 'base_url': BASE_URL, 'api_key': _key(os.environ['KIMI_API_KEY'])}
        source = Path(os.environ.get('KIMI_CODE_HOME') or (Path.home() / '.kimi-code')).expanduser()
        config = tomllib.loads(_read_regular(source / 'config.toml').decode('utf-8'))
        model = config.get('models', {}).get(config.get('default_model'), {})
        provider = config.get('providers', {}).get(model.get('provider'), {})
        base = provider.get('base_url', BASE_URL).rstrip('/')
        if (provider.get('type') != 'kimi' or base not in REGIONS or provider.get('env')
                or provider.get('custom_headers') or model.get('base_url')):
            raise ValueError
        result = {'type': 'kimi', 'base_url': base}
        key = provider.get('api_key')
        if not key and provider.get('api_key_env'):
            # Only a named local credential is read, never the entire env.
            key = os.environ.get(provider['api_key_env'])
        if key:
            return {**result, 'api_key': _key(key)}
        oauth = provider.get('oauth')
        host = REGIONS[base]
        storage = 'kimi-code'
        if base != BASE_URL:
            identity = json.dumps({'oauthHost': host, 'baseUrl': base}, separators=(',', ':'))
            storage += '-env-' + hashlib.sha256(identity.encode()).hexdigest()[:16]
        if (not isinstance(oauth, dict) or oauth.get('storage') != 'file'
                or oauth.get('key') != f'oauth/{storage}' or oauth.get('oauth_host', host) != host):
            raise ValueError
        raw = _read_regular(source / 'credentials' / f'{storage}.json')
        token = _load(raw, MAX_AUTH_BYTES)
        _key(token.get('access_token'))
        if token.get('refresh_token') is not None:
            _key(token['refresh_token'])
        if type(token.get('expires_at')) not in {float, int}:
            raise ValueError
        target = Path(environment['KIMI_CODE_HOME']) / 'credentials'
        target.mkdir(mode=0o700)
        _write_private(target / f'{storage}.json', raw)
        return {**result, 'oauth': {'storage': 'file', 'key': f'oauth/{storage}', 'oauth_host': host}}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RunProtocolError):
        raise RunFailure('AI_PROVIDER_AUTH_FAILED') from None


def configuration(offer, provider):
    validate_offer(offer)
    names = [f'mcp__mindmap__{tool["name"]}' for tool in offer.tools]
    # Kimi treats an empty enabled list as unrestricted! A nonempty impossible
    # tool name intentionally exposes zero tools for discuss mode.
    return {
        'default_model': MODEL_ALIAS, 'default_permission_mode': 'manual',
        'telemetry': False, 'auto_session_title': False, 'merge_all_available_skills': False,
        'builtin_product_skills': False, 'extra_skill_dirs': [], 'extra_agent_dirs': [], 'hooks': [],
        'providers': {PROVIDER_ALIAS: provider},
        'models': {MODEL_ALIAS: {'provider': PROVIDER_ALIAS, 'model': MODEL, 'max_context_size': 262144,
                               'capabilities': ['tool_use']}},
        'tools': {'enabled': names or [NO_TOOLS]},
        # ACP approval is checked per call by KimiSession. Do not rely on
        # persisted permission rules being imported into a new ACP session.
        'permission': {'rules': []},
        'loop_control': {'max_steps_per_turn': 80, 'max_retries_per_step': 0, 'max_attempts_per_step': 1},
    }


def _toml(value):
    if isinstance(value, dict):
        return '{' + ', '.join(f'{json.dumps(k)} = {_toml(v)}' for k, v in value.items()) + '}'
    if isinstance(value, list):
        return '[' + ', '.join(_toml(item) for item in value) + ']'
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def write_configuration(environment, offer, provider):
    values = configuration(offer, provider)
    raw = '\n'.join(f'{key} = {_toml(value)}' for key, value in values.items()) + '\n'
    # Validate our generated syntax before a runtime which ignores malformed
    # config sections could silently fall back to unrestricted defaults.
    if tomllib.loads(raw) != values:
        raise RunFailure('AI_CAPABILITY_UNSUPPORTED')
    _write_private(Path(environment['KIMI_CODE_HOME']) / 'config.toml', raw.encode('utf-8'))
