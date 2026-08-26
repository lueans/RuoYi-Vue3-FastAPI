import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const frontendRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../..',
)

for (const configName of ['nginx.dockermy.conf', 'nginx.dockerpg.conf']) {
  test(`${configName} 为脑图协作代理 WebSocket 升级`, async () => {
    const config = await readFile(
      path.join(frontendRoot, 'bin', configName),
      'utf8',
    )

    assert.match(config, /map\s+\$http_upgrade\s+\$connection_upgrade\s*{/)
    assert.match(config, /proxy_http_version\s+1\.1;/)
    assert.match(config, /proxy_set_header\s+Upgrade\s+\$http_upgrade;/)
    assert.match(config, /proxy_set_header\s+Connection\s+\$connection_upgrade;/)
    assert.match(config, /proxy_read_timeout\s+3600s;/)
  })
}
