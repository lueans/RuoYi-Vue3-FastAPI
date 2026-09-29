"""Pinned local Codex policy. Estimates are NOT a provider dollar hard cap."""

import json
import math
import re
from decimal import Decimal

from .execution import RunFailure

CLI_VERSION = '0.147.0'
# Deliberately no default/substitute model: the platform must select an audited
# model explicitly. Adding a model requires current pricing and coverage.
PRICED_MODEL = 'gpt-5.6-terra'
# Verified 2026-09-26: https://developers.openai.com/api/docs/models/gpt-5.6-terra
# Standard API equivalent only, not a ChatGPT plan bill or provider hard cap.
DISABLED_SKILLS = ('imagegen', 'openai-docs', 'plugin-creator', 'review-agent', 'skill-creator', 'skill-installer')
DISABLED_FEATURES = (
    'shell_tool', 'unified_exec', 'apply_patch_freeform', 'view_image',
    'web_search_request', 'web_search_cached', 'standalone_web_search', 'search_tool',
    'apps', 'enable_mcp_apps', 'browser_use', 'browser_use_external', 'browser_use_full_cdp_access',
    'in_app_browser', 'computer_use', 'image_generation', 'multi_agent', 'multi_agent_v2',
    'hooks', 'plugins', 'remote_plugin', 'plugin_sharing', 'recommended_plugins',
    'skill_search', 'skill_mcp_dependency_install', 'workspace_dependencies',
    'code_mode_only', 'code_mode_buffered_exec', 'auth_elicitation', 'tool_call_mcp_elicitation',
    'tool_suggest', 'deferred_executor', 'executor_capability_discovery', 'request_permissions_tool',
    'default_mode_request_user_input', 'network_proxy', 'respect_system_proxy', 'shell_snapshot',
)
CONFIG_POLICY = {
    'sandbox_mode': 'read-only', 'approval_policy': 'never', 'web_search': 'disabled',
    'model_provider': 'openai', 'service_tier': 'default',
    'tools.web_search': False, 'tools.experimental_request_user_input.enabled': False,
    'tools.update_plan.enabled': False,
    'skills.config': [{'name': name, 'enabled': False} for name in DISABLED_SKILLS],
    **{name: {} for name in ('mcp_servers', 'model_providers', 'plugins', 'hooks', 'marketplaces',
                            'apps', 'projects', 'profiles')},
    'memories.generate_memories': False, 'memories.use_memories': False, 'memories.dedicated_tools': False,
    'project_doc_max_bytes': 0, 'project_doc_fallback_filenames': [], 'project_root_markers': [],
    'history.persistence': 'none', 'shell_environment_policy.inherit': 'none',
    'allow_login_shell': False, 'cli_auth_credentials_store': 'file', 'mcp_oauth_credentials_store': 'file',
    'check_for_update_on_startup': False, 'include_apps_instructions': False,
    'include_collaboration_mode_instructions': False, 'include_environment_context': False,
    'include_permissions_instructions': False, 'analytics.enabled': False,
    **{f'features.{name}': False for name in DISABLED_FEATURES},
    # Keep the pinned model's function-call router, not shell/MCP capabilities.
    'features.code_mode.enabled': True, 'features.code_mode.excluded_tool_namespaces': [],
    'features.code_mode.direct_only_tool_namespaces': [], 'features.code_mode_host': True,
}


def _toml(value):
    if isinstance(value, dict):
        return '{' + ','.join(f'{key}={_toml(item)}' for key, item in value.items()) + '}'
    if isinstance(value, list):
        return '[' + ','.join(_toml(item) for item in value) + ']'
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def startup_arguments():
    return [argument for key, value in CONFIG_POLICY.items() for argument in ('-c', f'{key}={_toml(value)}')]


def validate_offer(offer):
    if offer.model_ref != PRICED_MODEL:
        raise RunFailure('AI_CAPABILITY_UNSUPPORTED')
    if (type(offer.max_budget_usd) not in {float, int} or not math.isfinite(offer.max_budget_usd)
            or not 0.0001 <= offer.max_budget_usd <= 1000):
        raise RunFailure('AI_BUDGET_EXCEEDED')


def _get(config, key):
    for part in key.split('.'):
        config = config.get(part) if isinstance(config, dict) else None
    return config


def _empty(value):
    # Pinned config/read expands empty hooks/apps into typed null/empty fields.
    return value is None or value == [] or (isinstance(value, dict) and all(_empty(v) for v in value.values()))


def validate_config(result):
    config, layers, origins = result.get('config'), result.get('layers'), result.get('origins')
    if not isinstance(config, dict) or not isinstance(layers, list) or not isinstance(origins, dict):
        raise RunFailure('AI_CAPABILITY_UNSUPPORTED')
    flags = []
    for layer in layers:
        if not isinstance(layer, dict) or not isinstance(layer.get('name'), dict):
            raise RunFailure('AI_CAPABILITY_UNSUPPORTED')
        if layer['name'].get('type') == 'sessionFlags' and layer.get('disabledReason') is None:
            flags.append(layer.get('config'))
        elif layer.get('config') != {}:
            # Do not inherit machine-managed instructions/MCP or enterprise
            # providers that this private launcher has not audited.
            raise RunFailure('AI_CAPABILITY_UNSUPPORTED')
    if len(flags) != 1:
        raise RunFailure('AI_CAPABILITY_UNSUPPORTED')
    for key, expected in CONFIG_POLICY.items():
        raw, value = _get(flags[0], key), _get(config, key)
        if type(raw) is not type(expected) or raw != expected:
            raise RunFailure('AI_CAPABILITY_UNSUPPORTED')
        if key.startswith('tools.'):
            # The pinned v2 ToolsV2 response omits these legacy fields. Check
            # the raw startup layer and its resolved origin, not a null value.
            origin = origins.get(key)
            if (not isinstance(origin, dict) or not isinstance(origin.get('name'), dict)
                    or origin['name'].get('type') != 'sessionFlags'):
                raise RunFailure('AI_CAPABILITY_UNSUPPORTED')
        elif expected == {} and isinstance(value, dict) and _empty(value):
            continue
        elif type(value) is not type(expected) or value != expected:
            raise RunFailure('AI_CAPABILITY_UNSUPPORTED')


class CodexPolicy:
    """One fresh ephemeral thread: total usage includes ALL model round trips.

    Conservatively price the cumulative input with the long-context multiplier;
    missing cache-write counts price all uncached input as cache writes. This
    can overestimate actual API charges. ChatGPT quotas are not API invoices.
    The provider can spend before publishing usage; this is a reported-usage
    stop/check policy, never a promise not to exceed the chosen dollar amount.
    """

    def __init__(self, offer):
        validate_offer(offer)
        self.limit = Decimal(str(offer.max_budget_usd))
        self.usage = None
        self.estimated_cost = Decimal(0)
        self.local_api_key = None  # supplied only by the trusted local launcher

    async def prepare(self, session, offer, initialized):
        agent = initialized.get('userAgent')
        if not isinstance(agent, str) or not re.match(r'^[^/\s]+/' + re.escape(CLI_VERSION) + r'(?:\s|$)', agent):
            raise RunFailure('AI_CAPABILITY_UNSUPPORTED')
        result = await session._request('config/read', {'cwd': session.cwd, 'includeLayers': True})
        validate_config(result)
        await self._login_local_key(session)
        result = await session._request('account/read', {'refreshToken': False})
        account = result.get('account')
        if (result.get('requiresOpenaiAuth') is not True or not isinstance(account, dict)
                or account.get('type') not in {'apiKey', 'chatgpt'}):
            raise RunFailure('AI_PROVIDER_AUTH_FAILED')
        await self._skills(session)

    async def _login_local_key(self, session):
        if self.local_api_key is not None:
            try:
                await session._request('account/login/start', {'type': 'apiKey', 'apiKey': self.local_api_key})
            finally:
                self.local_api_key = None

    async def _skills(self, session):
        result = await session._request('skills/list', {'cwds': [session.cwd], 'forceReload': True})
        rows = result.get('data')
        if not isinstance(rows, list) or len(rows) != 1:
            raise RunFailure('AI_CAPABILITY_UNSUPPORTED')
        row = rows[0]
        if (not isinstance(row, dict) or row.get('cwd') != session.cwd or row.get('errors') != []
                or not isinstance(row.get('skills'), list)):
            raise RunFailure('AI_CAPABILITY_UNSUPPORTED')
        for skill in row['skills']:
            if (not isinstance(skill, dict) or skill.get('name') not in DISABLED_SKILLS
                    or skill.get('enabled') is not False):
                raise RunFailure('AI_CAPABILITY_UNSUPPORTED')

    async def before_turn(self, session, offer, thread):
        if (thread.get('model') != offer.model_ref or thread.get('modelProvider') != 'openai'
                or thread.get('cwd') != session.cwd or thread.get('approvalPolicy') != 'never'
                or not isinstance(thread.get('sandbox'), dict) or thread['sandbox'].get('type') != 'readOnly'
                or thread['sandbox'].get('networkAccess', False) is not False
                or thread.get('instructionSources') not in (None, [])
                or thread.get('serviceTier') not in (None, 'default')):
            raise RunFailure('AI_CAPABILITY_UNSUPPORTED')
        # Thread creation may materialize bundled skills; check again before
        # the first model request, not only at process initialization.
        await self._skills(session)

    def observe(self, method, params):
        if method == 'model/rerouted':
            # No silently substituted model or price. A response already in
            # flight can have consumed quota; stopping cannot undo that.
            raise RunFailure('AI_CAPABILITY_UNSUPPORTED')
        if method != 'thread/tokenUsage/updated':
            return
        token_usage = params.get('tokenUsage')
        usage = token_usage.get('total') if isinstance(token_usage, dict) else None
        required = ('inputTokens', 'cachedInputTokens', 'outputTokens', 'totalTokens', 'reasoningOutputTokens')
        if (not isinstance(usage, dict)
                or any(type(usage.get(key)) is not int or not 0 <= usage[key] <= 10**12 for key in required)):
            raise RunFailure('AI_BUDGET_EXCEEDED')
        inp, cached, out = usage['inputTokens'], usage['cachedInputTokens'], usage['outputTokens']
        write = usage.get('cacheWriteInputTokens')
        if write is None:
            write = inp - cached
        if (type(write) is not int or write < 0 or cached + write > inp
                or usage['totalTokens'] != inp + out or usage['reasoningOutputTokens'] > out
                or (self.usage is not None and any(usage[key] < self.usage[key] for key in required))):
            raise RunFailure('AI_BUDGET_EXCEEDED')
        input_rate, output_rate = (Decimal(2), Decimal('1.5')) if inp > 272_000 else (Decimal(1), Decimal(1))
        cost = ((inp - cached - write) * 2 * input_rate + cached * Decimal('0.2') * input_rate
                + write * Decimal('2.5') * input_rate + out * 12 * output_rate) / 1_000_000
        self.usage = {key: usage[key] for key in required}
        self.estimated_cost = max(self.estimated_cost, cost)
        if self.estimated_cost > self.limit:
            raise RunFailure('AI_BUDGET_EXCEEDED')

    def finish(self):
        if self.usage is None or self.usage['totalTokens'] == 0:
            raise RunFailure('AI_BUDGET_EXCEEDED')
