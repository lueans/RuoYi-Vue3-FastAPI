"""Installation diagnostics only: no pairing, credentials, model or run recovery."""

import asyncio
import re
from importlib.metadata import PackageNotFoundError

from .client import BridgeError
from .discovery import BINARIES, MAX_VERSION_CHARS, probe


def installation_binary(agent_key):
    # Reuse execution's local installation checks, without constructing a
    # driver or granting execution/budget consent. No auth staging is invoked.
    if agent_key == 'claude':
        from .claude_driver import local_binary
        return local_binary(), None
    if agent_key == 'codex':
        from .codex_driver import bundled_binary
        from .codex_policy import CLI_VERSION
        return bundled_binary(), CLI_VERSION
    if agent_key == 'kimi':
        from .kimi_driver import local_command
        from .kimi_policy import CLI_VERSION
        argv, _ = local_command()
        return argv[0], CLI_VERSION
    raise ValueError('Unknown Agent')


async def diagnose_agent(agent_key):
    if agent_key not in BINARIES:
        raise ValueError('Unknown Agent')
    result = {
        'agentKey': agent_key, 'installationStatus': 'blocked', 'version': None,
        'requiredVersion': None, 'executionSource': 'bundled_cli' if agent_key == 'codex' else 'local_cli',
        'authenticationStatus': 'not_checked', 'executionAvailable': False,
        'installCommand': f"python -m pip install './mindmap-agent-bridge[{agent_key}]'",
    }
    try:
        binary, required = installation_binary(agent_key)
        result['requiredVersion'] = required
        raw = await probe(binary, '--version', isolated_home=True)
        match = re.search(r'\d+\.\d+(?:\.\d+)?(?:[-+][\w.]+)?', raw)
        version = match.group() if match and len(match.group()) <= MAX_VERSION_CHARS else None
        result['version'] = version
        if not version:
            result['message'] = '未能识别 CLI 版本，请检查或重新安装所选 Agent。'
        elif required and (version != required or (agent_key == 'kimi' and raw.strip() != required)):
            result['message'] = f'CLI 版本不匹配，需要 {required}；不会自动升级或换用其他 Agent。'
        else:
            result['installationStatus'] = 'passed'
            result['message'] = '基础安装检查通过；未检查登录、模型、协议握手或平台授权，不代表可执行。'
    except BridgeError as error:
        result['message'] = str(error)  # installation checks use fixed, credential-free messages
    except (ImportError, PackageNotFoundError):
        result['message'] = '执行依赖缺失或安装不完整，请在项目根目录执行 installCommand 后重试。'
    except (OSError, ValueError, asyncio.TimeoutError):
        result['message'] = '版本探测失败或超时，请检查 CLI 安装；未输出原始错误或本机路径。'
    return result


async def diagnose(agent_keys=BINARIES):
    return list(await asyncio.gather(*(diagnose_agent(key) for key in agent_keys)))
