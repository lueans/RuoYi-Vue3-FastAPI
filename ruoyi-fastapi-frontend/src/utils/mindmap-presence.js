const DEFAULT_PRESENCE_DISPLAY_LIMIT = 5
const MIN_PRESENCE_DISPLAY_LIMIT = 1
const MAX_PRESENCE_DISPLAY_LIMIT = 8
const MAX_PRESENCE_NAME_LENGTH = 80
const MAX_PRESENCE_IDENTITY_LENGTH = 128
const MAX_PRESENCE_AVATAR_LENGTH = 8192

const PRESENCE_COLORS = Object.freeze([
  '#3159c7',
  '#6d3bc0',
  '#087b72',
  '#a14f08',
  '#b42355',
  '#096b9f',
  '#5d3fb4',
  '#287a3d',
])

function truncateCodePoints(value, maxLength) {
  const codePoints = Array.from(value)
  return codePoints.length > maxLength
    ? codePoints.slice(0, maxLength).join('')
    : value
}

function normalizeIdentity(value) {
  if (!['string', 'number', 'bigint'].includes(typeof value)) return ''
  if (typeof value === 'number' && !Number.isFinite(value)) return ''
  const identity = String(value).trim()
  if (!identity || identity.length > MAX_PRESENCE_IDENTITY_LENGTH || /[\u0000-\u001f\u007f\u202a-\u202e\u2066-\u2069]/.test(identity)) {
    return ''
  }
  return identity
}

function normalizeName(user, identity) {
  const candidate = [user.name, user.nickName, user.userName, user.user_name]
    .find(value => typeof value === 'string' && value.trim())
  const name = (candidate || identity || '协作者')
    .replace(/[\u0000-\u001f\u007f\u202a-\u202e\u2066-\u2069]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  return truncateCodePoints(name || '协作者', MAX_PRESENCE_NAME_LENGTH)
}

function normalizeAvatar(value) {
  if (typeof value !== 'string') return ''
  const avatar = value.trim()
  if (!avatar || avatar.length > MAX_PRESENCE_AVATAR_LENGTH) return ''
  return /^(?:https?:|data:image\/|blob:|\/)/i.test(avatar) ? avatar : ''
}

function normalizeColor(value) {
  if (typeof value !== 'string') return ''
  const color = value.trim()
  return /^#[\da-f]{6}$/i.test(color) ? color : ''
}

function stableColorIndex(value) {
  let hash = 2166136261
  for (const character of Array.from(value)) {
    hash ^= character.codePointAt(0)
    hash = Math.imul(hash, 16777619)
  }
  return (hash >>> 0) % PRESENCE_COLORS.length
}

export function normalizeMindmapPresenceUsers(users) {
  if (!Array.isArray(users)) return []
  const seen = new Set()
  const normalized = []
  for (const user of users) {
    if (!user || typeof user !== 'object' || Array.isArray(user)) continue
    const identity = normalizeIdentity(user.id ?? user.userId)
    if (!identity || seen.has(identity)) continue
    seen.add(identity)
    normalized.push({
      id: user.id ?? user.userId,
      identity,
      name: normalizeName(user, identity),
      avatar: normalizeAvatar(user.avatar),
      color: normalizeColor(user.color) || PRESENCE_COLORS[stableColorIndex(identity)],
    })
  }
  return normalized
}

export function normalizeMindmapPresenceDisplayLimit(value) {
  const parsed = typeof value === 'number' && Number.isFinite(value)
    ? Math.trunc(value)
    : DEFAULT_PRESENCE_DISPLAY_LIMIT
  return Math.min(MAX_PRESENCE_DISPLAY_LIMIT, Math.max(MIN_PRESENCE_DISPLAY_LIMIT, parsed))
}

export function getMindmapPresenceInitial(name) {
  const normalized = typeof name === 'string' ? name.trim() : ''
  const [first = '?'] = Array.from(normalized)
  return first.toLocaleUpperCase()
}

export const MINDMAP_PRESENCE_PANEL_LIMIT = 100
