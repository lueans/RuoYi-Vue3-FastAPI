import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  DEFAULT_MINDMAP_LIST_PREFERENCES,
  MINDMAP_LIST_PREFERENCE_KEY,
  normalizeMindmapListPreferences,
  readMindmapListPreferenceState,
  readMindmapListPreferences,
  resolveInitialMindmapListViewMode,
  resolveMindmapListSort,
  writeMindmapListPreferences,
} from '../mindmap-list-preferences.js'

class MemoryStorage {
  constructor() {
    this.values = new Map()
  }

  getItem(key) {
    return this.values.get(key) ?? null
  }

  setItem(key, value) {
    this.values.set(key, String(value))
  }
}

const listPageUrl = new URL('../../views/mindmap/index.vue', import.meta.url)
const cardUrl = new URL('../../components/MindMap/MindmapFileCard.vue', import.meta.url)
const voUrl = new URL(
  '../../../../ruoyi-fastapi-backend/module_mindmap/entity/vo/mindmap_vo.py',
  import.meta.url,
)
const daoUrl = new URL(
  '../../../../ruoyi-fastapi-backend/module_mindmap/dao/mindmap_dao.py',
  import.meta.url,
)

test('file workspace preferences are versioned, normalized and storage-failure safe', () => {
  assert.deepEqual(normalizeMindmapListPreferences(null), DEFAULT_MINDMAP_LIST_PREFERENCES)
  assert.deepEqual(
    normalizeMindmapListPreferences({ viewMode: 'script', sortKey: '__proto__' }),
    DEFAULT_MINDMAP_LIST_PREFERENCES,
  )

  const storage = new MemoryStorage()
  assert.equal(writeMindmapListPreferences({ viewMode: 'table', sortKey: 'name-asc' }, storage), true)
  assert.deepEqual(readMindmapListPreferences(storage), { viewMode: 'table', sortKey: 'name-asc' })
  assert.equal(readMindmapListPreferenceState(storage).hasExplicitViewPreference, true)
  assert.deepEqual(resolveMindmapListSort('name-asc'), { sortField: 'name', sortOrder: 'asc' })

  storage.setItem(MINDMAP_LIST_PREFERENCE_KEY, '{broken')
  assert.deepEqual(readMindmapListPreferences(storage), DEFAULT_MINDMAP_LIST_PREFERENCES)
  assert.equal(writeMindmapListPreferences({}, { setItem() { throw new Error('quota') } }), false)
})

test('compact workspace defaults to cards until the user explicitly chooses a view', () => {
  const storage = new MemoryStorage()
  const initialState = readMindmapListPreferenceState(storage)
  assert.equal(resolveInitialMindmapListViewMode(initialState, true), 'grid')
  assert.equal(resolveInitialMindmapListViewMode(initialState, false), 'table')

  assert.equal(writeMindmapListPreferences(
    { viewMode: 'grid', sortKey: 'name-asc' },
    storage,
    { viewModeExplicit: false },
  ), true)
  const responsiveState = readMindmapListPreferenceState(storage)
  assert.equal(responsiveState.hasExplicitViewPreference, false)
  assert.equal(resolveInitialMindmapListViewMode(responsiveState, false), 'table')

  assert.equal(writeMindmapListPreferences(
    { viewMode: 'table', sortKey: 'name-asc' },
    storage,
    { viewModeExplicit: true },
  ), true)
  const explicitState = readMindmapListPreferenceState(storage)
  assert.equal(resolveInitialMindmapListViewMode(explicitState, true), 'table')

  storage.setItem(MINDMAP_LIST_PREFERENCE_KEY, JSON.stringify({
    schemaVersion: 1,
    values: { viewMode: 'grid', sortKey: 'updated-desc' },
  }))
  assert.equal(readMindmapListPreferenceState(storage).hasExplicitViewPreference, true)
})

test('grid workspace exposes accessible cards, complete actions and responsive layouts', async () => {
  const [listPage, card] = await Promise.all([
    readFile(listPageUrl, 'utf8'),
    readFile(cardUrl, 'utf8'),
  ])

  assert.match(listPage, /<MindmapFileCard/)
  assert.match(listPage, /aria-label="脑图展示方式"/)
  assert.match(listPage, /:aria-pressed="viewMode === 'grid'"/)
  assert.match(listPage, /resolveInitialMindmapListViewMode\([\s\S]*?matchMedia\?\.\('\(max-width: 760px\)'\)/)
  assert.match(listPage, /function setViewMode\(nextViewMode\) \{[\s\S]*?hasExplicitViewPreference\.value = true[\s\S]*?nextViewMode === viewMode\.value[\s\S]*?persistListPreferences\(\)/)
  assert.match(listPage, /@selection-change="selected => handleCardSelection\(item, selected\)"/)
  assert.match(listPage, /grid-template-columns: repeat\(3, minmax\(230px, 1fr\)\)/)
  assert.match(listPage, /grid-template-columns: minmax\(0, 1fr\)/)

  assert.match(card, /aria-label="`打开脑图：\$\{item\.name/)
  assert.match(card, /loading="lazy"/)
  assert.match(card, /command="metadata"/)
  assert.match(card, /command="copy"/)
  assert.match(card, /command="move"/)
  assert.match(card, /command="status"/)
  assert.match(card, /command="delete"/)
  assert.match(card, /emit\('command', 'restore', item\)/)
  assert.match(card, /emit\('command', 'purge', item\)/)
  assert.match(card, /prefers-reduced-motion/)
})

test('sorting is a strict end-to-end contract with deterministic pagination', async () => {
  const [listPage, vo, dao] = await Promise.all([
    readFile(listPageUrl, 'utf8'),
    readFile(voUrl, 'utf8'),
    readFile(daoUrl, 'utf8'),
  ])

  assert.match(listPage, /resolveMindmapListSort\(initialListRouteState\.sortKey\)/)
  assert.match(listPage, /queryParams\.value\.sortField = sort\.sortField/)
  assert.match(listPage, /queryParams\.value\.sortOrder = sort\.sortOrder/)
  assert.match(vo, /sort_field: Literal\['name', 'create_time', 'update_time', 'version_count', 'status'\]/)
  assert.match(vo, /sort_order: Literal\['asc', 'desc'\]/)
  assert.match(dao, /order_by\(sort_column\.desc\(\), Mindmap\.id\.desc\(\)\)/)
  assert.match(dao, /order_by\(sort_column\.asc\(\), Mindmap\.id\.asc\(\)\)/)
})
