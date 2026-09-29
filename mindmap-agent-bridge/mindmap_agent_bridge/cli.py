"""No passwords/tokens in command-line arguments or process listings."""

import argparse
import asyncio
import getpass
import json
import os
import secrets
from pathlib import Path
from uuid import UUID

from .client import SECRET_PATTERN, BridgeError, enroll, normalize_server, read_config, run, save_config
from .discovery import BINARIES, discover


def pair_device(server: str, path: Path) -> None:
    server = normalize_server(server)
    if path.exists():
        config = read_config(path)
        if config['server'] != server or not config.get('pairingSecret'):
            raise BridgeError('已有设备配置；请在网页撤销旧设备，或明确选择另一个 --config 文件')
    else:
        code = getpass.getpass('请粘贴网页配对码（输入不回显）：').strip()
        device_id, separator, secret = code.partition('.')
        if not separator or not SECRET_PATTERN.fullmatch(secret) or str(UUID(device_id)) != device_id:
            raise BridgeError('配对码格式无效')
        config = {'version': 1, 'server': server, 'deviceId': device_id,
                  'pairingSecret': secret, 'deviceSecret': secrets.token_urlsafe(32)}
        # Persist before the request: an accepted enrollment with a lost
        # response must not leave an unrecoverable remote credential.
        save_config(path, config, initial=True)
    asyncio.run(enroll(config))
    config.pop('pairingSecret', None)
    save_config(path, config)
    print('设备配对完成。运行 mindmap-agent-bridge run 建立连接；可随时在网页撤销授权。')


def main() -> None:
    parser = argparse.ArgumentParser(description='脑图 Agent 本地桥接（默认仅扫描；macOS / Linux）')
    parser.add_argument('--config', type=Path, default=Path.home() / '.config/mindmap-agent-bridge/device.json')
    commands = parser.add_subparsers(dest='command', required=True)
    pairing = commands.add_parser('pair', help='使用网页生成的短时配对码配对')
    pairing.add_argument('--server', required=True, help='平台 HTTPS API 根地址；本机开发可使用回环 HTTP')
    running = commands.add_parser('run', help='保持出站扫描连接；本机执行必须额外显式启用')
    running.add_argument('--execute', action='append', choices=['claude', 'codex', 'kimi'], help='显式授权本机 Agent；可重复以支持网页切换')
    running.add_argument('--accept-estimated-budget', action='store_true', help='确认 Codex 预算为用量回报后的估算检查，可能超额，并非硬费用上限')
    running.add_argument('--accept-unmetered-budget', action='store_true', help='确认 Kimi 不限制金额预算，仅限制时间与工具次数')
    commands.add_parser('scan', help='仅在本机打印已知 CLI 的公开安装信息')
    doctor = commands.add_parser('doctor', help='无模型调用的执行依赖/版本检查，不读取登录或配对凭据')
    doctor.add_argument('--agent', action='append', choices=BINARIES, help='检查指定 Agent，可重复；默认检查全部')
    commands.add_parser('status', help='查看设备配置状态，不显示密钥')
    args = parser.parse_args()
    try:
        if os.name != 'posix':
            raise BridgeError('当前伴随程序支持 macOS / Linux，尚未提供 Windows 进程树隔离')
        if args.command == 'scan':
            print(json.dumps(asyncio.run(discover()), ensure_ascii=False, indent=2))
        elif args.command == 'doctor':
            from .diagnostics import diagnose
            results = asyncio.run(diagnose(tuple(dict.fromkeys(args.agent or BINARIES))))
            print(json.dumps(results, ensure_ascii=False, indent=2))
            if any(result['installationStatus'] != 'passed' for result in results):
                parser.exit(1)
        elif args.command == 'pair':
            pair_device(args.server, args.config)
        else:
            config = read_config(args.config)
            if args.command == 'status':
                print(json.dumps({'server': config['server'], 'deviceId': config['deviceId'],
                                  'paired': not bool(config.get('pairingSecret')), 'executionAvailable': False},
                                 ensure_ascii=False, indent=2))
            elif config.get('pairingSecret'):
                raise BridgeError('配对尚未确认，请重试 pair 命令')
            else:
                if args.execute:
                    from .execution_client import run_with_execution
                    asyncio.run(run_with_execution(config, agent_keys=tuple(dict.fromkeys(args.execute)),
                                                   accept_estimated_budget=args.accept_estimated_budget,
                                                   accept_unmetered_budget=args.accept_unmetered_budget))
                elif args.accept_estimated_budget:
                    raise BridgeError('--accept-estimated-budget 不能单独启用 Agent，请同时指定 --execute codex')
                elif args.accept_unmetered_budget:
                    raise BridgeError('--accept-unmetered-budget 不能单独启用 Agent，请同时指定 --execute kimi')
                else:
                    asyncio.run(run(config))
    except KeyboardInterrupt:
        print('桥接已停止。')
    except BridgeError as error:
        parser.exit(1, f'{error}\n')
    except (OSError, ValueError):
        parser.exit(1, '操作失败，请检查配置文件、服务地址或配对码；未输出秘密内容。\n')
